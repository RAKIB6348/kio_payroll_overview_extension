from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    salary_journal_id = fields.Many2one(
        "account.journal",
        string="Salary Journal",
        check_company=True,
        domain="[('type', '=', 'general')]",
        help="Miscellaneous journal used for payroll accounting entries.",
    )
    salary_debit_account_id = fields.Many2one(
        "account.account",
        string="Salary Debit Account",
        check_company=True,
        domain=(
            "[('deprecated', '=', False), "
            "('account_type', 'in', "
            "('expense', 'expense_direct_cost', 'expense_depreciation'))]"
        ),
        help="Expense account debited for salary expense.",
    )
    salary_credit_account_id = fields.Many2one(
        "account.account",
        string="Salary Credit Account",
        check_company=True,
        domain=(
            "[('deprecated', '=', False), "
            "('account_type', 'in', "
            "('liability_payable', 'liability_credit_card', "
            "'liability_current', 'liability_non_current'))]"
        ),
        help="Liability account credited for salary payable.",
    )

    kio_overtime_multiplier = fields.Float(
        string="Overtime Multiplier",
        default=1.5,
        help="Documented default policy multiplier (e.g. 1.5). Monetary overtime "
             "is only calculated when 'Enable Overtime Monetary Calculation' is enabled.",
    )
    kio_overtime_monetary_enabled = fields.Boolean(
        string="Enable Overtime Monetary Calculation",
        default=False,
        help="When enabled, confirmed/applicable overtime hours are converted to "
             "amounts using wage, monthly scheduled hours, and the overtime multiplier. "
             "When disabled, overtime hours are shown but amount is not calculated.",
    )

    @api.constrains("kio_overtime_multiplier")
    def _check_kio_overtime_multiplier(self):
        for company in self:
            if company.kio_overtime_multiplier < 0:
                raise ValidationError(_("Overtime multiplier cannot be negative."))

    @api.constrains(
        "salary_journal_id",
        "salary_debit_account_id",
        "salary_credit_account_id",
    )
    def _check_salary_accounting_company(self):
        for company in self:
            for field_name in (
                "salary_journal_id",
                "salary_debit_account_id",
                "salary_credit_account_id",
            ):
                record = company[field_name]
                if record.company_id and record.company_id != company:
                    raise ValidationError(_(
                        "%(record)s must belong to the same company as the "
                        "payroll accounting configuration.",
                        record=record.display_name,
                    ))
