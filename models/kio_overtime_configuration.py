import calendar as pycalendar
from datetime import datetime, time

import pytz

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
    employee_scope = fields.Selection(
        [
            ("all", "All Employees"),
            ("department", "Department"),
            ("individual", "Individual Employee"),
        ],
        string="Employee Scope",
        default="all",
        required=True,
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
        domain="[('company_id', '=', company_id), ('active', '=', True), ('department_id', '=', department_id)] if department_id else [('company_id', '=', company_id), ('active', '=', True)]",
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
        normalized = []
        for vals in vals_list:
            vals = dict(vals)
            # Safe default for existing/programmatic creates without explicit scope.
            if not vals.get("employee_scope"):
                if vals.get("employee_id"):
                    vals["employee_scope"] = "individual"
                elif vals.get("department_id"):
                    vals["employee_scope"] = "department"
                else:
                    vals["employee_scope"] = "all"
            vals = self._normalize_scope_vals(vals)
            normalized.append(vals)
        records = super().create(normalized)
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

    def _normalize_scope_vals(self, vals):
        """Normalize Department/Employee values according to Employee Scope (draft-safe helper)."""
        scope = vals.get("employee_scope")
        if not scope:
            return vals
        vals = dict(vals)
        if scope == "all":
            vals.setdefault("department_id", False)
            vals.setdefault("employee_id", False)
            vals["department_id"] = False
            vals["employee_id"] = False
        elif scope == "department":
            vals.setdefault("employee_id", False)
            vals["employee_id"] = False
        elif scope == "individual":
            vals.setdefault("department_id", False)
            vals["department_id"] = False
        return vals

    def _check_scope_requirements(self):
        for rec in self:
            if rec.employee_scope == "department" and not rec.department_id:
                raise ValidationError(_("Please select a Department for Employee Scope 'Department'."))
            if rec.employee_scope == "individual" and not rec.employee_id:
                raise ValidationError(_("Please select an Employee for Employee Scope 'Individual Employee'."))

    def _employees_for_selection(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        Employee = self.env["hr.employee"]
        base_domain = [("company_id", "=", company.id), ("active", "=", True)]
        scope = self.employee_scope or "all"

        if scope == "individual":
            if not self.employee_id:
                return Employee.browse()
            return self.employee_id.filtered(lambda e: e.active and e.company_id == company)

        if scope == "department":
            if not self.department_id:
                return Employee.browse()
            base_domain.append(("department_id", "=", self.department_id.id))
            return Employee.search(base_domain, order="name")

        return Employee.search(base_domain, order="name")

    def _refresh_lines_from_scope(self):
        for rec in self:
            if rec.state != "draft":
                continue
            employees = rec._employees_for_selection()
            existing = {}
            for line in rec.line_ids:
                emp_id = line.employee_id._origin.id or line.employee_id.id
                if emp_id:
                    existing[emp_id] = line
            commands = [(5, 0, 0)]
            for emp in employees:
                emp_id = emp._origin.id or emp.id
                old = existing.get(emp_id)
                commands.append((0, 0, {
                    "employee_id": emp_id,
                    "per_hour_rate": old.per_hour_rate if old else 0.0,
                    "per_day_rate": old.per_day_rate if old else 0.0,
                    "overtime_percentage": old.overtime_percentage if old else 0.0,
                }))
            rec.line_ids = commands

    def action_populate_lines(self):
        for rec in self:
            rec._check_draft()
            rec._check_scope_requirements()
            rec._refresh_lines_from_scope()
        return True

    @api.onchange("employee_scope")
    def _onchange_employee_scope(self):
        for rec in self:
            if rec.state != "draft":
                continue
            if rec.employee_scope == "all":
                rec.department_id = False
                rec.employee_id = False
            elif rec.employee_scope == "department":
                rec.employee_id = False
            elif rec.employee_scope == "individual":
                rec.department_id = False
            rec._refresh_lines_from_scope()

    @api.onchange("department_id")
    def _onchange_department_id(self):
        for rec in self:
            if rec.employee_scope == "individual" and rec.department_id:
                rec.employee_scope = "department"
                rec.employee_id = False
            if rec.employee_scope == "all" and rec.department_id:
                rec.employee_scope = "department"
            if rec.employee_id and rec.department_id and rec.employee_id.department_id != rec.department_id:
                rec.employee_id = False
            rec._refresh_lines_from_scope()

    @api.onchange("employee_id")
    def _onchange_employee_id(self):
        for rec in self:
            if rec.employee_scope == "department" and rec.employee_id:
                rec.employee_scope = "individual"
                rec.department_id = False
            if rec.employee_scope == "all" and rec.employee_id:
                rec.employee_scope = "individual"
            rec._refresh_lines_from_scope()

    def action_confirm(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft overtime configurations can be confirmed."))
            rec._check_scope_requirements()
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
        vals = dict(vals)
        if vals.get("employee_scope"):
            vals = self._normalize_scope_vals(vals)
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
    currency_id = fields.Many2one(
        related="configuration_id.company_id.currency_id",
        string="Currency",
        readonly=True,
    )
    has_applicable_contract = fields.Boolean(
        string="Has Applicable Contract",
        compute="_compute_contract_salary_info",
        readonly=True,
    )
    basic_salary = fields.Monetary(
        string="Basic Salary (BDT)",
        compute="_compute_contract_salary_info",
        currency_field="currency_id",
        readonly=True,
        help="Read from the applicable running hr.contract wage for the effective date. "
             "If no applicable contract is found, this is shown as 0.00 and marked as missing contract information.",
    )
    per_hour_salary = fields.Monetary(
        string="Per Hour Salary (BDT)",
        compute="_compute_contract_salary_info",
        currency_field="currency_id",
        readonly=True,
        help="Basic Salary divided by the applicable monthly scheduled working hours from the working schedule.",
    )
    per_hour_rate = fields.Float(string="Per Hour Rate (BDT)", default=0.0, digits=(16, 2))
    per_day_rate = fields.Float(string="Per Day Rate (BDT)", default=0.0, digits=(16, 2))
    overtime_percentage = fields.Float(string="Overtime Rate (%)", default=0.0, digits=(16, 2))
    overtime_amount = fields.Monetary(
        string="Overtime Amount (BDT)",
        compute="_compute_overtime_amount",
        currency_field="currency_id",
        readonly=True,
    )
    company_id = fields.Many2one(
        related="configuration_id.company_id",
        string="Company",
        store=True,
        readonly=True,
    )

    def _get_salary_effective_date(self):
        self.ensure_one()
        return fields.Date.context_today(self)

    def _get_applicable_contract(self, date_ref=None):
        """Return the applicable running contract for the employee/company/effective date.

        Uses hr.employee._get_contracts (Odoo's canonical contract lookup) to respect
        the database's actual contract state/date semantics. A Running contract is
        state 'open' in Odoo 17 hr_contract.
        """
        self.ensure_one()
        if not self.employee_id or "hr.contract" not in self.env:
            return self.env["hr.contract"].browse() if "hr.contract" in self.env else False
        date_ref = date_ref or self._get_salary_effective_date()
        company = self.company_id or self.configuration_id.company_id or self.env.company
        employee = self.employee_id.sudo()

        contracts = self.env["hr.contract"].browse()
        if hasattr(employee, "_get_contracts"):
            contracts = employee._get_contracts(date_ref, date_ref, states=["open"])
            contracts = contracts.filtered(lambda c: c.company_id == company)
        if not contracts:
            # ORM fallback using actual state/date fields (do not rely on employee.contract_id).
            contracts = self.env["hr.contract"].sudo().search([
                ("employee_id", "=", self.employee_id.id),
                ("company_id", "=", company.id),
                ("state", "=", "open"),
                ("date_start", "<=", date_ref),
                "|",
                ("date_end", "=", False),
                ("date_end", ">=", date_ref),
            ], order="date_start desc, id desc")
        return contracts[:1]

    def _get_applicable_calendar(self, contract, date_ref=None):
        self.ensure_one()
        date_ref = date_ref or self._get_salary_effective_date()
        calendar = self.env["resource.calendar"].browse()
        if contract and "resource_calendar_id" in contract._fields and contract.resource_calendar_id:
            calendar = contract.resource_calendar_id
        if not calendar and self.employee_id:
            calendar = self.employee_id.resource_calendar_id
        if not calendar and contract and contract.company_id.resource_calendar_id:
            calendar = contract.company_id.resource_calendar_id
        if not calendar:
            company = self.company_id or self.configuration_id.company_id or self.env.company
            calendar = company.resource_calendar_id
        return calendar

    def _get_monthly_scheduled_hours(self, contract=None, date_ref=None):
        self.ensure_one()
        date_ref = date_ref or self._get_salary_effective_date()
        calendar = self._get_applicable_calendar(contract, date_ref=date_ref)
        resource = self.employee_id.resource_id if self.employee_id else self.env["resource.resource"].browse()
        if not calendar:
            return 0.0

        tz_name = (
            calendar.tz
            or (self.employee_id.tz if self.employee_id else False)
            or self.env.company.resource_calendar_id.tz
            or "UTC"
        )
        try:
            local_tz = pytz.timezone(tz_name)
        except Exception:
            local_tz = pytz.UTC

        last_day = pycalendar.monthrange(date_ref.year, date_ref.month)[1]
        start_local = local_tz.localize(datetime.combine(date_ref.replace(day=1), time.min))
        end_local = local_tz.localize(datetime.combine(date_ref.replace(day=last_day), time.max))
        start_dt = start_local.astimezone(pytz.UTC).replace(tzinfo=None)
        end_dt = end_local.astimezone(pytz.UTC).replace(tzinfo=None)

        # Primary: calendar scheduled hours for the month (respects attendances/schedule).
        for compute_leaves in (False, True):
            try:
                hours = calendar.get_work_hours_count(start_dt, end_dt, compute_leaves=compute_leaves)
                if hours:
                    return float(hours)
            except TypeError:
                try:
                    hours = calendar.get_work_hours_count(start_dt, end_dt)
                    if hours:
                        return float(hours)
                except Exception:
                    pass
            except Exception:
                pass

        # Fallback: attendance/work intervals for employee-specific resource schedules.
        if resource and hasattr(calendar, "_work_intervals_batch"):
            for compute_leaves in (False, True):
                try:
                    intervals = calendar._work_intervals_batch(
                        start_local, end_local, resources=resource, compute_leaves=compute_leaves
                    )[resource.id]
                    total = 0.0
                    for start_dt_i, stop_dt_i, _meta in intervals:
                        total += (stop_dt_i - start_dt_i).total_seconds() / 3600.0
                    if total > 0:
                        return float(total)
                except Exception:
                    continue
        return 0.0

    @api.depends("employee_id", "employee_id.contract_id", "employee_id.resource_calendar_id", "company_id")
    def _compute_contract_salary_info(self):
        for line in self:
            contract = line._get_applicable_contract()
            if not contract:
                line.has_applicable_contract = False
                line.basic_salary = 0.0
                line.per_hour_salary = 0.0
                continue

            wage = contract.wage
            basic_salary = 0.0 if wage is False or wage is None else wage
            monthly_hours = line._get_monthly_scheduled_hours(contract=contract)
            per_hour_salary = (basic_salary / monthly_hours) if monthly_hours > 0 else 0.0

            line.has_applicable_contract = True
            line.basic_salary = basic_salary
            line.per_hour_salary = per_hour_salary

    @api.depends(
        "configuration_id.calculation_type",
        "per_hour_salary",
        "overtime_percentage",
        "per_hour_rate",
    )
    def _compute_overtime_amount(self):
        for line in self:
            calc_type = line.configuration_id.calculation_type or "fixed"
            if calc_type == "percentage":
                per_hour_salary = line.per_hour_salary or 0.0
                overtime_percentage = line.overtime_percentage or 0.0
                line.overtime_amount = (per_hour_salary * overtime_percentage / 100.0) if per_hour_salary and overtime_percentage else 0.0
            else:
                line.overtime_amount = line.per_hour_rate or 0.0

    @api.onchange("overtime_percentage", "per_hour_rate", "employee_id")
    def _onchange_overtime_amount_inputs(self):
        self._compute_overtime_amount()

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
