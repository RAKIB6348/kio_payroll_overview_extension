from odoo import api, fields, models


class HrContract(models.Model):
    _inherit = "hr.contract"

    # Legacy percentage input, kept for backward compatibility only. Payroll
    # allowances are fixed monetary amounts; this field is no longer used.
    kio_house_rent_allowance_percent = fields.Float(
        string="House Rent Allowance (%) (legacy)",
        digits=(16, 2),
        default=0.0,
    )
    # House Rent Allowance: fixed monetary amount
    kio_house_rent_allowance = fields.Monetary(
        string="House Rent Allowance",
        currency_field="currency_id",
        default=0.0,
    )

    # Medical Allowance: fixed monetary amount
    kio_medical_allowance = fields.Monetary(
        string="Medical Allowance",
        currency_field="currency_id",
        default=0.0,
    )

    # Fixed-amount allowances
    kio_conveyance_allowance = fields.Monetary(
        string="Conveyance Allowance",
        currency_field="currency_id",
        default=0.0,
    )
    kio_food_allowance = fields.Monetary(
        string="Food Allowance",
        currency_field="currency_id",
        default=0.0,
    )
    kio_mobile_allowance = fields.Monetary(
        string="Mobile Allowance",
        currency_field="currency_id",
        default=0.0,
    )
    kio_transport_allowance = fields.Monetary(
        string="Transport Allowance",
        currency_field="currency_id",
        default=0.0,
    )
    kio_other_allowance = fields.Monetary(
        string="Other Allowance",
        currency_field="currency_id",
        default=0.0,
    )

    kio_total_allowance = fields.Monetary(
        string="Total Allowance",
        compute="_compute_kio_allowances",
        store=True,
        currency_field="currency_id",
        readonly=True,
    )
    kio_gross_salary = fields.Monetary(
        string="Gross Salary",
        compute="_compute_kio_allowances",
        store=True,
        currency_field="currency_id",
        readonly=True,
    )

    @api.depends(
        "wage",
        "currency_id",
        "kio_house_rent_allowance",
        "kio_medical_allowance",
        "kio_conveyance_allowance",
        "kio_food_allowance",
        "kio_mobile_allowance",
        "kio_transport_allowance",
        "kio_other_allowance",
    )
    def _compute_kio_allowances(self):
        for contract in self:
            wage = contract.wage or 0.0
            currency = contract.currency_id or contract.company_id.currency_id
            # All allowances are fixed monetary amounts; House Rent is not a
            # percentage of the basic wage.
            house_rent = contract.kio_house_rent_allowance or 0.0
            medical = contract.kio_medical_allowance or 0.0
            conveyance = contract.kio_conveyance_allowance or 0.0
            food = contract.kio_food_allowance or 0.0
            mobile = contract.kio_mobile_allowance or 0.0
            transport = contract.kio_transport_allowance or 0.0
            other = contract.kio_other_allowance or 0.0
            total = (
                house_rent + medical + conveyance + food + mobile + transport
                + other
            )
            gross = wage + total
            if currency:
                total = currency.round(total)
                gross = currency.round(gross)
            contract.kio_total_allowance = total
            contract.kio_gross_salary = gross
