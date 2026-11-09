from odoo import _, api, fields, models
from odoo.exceptions import AccessError

SALARY_SETTING_FIELDS = frozenset({
    "salary_journal_id",
    "salary_debit_account_id",
    "salary_credit_account_id",
    "kio_overtime_monetary_enabled",
})
OVERTIME_RATE_CONFIG_FIELDS = {
    "kio_overtime_per_hour_rate": "kio_payroll_overview_extension.overtime_per_hour_rate",
    "kio_overtime_per_day_rate": "kio_payroll_overview_extension.overtime_per_day_rate",
}
LATE_DEDUCTION_CONFIG_FIELDS = {
    "kio_late_deduction_enabled": "kio_payroll_overview_extension.late_deduction_enabled",
    "kio_late_buffer_minutes": "kio_payroll_overview_extension.late_buffer_minutes",
    "kio_late_days_threshold": "kio_payroll_overview_extension.late_days_threshold",
    "kio_late_salary_deduction_days": "kio_payroll_overview_extension.late_salary_deduction_days",
}
CONFIG_PARAM_FIELDS = {**OVERTIME_RATE_CONFIG_FIELDS, **LATE_DEDUCTION_CONFIG_FIELDS}
SALARY_SETTINGS_WRITE_FIELDS = SALARY_SETTING_FIELDS | set(CONFIG_PARAM_FIELDS) | {"company_id"}

PAYROLL_SETTINGS_GROUPS = (
    "kio_payroll_overview_extension.group_kio_payroll_manager",
    "account.group_account_manager",
)


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    salary_journal_id = fields.Many2one(
        "account.journal",
        string="Salary Journal",
        related="company_id.salary_journal_id",
        readonly=False,
    )
    salary_debit_account_id = fields.Many2one(
        "account.account",
        string="Salary Debit Account",
        related="company_id.salary_debit_account_id",
        readonly=False,
    )
    salary_credit_account_id = fields.Many2one(
        "account.account",
        string="Salary Credit Account",
        related="company_id.salary_credit_account_id",
        readonly=False,
    )
    kio_overtime_monetary_enabled = fields.Boolean(
        related="company_id.kio_overtime_monetary_enabled",
        readonly=False,
        string="Enable Overtime Monetary Calculation",
    )
    kio_overtime_per_hour_rate = fields.Float(
        string="Per Hour Rate (BDT)",
        config_parameter="kio_payroll_overview_extension.overtime_per_hour_rate",
        default=0.0,
        digits=(16, 2),
    )
    kio_overtime_per_day_rate = fields.Float(
        string="Per Day Rate (BDT)",
        config_parameter="kio_payroll_overview_extension.overtime_per_day_rate",
        default=0.0,
        digits=(16, 2),
    )
    kio_late_deduction_enabled = fields.Boolean(
        string="Enable Late Salary Deduction",
        config_parameter="kio_payroll_overview_extension.late_deduction_enabled",
        default=False,
    )
    kio_late_buffer_minutes = fields.Integer(
        string="Buffer Time (Minutes)",
        config_parameter="kio_payroll_overview_extension.late_buffer_minutes",
        default=10,
    )
    kio_late_days_threshold = fields.Integer(
        string="Late Days Threshold",
        config_parameter="kio_payroll_overview_extension.late_days_threshold",
        default=3,
    )
    kio_late_salary_deduction_days = fields.Float(
        string="Salary Deduction Days",
        config_parameter="kio_payroll_overview_extension.late_salary_deduction_days",
        default=1.0,
        digits=(16, 2),
    )

    def _is_salary_settings_manager(self):
        """Return whether the user may edit payroll accounting settings."""
        if self.env.is_admin():
            return True
        return any(
            self.env.user.has_group(group) for group in PAYROLL_SETTINGS_GROUPS
        )

    def _check_salary_settings_write_access(self, vals):
        """Restrict non-admin managers to the payroll accounting fields."""
        if self.env.is_admin():
            return
        if not self._is_salary_settings_manager():
            raise AccessError(_(
                "Only Payroll or Accounting administrators can modify the "
                "payroll accounting configuration."
            ))
        extra_fields = set(vals) - SALARY_SETTINGS_WRITE_FIELDS
        if extra_fields:
            raise AccessError(_(
                "You are not allowed to modify these settings: %(fields)s",
                fields=", ".join(sorted(extra_fields)),
            ))

    @staticmethod
    def _extract_salary_values(vals):
        """Pop salary fields from vals and return them separately."""
        salary_values = {
            field_name: vals.pop(field_name)
            for field_name in SALARY_SETTING_FIELDS
            if field_name in vals
        }
        return salary_values

    def _extract_overtime_rate_config_values(self, vals):
        values = {}
        for field_name, param in CONFIG_PARAM_FIELDS.items():
            if field_name in vals:
                values[field_name] = (param, vals.pop(field_name))
        return values

    def _persist_overtime_rate_config_values(self, company, values):
        ICP = self.env["ir.config_parameter"].sudo()
        company_vals = {}
        bool_fields = {"kio_late_deduction_enabled"}
        int_fields = {"kio_late_buffer_minutes", "kio_late_days_threshold"}
        for field_name, (param, value) in values.items():
            if field_name in bool_fields:
                ICP.set_param(param, "True" if value else "False")
                company_vals[field_name] = bool(value)
            elif field_name in int_fields:
                ival = int(value or 0)
                ICP.set_param(param, str(ival))
                company_vals[field_name] = ival
            else:
                fval = float(value or 0.0)
                ICP.set_param(param, str(fval))
                company_vals[field_name] = fval
        if company_vals and company:
            company.sudo().write(company_vals)

    @api.model_create_multi
    def create(self, vals_list):
        cleaned_vals_list = []
        salary_values_list = []
        overtime_values_list = []
        for vals in vals_list:
            vals = dict(vals)
            self._check_salary_settings_write_access(vals)
            salary_values_list.append(self._extract_salary_values(vals))
            overtime_values_list.append(self._extract_overtime_rate_config_values(vals))
            cleaned_vals_list.append(vals)
        records = super().create(cleaned_vals_list)
        for record, salary_values, overtime_values in zip(records, salary_values_list, overtime_values_list):
            if salary_values:
                record.company_id.sudo().write(salary_values)
            if overtime_values:
                record._persist_overtime_rate_config_values(record.company_id, overtime_values)
        return records

    def write(self, vals):
        vals = dict(vals)
        self._check_salary_settings_write_access(vals)
        salary_values = self._extract_salary_values(vals)
        overtime_values = self._extract_overtime_rate_config_values(vals)
        result = super().write(vals)
        if salary_values or overtime_values:
            for record in self:
                if salary_values:
                    record.company_id.sudo().write(salary_values)
                if overtime_values:
                    record._persist_overtime_rate_config_values(record.company_id, overtime_values)
        return result

    def execute(self):
        """Allow payroll/accounting managers to save the payroll settings."""
        if not self.env.is_admin():
            if not self._is_salary_settings_manager():
                raise AccessError(_(
                    "Only Payroll or Accounting administrators can modify the "
                    "payroll accounting configuration."
                ))
            # The salary fields are already persisted on res.company by
            # create()/write(). Do not run the global settings pipeline here:
            # it would execute the set_values() overrides of every installed
            # application and require unrelated administrative rights.
            return {"type": "ir.actions.client", "tag": "reload"}
        return super().execute()
