from odoo import _, api, fields, models
from odoo.exceptions import AccessError

SALARY_SETTING_FIELDS = frozenset({
    "salary_journal_id",
    "salary_debit_account_id",
    "salary_credit_account_id",
    "kio_overtime_multiplier",
    "kio_overtime_monetary_enabled",
})
SALARY_SETTINGS_WRITE_FIELDS = SALARY_SETTING_FIELDS | {"company_id"}

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
    kio_overtime_multiplier = fields.Float(
        related="company_id.kio_overtime_multiplier",
        readonly=False,
        string="Overtime Multiplier",
    )
    kio_overtime_monetary_enabled = fields.Boolean(
        related="company_id.kio_overtime_monetary_enabled",
        readonly=False,
        string="Enable Overtime Monetary Calculation",
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

    @api.model_create_multi
    def create(self, vals_list):
        cleaned_vals_list = []
        salary_values_list = []
        for vals in vals_list:
            vals = dict(vals)
            self._check_salary_settings_write_access(vals)
            salary_values_list.append(self._extract_salary_values(vals))
            cleaned_vals_list.append(vals)
        records = super().create(cleaned_vals_list)
        for record, salary_values in zip(records, salary_values_list):
            if salary_values:
                record.company_id.sudo().write(salary_values)
        return records

    def write(self, vals):
        vals = dict(vals)
        self._check_salary_settings_write_access(vals)
        salary_values = self._extract_salary_values(vals)
        result = super().write(vals)
        if salary_values:
            for record in self:
                record.company_id.sudo().write(salary_values)
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
