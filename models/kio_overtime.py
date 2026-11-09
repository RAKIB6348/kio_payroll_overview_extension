import math
from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import float_compare


class KioOvertime(models.Model):
    _name = "kio.overtime"
    _description = "Overtime"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        default=lambda self: _("New"),
        index=True,
        tracking=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        required=True,
        index=True,
        tracking=True,
        check_company=True,
    )
    department_id = fields.Many2one(
        "hr.department",
        string="Department",
        related="employee_id.department_id",
        store=True,
        readonly=True,
        index=True,
    )
    date = fields.Date(string="Date", required=True, default=fields.Date.context_today, index=True, tracking=True)
    check_in = fields.Datetime(string="Check In", readonly=True, copy=False)
    check_out = fields.Datetime(string="Check Out", readonly=True, copy=False)
    scheduled_hours = fields.Float(string="Scheduled Hours", readonly=True, copy=False, digits=(16, 2))
    worked_hours = fields.Float(string="Worked Hours", readonly=True, copy=False, digits=(16, 2))
    overtime_hours = fields.Float(string="Overtime Hours", readonly=True, copy=False, digits=(16, 2), tracking=True)
    hourly_rate = fields.Monetary(string="Hourly Rate", currency_field="currency_id", readonly=True, copy=False)
    overtime_rate = fields.Float(string="Overtime Rate", readonly=True, copy=False, digits=(16, 4))
    overtime_amount = fields.Monetary(
        string="Overtime Amount",
        currency_field="currency_id",
        readonly=True,
        copy=False,
        tracking=True,
    )
    amount = fields.Monetary(
        string="Amount",
        currency_field="currency_id",
        compute="_compute_amount",
        inverse="_inverse_amount",
        store=True,
        readonly=False,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
            ("cancelled", "Cancelled"),
        ],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )
    needs_review = fields.Boolean(string="Needs Review", default=False, copy=False, tracking=True, index=True)
    review_note = fields.Text(string="Review Note", copy=False)
    attendance_ids = fields.Many2many(
        "hr.attendance",
        "kio_overtime_hr_attendance_rel",
        "overtime_id",
        "attendance_id",
        string="Attendance References",
        readonly=True,
        copy=False,
    )
    source = fields.Selection(
        [("manual", "Manual"), ("attendance", "Attendance")],
        string="Source",
        default="manual",
        required=True,
        copy=False,
        index=True,
    )
    description = fields.Text(string="Description")
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

    _sql_constraints = [
        (
            "kio_overtime_employee_date_company_uniq",
            "unique(employee_id, date, company_id)",
            "An overtime record already exists for this employee and date.",
        ),
    ]

    @api.depends("overtime_amount", "source")
    def _compute_amount(self):
        for rec in self:
            if rec.source == "attendance" or rec._origin.source == "attendance":
                rec.amount = rec.overtime_amount
            elif rec.overtime_amount and not rec.amount:
                rec.amount = rec.overtime_amount

    def _inverse_amount(self):
        for rec in self:
            if rec.source != "attendance":
                rec.overtime_amount = rec.amount

    @api.constrains("amount", "overtime_amount")
    def _check_amount(self):
        for rec in self:
            if (rec.amount or 0.0) < 0 or (rec.overtime_amount or 0.0) < 0:
                raise ValidationError(_("Amount cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.name or rec.name == _("New"):
                rec.name = "OT/%05d" % rec.id
        return records

    def _check_manager(self):
        if not self.env.user.has_group("kio_payroll_overview_extension.group_kio_payroll_manager"):
            raise AccessError(_("Only Payroll Managers can confirm, cancel, or sync overtime."))

    def action_confirm(self):
        self._check_manager()
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft overtime records can be confirmed."))
            if rec.needs_review:
                raise UserError(_("Resolve the review flag before confirming overtime for %s.") % rec.display_name)
            rec.state = "confirmed"
            rec.message_post(body=_("Overtime confirmed."))

    def action_cancel(self):
        self._check_manager()
        for rec in self:
            if rec.state == "cancelled":
                continue
            rec.state = "cancelled"
            rec.message_post(body=_("Overtime cancelled."))

    def action_draft(self):
        self._check_manager()
        for rec in self:
            if rec.state != "cancelled":
                raise UserError(_("Only cancelled overtime records can be reset to draft."))
            rec.state = "draft"
            rec.message_post(body=_("Overtime reset to draft."))

    def unlink(self):
        if any(rec.state != "draft" for rec in self):
            raise UserError(_("Only draft overtime records can be deleted."))
        return super().unlink()

    def write(self, vals):
        res = super().write(vals)
        return res

    # ------------------------------------------------------------------
    # Attendance-based calculation
    # ------------------------------------------------------------------
    @api.model
    def _get_tz(self, employee):
        tz_name = employee.tz or employee.resource_calendar_id.tz or self.env.company.partner_id.tz or "UTC"
        try:
            return pytz.timezone(tz_name)
        except Exception:
            return pytz.UTC

    @api.model
    def _local_date(self, dt, tz):
        if not dt:
            return False
        if not dt.tzinfo:
            dt = pytz.UTC.localize(dt)
        return dt.astimezone(tz).date()

    @api.model
    def _day_bounds_utc(self, day_date, tz):
        start_local = tz.localize(datetime.combine(day_date, time.min))
        end_local = tz.localize(datetime.combine(day_date, time.max))
        return start_local.astimezone(pytz.UTC).replace(tzinfo=None), end_local.astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def _get_employee_calendar(self, employee, day_date):
        calendar = employee.resource_calendar_id
        if hasattr(employee, "_get_calendar"):
            try:
                cal = employee._get_calendar(fields.Datetime.to_datetime(day_date), fields.Datetime.to_datetime(day_date))
                if cal:
                    calendar = cal
            except Exception:
                pass
        return calendar

    @api.model
    def _get_scheduled_hours(self, employee, calendar, day_date, tz):
        if not calendar:
            return 0.0, _("No working schedule assigned.")
        start_local = tz.localize(datetime.combine(day_date, time.min))
        end_local = start_local + timedelta(days=1)
        try:
            hours = calendar.get_work_hours_count(
                start_local,
                end_local,
                compute_leaves=False,
            )
        except Exception as exc:
            return 0.0, _("Unable to compute scheduled hours: %s") % exc
        return max(hours or 0.0, 0.0), False

    @api.model
    def _get_monthly_scheduled_hours(self, calendar, day_date, tz):
        if not calendar or not day_date:
            return 0.0
        first = day_date.replace(day=1)
        if first.month == 12:
            next_first = first.replace(year=first.year + 1, month=1)
        else:
            next_first = first.replace(month=first.month + 1)
        start_local = tz.localize(datetime.combine(first, time.min))
        end_local = tz.localize(datetime.combine(next_first, time.min))
        try:
            return max(calendar.get_work_hours_count(start_local, end_local, compute_leaves=False) or 0.0, 0.0)
        except Exception:
            return 0.0

    @api.model
    def _get_applicable_wage(self, employee, day_date, company):
        Contract = self.env.get("hr.contract")
        if not Contract:
            return 0.0, _("hr.contract is unavailable.")
        contract = Contract.search([
            ("employee_id", "=", employee.id),
            ("company_id", "=", company.id),
            ("state", "=", "open"),
            ("date_start", "<=", day_date),
            "|",
            ("date_end", "=", False),
            ("date_end", ">=", day_date),
        ], order="date_start desc, id desc", limit=1)
        if not contract:
            return 0.0, _("No applicable running contract found.")
        return contract.wage or 0.0, False

    @api.model
    def _get_overtime_policy(self, company):
        enabled = bool(company.kio_overtime_monetary_enabled)
        per_hour_rate = float(company.kio_overtime_per_hour_rate or 0.0)
        if not per_hour_rate:
            icp = self.env["ir.config_parameter"].sudo().get_param(
                "kio_payroll_overview_extension.overtime_per_hour_rate", "0.0"
            )
            try:
                per_hour_rate = float(icp or 0.0)
            except (TypeError, ValueError):
                per_hour_rate = 0.0
        return enabled, per_hour_rate

    @api.model
    def _compute_day_values(self, employee, day_date, attendances):
        company = employee.company_id or self.env.company
        tz = self._get_tz(employee)
        calendar = self._get_employee_calendar(employee, day_date)
        scheduled_hours, schedule_issue = self._get_scheduled_hours(employee, calendar, day_date, tz)
        completed = attendances.filtered(lambda a: a.check_in and a.check_out)
        missing_checkout = attendances.filtered(lambda a: a.check_in and not a.check_out)
        worked_hours = sum(completed.mapped("worked_hours"))
        overtime_hours = max(worked_hours - scheduled_hours, 0.0)
        check_in = min(attendances.mapped("check_in")) if attendances else False
        check_out = max(completed.mapped("check_out")) if completed else False

        review_reasons = []
        if schedule_issue:
            review_reasons.append(schedule_issue)
        if missing_checkout:
            review_reasons.append(_("Attendance has no check-out."))
        if not completed:
            review_reasons.append(_("No completed attendance found."))
        for att in completed:
            if att.check_out.date() != att.check_in.date():
                review_reasons.append(_("Overnight shift detected; verify schedule/day attribution."))
                break

        overtime_amount = 0.0
        hourly_rate = 0.0
        overtime_rate = 0.0
        if overtime_hours > 0 and not review_reasons:
            enabled, per_hour_rate = self._get_overtime_policy(company)
            if not enabled:
                # Monetary calculation disabled: keep hours, no amount.
                overtime_amount = 0.0
            elif per_hour_rate <= 0:
                review_reasons.append(
                    _("Per Hour Rate is not configured. Set Payroll > Configuration > Settings > Attendance Overtime Policy > Per Hour Rate (BDT) before enabling monetary overtime calculation.")
                )
            else:
                hourly_rate = per_hour_rate
                overtime_amount = company.currency_id.round(
                    overtime_hours * per_hour_rate
                )

        vals = {
            "name": self._attendance_reference(employee, day_date),
            "employee_id": employee.id,
            "date": day_date,
            "check_in": check_in,
            "check_out": check_out,
            "scheduled_hours": round(scheduled_hours, 2),
            "worked_hours": round(worked_hours, 2),
            "overtime_hours": round(overtime_hours, 2),
            "hourly_rate": hourly_rate,
            "overtime_rate": overtime_rate,
            "overtime_amount": overtime_amount,
            "amount": overtime_amount,
            "needs_review": bool(review_reasons),
            "review_note": "\n".join(dict.fromkeys(review_reasons)) or False,
            "attendance_ids": [(6, 0, attendances.ids)],
            "source": "attendance",
            "company_id": company.id,
        }
        return vals

    @api.model
    def _attendance_reference(self, employee, day_date):
        return "OT/%s/%s" % (employee.id, fields.Date.to_string(day_date))

    @api.model
    def _sync_employee_dates(self, employee_date_pairs):
        if not employee_date_pairs:
            return self.browse()
        Attendance = self.env["hr.attendance"]
        processed = self.browse()
        for employee, day_date in employee_date_pairs:
            if not employee or not day_date:
                continue
            tz = self._get_tz(employee)
            start_utc, end_utc = self._day_bounds_utc(day_date, tz)
            attendances = Attendance.search([
                ("employee_id", "=", employee.id),
                ("check_in", ">=", start_utc),
                ("check_in", "<=", end_utc),
            ], order="check_in asc, id asc")
            existing = self.search([
                ("employee_id", "=", employee.id),
                ("date", "=", day_date),
                ("company_id", "=", (employee.company_id or self.env.company).id),
            ], limit=1)
            if not attendances:
                if existing and existing.state == "draft" and existing.source == "attendance":
                    existing.unlink()
                continue
            vals = self._compute_day_values(employee, day_date, attendances)
            if existing:
                if existing.state == "confirmed":
                    changed = []
                    if existing.attendance_ids != attendances:
                        changed.append(_("Attendance references changed."))
                    if float_compare(existing.worked_hours, vals["worked_hours"], precision_digits=2):
                        changed.append(_("Worked hours changed after confirmation."))
                    if changed:
                        existing.message_post(body=_("Attendance changed after confirmation; review required.\n%s") % "\n".join(changed))
                        existing.write({
                            "needs_review": True,
                            "review_note": "\n".join(dict.fromkeys(filter(None, [existing.review_note] + changed))),
                        })
                    continue
                if existing.state == "cancelled":
                    continue
                existing.write(vals)
                processed |= existing
            else:
                if vals["overtime_hours"] <= 0 and not vals["needs_review"]:
                    continue
                processed |= self.create(vals)
        return processed

    def action_sync_attendance(self):
        self._check_manager()
        ctx = self.env.context
        employee_ids = ctx.get("active_employee_ids") or self.employee_id.ids
        date_from = ctx.get("kio_overtime_date_from")
        date_to = ctx.get("kio_overtime_date_to") or date_from
        if not employee_ids:
            employee_ids = self.env["hr.employee"].search([
                ("company_id", "=", self.env.company.id),
                ("active", "=", True),
            ]).ids
        if date_from:
            date_from = fields.Date.to_date(date_from)
            date_to = fields.Date.to_date(date_to)
        else:
            date_to = fields.Date.context_today(self)
            date_from = date_to - timedelta(days=30)
        employees = self.env["hr.employee"].browse(employee_ids).exists()
        pairs = []
        current = date_from
        while current <= date_to:
            for employee in employees:
                pairs.append((employee, current))
            current += timedelta(days=1)
        self._sync_employee_dates(pairs)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Overtime Sync"),
                "message": _("Attendance-based overtime synchronization completed."),
                "type": "success",
                "sticky": False,
            },
        }
