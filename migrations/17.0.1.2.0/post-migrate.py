def migrate(cr, version):
    cr.execute("""
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'kio_bonus' AND column_name = 'employee_id'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        SELECT 1
          FROM information_schema.tables
         WHERE table_name = 'kio_bonus_hr_employee_rel'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        INSERT INTO kio_bonus_hr_employee_rel (bonus_id, employee_id)
        SELECT b.id, b.employee_id
          FROM kio_bonus b
         WHERE b.employee_id IS NOT NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM kio_bonus_hr_employee_rel rel
                WHERE rel.bonus_id = b.id
                  AND rel.employee_id = b.employee_id
           )
    """)
