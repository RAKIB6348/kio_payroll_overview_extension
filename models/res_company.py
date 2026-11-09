from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    salary_journal_id = fields.Many2one(
        "account.journal",
        string="Salary Journal",
        check_company=True,
        domain="[('type', '=', 'general')]",
        help="Miscellaneous journal used for payroll accounting entries.",
    )
    salary_debit_account_id = fields.Many2one(
        "account.account",
        string="Salary Debit Account",
        check_company=True,
        domain=(
            "[('deprecated', '=', False), "
            "('account_type', 'in', "
            "('expense', 'expense_direct_cost', 'expense_depreciation'))]"
        ),
        help="Expense account debited for salary expense.",
    )
    salary_credit_account_id = fields.Many2one(
        "account.account",
        string="Salary Credit Account",
        check_company=True,
        domain=(
            "[('deprecated', '=', False), "
            "('account_type', 'in', "
            "('liability_payable', 'liability_credit_card', "
            "'liability_current', 'liability_non_current'))]"
        ),
        help="Liability account credited for salary payable.",
    )

    kio_overtime_monetary_enabled = fields.Boolean(
        string="Enable Overtime Monetary Calculation",
        default=False,
        help="When enabled, confirmed/applicable overtime hours are converted to "
             "amounts using Per Hour Rate. When disabled, overtime hours are shown "
             "but amount is not calculated.",
    )
    kio_overtime_per_hour_rate = fields.Float(
        string="Per Hour Rate (BDT)",
        default=0.0,
        digits=(16, 2),
        help="Company-wide fixed hourly rate used for overtime: "
             "Overtime Amount = Overtime Hours × Per Hour Rate.",
    )
    kio_overtime_per_day_rate = fields.Float(
        string="Per Day Rate (BDT)",
        default=0.0,
        digits=(16, 2),
        help="Company-wide fixed daily rate reserved for future daily-rate-based payroll calculations.",
    )

    @api.constrains(
        "kio_overtime_per_hour_rate",
        "kio_overtime_per_day_rate",
    )
    def _check_kio_overtime_rates(self):
        for company in self:
            if company.kio_overtime_per_hour_rate < 0:
                raise ValidationError(_("Per Hour Rate cannot be negative."))
            if company.kio_overtime_per_day_rate < 0:
                raise ValidationError(_("Per Day Rate cannot be negative."))

    @api.constrains(
        "salary_journal_id",
        "salary_debit_account_id",
        "salary_credit_account_id",
    )
    def _check_salary_accounting_company(self):
        for company in self:
            for field_name in (
                "salary_journal_id",
                "salary_debit_account_id",
                "salary_credit_account_id",
            ):
                record = company[field_name]
                if record.company_id and record.company_id != company:
                    raise ValidationError(_(
                        "%(record)s must belong to the same company as the "
                        "payroll accounting configuration.",
                        record=record.display_name,
                    ))
