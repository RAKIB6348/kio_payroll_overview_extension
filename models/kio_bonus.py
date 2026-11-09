from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class KioBonus(models.Model):
    _name = "kio.bonus"
    _description = "Bonus Management"
    _order = "bonus_date desc, id desc"

    name = fields.Char(string="Bonus Name", required=True)
    bonus_type_id = fields.Many2one(
        "kio.bonus.type",
        string="Bonus Type",
        required=True,
        check_company=True,
        domain=(
            "[('active', '=', True), '|', "
            "('company_id', '=', False), ('company_id', '=', company_id)]"
        ),
    )
    payment_scope = fields.Selection(
        [
            ("all", "All Employees"),
            ("department", "Department Wise"),
            ("individual", "Individual Employee"),
        ],
        string="Payment Scope",
        required=True,
        default="all",
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        ondelete="restrict",
    )
    employee_ids = fields.Many2many(
        "hr.employee",
        "kio_bonus_hr_employee_rel",
        "bonus_id",
        "employee_id",
        string="Employees",
        check_company=True,
        domain="[('company_id', '=', company_id), ('active', '=', True)]",
        help="For Individual Employee scope, select one or more eligible employees.",
    )
    calculation_type = fields.Selection(
        [
            ("fixed", "Fixed Amount"),
            ("percentage", "Percentage of Basic Salary"),
        ],
        string="Bonus Calculation Type",
        required=True,
        default="fixed",
    )
    amount = fields.Monetary(
        string="Bonus Amount",
        currency_field="currency_id",
    )
    percentage = fields.Float(string="Bonus Percentage")
    bonus_date = fields.Date(
        string="Bonus Date",
        required=True,
        default=fields.Date.context_today,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        required=True,
        default="draft",
        copy=False,
    )
    confirmed_on = fields.Datetime(string="Confirmed On", readonly=True, copy=False)
    confirmed_by = fields.Many2one(
        "res.users",
        string="Confirmed By",
        readonly=True,
        copy=False,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Currency",
        store=True,
        readonly=True,
    )
    line_ids = fields.One2many(
        "kio.bonus.line",
        "bonus_id",
        string="Employee Bonus Details",
    )
    total_employees = fields.Integer(
        string="Total Employees",
        compute="_compute_totals",
    )
    total_bonus = fields.Monetary(
        string="Total Bonus Amount",
        currency_field="currency_id",
        compute="_compute_totals",
    )

    @api.depends("line_ids.bonus_amount")
    def _compute_totals(self):
        for bonus in self:
            bonus.total_employees = len(bonus.line_ids)
            bonus.total_bonus = sum(
                bonus.line_ids.mapped("bonus_amount")
            )

    @api.constrains("amount", "percentage")
    def _check_amounts(self):
        for bonus in self:
            if bonus.amount < 0:
                raise ValidationError(_("Bonus amount cannot be negative."))
            if bonus.percentage < 0:
                raise ValidationError(_("Bonus percentage cannot be negative."))

    @api.constrains("calculation_type", "amount", "percentage")
    def _check_calculation_values(self):
        for bonus in self:
            if bonus.calculation_type == "percentage" and bonus.percentage > 100:
                raise ValidationError(
                    _("Bonus percentage cannot be greater than 100.")
                )

    def _get_eligible_employees(self):
        """Return eligible employees and their salary configurations."""
        self.ensure_one()
        if not self.bonus_date:
            raise UserError(_("Select a Bonus Date first."))
        company = self.company_id or self.env.company
        if self.payment_scope == "department":
            if not self.department_id:
                raise UserError(_("Select a department for this bonus."))
            employees = self.env["hr.employee"].search([
                ("company_id", "=", company.id),
                ("active", "=", True),
                ("department_id", "=", self.department_id.id),
            ])
        elif self.payment_scope == "individual":
            if not self.employee_ids:
                raise UserError(_("Select at least one employee for this bonus."))
            outside_company = self.employee_ids.filtered(
                lambda employee: employee.company_id != company
            )
            if outside_company:
                raise UserError(_(
                    "All selected employees must belong to the bonus company."
                ))
            employees = self.employee_ids.filtered("active")
        else:
            employees = self.env["hr.employee"].search([
                ("company_id", "=", company.id),
                ("active", "=", True),
            ])

        configs = self.env["kio.payroll.salary.config"].search([
            ("employee_id", "in", employees.ids),
            ("company_id", "=", company.id),
            ("active", "=", True),
        ])
        config_by_employee = {cfg.employee_id.id: cfg for cfg in configs}
        eligible = employees.filtered(
            lambda employee: employee.id in config_by_employee
            and (config_by_employee[employee.id].basic_salary or 0.0) > 0
        )
        return eligible, config_by_employee

    def _get_bonus_amount(self, config):
        """Return the bonus amount for one employee salary configuration."""
        self.ensure_one()
        if self.calculation_type == "percentage":
            amount = (config.basic_salary or 0.0) * (self.percentage or 0.0) / 100.0
        else:
            amount = self.amount or 0.0
        return self.currency_id.round(amount)

    def action_generate_employees(self):
        """Populate employee bonus lines from the selected payment scope."""
        for bonus in self:
            if bonus.state != "draft":
                raise UserError(_(
                    "Employee bonus details can only be generated for a draft bonus."
                ))
            employees, config_by_employee = bonus._get_eligible_employees()
            if not employees:
                raise UserError(_(
                    "No eligible employees were found for the selected bonus scope."
                ))
            bonus.line_ids.unlink()
            self.env["kio.bonus.line"].create([{
                "bonus_id": bonus.id,
                "employee_id": employee.id,
                "basic_salary": config_by_employee[employee.id].basic_salary or 0.0,
                "bonus_amount": bonus._get_bonus_amount(
                    config_by_employee[employee.id]
                ),
            } for employee in employees])
        return True

    def action_confirm(self):
        """Confirm the bonus and its employee details."""
        for bonus in self:
            if bonus.state == "confirmed":
                raise UserError(_("This bonus is already confirmed."))
            if bonus.state != "draft":
                raise UserError(_("Only draft bonuses can be confirmed."))
            if not bonus.name or not bonus.bonus_type_id or not bonus.payment_scope:
                raise UserError(_("Complete the required bonus information first."))
            if not bonus.line_ids:
                bonus.action_generate_employees()
            if not bonus.line_ids:
                raise UserError(_(
                    "At least one eligible employee is required to confirm a bonus."
                ))
            negative_lines = bonus.line_ids.filtered(
                lambda line: line.bonus_amount < 0
            )
            if negative_lines:
                raise UserError(_("Bonus amounts cannot be negative."))
            bonus.write({
                "state": "confirmed",
                "confirmed_on": fields.Datetime.now(),
                "confirmed_by": self.env.uid,
            })
        return True

    def action_cancel(self):
        for bonus in self:
            if bonus.state == "cancelled":
                raise UserError(_("This bonus is already cancelled."))
            bonus.write({"state": "cancelled"})
        return True

    def write(self, vals):
        if any(bonus.state != "draft" for bonus in self):
            allowed = {"state", "confirmed_on", "confirmed_by"}
            if set(vals) - allowed:
                raise UserError(_(
                    "Confirmed or cancelled bonuses are read-only. "
                    "Cancel the bonus or reset it through an allowed action."
                ))
        return super().write(vals)

    def unlink(self):
        if any(bonus.state != "draft" for bonus in self):
            raise UserError(_("Only draft bonuses can be deleted."))
        return super().unlink()


class KioBonusLine(models.Model):
    _name = "kio.bonus.line"
    _description = "Bonus Employee Detail"
    _order = "bonus_id, employee_id"

    bonus_id = fields.Many2one(
        "kio.bonus",
        string="Bonus",
        required=True,
        ondelete="cascade",
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        ondelete="restrict",
    )
    department_id = fields.Many2one(
        related="employee_id.department_id",
        string="Department",
        store=True,
        readonly=True,
    )
    basic_salary = fields.Monetary(
        string="Basic Salary",
        currency_field="currency_id",
    )
    bonus_amount = fields.Monetary(
        string="Bonus Amount",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        related="bonus_id.currency_id",
        string="Currency",
        store=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        related="bonus_id.company_id",
        string="Company",
        store=True,
        readonly=True,
    )
    applied_payslip_id = fields.Many2one(
        "kio.payroll.payslip",
        string="Applied Payslip",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    applied = fields.Boolean(
        string="Applied to Payroll",
        default=False,
        readonly=True,
        copy=False,
    )

    _sql_constraints = [
        (
            "kio_bonus_line_employee_uniq",
            "unique(bonus_id, employee_id)",
            "An employee can only appear once on a bonus.",
        ),
    ]

    @api.constrains("bonus_amount", "basic_salary")
    def _check_bonus_amounts(self):
        for line in self:
            if line.bonus_amount < 0:
                raise ValidationError(_("Bonus amounts cannot be negative."))
            if line.basic_salary < 0:
                raise ValidationError(_("Basic salary cannot be negative."))

    def write(self, vals):
        if any(line.bonus_id.state != "draft" for line in self):
            if set(vals) - {"applied", "applied_payslip_id"}:
                raise UserError(_(
                    "Employee bonus details are read-only once the bonus is confirmed."
                ))
        return super().write(vals)

    def unlink(self):
        if any(line.bonus_id.state != "draft" for line in self):
            raise UserError(_(
                "Employee bonus details are read-only once the bonus is confirmed."
            ))
        return super().unlink()

    @api.model
    def _get_payroll_bonus_amounts(
        self, company, date_start, date_end, employee_ids=None, pending_only=False
    ):
        """Return confirmed bonus totals grouped by employee for the period.

        Uses bonus_date as the applicable payroll period. Only confirmed bonuses
        are included; company rules/access apply. Each kio.bonus.line is unique
        per (bonus, employee), so summing line amounts avoids duplicate counting
        even when bonuses are applied to payslips.
        """
        domain = [
            ("company_id", "=", company.id),
            ("bonus_id.state", "=", "confirmed"),
            ("bonus_id.bonus_date", ">=", date_start),
            ("bonus_id.bonus_date", "<=", date_end),
        ]
        if employee_ids:
            domain.append(("employee_id", "in", list(employee_ids)))
        if pending_only:
            domain.append(("applied", "=", False))
        rows = self.read_group(domain, ["bonus_amount:sum"], ["employee_id"], lazy=False)
        amounts = {}
        for row in rows:
            employee = row.get("employee_id")
            employee_id = employee[0] if isinstance(employee, (list, tuple)) else employee
            if employee_id:
                amounts[employee_id] = row.get("bonus_amount") or row.get("bonus_amount_sum") or 0.0
        return amounts

    @api.model
    def _get_payroll_bonus_total(
        self, company, date_start, date_end, pending_only=False
    ):
        """Return the total confirmed bonus amount for a period."""
        amounts = self._get_payroll_bonus_amounts(
            company,
            date_start,
            date_end,
            pending_only=pending_only,
        )
        return company.currency_id.round(sum(amounts.values()))
