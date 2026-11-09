from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class KioPayrollAdjustment(models.AbstractModel):
    _name = "kio.payroll.adjustment"
    _description = "Payroll Adjustment"
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        default=lambda self: _("New"),
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        tracking=True,
        check_company=True,
    )
    date = fields.Date(string="Date", required=True, default=fields.Date.context_today, tracking=True)
    amount = fields.Monetary(string="Amount", required=True, currency_field="currency_id", tracking=True)
    description = fields.Text(string="Description")
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled")],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        string="Currency",
        store=True,
        readonly=True,
    )

    @api.constrains("amount")
    def _check_amount(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_("Amount cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        prefixes = {
            "kio.overtime": "OT",
            "kio.commission": "COM",
            "kio.deduction": "DED",
        }
        prefix = prefixes.get(self._name, "ADJ")
        for rec in records:
            if not rec.name or rec.name == _("New"):
                rec.name = "%s/%05d" % (prefix, rec.id)
        return records

    def action_confirm(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft records can be confirmed."))
            if rec.amount < 0:
                raise ValidationError(_("Amount cannot be negative."))
            rec.state = "confirmed"

    def action_cancel(self):
        for rec in self:
            if rec.state == "cancelled":
                continue
            rec.state = "cancelled"

    def action_draft(self):
        for rec in self:
            if rec.state != "cancelled":
                raise UserError(_("Only cancelled records can be reset to draft."))
            rec.state = "draft"

    def unlink(self):
        if any(rec.state != "draft" for rec in self):
            raise UserError(_("Only draft records can be deleted."))
        return super().unlink()


class KioCommission(models.Model):
    _name = "kio.commission"
    _description = "Commission"
    _inherit = ["mail.thread", "mail.activity.mixin", "kio.payroll.adjustment"]

    applied_payslip_id = fields.Many2one(
        "kio.payroll.payslip",
        string="Applied Payslip",
        readonly=True,
        copy=False,
        ondelete="set null",
        index=True,
    )
    applied = fields.Boolean(
        string="Applied to Payroll",
        default=False,
        readonly=True,
        copy=False,
        index=True,
    )


class KioDeduction(models.Model):
    _name = "kio.deduction"
    _description = "Deduction"
    _inherit = ["mail.thread", "mail.activity.mixin", "kio.payroll.adjustment"]
