from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """BUG-002: fix Late Attendance dispatcher schedule on existing databases.

    The cron XML is noupdate="1", so upgrades would not correct the legacy
    1-minute schedule. Update only the module's late-attendance cron.
    Preserve unrelated settings (e.g. admin-disabled active state) and do not
    touch other scheduled actions.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    cron = env.ref(
        "kio_payroll_overview_extension.ir_cron_kio_daily_late_attendance_sync",
        raise_if_not_found=False,
    )
    if not cron:
        return
    vals = {}
    # Lightweight periodic dispatcher with per-employee due-time checks.
    if cron.interval_type != "minutes" or cron.interval_number != 15:
        vals.update({"interval_number": 15, "interval_type": "minutes"})
    if cron.name in ("Daily Late Attendance Sync", "Late Attendance Sync"):
        vals["name"] = "Late Attendance Dispatcher"
    # Ensure the intended model method is used; do not alter active/doall/nextcall.
    if cron.code != "model._cron_daily_late_attendance_sync()":
        vals["code"] = "model._cron_daily_late_attendance_sync()"
    if vals:
        cron.sudo().write(vals)
