import calendar
from collections import Counter
from datetime import date, timedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class KioPayrollBatch(models.Model):
    _name = "kio.payroll.batch"
    _description = "Payroll Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_start desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    date_start = fields.Date(required=True, tracking=True)
    date_end = fields.Date(required=True, tracking=True)
    payroll_type = fields.Selection(
        [("monthly", "Monthly Payroll")],
        default="monthly",
        required=True,
    )
    payroll_scope = fields.Selection(
        [("all", "All Employees"), ("department", "Department-wise")],
        default="all", required=True, tracking=True,
    )
    department_id = fields.Many2one(
        "hr.department", string="Department", check_company=True, ondelete="restrict",
    )
    payment_date = fields.Date()
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
                ("done", "Confirmed"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    payslip_ids = fields.One2many(
        "kio.payroll.payslip", "batch_id", string="Payslips"
    )
    payslip_count = fields.Integer(compute="_compute_payslip_stats")
    employee_count = fields.Integer(compute="_compute_payslip_stats")
    total_net = fields.Monetary(
        string="Total Net", compute="_compute_payslip_stats", currency_field="currency_id"
    )
    note = fields.Text()
    salary_move_id = fields.Many2one(
        "account.move", string="Payroll Journal Entry", readonly=True,
        copy=False, check_company=True,
    )

    @api.depends("payslip_ids", "payslip_ids.employee_id", "payslip_ids.net_pay")
    def _compute_payslip_stats(self):
        for batch in self:
            slips = batch.payslip_ids
            batch.payslip_count = len(slips)
            batch.employee_count = len(slips.mapped("employee_id"))
            batch.total_net = sum(slips.mapped("net_pay"))

    def get_payroll_report_totals(self):
        self.ensure_one()
        totals = {"paid": 0.0, "unpaid": 0.0}
        for slip in self.payslip_ids:
            payment_info = slip._get_kio_salary_payment_info()
            totals["paid"] += payment_info["paid_amount"]
            totals["unpaid"] += payment_info["unpaid_amount"]
        return totals

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for batch in self:
            if batch.date_start and batch.date_end and batch.date_end < batch.date_start:
                raise ValidationError(_("The end date must be on or after the start date."))

    @api.constrains("payroll_scope", "department_id", "company_id")
    def _check_payroll_scope(self):
        for batch in self:
            if batch.payroll_scope == "department" and not batch.department_id:
                raise ValidationError(_("Select a department for department-wise payroll."))
            if batch.payroll_scope == "all" and batch.department_id:
                raise ValidationError(_("All Employees payroll cannot have a department."))
            if batch.department_id and batch.department_id.company_id != batch.company_id:
                raise ValidationError(_("The department must belong to the payroll company."))

    def unlink(self):
        moves = self.mapped("salary_move_id")
        for move in moves.filtered(lambda item: item.state == "posted"):
            if any(
                line.matched_debit_ids or line.matched_credit_ids
                for line in move.line_ids
            ):
                raise UserError(_(
                    "Payroll batch %(batch)s cannot be deleted because its salary "
                    "journal entry has reconciled payments. Unreconcile or reverse "
                    "those payments first.",
                    batch=(self.filtered(lambda record: record.salary_move_id == move)[:1].name),
                ))
        for move in moves:
            if move.state == "posted":
                move.button_draft()
            if move.state == "draft":
                move.button_cancel()
            move.with_context(force_delete=True).unlink()
        return super().unlink()


class KioPayrollPayslip(models.Model):
    _name = "kio.payroll.payslip"
    _description = "Payroll Payslip"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_from desc, id desc"
    _check_company_auto = True

    # Contract allowance fields that make up an employee's payroll allowances.
    # All of them are fixed monetary amounts on the running contract.
    _CONTRACT_ALLOWANCE_FIELDS = (
        "kio_house_rent_allowance",
        "kio_medical_allowance",
        "kio_conveyance_allowance",
        "kio_food_allowance",
        "kio_mobile_allowance",
        "kio_transport_allowance",
        "kio_other_allowance",
    )

    name = fields.Char(required=True)
    number = fields.Char(copy=False, readonly=True)
    batch_id = fields.Many2one(
        "kio.payroll.batch",
        string="Payroll Batch",
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done"), ("cancel", "Cancelled")],
        default="draft",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many("kio.payroll.payslip.line", "payslip_id", string="Lines")
    note = fields.Text()

    basic_salary = fields.Monetary(compute="_compute_amounts", store=True)
    allowance = fields.Monetary(compute="_compute_amounts", store=True)
    overtime = fields.Monetary(compute="_compute_amounts", store=True)
    commission = fields.Monetary(compute="_compute_amounts", store=True)
    bonus = fields.Monetary(compute="_compute_amounts", store=True)
    deduction = fields.Monetary(compute="_compute_amounts", store=True)
    gross_salary = fields.Monetary(compute="_compute_amounts", store=True)
    net_pay = fields.Monetary(compute="_compute_amounts", store=True)

    paid = fields.Boolean(string="Paid", copy=False, default=False)
    payment_date = fields.Date(string="Payment Date", copy=False)
    payment_journal_id = fields.Many2one(
        "account.journal", string="Payment Journal", copy=False, check_company=True
    )
    payment_move_id = fields.Many2one(
        "account.move", string="Payment Entry", copy=False, readonly=True, check_company=True
    )
    kio_payment_move_id = fields.Many2one(
        "account.move", string="Salary Payment Entry", copy=False, readonly=True, check_company=True
    )
    salary_move_id = fields.Many2one(
        "account.move",
        string="Salary Payable Entry",
        copy=False,
        readonly=True,
        check_company=True,
        help="Posted salary accrual entry used by the standard Register Payment wizard.",
    )

    _sql_constraints = [
        (
            "kio_payroll_payslip_employee_period_company_uniq",
            "unique(employee_id, company_id, date_from, date_to)",
            "A payslip already exists for this employee and period.",
        ),
    ]

    @api.depends("line_ids.total", "line_ids.code")
    def _compute_amounts(self):
        for slip in self:
            totals = Counter()
            for line in slip.line_ids:
                totals[(line.code or "").upper()] += line.total
            basic = totals.get("BASIC", 0.0)
            allowance = totals.get("ALW", 0.0)
            overtime = totals.get("OVERTIME", 0.0) or totals.get("OT", 0.0)
            commission = totals.get("COMMISSION", 0.0) or totals.get("COM", 0.0)
            bonus = totals.get("BONUS", 0.0)
            deduction = abs(totals.get("DED", 0.0) or totals.get("DEDUCTION", 0.0))
            gross = totals.get("GROSS", 0.0)
            if not gross:
                gross = basic + allowance + overtime + commission + bonus
            net = totals.get("NET", 0.0)
            if not net:
                net = gross - deduction
            slip.basic_salary = basic
            slip.allowance = allowance
            slip.overtime = overtime
            slip.commission = commission
            slip.bonus = bonus
            slip.deduction = deduction
            slip.gross_salary = gross
            slip.net_pay = net

    # ------------------------------------------------------------------
    # Helpers used by dashboard / JS / report
    # ------------------------------------------------------------------
    @api.model
    def _check_payroll_overview_manager(self):
        if not self.env.user.has_group(
            "kio_payroll_overview_extension.group_kio_payroll_manager"
        ):
            raise AccessError(_("Only Payroll Managers can access Payroll Overview."))

    def _get_kio_net_pay_amount(self):
        self.ensure_one()
        return self.company_id.currency_id.round(self.net_pay)

    def _get_kio_payment_partner(self):
        """Return the employee partner used on the salary payable entry."""
        self.ensure_one()
        employee = self.employee_id
        partner = employee.work_contact_id or employee.user_partner_id
        if not partner:
            raise UserError(_(
                "Employee %(employee)s has no payment partner. Set the "
                "employee's Work Contact (or linked user) before registering "
                "the salary payment.",
                employee=employee.display_name,
            ))
        if partner.company_id and partner.company_id != self.company_id:
            raise UserError(_(
                "The payment partner of %(employee)s belongs to another "
                "company. Please use a contact from %(company)s.",
                employee=employee.display_name,
                company=self.company_id.display_name,
            ))
        return partner

    def _get_kio_payment_reference(self):
        """Memo/reference shared by the accrual entry and the payment."""
        self.ensure_one()
        batch_reference = (
            self.batch_id.name
            or self.name
            or _("Payroll")
        )
        return "%s - %s" % (batch_reference, self.employee_id.display_name)

    def _get_kio_salary_payable_lines(self, move=None, only_due=False):
        """Return the payable lines of the salary accrual entry.

        :param move: optional account.move; defaults to ``salary_move_id``.
        :param only_due: keep only lines that still have an unreconciled
            amount. Fully reconciled lines are returned otherwise so payment
            matching/status can still be inspected.
        """
        self.ensure_one()
        move = move or self.salary_move_id
        if not move or move.state != "posted":
            return self.env["account.move.line"]
        partner = self._get_kio_payment_partner()
        lines = move.line_ids.filtered(
            lambda line: line.account_id.account_type == "liability_payable"
            and line.partner_id == partner
        )
        if only_due:
            currency = move.company_id.currency_id
            lines = lines.filtered(
                lambda line: not currency.is_zero(line.amount_residual)
            )
        return lines

    def _get_kio_salary_payment_info(self):
        """Return paid/unpaid amounts derived from reconciliation.

        The salary payable entry is the source of truth. Partial payments are
        therefore supported automatically: the payable line residual is the
        unpaid salary and the difference is the paid amount.
        """
        self.ensure_one()
        currency = self.company_id.currency_id or self.currency_id
        net_amount = currency.round(self.net_pay)
        paid_amount = 0.0
        unpaid_amount = net_amount if net_amount > 0 else 0.0
        source = "none"

        payable_lines = self._get_kio_salary_payable_lines()
        if payable_lines:
            source = "salary_move"
            residual = sum(abs(line.amount_residual) for line in payable_lines)
            unpaid_amount = min(net_amount, currency.round(residual))
            unpaid_amount = max(unpaid_amount, 0.0)
            paid_amount = max(currency.round(net_amount - unpaid_amount), 0.0)
        elif self.salary_move_id and self.salary_move_id.state == "draft":
            source = "draft_salary_move"
        else:
            legacy_move = self.payment_move_id or self.kio_payment_move_id
            if self.paid or (legacy_move and legacy_move.state == "posted"):
                source = "legacy_payment"
                paid_amount = max(net_amount, 0.0)
                unpaid_amount = 0.0

        if net_amount <= 0:
            is_paid = False
            payment_state = "unpaid"
        elif unpaid_amount <= 0:
            is_paid = True
            payment_state = "paid"
        elif paid_amount > 0:
            is_paid = False
            payment_state = "partial"
        else:
            is_paid = False
            payment_state = "unpaid"

        return {
            "net_amount": net_amount,
            "paid_amount": paid_amount,
            "unpaid_amount": unpaid_amount,
            "is_paid": is_paid,
            "payment_state": payment_state,
            "source": source,
        }

    def _is_kio_salary_paid(self):
        self.ensure_one()
        return self._get_kio_salary_payment_info()["is_paid"]

    def _validate_kio_salary_accounting(self):
        """Validate the company payroll accounting configuration."""
        self.ensure_one()
        company = self.company_id
        journal = company.salary_journal_id
        debit_account = company.salary_debit_account_id
        credit_account = company.salary_credit_account_id

        missing = []
        if not journal:
            missing.append(_("Salary Journal"))
        if not debit_account:
            missing.append(_("Salary Debit Account"))
        if not credit_account:
            missing.append(_("Salary Credit Account"))
        if missing:
            raise UserError(_(
                "Payroll accounting is not configured. Set the following "
                "values in Payroll Accounting Configuration: %(fields)s.",
                fields=", ".join(missing),
            ))

        if journal.company_id and journal.company_id != company:
            raise UserError(_(
                "Salary Journal must belong to %(company)s.",
                company=company.display_name,
            ))
        if journal.type != "general":
            raise UserError(_(
                "Salary Journal must be a Miscellaneous journal."
            ))
        if debit_account.deprecated or debit_account.account_type not in (
            "expense",
            "expense_direct_cost",
            "expense_depreciation",
        ):
            raise UserError(_(
                "Salary Debit Account must be an active expense account."
            ))
        if credit_account.deprecated or credit_account.account_type != "liability_payable":
            raise UserError(_(
                "Salary Credit Account must be an active Payable account. "
                "Odoo's Register Payment wizard only reconciles Payable or "
                "Receivable journal items."
            ))
        return journal, debit_account, credit_account

    def _find_kio_existing_salary_move(self, debit_account, credit_account,
                                       partner, net_amount):
        """Find a compatible posted salary accrual to avoid duplicates."""
        self.ensure_one()
        if not self.date_from or not self.date_to or net_amount <= 0:
            return self.env["account.move"]
        candidates = self.env["account.move.line"].search([
            ("company_id", "=", self.company_id.id),
            ("move_id.state", "=", "posted"),
            ("move_id.move_type", "=", "entry"),
            ("account_id", "=", credit_account.id),
            ("partner_id", "=", partner.id),
            ("credit", ">", 0.0),
            ("date", ">=", self.date_from),
            ("date", "<=", self.date_to),
        ], order="date desc, id desc")
        currency = self.company_id.currency_id
        for line in candidates:
            move = line.move_id
            payable_total = sum(
                abs(item.balance)
                for item in move.line_ids
                if item.account_id == credit_account
            )
            expense_total = sum(
                item.debit
                for item in move.line_ids
                if item.account_id == debit_account
            )
            if (
                currency.compare_amounts(payable_total, net_amount) == 0
                and currency.compare_amounts(expense_total, net_amount) == 0
            ):
                return move
        return self.env["account.move"]

    def _ensure_kio_salary_payable_move(self):
        """Return a posted salary accrual entry, creating it only if needed.

        The entry debits the configured salary expense account and credits the
        configured salary payable account. The payable line is linked to the
        employee payment partner so it is eligible for the standard Register
        Payment wizard.
        """
        self.ensure_one()
        if self.batch_id and self.batch_id.salary_move_id:
            move = self.batch_id.salary_move_id
            if move.state == "posted":
                self.sudo().write({"salary_move_id": move.id})
                return move
            if move.state == "draft":
                move.action_post()
                self.sudo().write({"salary_move_id": move.id})
                return move
        net_amount = self._get_kio_net_pay_amount()
        if net_amount <= 0:
            raise UserError(_("This payslip has no payable net salary amount."))

        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)", (0x4B4950, self.id)
        )
        # Re-read after taking the lock to avoid duplicate accrual entries
        # when Pay Now is clicked more than once concurrently.
        self.invalidate_recordset(["salary_move_id"])

        move = self.salary_move_id
        if move and move.state == "cancel":
            move = self.env["account.move"]
        if move and move.state == "posted":
            return move
        if move and move.state == "draft":
            move.action_post()
            return move

        journal, debit_account, credit_account = (
            self._validate_kio_salary_accounting()
        )
        partner = self._get_kio_payment_partner()

        existing = self._find_kio_existing_salary_move(
            debit_account, credit_account, partner, net_amount
        )
        if existing:
            self.sudo().write({"salary_move_id": existing.id})
            return existing

        move_date = (
            self.batch_id.payment_date
            or self.date_to
            or fields.Date.context_today(self)
        )
        reference = self._get_kio_payment_reference()
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": journal.id,
            "date": move_date,
            "ref": reference,
            "company_id": self.company_id.id,
            "line_ids": [
                Command.create({
                    "name": reference,
                    "account_id": debit_account.id,
                    "partner_id": partner.id,
                    "debit": net_amount,
                    "credit": 0.0,
                }),
                Command.create({
                    "name": reference,
                    "account_id": credit_account.id,
                    "partner_id": partner.id,
                    "debit": 0.0,
                    "credit": net_amount,
                }),
            ],
        })
        move.action_post()
        self.sudo().write({"salary_move_id": move.id})
        return move

    def _sync_kio_payment_state(self, payment_move=None):
        """Persist the payment status derived from the payable reconciliation."""
        self.ensure_one()
        info = self._get_kio_salary_payment_info()
        values = {"paid": info["is_paid"]}
        if payment_move:
            values["payment_move_id"] = payment_move.id
            values["payment_date"] = payment_move.date
        elif info["is_paid"]:
            values["payment_date"] = fields.Date.context_today(self)
        self.sudo().write(values)

    def _prepare_kio_pay_now_action(self):
        """Build the standard Register Payment action for this payslip."""
        self.ensure_one()
        if self.state == "cancel" or (
            self.batch_id and self.batch_id.state == "cancel"
        ):
            raise UserError(_("A cancelled payroll cannot be paid."))

        net_amount = self._get_kio_net_pay_amount()
        if net_amount <= 0:
            raise UserError(_("This payslip has no payable net salary amount."))

        self._get_kio_payment_partner()
        self._validate_kio_salary_accounting()

        if self._get_kio_salary_payment_info()["is_paid"]:
            raise UserError(_(
                "The salary of %(employee)s is already fully paid.",
                employee=self.employee_id.display_name,
            ))

        self._ensure_kio_salary_payable_move()
        if self._get_kio_salary_payment_info()["is_paid"]:
            raise UserError(_(
                "The salary of %(employee)s is already fully paid.",
                employee=self.employee_id.display_name,
            ))

        payable_lines = self._get_kio_salary_payable_lines(only_due=True)
        if not payable_lines:
            raise UserError(_(
                "No unpaid salary payable line was found for %(employee)s. "
                "Check the salary payable entry and its reconciliation.",
                employee=self.employee_id.display_name,
            ))
        if any(not line.partner_id for line in payable_lines):
            raise UserError(_(
                "The salary payable entry of %(employee)s is not linked to an "
                "employee payment partner.",
                employee=self.employee_id.display_name,
            ))

        reference = self._get_kio_payment_reference()
        context = {
            "active_model": "account.move.line",
            "active_ids": payable_lines.ids,
            "default_communication": reference,
            "kio_payroll_pay_now": True,
            "kio_payroll_slip_id": self.id,
        }
        payment_date = self.batch_id.payment_date
        if payment_date:
            context["default_payment_date"] = payment_date

        view = self.env.ref(
            "account.view_account_payment_register_form", raise_if_not_found=False
        )
        return {
            "name": _("Register Payment"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment.register",
            "view_mode": "form",
            "views": [(view.id if view else False, "form")],
            "target": "new",
            "context": context,
        }

    @api.model
    def action_payroll_pay_now(self, slip_id):
        """Open the standard Register Payment wizard for a payslip."""
        self._check_payroll_overview_manager()
        try:
            slip_id = int(slip_id)
        except (TypeError, ValueError):
            raise ValidationError(_("A valid payslip is required."))
        slip = self.search([
            ("id", "=", slip_id),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not slip:
            raise AccessError(_(
                "The selected payslip is unavailable for the current company."
            ))
        slip.check_access_rights("read")
        return slip._prepare_kio_pay_now_action()

    @api.model
    def action_payroll_download_payslip(self, slip_id):
        """Download the custom payslip PDF for the selected payslip."""
        self._check_payroll_overview_manager()
        try:
            slip_id = int(slip_id)
        except (TypeError, ValueError):
            raise ValidationError(_("A valid payslip is required."))
        slip = self.search([
            ("id", "=", slip_id),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not slip:
            raise AccessError(_(
                "The selected payslip is unavailable for the current company."
            ))
        slip.check_access_rights("read")
        report = self.env.ref(
            "kio_payroll_overview_extension.action_report_employee_payslip",
            raise_if_not_found=False,
        )
        if not report:
            raise UserError(_(
                "The Employee Payslip report is not available. "
                "Please update the KIO Payroll Overview Extension module."
            ))
        return report.report_action(slip)

    @api.model
    def action_payroll_download_batch_report(self, batch_id):
        """Download the PDF summary for one authorized payroll batch."""
        self._check_payroll_overview_manager()
        batch = self._get_authorized_payroll_batch(batch_id)
        report = self.env.ref(
            "kio_payroll_overview_extension.action_report_payroll_batch",
            raise_if_not_found=False,
        )
        if not report:
            raise UserError(_(
                "The Payroll Batch PDF report is unavailable. Update the "
                "KIO Payroll Overview Extension module."
            ))
        return report.report_action(batch)

    @api.model
    def action_payroll_show_payments(self, slip_id):
        """Open payments reconciled against this payslip's payable line(s)."""
        self._check_payroll_overview_manager()
        try:
            slip_id = int(slip_id)
        except (TypeError, ValueError):
            raise ValidationError(_("A valid payslip is required."))
        company = self.env.company
        slip = self.search([
            ("id", "=", slip_id),
            ("company_id", "=", company.id),
        ], limit=1)
        if not slip:
            raise AccessError(_(
                "The selected payslip is unavailable for the current company."
            ))
        slip.check_access_rights("read")
        slip.check_access_rule("read")

        payable_lines = slip._get_kio_salary_payable_lines()
        payment_moves = (
            payable_lines.mapped("matched_debit_ids.debit_move_id.move_id")
            | payable_lines.mapped("matched_credit_ids.credit_move_id.move_id")
        ).filtered(lambda move: move != slip.salary_move_id and move.state == "posted")
        legacy_payment_moves = (slip.payment_move_id | slip.kio_payment_move_id).filtered(
            lambda move: move.state == "posted"
        )
        payments = (payment_moves | legacy_payment_moves).mapped("payment_id").filtered(
            lambda payment: payment.company_id == company
        )
        payments.check_access_rights("read")
        payments.check_access_rule("read")
        if not payments:
            raise UserError(_("No registered payments are linked to this payslip."))

        return {
            "type": "ir.actions.act_window",
            "name": _("Payments: %s") % slip.employee_id.display_name,
            "res_model": "account.payment",
            "view_mode": "tree,form",
            "views": [
                (self.env.ref("account.view_account_payment_tree").id, "tree"),
                (self.env.ref("account.view_account_payment_form").id, "form"),
            ],
            "domain": [("id", "in", payments.ids)],
            "context": {
                "create": False,
                "default_company_id": company.id,
                "search_default_group_by_partner": False,
            },
            "target": "current",
        }

    @api.model
    def _get_payroll_overview_period(self, month, year):
        try:
            month = int(month)
            year = int(year)
        except (TypeError, ValueError):
            raise ValidationError(_("Month and year must be valid numbers."))
        if month not in range(0, 13) or year not in range(1, 10000):
            raise ValidationError(_("Month must be between 0 and 12 and year must be valid."))
        if month == 0:
            return month, year, date(year, 1, 1), date(year, 12, 31)
        return (
            month,
            year,
            date(year, month, 1),
            date(year, month, calendar.monthrange(year, month)[1]),
        )

    @api.model
    def _get_authorized_payroll_batch(self, batch_id, write=False):
        try:
            batch_id = int(batch_id)
        except (TypeError, ValueError):
            raise ValidationError(_("A valid payslip batch is required."))
        if batch_id <= 0:
            raise ValidationError(_("A valid payslip batch is required."))
        batch_model = self.env["kio.payroll.batch"]
        batch_model.check_access_rights("write" if write else "read")
        batch = batch_model.search([
            ("id", "=", batch_id),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not batch:
            raise AccessError(_("The selected payroll batch is unavailable for the current company."))
        return batch

    @api.model
    def _get_employee_salary_config(self, employees, company):
        config_model = self.env["kio.payroll.salary.config"]
        configs = config_model.search([
            ("employee_id", "in", employees.ids),
            ("company_id", "=", company.id),
            ("active", "=", True),
        ])
        return {cfg.employee_id.id: cfg for cfg in configs}

    @api.model
    def _get_contract_total_allowance(self, contract, currency=None):
        """Return the applicable contract's total allowance.

        The employee's running contract is the single source of truth. All
        seven allowance fields are fixed monetary amounts and are summed
        exactly once; House Rent is never recomputed as a percentage of the
        basic wage. Historical payslips keep the amounts stored in their
        lines and are not recomputed from current contract values.
        """
        if not contract:
            return 0.0
        currency = currency or contract.currency_id or contract.company_id.currency_id
        amount = sum(
            (getattr(contract, field_name, 0.0) or 0.0)
            for field_name in self._CONTRACT_ALLOWANCE_FIELDS
            if field_name in contract._fields
        )
        return currency.round(amount) if currency else amount

    @api.model
    def _get_employee_contracts(self, employees, company, date_start, date_end):
        """Return eligible running contracts per employee for the period.

        Only standard Odoo 17 running contracts (``state = 'open'``) are
        considered. A contract is applicable when it overlaps the payroll
        period:
        date_start <= payroll end and (date_end is empty or date_end >=
        payroll start).

        The result is ``(contract_by_employee, ambiguous_employee_ids)``.
        Employees with more than one overlapping running contract are
        flagged as ambiguous instead of silently choosing one of them.
        Multiple non-overlapping running contracts are allowed; the most
        recent contract covering the period is used.
        """
        if not employees or "hr.contract" not in self.env.registry.models:
            return {}, set()
        contracts = self.env["hr.contract"].search([
            ("employee_id", "in", employees.ids),
            ("company_id", "=", company.id),
            ("active", "=", True),
            ("state", "=", "open"),
            ("date_start", "<=", date_end),
            "|",
            ("date_end", "=", False),
            ("date_end", ">=", date_start),
        ], order="employee_id, date_start asc, id asc")

        contracts_by_employee = {}
        for contract in contracts:
            contracts_by_employee.setdefault(
                contract.employee_id.id, []
            ).append(contract)

        contract_by_employee = {}
        ambiguous_employee_ids = set()
        for employee_id, employee_contracts in contracts_by_employee.items():
            if len(employee_contracts) == 1:
                contract_by_employee[employee_id] = employee_contracts[0]
                continue

            # Multiple running contracts are only safe when they do not
            # overlap each other. Overlap makes the payable contract
            # ambiguous for the selected period.
            overlaps = False
            for previous, current in zip(
                employee_contracts, employee_contracts[1:]
            ):
                if not previous.date_end or previous.date_end >= current.date_start:
                    overlaps = True
                    break
            if overlaps:
                ambiguous_employee_ids.add(employee_id)
            else:
                # Contracts are sequential: the latest one applies.
                contract_by_employee[employee_id] = employee_contracts[-1]
        return contract_by_employee, ambiguous_employee_ids

    @api.model
    def _count_scheduled_working_days(self, calendar, date_start, date_end,
                                      resource=None):
        """Count scheduled working dates in a payroll period.

        Dates are evaluated as calendar-local dates using the working
        schedule's timezone. Only schedule lines are used; attendance
        check-ins are deliberately ignored. Split shifts are de-duplicated
        by collecting distinct dates, and overnight lines are attached to
        their scheduled start date.
        """
        if not calendar or not date_start or not date_end or date_end < date_start:
            return None

        attendances = calendar.attendance_ids.filtered(
            lambda attendance: not attendance.display_type
            and attendance.day_period != "lunch"
        )
        if resource:
            # Include the calendar's common schedule and any schedule
            # lines configured specifically for this employee resource.
            attendances = attendances.filtered(
                lambda attendance: not attendance.resource_id
                or attendance.resource_id == resource
            )
        else:
            # The company/default calendar reference must not depend on an
            # arbitrary employee's resource-specific schedule.
            attendances = attendances.filtered(
                lambda attendance: not attendance.resource_id
            )
        if not attendances:
            return 0

        attendance_model = self.env["resource.calendar.attendance"]
        working_dates = set()
        current_date = date_start
        while current_date <= date_end:
            weekday = str(current_date.weekday())
            week_type = (
                str(attendance_model.get_week_type(current_date))
                if calendar.two_weeks_calendar else False
            )
            for attendance in attendances:
                if str(attendance.dayofweek) != weekday:
                    continue
                if (
                    calendar.two_weeks_calendar
                    and attendance.week_type
                    and str(attendance.week_type) != week_type
                ):
                    continue
                if attendance.date_from and current_date < attendance.date_from:
                    continue
                if attendance.date_to and current_date > attendance.date_to:
                    continue
                hour_from = attendance.hour_from or 0.0
                hour_to = attendance.hour_to or 0.0
                if hour_from == hour_to:
                    continue
                # A non-zero interval is a worked day. hour_to < hour_from
                # represents an overnight shift and is still valid.
                working_dates.add(current_date)
                break
            current_date += timedelta(days=1)
        return len(working_dates)

    @api.model
    def _get_payroll_bonus_amounts(self, company, date_start, date_end, employee_ids=None):
        if "kio.bonus.line" not in self.env.registry.models:
            return {}
        return self.env["kio.bonus.line"]._get_payroll_bonus_amounts(
            company, date_start, date_end, employee_ids=employee_ids, pending_only=True
        )

    @api.model
    def _get_payroll_adjustment_amounts(
        self, model_name, company, date_start, date_end, employee_ids=None, amount_field="amount"
    ):
        """Return confirmed adjustment totals grouped by employee for the period.

        Only confirmed records matching employee/company/date range are included.
        Records already applied to a non-cancelled payslip are excluded when the
        model supports payroll-application tracking.
        """
        Model = self.env.get(model_name)
        if not Model or "state" not in Model._fields or "date" not in Model._fields:
            return {}
        domain = [
            ("state", "=", "confirmed"),
            ("company_id", "=", company.id),
            ("date", ">=", date_start),
            ("date", "<=", date_end),
        ]
        if employee_ids:
            domain.append(("employee_id", "in", list(employee_ids)))
        if "applied" in Model._fields and "applied_payslip_id" in Model._fields:
            domain += ["|", ("applied", "=", False), ("applied_payslip_id.state", "=", "cancel")]
        rows = Model.read_group(
            domain,
            [f"{amount_field}:sum"],
            ["employee_id"],
            lazy=False,
        )
        amounts = {}
        sum_key = f"{amount_field}_sum"
        for row in rows:
            employee = row.get("employee_id")
            employee_id = employee[0] if isinstance(employee, (list, tuple)) else employee
            if employee_id:
                amounts[employee_id] = row.get(amount_field) or row.get(sum_key) or 0.0
        return amounts

    @api.model
    def _get_payroll_adjustment_records(
        self, model_name, company, date_start, date_end, employee_ids=None
    ):
        """Return confirmed adjustment records eligible for payroll inclusion.

        Used only for post-generation tracking (after successful payslip creation).
        """
        Model = self.env.get(model_name)
        if not Model or "state" not in Model._fields or "date" not in Model._fields:
            return Model.browse() if Model else self.env["ir.model"]  # unreachable fallback
        domain = [
            ("state", "=", "confirmed"),
            ("company_id", "=", company.id),
            ("date", ">=", date_start),
            ("date", "<=", date_end),
        ]
        if employee_ids:
            domain.append(("employee_id", "in", list(employee_ids)))
        if "applied" in Model._fields and "applied_payslip_id" in Model._fields:
            domain += ["|", ("applied", "=", False), ("applied_payslip_id.state", "=", "cancel")]
        return Model.search(domain)

    @api.model
    def _get_payroll_scope_department(self, payroll_scope, department_id):
        if payroll_scope not in ("all", "department"):
            raise ValidationError(_("Invalid payroll scope."))
        if payroll_scope == "all":
            if department_id:
                raise ValidationError(_("All Employees payroll cannot have a department."))
            return self.env["hr.department"]
        try:
            department_id = int(department_id)
        except (TypeError, ValueError):
            raise ValidationError(_("Select a valid department for department-wise payroll."))
        if department_id <= 0:
            raise ValidationError(_("Select a valid department for department-wise payroll."))
        department = self.env["hr.department"].search([
            ("id", "=", department_id), ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not department:
            raise AccessError(_("The department is unavailable for the current company."))
        return department

    @api.model
    def get_new_payroll_run_data(self, date_start, date_end, payroll_scope="all", department_id=False):
        self._check_payroll_overview_manager()
        department = self._get_payroll_scope_department(payroll_scope, department_id)
        try:
            date_start = fields.Date.to_date(date_start)
            date_end = fields.Date.to_date(date_end)
        except (TypeError, ValueError):
            raise ValidationError(_("Enter valid payroll start and end dates."))
        if not date_start or not date_end or date_end < date_start:
            raise ValidationError(_("The end date must be on or after the start date."))

        company = self.env.company
        currency = company.currency_id
        employee_domain = [
            ("company_id", "=", company.id),
            ("active", "=", True),
        ]
        if department:
            employee_domain.append(("department_id", "=", department.id))
        employees = self.env["hr.employee"].search(employee_domain, order="name, id")
        configs = self._get_employee_salary_config(employees, company)
        contracts, ambiguous_employee_ids = self._get_employee_contracts(
            employees, company, date_start, date_end
        )
        employee_ids = employees.ids
        pending_bonuses = self._get_payroll_bonus_amounts(
            company, date_start, date_end, employee_ids=employee_ids
        )
        # Confirmed adjustments: overtime (attendance/config model, monetary amount),
        # commission, and deductions. Late deduction is integrated via kio.deduction
        # confirmed records only; monthly late deduction summaries are not combined
        # here to avoid double-counting the same penalty.
        overtime_amounts = self._get_payroll_adjustment_amounts(
            "kio.overtime", company, date_start, date_end, employee_ids=employee_ids, amount_field="overtime_amount"
        )
        commission_amounts = self._get_payroll_adjustment_amounts(
            "kio.commission", company, date_start, date_end, employee_ids=employee_ids
        )
        deduction_amounts = self._get_payroll_adjustment_amounts(
            "kio.deduction", company, date_start, date_end, employee_ids=employee_ids, amount_field="deduction_amount"
        )
        existing_payslips = self.search([
            ("employee_id", "in", employee_ids),
            ("company_id", "=", company.id),
            ("date_from", "<=", date_end),
            ("date_to", ">=", date_start),
            ("state", "!=", "cancel"),
        ]) if employees else self.browse()
        existing_by_employee = {s.employee_id.id for s in existing_payslips}

        rows = []
        seen_employee_ids = set()
        invalid_wage_count = 0
        for employee in employees:
            if employee.id in seen_employee_ids:
                continue
            seen_employee_ids.add(employee.id)

            contract = contracts.get(employee.id)
            # Employees without a unique Running Contract are excluded
            # completely from the New Payroll Run employee list.
            if not contract:
                continue

            basic = contract.wage or 0.0
            if basic <= 0:
                invalid_wage_count += 1
                continue

            # Basic and allowances come from the applicable running contract.
            allowance = self._get_contract_total_allowance(contract, currency)
            overtime = overtime_amounts.get(employee.id, 0.0) or 0.0
            commission = commission_amounts.get(employee.id, 0.0) or 0.0
            bonus = pending_bonuses.get(employee.id, 0.0) or 0.0
            deduction = deduction_amounts.get(employee.id, 0.0) or 0.0
            # Gross = Basic + Allowances + Overtime + Commission + Bonus; Net = Gross - Deductions
            gross = basic + allowance + overtime + commission + bonus
            net_pay = gross - deduction
            basic = currency.round(basic)
            allowance = currency.round(allowance)
            overtime = currency.round(overtime)
            commission = currency.round(commission)
            bonus = currency.round(bonus)
            deduction = currency.round(deduction)
            gross = currency.round(gross)
            net_pay = currency.round(net_pay)

            calendar = (
                contract.resource_calendar_id
                or employee.resource_calendar_id
                or company.resource_calendar_id
            )
            if contract.resource_calendar_id:
                calendar_source = "contract"
            elif employee.resource_calendar_id:
                calendar_source = "employee"
            elif company.resource_calendar_id:
                calendar_source = "company"
            else:
                calendar_source = False
            contract_start = max(date_start, contract.date_start)
            contract_end = min(date_end, contract.date_end) if contract.date_end else date_end
            working_days = self._count_scheduled_working_days(
                calendar,
                contract_start,
                contract_end,
                resource=employee.resource_id,
            )

            rows.append({
                "employee_id": employee.id,
                "name": employee.display_name,
                "identification_id": employee.identification_id or "-",
                "avatar_url": f"/web/image/hr.employee/{employee.id}/avatar_128",
                "department": employee.department_id.display_name or "-",
                "designation": employee.job_id.display_name or "-",
                "basic_salary": currency.round(basic),
                "allowance": currency.round(allowance),
                "overtime": currency.round(overtime),
                "commission": currency.round(commission),
                "bonus": currency.round(bonus),
                "deduction": currency.round(deduction),
                "net_pay": currency.round(net_pay),
                "working_days": working_days,
                "working_days_available": working_days is not None,
                "working_calendar_id": calendar.id if calendar else False,
                "working_calendar_name": calendar.display_name if calendar else False,
                "working_days_source": calendar_source,
                "eligible": True,
                "contract_id": contract.id,
                "contract_name": contract.name,
                "contract_status": contract.state,
                "contract_status_label": dict(
                    contract._fields["state"].selection
                ).get(contract.state, contract.state),
                "has_existing_payslip": employee.id in existing_by_employee,
            })

        employee_count = len(rows)
        company_calendar = company.resource_calendar_id
        payroll_working_days = self._count_scheduled_working_days(
            company_calendar, date_start, date_end
        )
        working_days_available = payroll_working_days is not None
        working_days_message = (
            False if working_days_available
            else _("No default Working Schedule is configured for this company.")
        )
        return {
            "company": {"id": company.id, "name": company.display_name},
            "currency": {
                "id": currency.id,
                "name": currency.name,
                "symbol": currency.symbol,
                "position": currency.position,
                "decimal_places": currency.decimal_places,
            },
            "date_start": date_start,
            "date_end": date_end,
            "default_name": "%s Payroll" % date_end.strftime("%B %Y"),
            "payment_date": date_end,
            "employee_count": employee_count,
            "eligible_employee_count": employee_count,
            "total_employee_count": employee_count,
            "ambiguous_contract_count": len(ambiguous_employee_ids),
            "invalid_wage_count": invalid_wage_count,
            "working_days": payroll_working_days,
            "working_days_available": working_days_available,
            "working_days_message": working_days_message,
            "working_calendar_id": company_calendar.id if company_calendar else False,
            "working_calendar_name": company_calendar.display_name if company_calendar else False,
            "employees": rows,
            "loan_count": 0,
            "loan_available": False,
            "leave_available": False,
            "leave_action": False,
        }

    @api.model
    def _prepare_payslip_lines(
        self, employee, cfg=None, bonus_amount=0.0, basic=None, allowance=None,
        overtime_amount=0.0, commission_amount=0.0, deduction_amount=0.0,
        contract=None, company=None,
    ):
        if basic is None:
            basic = contract.wage if contract and contract.wage else (
                (cfg.basic_salary or 0.0) if cfg else 0.0
            )
        if allowance is None:
            if contract:
                currency = (company or contract.company_id or self.env.company).currency_id
                allowance = self._get_contract_total_allowance(contract, currency)
            else:
                # Contract allowances are the payroll source of truth. Legacy
                # salary-config allowance is intentionally not added here.
                allowance = 0.0
        overtime = overtime_amount or 0.0
        commission = commission_amount or 0.0
        bonus = bonus_amount or 0.0
        deduction = deduction_amount or 0.0
        gross = basic + allowance + overtime + commission + bonus
        net = gross - deduction
        return [
            Command.create({"name": _("Basic Salary"), "code": "BASIC", "sequence": 1, "amount": basic, "total": basic}),
            Command.create({"name": _("Allowances"), "code": "ALW", "sequence": 5, "amount": allowance, "total": allowance}),
            Command.create({"name": _("Overtime"), "code": "OVERTIME", "sequence": 10, "amount": overtime, "total": overtime}),
            Command.create({"name": _("Commission"), "code": "COMMISSION", "sequence": 12, "amount": commission, "total": commission}),
            Command.create({"name": _("Bonus"), "code": "BONUS", "sequence": 15, "amount": bonus, "total": bonus}),
            Command.create({"name": _("Deductions"), "code": "DED", "sequence": 90, "amount": deduction, "total": deduction}),
            Command.create({"name": _("Gross"), "code": "GROSS", "sequence": 100, "amount": gross, "total": gross}),
            Command.create({"name": _("Net"), "code": "NET", "sequence": 200, "amount": net, "total": net}),
        ]

    @api.model
    def generate_new_payroll_run(self, values):
        self._check_payroll_overview_manager()
        if not isinstance(values, dict):
            raise ValidationError(_("Payroll run data is invalid."))
        payroll_scope = values.get("payroll_scope", "all")
        department = self._get_payroll_scope_department(payroll_scope, values.get("department_id"))
        name = (values.get("name") or "").strip()
        payroll_type = values.get("payroll_type") or "monthly"
        try:
            payment_date = fields.Date.to_date(values.get("payment_date"))
            date_start = fields.Date.to_date(values.get("date_start"))
            date_end = fields.Date.to_date(values.get("date_end"))
        except (TypeError, ValueError):
            raise ValidationError(_("Enter valid payroll dates."))
        if not name or not payment_date or not date_start or not date_end:
            raise ValidationError(_("Payroll name, payment date, start date, and end date are required."))
        if payroll_type != "monthly":
            raise ValidationError(_("Unsupported payroll type."))
        if date_end < date_start:
            raise ValidationError(_("The end date must be on or after the start date."))
        try:
            employee_ids = list(dict.fromkeys(int(v) for v in values.get("employee_ids", [])))
        except (TypeError, ValueError):
            raise ValidationError(_("Employee selection is invalid."))
        if not employee_ids:
            raise ValidationError(_("Select at least one eligible employee."))

        company = self.env.company
        employee_domain = [("id", "in", employee_ids), ("company_id", "=", company.id), ("active", "=", True)]
        if department:
            employee_domain.append(("department_id", "=", department.id))
        employees = self.env["hr.employee"].search(employee_domain)
        if set(employees.ids) != set(employee_ids):
            raise ValidationError(_("One or more selected employees are unavailable or do not belong to the selected payroll scope."))
        configs = self._get_employee_salary_config(employees, company)
        contracts, ambiguous_employee_ids = self._get_employee_contracts(
            employees, company, date_start, date_end
        )
        ambiguous = [
            emp.display_name
            for emp in employees
            if emp.id in ambiguous_employee_ids
        ]
        if ambiguous:
            raise ValidationError(_(
                "The following employees have multiple overlapping Running "
                "Contracts for this period, so payroll cannot choose one "
                "automatically: %s."
            ) % ", ".join(ambiguous))
        ineligible = [
            emp.display_name
            for emp in employees
            if not emp.active
            or emp.company_id != company
            or emp.id not in contracts
            or (contracts[emp.id].wage or 0.0) <= 0
        ]
        if ineligible:
            raise ValidationError(_(
                "The following employees do not have a valid Running Contract "
                "with a wage for this period: %s."
            ) % ", ".join(ineligible))

        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", (0x4B494F, company.id))
        duplicates = self.search([
            ("employee_id", "in", employees.ids),
            ("company_id", "=", company.id),
            ("date_from", "<=", date_end),
            ("date_to", ">=", date_start),
            ("state", "!=", "cancel"),
        ])
        if duplicates:
            raise ValidationError(_(
                "Existing payslips overlap this period for: %s. No new payroll was created."
            ) % ", ".join(duplicates.mapped("employee_id.display_name")))

        batch = self.env["kio.payroll.batch"].create({
            "name": name,
            "date_start": date_start,
            "date_end": date_end,
            "payment_date": payment_date,
            "payroll_type": payroll_type,
            "payroll_scope": payroll_scope,
            "department_id": department.id or False,
            "company_id": company.id,
            "state": "done",
        })
        # Server-side amounts only (frontend values are never trusted).
        employee_ids = employees.ids
        bonus_amounts = self._get_payroll_bonus_amounts(
            company, date_start, date_end, employee_ids=employee_ids
        )
        overtime_amounts = self._get_payroll_adjustment_amounts(
            "kio.overtime", company, date_start, date_end, employee_ids=employee_ids, amount_field="overtime_amount"
        )
        commission_amounts = self._get_payroll_adjustment_amounts(
            "kio.commission", company, date_start, date_end, employee_ids=employee_ids
        )
        deduction_amounts = self._get_payroll_adjustment_amounts(
            "kio.deduction", company, date_start, date_end, employee_ids=employee_ids, amount_field="deduction_amount"
        )
        payslip_vals = []
        for employee in employees:
            cfg = configs.get(employee.id)
            contract = contracts[employee.id]
            contract_allowance = self._get_contract_total_allowance(
                contract, company.currency_id
            )
            payslip_vals.append({
                "name": _("Payslip - %s") % employee.display_name,
                "batch_id": batch.id,
                "employee_id": employee.id,
                "company_id": company.id,
                "date_from": date_start,
                "date_to": date_end,
                "state": "draft",
                "line_ids": self._prepare_payslip_lines(
                    employee,
                    cfg,
                    bonus_amount=bonus_amounts.get(employee.id, 0.0),
                    basic=contract.wage or 0.0,
                    allowance=contract_allowance,
                    overtime_amount=overtime_amounts.get(employee.id, 0.0),
                    commission_amount=commission_amounts.get(employee.id, 0.0),
                    deduction_amount=deduction_amounts.get(employee.id, 0.0),
                    contract=contract,
                    company=company,
                ),
            })
        slips = self.create(payslip_vals)
        self._post_batch_salary_entry(batch, slips)
        self._mark_bonuses_applied(slips)
        self._mark_payroll_adjustments_applied(
            slips, company, date_start, date_end, employee_ids=employee_ids
        )
        return {
            "type": "ir.actions.client",
            "tag": "kio_payroll_overview.batch_details",
            "name": _("Payroll Batch Details"),
            "target": "current",
            "context": {
                "kio_batch_id": batch.id,
                "kio_payroll_month": date_start.month,
                "kio_payroll_year": date_start.year,
            },
        }

    @api.model
    def _post_batch_salary_entry(self, batch, slips):
        """Post one consolidated salary accrual with employee payable lines."""
        if not slips:
            return self.env["account.move"]
        total_net = batch.currency_id.round(sum(slips.mapped("net_pay")))
        if total_net <= 0:
            raise UserError(_("The payroll batch net total must be greater than zero."))
        journal, debit_account, credit_account = slips[:1]._validate_kio_salary_accounting()
        line_commands = [Command.create({
            "name": batch.name,
            "account_id": debit_account.id,
            "debit": total_net,
            "credit": 0.0,
        })]
        for slip in slips:
            amount = slip._get_kio_net_pay_amount()
            if amount <= 0:
                continue
            partner = slip._get_kio_payment_partner()
            line_commands.append(Command.create({
                "name": slip._get_kio_payment_reference(),
                "account_id": credit_account.id,
                "partner_id": partner.id,
                "debit": 0.0,
                "credit": amount,
            }))
        move = self.env["account.move"].create({
            "move_type": "entry",
            "journal_id": journal.id,
            "date": batch.payment_date or batch.date_end,
            "ref": batch.name,
            "company_id": batch.company_id.id,
            "line_ids": line_commands,
        })
        move.action_post()
        batch.sudo().write({"salary_move_id": move.id})
        slips.sudo().write({"salary_move_id": move.id})
        return move

    @api.model
    def _mark_bonuses_applied(self, slips):
        if "kio.bonus.line" not in self.env.registry.models or not slips:
            return
        bonus_model = self.env["kio.bonus.line"]
        for slip in slips:
            bonus_lines = bonus_model.search([
                ("company_id", "=", slip.company_id.id),
                ("bonus_id.state", "=", "confirmed"),
                ("employee_id", "=", slip.employee_id.id),
                ("bonus_id.bonus_date", ">=", slip.date_from),
                ("bonus_id.bonus_date", "<=", slip.date_to),
                ("applied", "=", False),
            ])
            if bonus_lines:
                bonus_lines.write({"applied": True, "applied_payslip_id": slip.id})

    @api.model
    def _mark_adjustments_applied_for_slip(self, slip, model_name, amount_field=None):
        Model = self.env.get(model_name)
        if not Model or not slip or "applied" not in Model._fields:
            return
        domain = [
            ("state", "=", "confirmed"),
            ("company_id", "=", slip.company_id.id),
            ("employee_id", "=", slip.employee_id.id),
            ("date", ">=", slip.date_from),
            ("date", "<=", slip.date_to),
            "|",
            ("applied", "=", False),
            ("applied_payslip_id.state", "=", "cancel"),
        ]
        records = Model.search(domain)
        if records:
            records.sudo().write({"applied": True, "applied_payslip_id": slip.id})

    @api.model
    def _mark_payroll_adjustments_applied(
        self, slips, company, date_start, date_end, employee_ids=None
    ):
        # Mark confirmed adjustments included in generated payslips. Called only
        # after successful payslip creation. Only kio.deduction (confirmed late
        # deduction records) is included; monthly late deduction summaries are not
        # consumed here to avoid double-counting.
        if not slips:
            return
        for slip in slips:
            self._mark_adjustments_applied_for_slip(slip, "kio.overtime")
            self._mark_adjustments_applied_for_slip(slip, "kio.commission")
            self._mark_adjustments_applied_for_slip(slip, "kio.deduction")

    @api.model
    def get_payroll_overview_data(self, month, year):
        self._check_payroll_overview_manager()
        month, year, period_start, period_end = self._get_payroll_overview_period(month, year)
        company = self.env.company
        payslip_domain = [
            ("company_id", "=", company.id),
            ("date_from", ">=", period_start),
            ("date_to", "<=", period_end),
            ("state", "in", ("draft", "done")),
        ]
        payslips = self.search(payslip_domain)
        batches = self.env["kio.payroll.batch"].search([
            ("company_id", "=", company.id),
            ("date_start", ">=", period_start),
            ("date_end", "<=", period_end),
        ], order="date_start desc, id desc")
        # Period headcount is distinct employees with eligible payslips, not
        # the sum of employee counts across batches (an employee may have
        # multiple payslips/batches in an all-months view).
        payroll_employee_ids = payslips.mapped("employee_id").ids
        total_employees_count = len(set(payroll_employee_ids))
        basic_salary = 0.0
        if "hr.contract" in self.env.registry.models:
            employees = self.env["hr.employee"].search([
                ("id", "in", payroll_employee_ids),
                ("company_id", "=", company.id),
            ]) if payroll_employee_ids else self.env["hr.employee"]
            if employees:
                contracts = self.env["hr.contract"].search([
                    ("employee_id", "in", employees.ids),
                    ("company_id", "=", company.id),
                    ("state", "=", "open"),
                    ("date_start", "<=", period_end),
                    "|",
                    ("date_end", "=", False),
                    ("date_end", ">=", period_start),
                ], order="employee_id, date_start desc, id desc")
                wage_by_employee = {}
                for contract in contracts:
                    emp_id = contract.employee_id.id
                    if emp_id not in wage_by_employee:
                        wage_by_employee[emp_id] = contract.wage or 0.0
                basic_salary = sum(wage_by_employee.values())

        total_allowance = sum(payslips.mapped("allowance"))
        gross_salary = sum(payslips.mapped("gross_salary"))
        total_deductions = sum(payslips.mapped("deduction"))
        net_salary = sum(payslips.mapped("net_pay"))
        payment_infos = {
            slip.id: slip._get_kio_salary_payment_info() for slip in payslips
        }
        total_paid_salary = sum(
            info["paid_amount"] for info in payment_infos.values()
        )
        total_unpaid_salary = sum(
            info["unpaid_amount"] for info in payment_infos.values()
        )
        cur = company.currency_id
        confirmed_bonus_total = 0.0
        if "kio.bonus.line" in self.env.registry.models:
            confirmed_bonus_total = self.env["kio.bonus.line"]._get_payroll_bonus_total(
                company, period_start, period_end, pending_only=False
            )

        recent_batches = []
        visible_batches = batches if month == 0 else batches[:10]
        for batch in visible_batches:
            batch_slips = payslips.filtered(lambda s: s.batch_id.id == batch.id)
            recent_batches.append({
                "id": batch.id,
                "name": batch.name,
                "payroll_scope": batch.payroll_scope,
                "department": batch.department_id.display_name or False,
                "date_start": batch.date_start,
                "date_end": batch.date_end,
                "payment_date": batch.payment_date,
                "payslip_count": len(batch_slips),
                "total_employees": len(batch_slips.mapped("employee_id")),
                "total_net_pay": cur.round(sum(batch_slips.mapped("net_pay"))),
                "state": batch.state,
                "state_label": dict(batch._fields["state"].selection).get(batch.state, batch.state),
            })

        detail_rows = []
        for slip in payslips.sorted(key=lambda s: (s.employee_id.name or "", s.id)):
            emp = slip.employee_id
            info = payment_infos[slip.id]
            detail_rows.append({
                "slip_id": slip.id,
                "batch_id": slip.batch_id.id,
                "batch_name": slip.batch_id.name or "-",
                "employee_id": emp.id,
                "employee_name": emp.display_name,
                "name": emp.display_name,
                "identification_id": emp.identification_id or "-",
                "department": emp.department_id.display_name or "-",
                "designation": emp.job_id.display_name or "-",
                "basic_salary": cur.round(slip.basic_salary),
                "allowance": cur.round(slip.allowance),
                "overtime": cur.round(slip.overtime),
                "bonus": cur.round(slip.bonus),
                "deduction": cur.round(slip.deduction),
                "net_pay": cur.round(slip.net_pay),
                "net_salary": cur.round(slip.net_pay),
                "paid_amount": cur.round(info["paid_amount"]),
                "unpaid_amount": cur.round(info["unpaid_amount"]),
                "paid": info["is_paid"],
                "payment_state": info["payment_state"],
                "payment_state_label": dict([
                    ("paid", _("Paid")),
                    ("partial", _("Partially Paid")),
                    ("unpaid", _("Unpaid")),
                ])[info["payment_state"]],
            })

        return {
            "period": {"month": month, "year": year, "date_start": period_start, "date_end": period_end, "policy": "full_period"},
            "company": {"id": company.id, "name": company.display_name},
            "currency": {"id": cur.id, "name": cur.name, "symbol": cur.symbol, "position": cur.position, "decimal_places": cur.decimal_places},
            "kpis": {
                "total_employees": total_employees_count,
                "basic_salary": cur.round(basic_salary),
                "total_allowance": cur.round(total_allowance),
                "payslip_batches": len(batches),
                "draft_payslips": len(payslips.filtered(lambda s: s.state == "draft")),
                "done_payslips": len(payslips.filtered(lambda s: s.state == "done")),
                "gross_salary": cur.round(gross_salary),
                "total_deductions": cur.round(total_deductions),
                "net_salary": cur.round(net_salary),
                "total_salary": cur.round(net_salary),
                "total_paid_salary": cur.round(total_paid_salary),
                "total_unpaid_salary": cur.round(total_unpaid_salary),
                "total_bonus": cur.round(confirmed_bonus_total),
            },
            "recent_batches": recent_batches,
            "paid_employees": [row for row in detail_rows if row["paid"]],
            "unpaid_employees": [row for row in detail_rows if not row["paid"]],
            "employee_payroll_details": {
                "rows": detail_rows,
                "totals": {
                    "overtime": cur.round(sum(r["overtime"] for r in detail_rows)),
                    "bonus": cur.round(confirmed_bonus_total),
                },
            },
        }

    @api.model
    def get_payroll_batch_details(self, batch_id):
        self._check_payroll_overview_manager()
        batch = self._get_authorized_payroll_batch(batch_id)
        company = self.env.company
        currency = company.currency_id
        slips = self.search([
            ("batch_id", "=", batch.id),
            ("company_id", "=", company.id),
        ], order="employee_id, id")
        employees = slips.mapped("employee_id")
        contracts_by_employee = {}
        if employees and batch.date_start and batch.date_end and "hr.contract" in self.env.registry.models:
            contracts, _ambiguous = self._get_employee_contracts(
                employees, company, batch.date_start, batch.date_end
            )
            contracts_by_employee = dict(contracts)
            # For existing/generated batches, fill gaps (e.g. ambiguous historical overlaps)
            # using the latest overlapping running contract for working-days display only.
            missing_ids = [eid for eid in employees.ids if eid not in contracts_by_employee]
            if missing_ids:
                fallback_contracts = self.env["hr.contract"].sudo().search([
                    ("employee_id", "in", missing_ids),
                    ("company_id", "=", company.id),
                    ("state", "=", "open"),
                    ("date_start", "<=", batch.date_end),
                    "|",
                    ("date_end", "=", False),
                    ("date_end", ">=", batch.date_start),
                ], order="employee_id, date_start desc, id desc")
                for contract in fallback_contracts:
                    contracts_by_employee.setdefault(contract.employee_id.id, contract)

        company_calendar = company.resource_calendar_id
        batch_working_days = self._count_scheduled_working_days(
            company_calendar, batch.date_start, batch.date_end
        )
        batch_working_days_available = batch_working_days is not None
        batch_working_days_message = (
            False if batch_working_days_available
            else _("No default Working Schedule is configured for this company.")
        )

        rows = []
        total_net = 0.0
        total_paid = 0.0
        total_unpaid = 0.0
        state_labels = {
            "paid": _("Paid"),
            "partial": _("Partially Paid"),
            "unpaid": _("Unpaid"),
        }
        batch_payable = batch.state != "cancel"
        for slip in slips:
            net_pay = slip._get_kio_net_pay_amount()
            info = slip._get_kio_salary_payment_info()
            is_paid = info["is_paid"]
            paid_amount = currency.round(info["paid_amount"])
            unpaid_amount = currency.round(info["unpaid_amount"])
            total_net += net_pay
            total_paid += paid_amount
            total_unpaid += unpaid_amount
            emp = slip.employee_id
            contract = contracts_by_employee.get(emp.id)
            calendar = (
                (contract.resource_calendar_id if contract else False)
                or emp.resource_calendar_id
                or company_calendar
            )
            employee_working_days = self._count_scheduled_working_days(
                calendar,
                slip.date_from or batch.date_start,
                slip.date_to or batch.date_end,
                resource=emp.resource_id,
            )
            rows.append({
                "slip_id": slip.id,
                "employee_id": emp.id,
                "employee_name": emp.display_name,
                "employee_identification": emp.identification_id or "-",
                "employee_avatar_url": f"/web/image/hr.employee/{emp.id}/avatar_128",
                "department": emp.department_id.display_name or "-",
                "designation": emp.job_id.display_name or "-",
                "basic_salary": currency.round(slip.basic_salary),
                "allowance": currency.round(slip.allowance),
                "overtime": currency.round(slip.overtime),
                "commission": currency.round(slip.commission),
                "bonus": currency.round(slip.bonus),
                "deduction": currency.round(slip.deduction),
                "net_pay": currency.round(net_pay),
                "net_salary": currency.round(net_pay),
                "paid_amount": paid_amount,
                "unpaid_amount": unpaid_amount,
                "payslip_number": slip.number or slip.name or "-",
                "working_days": employee_working_days,
                "working_days_available": employee_working_days is not None,
                "working_calendar_name": calendar.display_name if calendar else False,
                "payment_state": info["payment_state"],
                "payment_state_label": state_labels[info["payment_state"]],
                "paid": is_paid,
                "can_pay": (
                    batch_payable
                    and slip.state != "cancel"
                    and net_pay > 0
                    and info["payment_state"] != "paid"
                ),
                "can_show_payments": info["payment_state"] in ("partial", "paid"),
            })
        totals = {
            "total_employees": len(slips.mapped("employee_id")),
            "total_net_salary": currency.round(total_net),
            "total_paid_salary": currency.round(total_paid),
            "total_unpaid_salary": currency.round(total_unpaid),
        }
        date_start = batch.date_start
        employees_data = [
            dict(
                r,
                name=r.get("employee_name"),
                identification_id=r.get("employee_identification"),
                avatar_url=r.get("employee_avatar_url"),
                paid=r.get("payment_state") == "paid",
            )
            for r in rows
        ]
        batch_data = {
            "id": batch.id,
            "name": batch.name,
            "payroll_scope": batch.payroll_scope,
            "department": batch.department_id.display_name or False,
            "payroll_type": batch.payroll_type,
            "payroll_type_label": dict(batch._fields["payroll_type"].selection).get(batch.payroll_type, batch.payroll_type),
            "payment_date": batch.payment_date,
            "date_start": batch.date_start,
            "date_end": batch.date_end,
            "month": date_start.month if date_start else False,
            "year": date_start.year if date_start else False,
            "state": (
                "paid"
                if slips and all(
                    slip._get_kio_salary_payment_info()["is_paid"]
                    for slip in slips
                )
                else batch.state
            ),
            "state_label": (
                _("Paid")
                if slips and all(
                    slip._get_kio_salary_payment_info()["is_paid"]
                    for slip in slips
                )
                else dict(batch._fields["state"].selection).get(batch.state, batch.state)
            ),
            "total_employees": len(slips.mapped("employee_id")),
            "working_days": batch_working_days,
            "working_days_available": batch_working_days_available,
            "working_days_message": batch_working_days_message,
            "working_calendar_name": company_calendar.display_name if company_calendar else False,
        }
        return {
            "company": {"id": company.id, "name": company.display_name},
            "currency": {"id": currency.id, "name": currency.name, "symbol": currency.symbol, "position": currency.position, "decimal_places": currency.decimal_places},
            "batch": batch_data,
            "period": {
                "date_start": batch.date_start,
                "date_end": batch.date_end,
                "working_days": batch_working_days,
                "working_days_available": batch_working_days_available,
                "working_days_message": batch_working_days_message,
                "working_calendar_name": company_calendar.display_name if company_calendar else False,
            },
            "totals": totals,
            "summary": totals,
            "rows": rows,
            "employees": employees_data,
        }

    # Stub compatibility methods used by older code paths (not required for clean install)
    @api.model
    def get_payroll_overview_batches(self):
        self._check_payroll_overview_manager()
        batches = self.env["kio.payroll.batch"].search([("company_id", "=", self.env.company.id)], order="date_start desc, id desc")
        return [{"id": b.id, "name": b.name, "date_start": b.date_start, "date_end": b.date_end, "state": b.state,
                 "state_label": dict(b._fields["state"].selection).get(b.state, b.state)} for b in batches]

    @api.model
    def get_payroll_overview_batch_page(self, offset=0, limit=20):
        self._check_payroll_overview_manager()
        offset = max(int(offset or 0), 0)
        limit = max(min(int(limit or 20), 100), 1)
        domain = [("company_id", "=", self.env.company.id)]
        total = self.env["kio.payroll.batch"].search_count(domain)
        batches = self.env["kio.payroll.batch"].search(domain, order="date_start desc, id desc", offset=offset, limit=limit)
        return {"total": total, "offset": offset, "limit": limit, "rows": [
            {"id": b.id, "name": b.name, "date_start": b.date_start, "date_end": b.date_end, "state": b.state,
             "state_label": dict(b._fields["state"].selection).get(b.state, b.state)} for b in batches]}

    @api.model
    def get_payroll_generation_data(self, batch_id=False):
        self._check_payroll_overview_manager()
        data = {"company": {"id": self.env.company.id, "name": self.env.company.display_name}, "batches": self.get_payroll_overview_batches(), "selected_batch": False}
        return data

    @api.model
    def prepare_payroll_generation(self, batch_id):
        raise UserError(_("Payroll generation is handled by the independent payroll workflow."))

    @api.model
    def get_create_payroll_batch_action(self):
        return {"type": "ir.actions.client", "tag": "kio_payroll_overview.new_payroll_generation", "target": "current"}

    def get_payslip_report_data(self):
        # Minimal compatibility for custom report template; preserve existing keys where possible.
        self.ensure_one()
        cur = self.company_id.currency_id
        info = self._get_kio_salary_payment_info()
        is_paid = info["is_paid"]
        payment_state = info["payment_state"]
        payment_status_labels = {
            "paid": _("Paid"),
            "partial": _("Partially Paid"),
            "unpaid": _("Unpaid"),
        }
        def fmt(v):
            return "%s %.2f" % (cur.symbol or cur.name or "", v or 0.0)
        return {
            "company_name": self.company_id.display_name,
            "employee_name": self.employee_id.display_name,
            "employee_id": self.employee_id.identification_id or "-",
            "designation": self.employee_id.job_id.display_name or "-",
            "department": self.employee_id.department_id.display_name or "-",
            "period": "%s - %s" % (self.date_from or "", self.date_to or ""),
            "batch_name": self.batch_id.name or "-",
            "payment_status": payment_status_labels[payment_state],
            "payment_state": payment_state,
            "payment_date": self.payment_date or (self.batch_id.payment_date if self.batch_id else False) or "-",
            "basic_salary": self.basic_salary,
            "allowance": self.allowance,
            "overtime": self.overtime,
            "bonus": self.bonus,
            "deduction": self.deduction,
            "net_salary_formatted": fmt(self.net_pay),
            "basic_salary_formatted": fmt(self.basic_salary),
            "allowance_formatted": fmt(self.allowance),
            "overtime_formatted": fmt(self.overtime),
            "bonus_formatted": fmt(self.bonus),
            "deduction_formatted": fmt(self.deduction),
            "paid_amount_formatted": fmt(info["paid_amount"]),
            "unpaid_amount_formatted": fmt(info["unpaid_amount"]),
        }


class KioPayrollPayslipLine(models.Model):
    _name = "kio.payroll.payslip.line"
    _description = "Payroll Payslip Line"
    _order = "sequence, id"
    _check_company_auto = True

    payslip_id = fields.Many2one(
        "kio.payroll.payslip", required=True, ondelete="cascade", index=True
    )
    employee_id = fields.Many2one(
        related="payslip_id.employee_id", store=True, readonly=True
    )
    company_id = fields.Many2one(
        related="payslip_id.company_id", store=True, readonly=True
    )
    currency_id = fields.Many2one(
        related="payslip_id.currency_id", store=True, readonly=True
    )
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    amount = fields.Monetary()
    quantity = fields.Float(default=1.0)
    rate = fields.Float(default=100.0)
    total = fields.Monetary(required=True)
