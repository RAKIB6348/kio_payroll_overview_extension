from odoo import _, fields, models
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    _inherit = "account.payment.register"

    def _kio_get_payroll_payslip(self):
        """Return the payslip when the wizard was opened from Pay Now."""
        slip_id = self.env.context.get("kio_payroll_slip_id")
        if not self.env.context.get("kio_payroll_pay_now") or not slip_id:
            return self.env["kio.payroll.payslip"]
        return self.env["kio.payroll.payslip"].browse(slip_id).exists()

    def _kio_validate_payroll_amount(self):
        """Block duplicate, zero, and excessive payroll payments."""
        slip = self._kio_get_payroll_payslip()
        if not slip:
            return
        # Serialize payment confirmations for the same payslip. Without this,
        # two open Pay Now wizards could both pass validation and overpay.
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)", (0x4B4951, slip.id)
        )
        slip.invalidate_recordset(["salary_move_id"])
        info = slip._get_kio_salary_payment_info()
        unpaid_amount = info["unpaid_amount"]
        currency = slip.company_id.currency_id
        if unpaid_amount <= 0:
            raise UserError(_(
                "The salary of %(employee)s is already fully paid.",
                employee=slip.employee_id.display_name,
            ))
        amount = self.amount or 0.0
        if currency.compare_amounts(amount, 0.0) <= 0:
            raise UserError(_("The payment amount must be greater than zero."))
        if currency.compare_amounts(amount, unpaid_amount) > 0:
            raise UserError(_(
                "The payment amount cannot exceed the unpaid salary of "
                "%(amount)s %(currency)s for %(employee)s.",
                amount=currency.round(unpaid_amount),
                currency=currency.name,
                employee=slip.employee_id.display_name,
            ))

    def _kio_sync_payroll_payment_state(self, source_lines):
        """Update payslip status after the standard reconciliation."""
        if not source_lines:
            return
        slips = self.env["kio.payroll.payslip"].search([
            ("salary_move_id", "in", source_lines.move_id.ids),
        ])
        for slip in slips:
            payable_lines = slip._get_kio_salary_payable_lines()
            payment_moves = (
                payable_lines.mapped("matched_debit_ids.debit_move_id.move_id")
                | payable_lines.mapped("matched_credit_ids.credit_move_id.move_id")
            ).filtered(
                lambda move: move != slip.salary_move_id
                and move.state == "posted"
            )
            payment_move = False
            if payment_moves:
                payment_move = payment_moves.sorted(
                    key=lambda move: (
                        move.date or fields.Date.today(),
                        move.id,
                    )
                )[-1]
            slip._sync_kio_payment_state(payment_move or None)

    def action_create_payments(self):
        source_lines = self.line_ids
        self._kio_validate_payroll_amount()
        action = super().action_create_payments()
        self._kio_sync_payroll_payment_state(source_lines)
        return action
