from . import models


def _post_init_kio_payroll_overview_extension(env):
    """Set a safe Employee Scope default for existing overtime configurations."""
    Config = env["kio.overtime.configuration"].sudo().with_context(active_test=False)
    configs = Config.search([("employee_scope", "=", False)])
    for rec in configs:
        if rec.employee_id:
            scope = "individual"
        elif rec.department_id:
            scope = "department"
        else:
            scope = "all"
        rec.write({"employee_scope": scope})

