from datetime import datetime, time, timedelta

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class KioDeduction(models.Model):
    _name = "kio.deduction"
    _description = "Late Deduction"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, actual_check_in desc, id desc"
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
    )
    date = fields.Date(
        string="Workday Date",
        required=True,
        default=fields.Date.context_today,
        index=True,
        tracking=True,
        help="Workday date used internally for duplicate prevention.",
    )
    scheduled_check_in = fields.Datetime(string="Scheduled In", readonly=True, copy=False)
    actual_check_in = fields.Datetime(string="Actual In", readonly=True, copy=False)
    late_minutes = fields.Float(string="Late Minutes", readonly=True, copy=False, digits=(16, 2), tracking=True)
    deduction_amount = fields.Monetary(
        string="Deduction Amount",
        currency_field="currency_id",
        readonly=True,
        copy=False,
        default=0.0,
        tracking=True,
    )
    amount = fields.Monetary(
        string="Amount",
        currency_field="currency_id",
        compute="_compute_amount",
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("cancelled", "Cancelled")],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
        index=True,
    )
    attendance_ids = fields.Many2many(
        "hr.attendance",
        "kio_late_deduction_hr_attendance_rel",
        "deduction_id",
        "attendance_id",
        string="Attendance References",
        readonly=True,
        copy=False,
    )
    source = fields.Selection(
        [("manual", "Manual"), ("attendance", "Attendance"), ("cron", "Scheduled Sync")],
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
            "kio_deduction_employee_date_company_uniq",
            "unique(employee_id, date, company_id)",
            "A late deduction record already exists for this employee and workday.",
        ),
    ]

    @api.depends("deduction_amount")
    def _compute_amount(self):
        for rec in self:
            rec.amount = rec.deduction_amount

    @api.constrains("deduction_amount", "amount")
    def _check_amount(self):
        for rec in self:
            if (rec.deduction_amount or 0.0) < 0 or (rec.amount or 0.0) < 0:
                raise ValidationError(_("Deduction amount cannot be negative."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if not rec.name or rec.name == _("New"):
                rec.name = "LD/%05d" % rec.id
        return records

    def _check_manager(self):
        if not self.env.user.has_group("kio_payroll_overview_extension.group_kio_payroll_manager"):
            raise AccessError(_("Only Payroll Managers can confirm, cancel, or sync late deductions."))

    def action_confirm(self):
        self._check_manager()
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Only draft late deduction records can be confirmed."))
            rec.state = "confirmed"
            rec.message_post(body=_("Late deduction confirmed."))

    def action_cancel(self):
        self._check_manager()
        for rec in self:
            if rec.state == "cancelled":
                continue
            rec.state = "cancelled"
            rec.message_post(body=_("Late deduction cancelled."))

    def action_draft(self):
        self._check_manager()
        for rec in self:
            if rec.state != "cancelled":
                raise UserError(_("Only cancelled late deduction records can be reset to draft."))
            rec.state = "draft"
            rec.message_post(body=_("Late deduction reset to draft."))

    def unlink(self):
        if any(rec.state != "draft" for rec in self):
            raise UserError(_("Only draft late deduction records can be deleted."))
        return super().unlink()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_tz(self, employee):
        tz_name = employee.tz or employee.resource_calendar_id.tz or (employee.company_id or self.env.company).partner_id.tz or "UTC"
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
    def _utc_naive(self, local_dt):
        return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

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
    def _get_calendar_day_start(self, employee, calendar, day_date, tz):
        """Return scheduled start (UTC naive) for the workday in local timezone."""
        if not calendar or not day_date:
            return False, False
        # Prefer actual calendar intervals (handles complex/overnight/two-week calendars).
        start_local = tz.localize(datetime.combine(day_date, time.min))
        end_local = start_local + timedelta(days=2)
        try:
            intervals = calendar._work_intervals_batch(
                start_local, end_local, resources=employee.resource_id, compute_leaves=False
            ).get(employee.resource_id.id) or calendar._attendance_intervals_batch(
                start_local, end_local, resources=employee.resource_id, tz=tz
            ).get(employee.resource_id.id)
            if intervals:
                for start, stop, _meta in sorted(intervals, key=lambda i: i[0]):
                    local_start_date = start.astimezone(tz).date()
                    if local_start_date == day_date:
                        return self._utc_naive(start), day_date
        except Exception:
            pass
        # Fallback: weekday attendance lines.
        weekday = str(day_date.weekday())
        lines = calendar.attendance_ids.filtered(lambda l: str(l.dayofweek) == weekday and not getattr(l, "display_type", False))
        if not lines:
            return False, False
        hour_from = min(lines.mapped("hour_from"))
        hours = int(hour_from)
        minutes = int(round((hour_from - hours) * 60))
        while minutes >= 60:
            hours += 1
            minutes -= 60
        local_dt = tz.localize(datetime.combine(day_date, time(min(hours, 23), minutes, 0)))
        return self._utc_naive(local_dt), day_date

    @api.model
    def _find_day_attendances(self, employee, workday_date, tz):
        # Use a generous UTC window around local workday to support overnight shifts.
        start_local = tz.localize(datetime.combine(workday_date, time.min)) - timedelta(hours=12)
        end_local = tz.localize(datetime.combine(workday_date, time.min)) + timedelta(days=2)
        return self.env["hr.attendance"].search([
            ("employee_id", "=", employee.id),
            ("check_in", ">=", self._utc_naive(start_local)),
            ("check_in", "<", self._utc_naive(end_local)),
        ], order="check_in asc, id asc")

    @api.model
    def _compute_workday_values(self, employee, workday_date, scheduled_check_in, attendances):
        company = employee.company_id or self.env.company
        actual_check_in = min(attendances.mapped("check_in")) if attendances else False
        late_minutes = 0.0
        if scheduled_check_in and actual_check_in and actual_check_in > scheduled_check_in:
            late_minutes = (actual_check_in - scheduled_check_in).total_seconds() / 60.0
        return {
            "name": "LD/%s/%s" % (employee.id, fields.Date.to_string(workday_date)),
            "employee_id": employee.id,
            "date": workday_date,
            "scheduled_check_in": scheduled_check_in,
            "actual_check_in": actual_check_in,
            "late_minutes": round(max(late_minutes, 0.0), 2),
            "deduction_amount": 0.0,
            "amount": 0.0,
            "attendance_ids": [(6, 0, attendances.ids)],
            "source": "cron",
            "company_id": company.id,
        }

    @api.model
    def _process_employee_workday(self, employee, workday_date, scheduled_check_in, allow_no_checkin=False):
        company = employee.company_id or self.env.company
        existing = self.search([
            ("employee_id", "=", employee.id),
            ("date", "=", workday_date),
            ("company_id", "=", company.id),
        ], limit=1)
        if existing and (existing.state == "confirmed" or existing.source == "manual"):
            return existing.browse()
        tz = self._get_tz(employee)
        attendances = self._find_day_attendances(employee, workday_date, tz)
        if not attendances:
            if not allow_no_checkin:
                return self.browse()  # skip; later cron can process valid attendance
            return self.browse()
        vals = self._compute_workday_values(employee, workday_date, scheduled_check_in, attendances)
        # Include late and on-time employees with valid attendance.
        if existing:
            if existing.state == "cancelled":
                return self.browse()
            existing.write(vals)
            return existing
        return self.create(vals)

    @api.model
    def _cron_daily_late_attendance_sync(self):
        """Every-minute scheduler: process each employee once per workday when
        local scheduled start + 30 minutes has passed. Single-company compatible.
        """
        now = fields.Datetime.now()
        employees = self.env["hr.employee"].search([("active", "=", True)])
        for employee in employees:
            company = employee.company_id or self.env.company
            tz = self._get_tz(employee)
            local_today = now.astimezone(pytz.UTC).astimezone(tz).date() if now.tzinfo else pytz.UTC.localize(now).astimezone(tz).date()
            calendar = self._get_employee_calendar(employee, local_today)
            scheduled_utc, workday_date = self._get_calendar_day_start(employee, calendar, local_today, tz)
            if not scheduled_utc or not workday_date:
                continue
            if now < scheduled_utc + timedelta(minutes=30):
                continue  # do not process future / before threshold
            existing = self.search([
                ("employee_id", "=", employee.id),
                ("date", "=", workday_date),
                ("company_id", "=", company.id),
            ], limit=1)
            if existing and existing.state in ("confirmed", "cancelled"):
                continue
            if existing and existing.source == "manual":
                continue
            # Safe rerun: if we already have an attendance-sourced record with actual check-in, it's processed.
            if existing and existing.source in ("attendance", "cron") and existing.actual_check_in:
                continue
            self._process_employee_workday(employee, workday_date, scheduled_utc, allow_no_checkin=False)

    # Keep manual sync action for authorized users.
    def action_sync_attendance(self):
        self._check_manager()
        ctx = self.env.context
        employee_ids = ctx.get("active_employee_ids") or self.employee_id.ids
        date_from = ctx.get("kio_late_date_from")
        date_to = ctx.get("kio_late_date_to") or date_from
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
        current = date_from
        while current <= date_to:
            for employee in employees:
                company = employee.company_id or self.env.company
                tz = self._get_tz(employee)
                calendar = self._get_employee_calendar(employee, current)
                scheduled_utc, workday_date = self._get_calendar_day_start(employee, calendar, current, tz)
                if not scheduled_utc:
                    current += timedelta(days=0)  # no-op
                else:
                    existing = self.search([
                        ("employee_id", "=", employee.id),
                        ("date", "=", workday_date),
                        ("company_id", "=", company.id),
                    ], limit=1)
                    if not (existing and existing.state == "confirmed"):
                        # manual sync: process if attendance exists
                        self._process_employee_workday(employee, workday_date, scheduled_utc, allow_no_checkin=False)
            current += timedelta(days=1)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Late Deductions Sync"),
                "message": _("Attendance-based late deduction synchronization completed."),
                "type": "success",
                "sticky": False,
            },
        }

    # Compatibility for any internal callers
    @api.model
    def _sync_employee_dates(self, employee_date_pairs):
        for employee, day_date in employee_date_pairs:
            if not employee or not day_date:
                continue
            tz = self._get_tz(employee)
            calendar = self._get_employee_calendar(employee, day_date)
            scheduled_utc, workday_date = self._get_calendar_day_start(employee, calendar, day_date, tz)
            if not scheduled_utc:
                continue
            self._process_employee_workday(employee, workday_date, scheduled_utc, allow_no_checkin=False)
        return self.browse()
