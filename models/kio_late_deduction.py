from datetime import datetime, time, timedelta
import math

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
    is_qualifying_late_day = fields.Boolean(
        string="Qualifying Late Day",
        readonly=True,
        copy=False,
        default=False,
        index=True,
        help="True when actual late minutes exceed the configured buffer time at calculation time.",
    )
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
    def _get_late_deduction_policy(self, company=None):
        company = company or self.env.company
        ICP = self.env["ir.config_parameter"].sudo()

        def _bool(key, default):
            val = ICP.get_param(key)
            if val is None:
                return default
            return str(val).strip().lower() in ("1", "true", "yes")

        def _int(key, default):
            try:
                return int(float(ICP.get_param(key, default)))
            except Exception:
                return default

        def _float(key, default):
            try:
                return float(ICP.get_param(key, default))
            except Exception:
                return default

        enabled = bool(getattr(company, "kio_late_deduction_enabled", _bool("kio_payroll_overview_extension.late_deduction_enabled", False)))
        buffer_minutes = max(0, int(getattr(company, "kio_late_buffer_minutes", _int("kio_payroll_overview_extension.late_buffer_minutes", 0)) or 0))
        threshold = int(getattr(company, "kio_late_days_threshold", _int("kio_payroll_overview_extension.late_days_threshold", 0)) or 0)
        deduction_days = float(getattr(company, "kio_late_salary_deduction_days", _float("kio_payroll_overview_extension.late_salary_deduction_days", 0.0)) or 0.0)
        if enabled and threshold <= 0:
            raise ValidationError(_(
                "Late Days Threshold must be greater than 0 when late salary deduction is enabled."
            ))
        if enabled and deduction_days <= 0:
            raise ValidationError(_(
                "Salary Deduction Days must be greater than 0 when late salary deduction is enabled."
            ))
        return {
            "enabled": enabled,
            "buffer_minutes": buffer_minutes,
            "late_days_threshold": threshold,
            "salary_deduction_days": deduction_days,
        }

    @api.model
    def _compute_workday_values(self, employee, workday_date, scheduled_check_in, attendances):
        company = employee.company_id or self.env.company
        actual_check_in = min(attendances.mapped("check_in")) if attendances else False
        late_minutes = 0.0
        if scheduled_check_in and actual_check_in and actual_check_in > scheduled_check_in:
            late_minutes = (actual_check_in - scheduled_check_in).total_seconds() / 60.0
        late_minutes = round(max(late_minutes, 0.0), 2)
        policy = self._get_late_deduction_policy(company)
        is_qualifying_late_day = bool(late_minutes > policy["buffer_minutes"])
        return {
            "name": "LD/%s/%s" % (employee.id, fields.Date.to_string(workday_date)),
            "employee_id": employee.id,
            "date": workday_date,
            "scheduled_check_in": scheduled_check_in,
            "actual_check_in": actual_check_in,
            "late_minutes": late_minutes,
            "is_qualifying_late_day": is_qualifying_late_day,
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
        """Lightweight periodic dispatcher for late attendance evaluation.

        Evaluates each employee only when the employee's local scheduled
        working start time + 30 minutes has passed (from the applicable
        resource.calendar). Supports employee/company timezones, different
        shifts, overnight schedules, weekends/non-working days, and missed-run
        recovery over a limited lookback window. No absent marking when
        attendance is not yet synchronized; existing grace/deduction policies
        are preserved.
        """
        now = fields.Datetime.now()  # naive UTC
        now_utc = pytz.UTC.localize(now)
        self.env.cr.execute("SELECT pg_try_advisory_xact_lock(%s)", (2017040001,))
        locked = self.env.cr.fetchone()
        if not locked or not locked[0]:
            return

        lookback_days = 7
        employees = self.env["hr.employee"].search([("active", "=", True)])
        for employee in employees:
            company = employee.company_id or self.env.company
            tz = self._get_tz(employee)
            local_now = now_utc.astimezone(tz)
            local_today = local_now.date()
            for offset in range(lookback_days):
                candidate_day = local_today - timedelta(days=offset)
                calendar = self._get_employee_calendar(employee, candidate_day)
                scheduled_utc, workday_date = self._get_calendar_day_start(
                    employee, calendar, candidate_day, tz
                )
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
                # Safe rerun: attendance/cron record with actual check-in is processed.
                if existing and existing.source in ("attendance", "cron") and existing.actual_check_in:
                    continue
                self._process_employee_workday(
                    employee, workday_date, scheduled_utc, allow_no_checkin=False
                )

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


class KioLateDeductionMonthlySummary(models.Model):
    _name = "kio.late.deduction.monthly.summary"
    _description = "Monthly Late Deduction Summary"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_from desc, employee_id"
    _check_company_auto = True

    name = fields.Char(string="Reference", compute="_compute_name", store=True)
    employee_id = fields.Many2one(
        "hr.employee", string="Employee", required=True, index=True, tracking=True, check_company=True
    )
    month = fields.Selection(
        [(str(i), str(i)) for i in range(1, 13)],
        string="Month",
        required=True,
    )
    year = fields.Integer(string="Year", required=True, default=lambda self: fields.Date.today().year)
    date_from = fields.Date(string="Period Start", compute="_compute_dates", store=True)
    date_to = fields.Date(string="Period End", compute="_compute_dates", store=True)
    total_attendance_days = fields.Integer(string="Total Attendance Days", readonly=True, copy=False)
    total_qualifying_late_days = fields.Integer(string="Total Qualifying Late Days", readonly=True, copy=False)
    buffer_minutes = fields.Integer(string="Configured Buffer Time", readonly=True, copy=False)
    late_days_threshold = fields.Integer(string="Late Days Threshold", readonly=True, copy=False)
    salary_deduction_days_per_threshold = fields.Float(
        string="Salary Deduction Days Per Threshold", readonly=True, copy=False, digits=(16, 2)
    )
    total_salary_deduction_days = fields.Float(
        string="Calculated Total Salary Deduction Days", readonly=True, copy=False, digits=(16, 2)
    )
    policy_enabled = fields.Boolean(string="Policy Enabled", readonly=True, copy=False)
    state = fields.Selection(
        [("draft", "Draft"), ("finalized", "Finalized")],
        string="Status",
        default="draft",
        required=True,
        tracking=True,
        copy=False,
    )
    company_id = fields.Many2one(
        "res.company", string="Company", required=True, default=lambda self: self.env.company, index=True
    )
    currency_id = fields.Many2one(related="company_id.currency_id", store=True, readonly=True)

    _sql_constraints = [
        (
            "kio_late_deduction_monthly_summary_uniq",
            "unique(employee_id, month, year, company_id)",
            "A monthly late deduction summary already exists for this employee and month.",
        ),
    ]

    @api.depends("employee_id", "month", "year")
    def _compute_name(self):
        for rec in self:
            if rec.employee_id and rec.month and rec.year:
                rec.name = "%s / %s-%02d" % (rec.employee_id.display_name, rec.year, int(rec.month))
            else:
                rec.name = _("New")

    @api.depends("month", "year")
    def _compute_dates(self):
        for rec in self:
            if rec.month and rec.year:
                m = int(rec.month)
                rec.date_from = fields.Date.to_date("%04d-%02d-01" % (rec.year, m))
                if m == 12:
                    rec.date_to = fields.Date.to_date("%04d-12-31" % rec.year)
                else:
                    rec.date_to = fields.Date.to_date("%04d-%02d-01" % (rec.year, m + 1)) - timedelta(days=1)
            else:
                rec.date_from = False
                rec.date_to = False

    def _check_manager(self):
        if not self.env.user.has_group("kio_payroll_overview_extension.group_kio_payroll_manager"):
            raise AccessError(_("Only Payroll Managers can manage monthly late deduction summaries."))

    @api.model
    def _calculate_month_values(self, employee, date_from, date_to, company):
        policy = self.env["kio.deduction"]._get_late_deduction_policy(company)
        lines = self.env["kio.deduction"].search([
            ("employee_id", "=", employee.id),
            ("company_id", "=", company.id),
            ("date", ">=", date_from),
            ("date", "<=", date_to),
            ("state", "!=", "cancelled"),
            ("actual_check_in", "!=", False),
        ])
        attendance_days = len(set(lines.mapped("date")))
        qualifying_days = sum(1 for line in lines if (line.late_minutes or 0.0) > policy["buffer_minutes"])
        if not policy["enabled"]:
            deduction_days = 0.0
        else:
            completed = math.floor(qualifying_days / policy["late_days_threshold"]) if policy["late_days_threshold"] else 0
            deduction_days = completed * policy["salary_deduction_days"]
        return {
            "total_attendance_days": attendance_days,
            "total_qualifying_late_days": qualifying_days,
            "buffer_minutes": policy["buffer_minutes"],
            "late_days_threshold": policy["late_days_threshold"],
            "salary_deduction_days_per_threshold": policy["salary_deduction_days"],
            "total_salary_deduction_days": deduction_days,
            "policy_enabled": policy["enabled"],
        }

    def action_compute(self):
        self._check_manager()
        for rec in self:
            if rec.state == "finalized":
                continue  # do not silently recalculate finalized periods
            if not rec.employee_id or not rec.date_from or not rec.date_to:
                continue
            vals = self._calculate_month_values(rec.employee_id, rec.date_from, rec.date_to, rec.company_id)
            rec.write(vals)
        return True

    def action_finalize(self):
        self._check_manager()
        for rec in self:
            if rec.state == "finalized":
                continue
            rec.action_compute()
            rec.state = "finalized"
            rec.message_post(body=_("Monthly late deduction summary finalized. Policy snapshot stored."))

    def action_draft(self):
        self._check_manager()
        for rec in self:
            # Explicit correction only; finalized historical snapshots should not be silently recalculated.
            rec.state = "draft"
            rec.message_post(body=_("Monthly late deduction summary reset to draft by an authorized user."))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered(lambda r: r.state == "draft").action_compute()
        return records

    def write(self, vals):
        res = super().write(vals)
        # Dynamic: draft records can be recomputed when key fields change; finalized remain unchanged.
        if any(f in vals for f in ("employee_id", "month", "year", "company_id")):
            self.filtered(lambda r: r.state == "draft").action_compute()
        return res
