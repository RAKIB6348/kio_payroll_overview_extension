from . import models


def _post_init_kio_payroll_overview_extension(env):
    """Set safe defaults and migrate legacy individual selections for overtime configurations."""
    Config = env["kio.overtime.configuration"].sudo().with_context(active_test=False)
    configs = Config.search([])
    for rec in configs:
        vals = {}
        if not rec.employee_scope:
            if rec.employee_ids or rec.employee_id:
                vals["employee_scope"] = "individual"
            elif rec.department_id:
                vals["employee_scope"] = "department"
            else:
                vals["employee_scope"] = "all"
        scope = vals.get("employee_scope") or rec.employee_scope
        if scope == "individual" and rec.employee_id and not rec.employee_ids:
            vals["employee_ids"] = [(6, 0, [rec.employee_id.id])]
            vals["employee_id"] = False
        if vals:
            rec.write(vals)

