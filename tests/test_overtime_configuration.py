from datetime import date

from dateutil.relativedelta import relativedelta

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKioOvertimeConfiguration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "OT Test 40 Hours/Week",
            "company_id": cls.company.id,
            "attendance_ids": [
                (0, 0, {"name": "Mon", "dayofweek": "0", "hour_from": 8.0, "hour_to": 16.0, "day_period": "morning"}),
                (0, 0, {"name": "Tue", "dayofweek": "1", "hour_from": 8.0, "hour_to": 16.0, "day_period": "morning"}),
                (0, 0, {"name": "Wed", "dayofweek": "2", "hour_from": 8.0, "hour_to": 16.0, "day_period": "morning"}),
                (0, 0, {"name": "Thu", "dayofweek": "3", "hour_from": 8.0, "hour_to": 16.0, "day_period": "morning"}),
                (0, 0, {"name": "Fri", "dayofweek": "4", "hour_from": 8.0, "hour_to": 16.0, "day_period": "morning"}),
            ],
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "Administrator OT Test",
            "company_id": cls.company.id,
            "resource_calendar_id": cls.calendar.id,
        })
        # Running contract as in the reported issue.
        cls.contract = cls.env["hr.contract"].create({
            "name": "Administrator OT Contract",
            "employee_id": cls.employee.id,
            "company_id": cls.company.id,
            "date_start": date(2026, 10, 10),
            "wage": 50000.0,
            "state": "open",
            "resource_calendar_id": cls.calendar.id,
        })
        cls.config = cls.env["kio.overtime.configuration"].create({
            "employee_scope": "individual",
            "employee_id": cls.employee.id,
            "calculation_type": "percentage",
            "company_id": cls.company.id,
            "line_ids": [(0, 0, {
                "employee_id": cls.employee.id,
                "overtime_percentage": 150.0,
            })],
        })
        cls.line = cls.config.line_ids[0]

    def _expected_monthly_hours(self, line):
        contract = line._get_applicable_contract()
        return line._get_monthly_scheduled_hours(contract=contract)

    def test_existing_line_reads_running_contract_basic_salary(self):
        """Regression: existing overtime config line must read running contract wage."""
        self.line.invalidate_recordset(["basic_salary", "per_hour_salary", "has_applicable_contract"])
        self.assertTrue(self.line.has_applicable_contract)
        self.assertAlmostEqual(self.line.basic_salary, 50000.0, places=2)

        monthly_hours = self._expected_monthly_hours(self.line)
        self.assertGreater(monthly_hours, 0.0)
        self.assertAlmostEqual(self.line.per_hour_salary, 50000.0 / monthly_hours, places=2)

        # Existing configured overtime rate must remain intact.
        self.assertAlmostEqual(self.line.overtime_percentage, 150.0, places=2)

    def test_missing_contract_is_marked_clearly(self):
        employee = self.env["hr.employee"].create({
            "name": "No Contract Employee",
            "company_id": self.company.id,
            "resource_calendar_id": self.calendar.id,
        })
        config = self.env["kio.overtime.configuration"].create({
            "employee_scope": "individual",
            "employee_id": employee.id,
            "calculation_type": "fixed",
            "company_id": self.company.id,
            "line_ids": [(0, 0, {"employee_id": employee.id, "per_hour_rate": 10.0})],
        })
        line = config.line_ids[0]
        self.assertFalse(line.has_applicable_contract)
        self.assertAlmostEqual(line.basic_salary, 0.0, places=2)
        self.assertAlmostEqual(line.per_hour_salary, 0.0, places=2)
        self.assertAlmostEqual(line.per_hour_rate, 10.0, places=2)
