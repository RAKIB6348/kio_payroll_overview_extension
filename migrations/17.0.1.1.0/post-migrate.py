from odoo import SUPERUSER_ID, api


DEFAULT_BONUS_TYPES = [
    ("kio_bonus_type_festival", "Festival Bonus", 10),
    ("kio_bonus_type_performance", "Performance Bonus", 20),
    ("kio_bonus_type_attendance", "Attendance Bonus", 30),
    ("kio_bonus_type_incentive", "Incentive Bonus", 40),
    ("kio_bonus_type_other", "Other Bonus", 50),
]

SELECTION_MAP = {
    "festival": "kio_bonus_type_festival",
    "performance": "kio_bonus_type_performance",
    "attendance": "kio_bonus_type_attendance",
    "incentive": "kio_bonus_type_incentive",
    "other": "kio_bonus_type_other",
}


def _ensure_bonus_types(env):
    """Create default bonus types without duplicating existing records."""
    BonusType = env["kio.bonus.type"].with_context(active_test=False)
    module = "kio_payroll_overview_extension"
    created = {}
    for xml_key, name, sequence in DEFAULT_BONUS_TYPES:
        xmlid = "%s.%s" % (module, xml_key)
        record = env.ref(xmlid, raise_if_not_found=False)
        if not record:
            record = BonusType.search([
                ("name", "=", name),
                ("company_id", "=", False),
            ], limit=1)
            if not record:
                record = BonusType.create({
                    "name": name,
                    "sequence": sequence,
                    "active": True,
                })
                env["ir.model.data"].create({
                    "name": xml_key,
                    "module": module,
                    "model": "kio.bonus.type",
                    "res_id": record.id,
                    "noupdate": True,
                })
        created[xml_key] = record.id
    return created


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    type_ids = _ensure_bonus_types(env)

    cr.execute("""
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'kio_bonus' AND column_name = 'bonus_type'
    """)
    if not cr.fetchone():
        return

    fallback_id = type_ids["kio_bonus_type_other"]
    for selection_value, xml_key in SELECTION_MAP.items():
        cr.execute(
            """
            UPDATE kio_bonus
               SET bonus_type_id = %s
             WHERE bonus_type = %s
               AND (bonus_type_id IS NULL OR bonus_type_id = 0)
            """,
            (type_ids[xml_key], selection_value),
        )

    cr.execute(
        """
        UPDATE kio_bonus
           SET bonus_type_id = %s
         WHERE bonus_type_id IS NULL OR bonus_type_id = 0
        """,
        (fallback_id,),
    )
