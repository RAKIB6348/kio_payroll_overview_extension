from datetime import date

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKioContractAllowanceIntegration(TransactionCase):
    """Contract allowances must drive payroll preview/generation (no salary config allowance)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.env.user.groups_id = [(4, cls.env.ref(
            "kio_payroll_overview_extension.group_kio_payroll_manager"
        ).id)]
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "KIO Allowance Test Calendar",
            "company_id": cls.company.id,
            "attendance_ids": [
                Command.create({"name": "Mon", "dayofweek": "0", "hour_from": 8.0, "hour_to": 17.0, "day_period": "morning"}),
                Command.create({"name": "Tue", "dayofweek": "1", "hour_from": 8.0, "hour_to": 17.0, "day_period": "morning"}),
                Command.create({"name": "Wed", "dayofweek": "2", "hour_from": 8.0, "hour_to": 17.0, "day_period": "morning"}),
                Command.create({"name": "Thu", "dayofweek": "3", "hour_from": 8.0, "hour_to": 17.0, "day_period": "morning"}),
                Command.create({"name": "Fri", "dayofweek": "4", "hour_from": 8.0, "hour_to": 17.0, "day_period": "morning"}),
            ],
        })
        cls.company.resource_calendar_id = cls.calendar.id
        cls.employee = cls.env["hr.employee"].create({
            "name": "Allowance Employee",
            "company_id": cls.company.id,
            "resource_calendar_id": cls.calendar.id,
        })
        cls.Contract = cls.env["hr.contract"]
        cls.contract = cls.Contract.create({
            "name": "Allowance Contract",
            "employee_id": cls.employee.id,
            "company_id": cls.company.id,
            "date_start": date(2026, 1, 1),
            "wage": 50000.0,
            "state": "open",
            "resource_calendar_id": cls.calendar.id,
            "kio_house_rent_allowance_percent": 40.0,
            "kio_medical_allowance": 2000.0,
            "kio_conveyance_allowance": 3000.0,
            "kio_food_allowance": 0.0,
            "kio_mobile_allowance": 0.0,
            "kio_transport_allowance": 0.0,
        })
        # Salary config allowance must NOT be used for payroll allowances.
        cls.salary_config = cls.env["kio.payroll.salary.config"].create({
            "employee_id": cls.employee.id,
            "company_id": cls.company.id,
            "basic_salary": 99999.0,
            "allowance": 7777.0,
            "active": True,
        })
        cls.start = date(2026, 11, 1)
        cls.end = date(2026, 11, 30)
        cls.Payslip = cls.env["kio.payroll.payslip"]

    def _preview_row(self, employee=None, start=None, end=None):
        employee = employee or self.employee
        data = self.Payslip.get_new_payroll_run_data(
            start or self.start, end or self.end
        )
        return next((r for r in data.get("employees", []) if r["employee_id"] == employee.id), None)

    def _generate(self, employee_ids, name="Nov 2026 Allowance Payroll"):
        return self.Payslip.generate_new_payroll_run({
            "name": name,
            "payroll_type": "monthly",
            "payment_date": fields.Date.to_string(self.end),
            "date_start": fields.Date.to_string(self.start),
            "date_end": fields.Date.to_string(self.end),
            "employee_ids": employee_ids,
        })

    def test_basic_from_contract_and_hra_medical_conveyance(self):
        # HRA = 40% of 50000 = 20000; Medical 2000; Conveyance 3000 => 25000
        row = self._preview_row()
        self.assertTrue(row)
        self.assertAlmostEqual(row["basic_salary"], 50000.0, places=2)
        self.assertAlmostEqual(row["allowance"], 25000.0, places=2)
        self.assertAlmostEqual(row["net_pay"], 75000.0, places=2)

    def test_salary_config_allowance_not_used(self):
        row = self._preview_row()
        self.assertNotAlmostEqual(row["allowance"], 7777.0, places=2)
        self.assertAlmostEqual(row["allowance"], 25000.0, places=2)

    def test_multiple_allowances_combined_and_zero_allowances(self):
        self.contract.write({
            "kio_food_allowance": 500.0,
            "kio_mobile_allowance": 300.0,
            "kio_transport_allowance": 200.0,
        })
        row = self._preview_row()
        self.assertAlmostEqual(row["allowance"], 26000.0, places=2)
        self.contract.write({
            "kio_house_rent_allowance_percent": 0.0,
            "kio_medical_allowance": 0.0,
            "kio_conveyance_allowance": 0.0,
            "kio_food_allowance": 0.0,
            "kio_mobile_allowance": 0.0,
            "kio_transport_allowance": 0.0,
        })
        row = self._preview_row()
        self.assertAlmostEqual(row["allowance"], 0.0, places=2)
        self.assertAlmostEqual(row["net_pay"], 50000.0, places=2)

    def test_missing_ineligible_contract_excluded(self):
        no_contract = self.env["hr.employee"].create({
            "name": "No Contract Allowance Emp",
            "company_id": self.company.id,
            "resource_calendar_id": self.calendar.id,
        })
        row = self._preview_row(no_contract)
        self.assertIsNone(row)

    def test_different_periods_and_multiple_contracts(self):
        # Future/ended contract should not apply; sequential contracts: applicable one used.
        self.Contract.create({
            "name": "Future Contract",
            "employee_id": self.employee.id,
            "company_id": self.company.id,
            "date_start": date(2027, 1, 1),
            "wage": 90000.0,
            "state": "open",
            "resource_calendar_id": self.calendar.id,
            "kio_medical_allowance": 9000.0,
        })
        row = self._preview_row()
        self.assertAlmostEqual(row["basic_salary"], 50000.0, places=2)
        self.assertAlmostEqual(row["allowance"], 25000.0, places=2)

    def test_company_isolation(self):
        other = self.env["res.company"].create({"name": "Other Allowance Co"})
        self.env.user.write({"company_ids": [Command.link(other.id)]})
        other_emp = self.env["hr.employee"].create({
            "name": "Other Co Emp",
            "company_id": other.id,
        })
        self.Contract.create({
            "name": "Other Co Contract",
            "employee_id": other_emp.id,
            "company_id": other.id,
            "date_start": date(2026, 1, 1),
            "wage": 10000.0,
            "state": "open",
            "kio_medical_allowance": 500.0,
        })
        # Preview uses env.company (current company)
        data = self.Payslip.with_company(self.company).get_new_payroll_run_data(self.start, self.end)
        ids = [r["employee_id"] for r in data.get("employees", [])]
        self.assertIn(self.employee.id, ids)
        self.assertNotIn(other_emp.id, ids)

    def test_preview_and_generated_payslip_match(self):
        row = self._preview_row()
        result = self._generate([self.employee.id])
        self.assertEqual(result.get("tag"), "kio_payroll_overview.batch_details")
        batch_id = result["context"]["kio_batch_id"]
        slip = self.env["kio.payroll.payslip"].search([
            ("batch_id", "=", batch_id), ("employee_id", "=", self.employee.id)
        ], limit=1)
        self.assertTrue(slip)
        self.assertAlmostEqual(slip.basic_salary, row["basic_salary"], places=2)
        self.assertAlmostEqual(slip.allowance, row["allowance"], places=2)
        self.assertAlmostEqual(slip.gross_salary, row["basic_salary"] + row["allowance"] + row["overtime"] + row["commission"] + row["bonus"], places=2)
        self.assertAlmostEqual(slip.net_pay, row["net_pay"], places=2)
        codes = {l.code: l.total for l in slip.line_ids}
        self.assertAlmostEqual(codes.get("ALW", 0.0), 25000.0, places=2)
        self.assertAlmostEqual(codes.get("GROSS", 0.0) - codes.get("DED", 0.0), codes.get("NET", 0.0), places=2)

    def test_historical_payslip_unchanged_after_contract_edit(self):
        self._generate([self.employee.id], name="Historical Allowance Payroll")
        slip = self.env["kio.payroll.payslip"].search([
            ("employee_id", "=", self.employee.id),
            ("date_from", "=", self.start),
            ("date_to", "=", self.end),
        ], limit=1)
        old_allowance = slip.allowance
        old_net = slip.net_pay
        old_alw_line = slip.line_ids.filtered(lambda l: l.code == "ALW").total
        self.contract.write({
            "kio_house_rent_allowance_percent": 0.0,
            "kio_medical_allowance": 0.0,
            "kio_conveyance_allowance": 0.0,
        })
        slip.invalidate_recordset()
        slip.line_ids.invalidate_recordset()
        self.assertAlmostEqual(slip.allowance, old_allowance, places=2)
        self.assertAlmostEqual(slip.net_pay, old_net, places=2)
        self.assertAlmostEqual(
            slip.line_ids.filtered(lambda l: l.code == "ALW").total, old_alw_line, places=2
        )

    def test_adjustments_and_bonus_still_integrated_with_contract_allowance(self):
        self.env["kio.overtime"].create({
            "employee_id": self.employee.id, "company_id": self.company.id,
            "date": date(2026, 11, 10), "overtime_hours": 1.0,
            "overtime_amount": 1000.0, "amount": 1000.0, "state": "confirmed", "source": "manual",
        })
        self.env["kio.commission"].create({
            "employee_id": self.employee.id, "company_id": self.company.id,
            "date": date(2026, 11, 11), "amount": 500.0, "state": "confirmed",
        })
        self.env["kio.deduction"].create({
            "employee_id": self.employee.id, "company_id": self.company.id,
            "date": date(2026, 11, 12), "deduction_amount": 200.0, "state": "confirmed", "source": "manual",
        })
        bonus_type = self.env.ref(
            "kio_payroll_overview_extension.kio_bonus_type_other", raise_if_not_found=False
        ) or self.env["kio.bonus.type"].search([], limit=1)
        if not bonus_type:
            bonus_type = self.env["kio.bonus.type"].create({"name": "Allowance Test Bonus"})
        bonus = self.env["kio.bonus"].create({
            "name": "Allowance Test Bonus",
            "bonus_type_id": bonus_type.id,
            "company_id": self.company.id,
            "payment_scope": "individual",
            "employee_ids": [Command.set([self.employee.id])],
            "calculation_type": "fixed",
            "amount": 300.0,
            "bonus_date": date(2026, 11, 15),
            "state": "draft",
        })
        bonus.action_generate_employees()
        bonus.action_confirm()
        row = self._preview_row()
        expected_gross = 50000.0 + 25000.0 + 1000.0 + 500.0 + row["bonus"]
        self.assertAlmostEqual(row["allowance"], 25000.0, places=2)
        self.assertGreaterEqual(row["bonus"], 0.0)
        self.assertAlmostEqual(row["net_pay"], expected_gross - 200.0, places=2)
        self._generate([self.employee.id], name="Allowance+Adjustments+Bonus Payroll")
        slip = self.env["kio.payroll.payslip"].search([
            ("employee_id", "=", self.employee.id),
            ("date_from", "=", self.start),
            ("company_id", "=", self.company.id),
        ], limit=1, order="id desc")
        self.assertAlmostEqual(slip.allowance, 25000.0, places=2)
        self.assertAlmostEqual(slip.overtime, 1000.0, places=2)
        self.assertAlmostEqual(slip.commission, 500.0, places=2)
        self.assertAlmostEqual(slip.deduction, 200.0, places=2)
        self.assertAlmostEqual(slip.bonus, row["bonus"], places=2)

    def test_no_duplicate_allowance_calculation(self):
        # Total allowance is contract total (HRA+fixed components), not added again.
        row = self._preview_row()
        self.assertAlmostEqual(row["allowance"], self.contract.kio_total_allowance, places=2)
        self._generate([self.employee.id], name="No Duplicate Allowance")
        slip = self.env["kio.payroll.payslip"].search([
            ("employee_id", "=", self.employee.id), ("date_from", "=", self.start)
        ], limit=1, order="id desc")
        alw_lines = slip.line_ids.filtered(lambda l: l.code == "ALW")
        self.assertEqual(len(alw_lines), 1)
        self.assertAlmostEqual(alw_lines.total, self.contract.kio_total_allowance, places=2)
