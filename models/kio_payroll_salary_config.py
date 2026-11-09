from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class KioPayrollSalaryConfig(models.Model):
    _name = "kio.payroll.salary.config"
    _description = "Employee Salary Configuration"
    _order = "employee_id, id desc"
    _check_company_auto = True

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        ondelete="cascade",
        check_company=True,
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
    active = fields.Boolean(default=True)
    basic_salary = fields.Monetary(string="Basic Salary", required=True)
    allowance = fields.Monetary(string="Allowances")
    working_days = fields.Float(string="Working Days", default=22.0)

    _sql_constraints = [
        (
            "kio_payroll_salary_config_employee_company_uniq",
            "unique(employee_id, company_id)",
            "An employee can only have one salary configuration per company.",
        ),
    ]

    @api.constrains("basic_salary", "allowance", "working_days")
    def _check_amounts(self):
        for rec in self:
            if rec.basic_salary < 0 or rec.allowance < 0:
                raise ValidationError(_("Salary amounts cannot be negative."))
            if rec.working_days < 0:
                raise ValidationError(_("Working days cannot be negative."))

    @api.model
    def get_employee_config(self, employee, company):
        if not employee:
            return self.browse()
        return self.search([
            ("employee_id", "=", employee.id),
            ("company_id", "=", company.id),
            ("active", "=", True),
        ], limit=1)
