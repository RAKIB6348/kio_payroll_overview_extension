from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class KioOvertimeConfiguration(models.Model):
    _name = "kio.overtime.configuration"
    _description = "Overtime Configuration"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"
    _check_company_auto = True

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        default=lambda self: _("New"),
        index=True,
        tracking=True,
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        tracking=True,
        check_company=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        tracking=True,
        check_company=True,
        domain="[('department_id', '=', department_id)] if department_id else []",
    )
    calculation_type = fields.Selection(
        [("fixed", "Fixed Amount"), ("percentage", "Percentage")],
        string="Calculation Type",
        default="fixed",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many(
        "kio.overtime.configuration.line",
        "configuration_id",
        string="Employee Overtime Rates",
        copy=True,
    )
    total_employees = fields.Integer(
        string="Total Employees",
        compute="_compute_total_employees",
        store=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed")],
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

    @api.depends("line_ids")
    def _compute_total_employees(self):
        for rec in self:
            rec.total_employees = len(rec.line_ids)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.name or rec.name == _("New"):
                rec.name = "OTC/%05d" % rec.id
        return records

    def _check_draft(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft overtime configurations can be modified."))

    @api.constrains("line_ids", "line_ids.employee_id")
    def _check_duplicate_employees(self):
        for rec in self:
            employees = rec.line_ids.mapped("employee_id").ids
            if len(employees) != len(set(employees)):
                raise ValidationError(_("Duplicate employees are not allowed in the same overtime configuration."))

    @api.constrains("state", "line_ids", "company_id")
    def _check_conflicting_active_configurations(self):
        confirmed = self.filtered(lambda r: r.state == "confirmed")
        for rec in confirmed:
            employee_ids = rec.line_ids.mapped("employee_id").ids
            if not employee_ids:
                continue
            conflicts = self.env["kio.overtime.configuration.line"].search([
                ("employee_id", "in", employee_ids),
                ("configuration_id.state", "=", "confirmed"),
                ("configuration_id", "!=", rec.id),
                ("company_id", "=", rec.company_id.id),
            ], limit=1)
            if conflicts:
                raise ValidationError(_(
                    "A confirmed overtime configuration already exists for employee: %s. "
                    "Reset or change the conflicting configuration before confirming."
                ) % conflicts.employee_id.display_name)

    def _employees_for_selection(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        domain = [("company_id", "=", company.id), ("active", "=", True)]
        if self.department_id:
            domain.append(("department_id", "=", self.department_id.id))
        if self.employee_id:
            return self.employee_id.filtered(lambda e: e.active and e.company_id == company and (not self.department_id or e.department_id == self.department_id))
        if self.department_id:
            return self.env["hr.employee"].search(domain, order="name")
        return self.env["hr.employee"].browse()

    def action_populate_lines(self):
        for rec in self:
            rec._check_draft()
            employees = rec._employees_for_selection()
            existing = {line.employee_id.id: line for line in rec.line_ids}
            commands = [(5, 0, 0)]
            for emp in employees:
                old = existing.get(emp.id)
                commands.append((0, 0, {
                    "employee_id": emp.id,
                    "per_hour_rate": old.per_hour_rate if old else 0.0,
                    "per_day_rate": old.per_day_rate if old else 0.0,
                    "overtime_percentage": old.overtime_percentage if old else 0.0,
                }))
            rec.line_ids = commands
        return True

    @api.onchange("department_id")
    def _onchange_department_id(self):
        for rec in self:
            if rec.employee_id and rec.department_id and rec.employee_id.department_id != rec.department_id:
                rec.employee_id = False
            if rec.state == "draft":
                employees = rec._employees_for_selection()
                existing = {line.employee_id.id: line for line in rec.line_ids}
                commands = [(5, 0, 0)]
                for emp in employees:
                    old = existing.get(emp._origin.id or emp.id)
                    commands.append((0, 0, {
                        "employee_id": emp.id,
                        "per_hour_rate": old.per_hour_rate if old else 0.0,
                        "per_day_rate": old.per_day_rate if old else 0.0,
                        "overtime_percentage": old.overtime_percentage if old else 0.0,
                    }))
                rec.line_ids = commands

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for rec in self:
            if rec.state == "draft":
                employees = rec._employees_for_selection()
                existing = {line.employee_id.id: line for line in rec.line_ids}
                commands = [(5, 0, 0)]
                for emp in employees:
                    old = existing.get(emp._origin.id or emp.id)
                    commands.append((0, 0, {
                        "employee_id": emp.id,
                        "per_hour_rate": old.per_hour_rate if old else 0.0,
                        "per_day_rate": old.per_day_rate if old else 0.0,
                        "overtime_percentage": old.overtime_percentage if old else 0.0,
                    }))
                rec.line_ids = commands

    def action_confirm(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft overtime configurations can be confirmed."))
            if not rec.line_ids:
                raise UserError(_("Add at least one employee overtime rate line before confirming."))
            rec._check_duplicate_employees()
            rec.state = "confirmed"
            rec._check_conflicting_active_configurations()
            rec.message_post(body=_("Overtime configuration confirmed."))

    def action_draft(self):
        for rec in self:
            rec.state = "draft"
            rec.message_post(body=_("Overtime configuration reset to draft."))

    def write(self, vals):
        for rec in self:
            if rec.state == "confirmed" and set(vals) - {"state", "message_main_attachment_id"}:
                # allow explicit reset to draft
                if vals.get("state") == "draft" and set(vals) <= {"state", "message_main_attachment_id"}:
                    continue
                raise UserError(_("Confirmed overtime configurations are read-only. Reset to draft to make changes."))
        return super().write(vals)

    def unlink(self):
        if any(rec.state == "confirmed" for rec in self):
            raise UserError(_("Confirmed overtime configurations cannot be deleted."))
        return super().unlink()

    @api.model
    def get_employee_overtime_rate_info(self, employee, company=None):
        company = company or (employee.company_id if employee else None) or self.env.company
        if not employee:
            return {}
        line = self.env["kio.overtime.configuration.line"].search([
            ("employee_id", "=", employee.id),
            ("company_id", "=", company.id),
            ("configuration_id.state", "=", "confirmed"),
        ], order="configuration_id desc, id desc", limit=1)
        if not line:
            return {}
        return {
            "calculation_type": line.configuration_id.calculation_type or "fixed",
            "per_hour_rate": line.per_hour_rate or 0.0,
            "per_day_rate": line.per_day_rate or 0.0,
            "overtime_percentage": line.overtime_percentage or 0.0,
            "line": line,
        }

    @api.model
    def get_employee_per_hour_rate(self, employee, company=None):
        info = self.get_employee_overtime_rate_info(employee, company=company)
        if info.get("calculation_type") == "fixed" and info.get("per_hour_rate", 0.0) > 0:
            return info["per_hour_rate"]
        return 0.0


class KioOvertimeConfigurationLine(models.Model):
    _name = "kio.overtime.configuration.line"
    _description = "Overtime Configuration Line"
    _order = "employee_id, id"

    configuration_id = fields.Many2one(
        "kio.overtime.configuration",
        string="Configuration",
        required=True,
        ondelete="cascade",
        index=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        check_company=True,
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        related="employee_id.department_id",
        store=True,
        readonly=True,
    )
    per_hour_rate = fields.Float(string="Per Hour Rate (BDT)", default=0.0, digits=(16, 2))
    per_day_rate = fields.Float(string="Per Day Rate (BDT)", default=0.0, digits=(16, 2))
    overtime_percentage = fields.Float(string="Overtime Rate (%)", default=0.0, digits=(16, 2))
    company_id = fields.Many2one(
        related="configuration_id.company_id",
        string="Company",
        store=True,
        readonly=True,
    )

    @api.constrains("per_hour_rate", "per_day_rate", "overtime_percentage")
    def _check_rates(self):
        for line in self:
            if line.per_hour_rate < 0:
                raise ValidationError(_("Per Hour Rate cannot be negative."))
            if line.per_day_rate < 0:
                raise ValidationError(_("Per Day Rate cannot be negative."))
            if line.overtime_percentage < 0:
                raise ValidationError(_("Overtime Rate (%) cannot be negative."))

    @api.constrains("employee_id", "configuration_id")
    def _check_employee_company(self):
        for line in self:
            if line.configuration_id and line.employee_id and line.employee_id.company_id != line.configuration_id.company_id:
                raise ValidationError(_("Employee must belong to the configuration company."))
