def migrate(cr, version):
    """Preserve existing medical allowance values before field simplification.

    Older versions stored medical allowance as type/fixed/percentage inputs with a
    computed amount. Convert to a single fixed monetary amount without dropping
    obsolete columns.
    """
    cr.execute("""
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'hr_contract'
    """)
    cols = {r[0] for r in cr.fetchall()}
    if "kio_medical_allowance" not in cols:
        return
    required = {
        "kio_medical_allowance_type",
        "kio_medical_allowance_fixed",
        "kio_medical_allowance_percent",
    }
    if not required.issubset(cols):
        return
    cr.execute("""
        UPDATE hr_contract
           SET kio_medical_allowance = CASE
               WHEN COALESCE(kio_medical_allowance_type, 'fixed') = 'percentage'
                    THEN COALESCE(wage, 0) * COALESCE(kio_medical_allowance_percent, 0) / 100.0
               ELSE COALESCE(kio_medical_allowance_fixed, 0)
           END
         WHERE (
                COALESCE(kio_medical_allowance_fixed, 0) != 0
             OR COALESCE(kio_medical_allowance_percent, 0) != 0
             OR COALESCE(kio_medical_allowance, 0) != 0
         )
    """)
