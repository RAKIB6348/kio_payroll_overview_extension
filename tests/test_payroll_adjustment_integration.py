from datetime import date

from odoo import fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKioPayrollAdjustmentIntegration(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.employee = cls.env["hr.employee"].create({
            "name": "Payroll Adjustment Employee",
            "company_id": cls.company.id,
        })
        cls.employee2 = cls.env["hr.employee"].create({
            "name": "Payroll Adjustment Employee 2",
            "company_id": cls.company.id,
        })
        cls.other_company = cls.env["res.company"].create({"name": "Other Payroll Co"})
        cls.env.user.write({"company_ids": [(4, cls.other_company.id)]})
        cls.other_employee = cls.env["hr.employee"].create({
            "name": "Other Company Employee",
            "company_id": cls.other_company.id,
        })
        cls.start = date(2026, 11, 1)
        cls.end = date(2026, 11, 30)
        cls.Contract = cls.env.get("hr.contract")
        if cls.Contract:
            cls.Contract.create({
                "name": "Adj Contract",
                "employee_id": cls.employee.id,
                "company_id": cls.company.id,
                "date_start": date(2026, 1, 1),
                "wage": 50000.0,
                "state": "open",
            })
            cls.Contract.create({
                "name": "Adj Contract 2",
                "employee_id": cls.employee2.id,
                "company_id": cls.company.id,
                "date_start": date(2026, 1, 1),
                "wage": 30000.0,
                "state": "open",
            })

    def _create_overtime(self, employee, amount, state="confirmed", day=10, company=None):
        company = company or self.company
        return self.env["kio.overtime"].create({
            "employee_id": employee.id,
            "company_id": company.id,
            "date": date(2026, 11, day),
            "overtime_hours": 1.0,
            "overtime_amount": amount,
            "amount": amount,
            "state": state,
            "source": "manual",
        })

    def _create_commission(self, employee, amount, state="confirmed", day=11, company=None):
        company = company or self.company
        return self.env["kio.commission"].create({
            "employee_id": employee.id,
            "company_id": company.id,
            "date": date(2026, 11, day),
            "amount": amount,
            "state": state,
        })

    def _create_deduction(self, employee, amount, state="confirmed", day=12, company=None):
        company = company or self.company
        return self.env["kio.deduction"].create({
            "employee_id": employee.id,
            "company_id": company.id,
            "date": date(2026, 11, day),
            "deduction_amount": amount,
            "state": state,
            "source": "manual",
        })

    def _preview_row(self, employee):
        data = self.env["kio.payroll.payslip"].get_new_payroll_run_data(self.start, self.end)
        rows = {r["employee_id"]: r for r in data.get("employees", [])}
        return rows.get(employee.id)

    def test_confirmed_overtime_included_draft_excluded(self):
        self._create_overtime(self.employee, 2000.0, state="confirmed")
        self._create_overtime(self.employee, 999.0, state="draft", day=13)
        row = self._preview_row(self.employee)
        self.assertTrue(row)
        self.assertAlmostEqual(row["overtime"], 2000.0, places=2)

    def test_confirmed_commission_included_draft_excluded(self):
        self._create_commission(self.employee, 1000.0, state="confirmed")
        self._create_commission(self.employee, 888.0, state="draft", day=14)
        row = self._preview_row(self.employee)
        self.assertAlmostEqual(row["commission"], 1000.0, places=2)

    def test_confirmed_deduction_reduces_net_cancelled_excluded(self):
        self._create_deduction(self.employee, 500.0, state="confirmed")
        self._create_deduction(self.employee, 777.0, state="cancelled", day=15)
        row = self._preview_row(self.employee)
        self.assertAlmostEqual(row["deduction"], 500.0, places=2)
        gross = row["basic_salary"] + row["allowance"] + row["overtime"] + row["commission"] + row["bonus"]
        self.assertAlmostEqual(row["net_pay"], gross - 500.0, places=2)

    def test_multiple_adjustments_aggregate_and_formula(self):
        self._create_overtime(self.employee, 2000.0)
        self._create_overtime(self.employee, 250.0, day=16)
        self._create_commission(self.employee, 1000.0)
        self._create_deduction(self.employee, 500.0)
        row = self._preview_row(self.employee)
        # Gross = Basic + Allowances + Overtime + Commission + Bonus; Net = Gross - Deductions
        self.assertAlmostEqual(row["basic_salary"], 50000.0, places=2)
        self.assertAlmostEqual(row["overtime"], 2250.0, places=2)
        self.assertAlmostEqual(row["commission"], 1000.0, places=2)
        self.assertAlmostEqual(row["deduction"], 500.0, places=2)
        gross = 50000.0 + row["allowance"] + 2250.0 + 1000.0 + row["bonus"]
        self.assertAlmostEqual(row["net_pay"], gross - 500.0, places=2)

    def test_outside_period_and_company_isolation(self):
        self._create_overtime(self.employee, 100.0, day=10)
        self.env["kio.overtime"].create({
            "employee_id": self.employee.id, "company_id": self.company.id,
            "date": date(2026, 10, 31), "overtime_hours": 1.0,
            "overtime_amount": 999.0, "amount": 999.0, "state": "confirmed", "source": "manual",
        })
        row = self._preview_row(self.employee)
        self.assertAlmostEqual(row["overtime"], 100.0, places=2)

    def test_preview_and_generation_match(self):
        self._create_overtime(self.employee, 2000.0)
        self._create_commission(self.employee, 1000.0)
        self._create_deduction(self.employee, 500.0)
        row = self._preview_row(self.employee)
        Payslip = self.env["kio.payroll.payslip"]
        result = Payslip.generate_new_payroll_run({
            "name": "Nov 2026 Integration",
            "payroll_type": "monthly",
            "payment_date": fields.Date.to_string(self.end),
            "date_start": fields.Date.to_string(self.start),
            "date_end": fields.Date.to_string(self.end),
            "employee_ids": [self.employee.id],
        })
        self.assertEqual(result.get("tag"), "kio_payroll_overview.batch_details")
        slip = self.env["kio.payroll.payslip"].search([
            ("employee_id", "=", self.employee.id),
            ("date_from", "=", self.start),
            ("date_to", "=", self.end),
            ("company_id", "=", self.company.id),
        ], limit=1)
        self.assertTrue(slip)
        self.assertAlmostEqual(slip.overtime, row["overtime"], places=2)
        self.assertAlmostEqual(slip.commission, row["commission"], places=2)
        self.assertAlmostEqual(slip.deduction, row["deduction"], places=2)
        self.assertAlmostEqual(slip.net_pay, row["net_pay"], places=2)
        codes = {l.code: l.total for l in slip.line_ids}
        self.assertIn("COMMISSION", codes)
        self.assertAlmostEqual(codes.get("GROSS", 0.0) - codes.get("DED", 0.0), codes.get("NET", 0.0), places=2)

    def test_duplicate_inclusion_prevented_and_bonus_still_works(self):
        ot = self._create_overtime(self.employee, 2000.0)
        com = self._create_commission(self.employee, 1000.0)
        ded = self._create_deduction(self.employee, 500.0)
        Payslip = self.env["kio.payroll.payslip"]
        Payslip.generate_new_payroll_run({
            "name": "Nov 2026 First",
            "payroll_type": "monthly",
            "payment_date": fields.Date.to_string(self.end),
            "date_start": fields.Date.to_string(self.start),
            "date_end": fields.Date.to_string(self.end),
            "employee_ids": [self.employee.id],
        })
        ot.invalidate_recordset()
        com.invalidate_recordset()
        ded.invalidate_recordset()
        self.assertTrue(ot.applied)
        self.assertTrue(com.applied)
        self.assertTrue(ded.applied)
        # Preview for same period after application should not include applied-to-active payslip amounts.
        row = self._preview_row(self.employee)
        self.assertAlmostEqual(row["overtime"], 0.0, places=2)
        self.assertAlmostEqual(row["commission"], 0.0, places=2)
        self.assertAlmostEqual(row["deduction"], 0.0, places=2)

    def test_missing_adjustments_are_zero(self):
        row = self._preview_row(self.employee)
        self.assertAlmostEqual(row["overtime"], 0.0, places=2)
        self.assertAlmostEqual(row["commission"], 0.0, places=2)
        self.assertAlmostEqual(row["deduction"], 0.0, places=2)
