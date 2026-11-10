from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    if not version:
        return

    # House Rent used to be stored as a percentage of the basic wage. Values
    # above 100 cannot be a sensible percentage and were in practice entered
    # as monetary amounts (for example 5000 instead of 5000 BDT). Preserve the
    # entered number as the fixed allowance instead of the old computed value
    # (wage * percent / 100). Genuine percentages (<= 100) keep their already
    # computed monetary amount.
    cr.execute("""
        UPDATE hr_contract
           SET kio_house_rent_allowance = kio_house_rent_allowance_percent
         WHERE kio_house_rent_allowance_percent > 100
    """)

    # Refresh the stored totals so existing contracts show the corrected
    # fixed allowance amounts.
    env = api.Environment(cr, SUPERUSER_ID, {})
    contracts = env["hr.contract"].search([])
    contracts._compute_kio_allowances()
