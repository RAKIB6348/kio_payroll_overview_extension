from datetime import date

from odoo import Command, fields
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKioContractAllowanceIntegration(TransactionCase):
    """Contract allowances drive payroll preview and generation.

    All seven allowances are fixed monetary amounts on the running contract.
    House Rent must never be recomputed as a percentage of the basic wage.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.env.user.write({
            "groups_id": [Command.link(cls.env.ref(
                "kio_payroll_overview_extension.group_kio_payroll_manager"
            ).id)],
        })
        cls.calendar = cls.env["resource.calendar"].create({
            "name": "KIO Allowance Test Calendar",
            "company_id": cls.company.id,
            "attendance_ids": [
                Command.create({
                    "name": day,
                    "dayofweek": str(index),
                    "hour_from": 8.0,
                    "hour_to": 17.0,
                    "day_period": "morning",
                })
                for index, day in enumerate(
                    ["Mon", "Tue", "Wed", "Thu", "Fri"]
                )
            ],
        })
        cls.company.resource_calendar_id = cls.calendar.id

        cls.employee = cls._create_employee("Administrator")
        cls.employee_no_allowance = cls._create_employee("No Allowance Employee")
        cls.employee_other = cls._create_employee("Other Allowance Employee")

        cls.contract = cls._create_contract(
            cls.employee,
            wage=50000.0,
            house_rent=5000.0,
            medical=5000.0,
            conveyance=0.0,
            food=0.0,
            mobile=500.0,
            transport=0.0,
            other=0.0,
        )
        cls.contract_no_allowance = cls._create_contract(
            cls.employee_no_allowance, wage=30000.0
        )
        cls.contract_other = cls._create_contract(
            cls.employee_other,
            wage=20000.0,
            house_rent=1000.0,
            medical=200.0,
            conveyance=300.0,
            food=400.0,
            mobile=500.0,
            transport=600.0,
            other=700.0,
        )

        cls.start = date(2026, 11, 1)
        cls.end = date(2026, 11, 30)
        cls.Payslip = cls.env["kio.payroll.payslip"]

    @classmethod
    def _create_employee(cls, name):
        return cls.env["hr.employee"].create({
            "name": name,
            "company_id": cls.company.id,
            "resource_calendar_id": cls.calendar.id,
        })

    @classmethod
    def _create_contract(cls, employee, wage, house_rent=0.0, medical=0.0,
                         conveyance=0.0, food=0.0, mobile=0.0, transport=0.0,
                         other=0.0):
        return cls.env["hr.contract"].create({
            "name": "Contract - %s" % employee.name,
            "employee_id": employee.id,
            "company_id": cls.company.id,
            "date_start": date(2026, 1, 1),
            "wage": wage,
            "state": "open",
            "resource_calendar_id": cls.calendar.id,
            "kio_house_rent_allowance": house_rent,
            "kio_medical_allowance": medical,
            "kio_conveyance_allowance": conveyance,
            "kio_food_allowance": food,
            "kio_mobile_allowance": mobile,
            "kio_transport_allowance": transport,
            "kio_other_allowance": other,
        })

    def _preview_row(self, employee, start=None, end=None):
        data = self.Payslip.get_new_payroll_run_data(
            start or self.start, end or self.end
        )
        return next(
            (row for row in data.get("employees", [])
             if row["employee_id"] == employee.id),
            None,
        )

    def test_contract_total_allowance_sums_seven_fixed_fields(self):
        """All seven fixed allowances are summed, HRA is not a percentage."""
        self.assertAlmostEqual(self.contract.kio_total_allowance, 10500.0)
        self.assertAlmostEqual(
            self.Payslip._get_contract_total_allowance(
                self.contract, self.currency
            ),
            10500.0,
        )

    def test_legacy_percentage_is_ignored(self):
        """A legacy HRA percentage must not change the fixed allowance sum."""
        self.contract.write({"kio_house_rent_allowance_percent": 40.0})
        self.assertAlmostEqual(
            self.Payslip._get_contract_total_allowance(
                self.contract, self.currency
            ),
            10500.0,
        )
        self.assertAlmostEqual(self.contract.kio_total_allowance, 10500.0)

    def test_preview_allowance_and_net_pay(self):
        row = self._preview_row(self.employee)
        self.assertTrue(row)
        self.assertAlmostEqual(row["basic_salary"], 50000.0)
        self.assertAlmostEqual(row["allowance"], 10500.0)
        self.assertAlmostEqual(row["net_pay"], 60500.0)

    def test_preview_employee_without_allowances(self):
        row = self._preview_row(self.employee_no_allowance)
        self.assertTrue(row)
        self.assertAlmostEqual(row["allowance"], 0.0)
        self.assertAlmostEqual(row["net_pay"], 30000.0)

    def test_preview_uses_each_employees_own_contract(self):
        row = self._preview_row(self.employee_other)
        self.assertTrue(row)
        self.assertAlmostEqual(row["allowance"], 3700.0)
        self.assertAlmostEqual(row["net_pay"], 23700.0)

    def test_generated_payslip_matches_preview(self):
        preview = self._preview_row(self.employee)
        self.Payslip.generate_new_payroll_run({
            "name": "Nov 2026 Allowance Payroll",
            "payroll_type": "monthly",
            "payment_date": fields.Date.to_string(self.end),
            "date_start": fields.Date.to_string(self.start),
            "date_end": fields.Date.to_string(self.end),
            "employee_ids": [
                self.employee.id,
                self.employee_no_allowance.id,
                self.employee_other.id,
            ],
        })
        slip = self.Payslip.search([
            ("employee_id", "=", self.employee.id),
            ("date_from", "=", self.start),
            ("date_to", "=", self.end),
        ])
        self.assertEqual(len(slip), 1)
        self.assertAlmostEqual(slip.allowance, preview["allowance"])
        self.assertAlmostEqual(slip.allowance, 10500.0)
        self.assertAlmostEqual(slip.net_pay, preview["net_pay"])
        self.assertAlmostEqual(slip.net_pay, 60500.0)

        allowance_lines = slip.line_ids.filtered(lambda line: line.code == "ALW")
        self.assertEqual(len(allowance_lines), 1, "Allowance must not be duplicated")
        self.assertAlmostEqual(allowance_lines.amount, 10500.0)

        no_allowance_slip = self.Payslip.search([
            ("employee_id", "=", self.employee_no_allowance.id),
        ])
        self.assertAlmostEqual(no_allowance_slip.allowance, 0.0)
        self.assertAlmostEqual(no_allowance_slip.net_pay, 30000.0)

    def test_historical_payslip_is_not_recomputed(self):
        historical = self.Payslip.create({
            "name": "Historical Payslip",
            "employee_id": self.employee.id,
            "company_id": self.company.id,
            "date_from": date(2026, 10, 1),
            "date_to": date(2026, 10, 31),
            "line_ids": [
                Command.create({"name": "Basic Salary", "code": "BASIC", "sequence": 1, "amount": 50000.0, "total": 50000.0}),
                Command.create({"name": "Allowances", "code": "ALW", "sequence": 5, "amount": 9000.0, "total": 9000.0}),
                Command.create({"name": "Gross", "code": "GROSS", "sequence": 100, "amount": 59000.0, "total": 59000.0}),
                Command.create({"name": "Net", "code": "NET", "sequence": 200, "amount": 59000.0, "total": 59000.0}),
            ],
        })
        self.contract.write({
            "kio_house_rent_allowance": 8000.0,
            "kio_medical_allowance": 8000.0,
        })
        historical.invalidate_recordset()
        self.assertAlmostEqual(historical.allowance, 9000.0)
        self.assertAlmostEqual(historical.net_pay, 59000.0)
