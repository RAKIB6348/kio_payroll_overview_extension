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
LATE_POLICY_FIELDS = frozenset({
    "kio_late_deduction_enabled",
    "kio_late_buffer_minutes",
    "kio_late_days_threshold",
    "kio_late_salary_deduction_days",
})
CONFIG_PARAM_FIELDS = OVERTIME_RATE_CONFIG_FIELDS
SALARY_SETTINGS_WRITE_FIELDS = (
    SALARY_SETTING_FIELDS | set(CONFIG_PARAM_FIELDS) | LATE_POLICY_FIELDS | {"company_id"}
)

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
        default=False,
    )
    kio_late_buffer_minutes = fields.Integer(
        string="Buffer Time (Minutes)",
        default=0,
    )
    kio_late_days_threshold = fields.Integer(
        string="Late Days Threshold",
        default=0,
    )
    kio_late_salary_deduction_days = fields.Float(
        string="Salary Deduction Days",
        default=0.0,
        digits=(16, 2),
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        policy_fields = LATE_POLICY_FIELDS.intersection(fields_list)
        if not policy_fields:
            return values

        company_id = (
            values.get("company_id")
            or self.env.context.get("default_company_id")
            or self.env.company.id
        )
        company = self.env["res.company"].browse(company_id).exists()
        if company:
            for field_name in policy_fields:
                values[field_name] = company[field_name]
        return values

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

    @staticmethod
    def _persist_late_policy_values(company, values):
        if values and company:
            # Store these settings on the selected company only. Older releases
            # wrote global ir.config_parameter values, which are not company-safe.
            company.sudo().write(values)

    def _persist_current_late_policy_values(self):
        for record in self:
            values = {
                field_name: record[field_name]
                for field_name in LATE_POLICY_FIELDS
            }
            self._persist_late_policy_values(record.company_id, values)

    def _persist_overtime_rate_config_values(self, company, values):
        ICP = self.env["ir.config_parameter"].sudo()
        company_vals = {}
        bool_fields = set()
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
        late_policy_values_list = []
        for vals in vals_list:
            vals = dict(vals)
            self._check_salary_settings_write_access(vals)
            salary_values_list.append(self._extract_salary_values(vals))
            overtime_values_list.append(self._extract_overtime_rate_config_values(vals))
            late_policy_values_list.append({
                field_name: vals[field_name]
                for field_name in LATE_POLICY_FIELDS
                if field_name in vals
            })
            cleaned_vals_list.append(vals)
        records = super().create(cleaned_vals_list)
        for record, salary_values, overtime_values, late_policy_values in zip(
            records, salary_values_list, overtime_values_list, late_policy_values_list
        ):
            if salary_values:
                record.company_id.sudo().write(salary_values)
            if overtime_values:
                record._persist_overtime_rate_config_values(record.company_id, overtime_values)
            if late_policy_values:
                record._persist_late_policy_values(record.company_id, late_policy_values)
                record.invalidate_recordset(list(LATE_POLICY_FIELDS))
        return records

    def write(self, vals):
        vals = dict(vals)
        self._check_salary_settings_write_access(vals)
        salary_values = self._extract_salary_values(vals)
        overtime_values = self._extract_overtime_rate_config_values(vals)
        late_policy_values = {
            field_name: vals[field_name]
            for field_name in LATE_POLICY_FIELDS
            if field_name in vals
        }
        result = super().write(vals)
        if salary_values or overtime_values or late_policy_values:
            for record in self:
                if salary_values:
                    record.company_id.sudo().write(salary_values)
                if overtime_values:
                    record._persist_overtime_rate_config_values(record.company_id, overtime_values)
                if late_policy_values:
                    record._persist_late_policy_values(record.company_id, late_policy_values)
                    record.invalidate_recordset(list(LATE_POLICY_FIELDS))
        return result

    def set_values(self):
        # Related settings fields are normally persisted through write(). This
        # explicit hook also covers the standard Settings Save/execute flow.
        super().set_values()
        self._persist_current_late_policy_values()

    def execute(self):
        """Allow payroll/accounting managers to save the payroll settings."""
        if not self.env.is_admin():
            if not self._is_salary_settings_manager():
                raise AccessError(_(
                    "Only Payroll or Accounting administrators can modify the "
                    "payroll accounting configuration."
                ))
            # Persist company-scoped settings explicitly. Do not run the global settings pipeline here:
            # it would execute the set_values() overrides of every installed
            # application and require unrelated administrative rights.
            self._persist_current_late_policy_values()
            return {"type": "ir.actions.client", "tag": "reload"}
        return super().execute()
