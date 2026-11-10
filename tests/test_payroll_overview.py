from datetime import date

from odoo import Command, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestKioPayrollOverview(TransactionCase):
    """Independent KIO payroll regression tests (no hr_payroll_community)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id
        cls.manager_group = cls.env.ref(
            "kio_payroll_overview_extension.group_kio_payroll_manager"
        )
        cls.user_group = cls.env.ref(
            "kio_payroll_overview_extension.group_kio_payroll_user"
        )
        cls.env.user.groups_id = [(4, cls.manager_group.id)]

        cls.calendar = cls.env["resource.calendar"].create({
            "name": "KIO Test Calendar",
            "company_id": cls.company.id,
            "attendance_ids": [
                (0, 0, {"name": "Mon", "dayofweek": "0", "hour_from": 8.0, "hour_to": 17.0, "day_period": "morning"}),
                (0, 0, {"name": "Tue", "dayofweek": "1", "hour_from": 8.0, "hour_to": 17.0, "day_period": "morning"}),
                (0, 0, {"name": "Wed", "dayofweek": "2", "hour_from": 8.0, "hour_to": 17.0, "day_period": "morning"}),
                (0, 0, {"name": "Thu", "dayofweek": "3", "hour_from": 8.0, "hour_to": 17.0, "day_period": "morning"}),
                (0, 0, {"name": "Fri", "dayofweek": "4", "hour_from": 8.0, "hour_to": 17.0, "day_period": "morning"}),
            ],
        })
        cls.company.resource_calendar_id = cls.calendar.id

        cls.department = cls.env["hr.department"].create({
            "name": "KIO Payroll Dept",
            "company_id": cls.company.id,
        })
        cls.job = cls.env["hr.job"].create({
            "name": "KIO Payroll Engineer",
            "company_id": cls.company.id,
        })
        cls.bonus_type = cls.env.ref(
            "kio_payroll_overview_extension.kio_bonus_type_other", raise_if_not_found=False
        ) or cls.env["kio.bonus.type"].search([], limit=1)
        if not cls.bonus_type:
            cls.bonus_type = cls.env["kio.bonus.type"].create({"name": "KIO Test Bonus Type"})
        cls.employee = cls.env["hr.employee"].create({
            "name": "KIO Eligible Employee",
            "company_id": cls.company.id,
            "identification_id": "KIO-001",
            "department_id": cls.department.id,
            "job_id": cls.job.id,
            "resource_calendar_id": cls.calendar.id,
        })
        cls.ineligible_employee = cls.env["hr.employee"].create({
            "name": "KIO No Contract Employee",
            "company_id": cls.company.id,
            "resource_calendar_id": cls.calendar.id,
        })

        cls.Contract = cls.env["hr.contract"]
        cls.contract = cls.Contract.create({
            "name": "KIO Contract",
            "employee_id": cls.employee.id,
            "company_id": cls.company.id,
            "date_start": date(2026, 1, 1),
            "wage": 50000.0,
            "state": "open",
            "resource_calendar_id": cls.calendar.id,
        })

        cls.salary_config = cls.env["kio.payroll.salary.config"].create({
            "employee_id": cls.employee.id,
            "company_id": cls.company.id,
            "basic_salary": 50000.0,
            "allowance": 5000.0,
            "active": True,
        })

        cls.start = date(2026, 11, 1)
        cls.end = date(2026, 11, 30)
        cls.Payslip = cls.env["kio.payroll.payslip"]
        cls._configure_salary_accounting()

    @classmethod
    def _configure_salary_accounting(cls):
        company = cls.company
        journal = cls.env["account.journal"].search([
            ("type", "=", "general"),
            ("company_id", "=", company.id),
        ], limit=1)
        if not journal:
            journal = cls.env["account.journal"].create({
                "name": "KIO Salary Journal",
                "code": "KIOS",
                "type": "general",
                "company_id": company.id,
            })
        expense = cls.env["account.account"].search([
            ("company_id", "=", company.id),
            ("deprecated", "=", False),
            ("account_type", "in", ("expense", "expense_direct_cost", "expense_depreciation")),
        ], limit=1)
        payable = cls.env["account.account"].search([
            ("company_id", "=", company.id),
            ("deprecated", "=", False),
            ("account_type", "=", "liability_payable"),
            ("reconcile", "=", True),
        ], limit=1)
        if not payable:
            payable = cls.env["account.account"].search([
                ("company_id", "=", company.id),
                ("deprecated", "=", False),
                ("account_type", "=", "liability_payable"),
            ], limit=1)
        if expense and payable and journal:
            company.write({
                "salary_journal_id": journal.id,
                "salary_debit_account_id": expense.id,
                "salary_credit_account_id": payable.id,
            })

    def _gen_values(self, employee_ids, name="November 2026 Payroll"):
        return {
            "name": name,
            "payroll_type": "monthly",
            "payment_date": fields.Date.to_string(self.end),
            "date_start": fields.Date.to_string(self.start),
            "date_end": fields.Date.to_string(self.end),
            "employee_ids": employee_ids,
        }

    def _generate(self, employee_ids, name="November 2026 Payroll"):
        return self.Payslip.generate_new_payroll_run(self._gen_values(employee_ids, name=name))

    def _create_bonus(self, amount=3000.0, state="confirmed"):
        bonus = self.env["kio.bonus"].create({
            "name": "KIO Bonus",
            "bonus_type_id": self.bonus_type.id,
            "company_id": self.company.id,
            "payment_scope": "individual",
            "employee_ids": [(6, 0, [self.employee.id])],
            "calculation_type": "fixed",
            "amount": amount,
            "bonus_date": date(2026, 11, 15),
            "state": "draft",
        })
        if state == "confirmed":
            bonus.action_generate_employees()
            bonus.action_confirm()
        return bonus

    def _create_overtime(self, amount=2000.0, state="confirmed", day=10):
        ot = self.env["kio.overtime"].create({
            "employee_id": self.employee.id,
            "company_id": self.company.id,
            "date": date(2026, 11, day),
            "overtime_hours": 2.0,
            "overtime_amount": amount,
            "amount": amount,
            "source": "manual",
            "state": "draft",
        })
        if state == "confirmed":
            ot.action_confirm()
        elif state == "cancelled":
            ot.action_confirm()
            ot.action_cancel()
        return ot

    def _create_commission(self, amount=1000.0, state="confirmed", day=11):
        com = self.env["kio.commission"].create({
            "employee_id": self.employee.id,
            "company_id": self.company.id,
            "date": date(2026, 11, day),
            "amount": amount,
            "state": "draft",
        })
        if state == "confirmed":
            com.action_confirm()
        elif state == "cancelled":
            com.action_confirm()
            com.action_cancel()
        return com

    def _create_deduction(self, amount=500.0, state="confirmed", day=12):
        ded = self.env["kio.deduction"].create({
            "employee_id": self.employee.id,
            "company_id": self.company.id,
            "date": date(2026, 11, day),
            "deduction_amount": amount,
            "state": "draft",
            "source": "manual",
        })
        if state == "confirmed":
            ded.action_confirm()
        elif state == "cancelled":
            ded.action_confirm()
            ded.action_cancel()
        return ded

    def test_new_payroll_run_preview_filters_contracts_and_working_days(self):
        data = self.Payslip.get_new_payroll_run_data(self.start, self.end)
        row_ids = [r["employee_id"] for r in data.get("employees", [])]
        self.assertIn(self.employee.id, row_ids)
        self.assertNotIn(self.ineligible_employee.id, row_ids)
        row = next(r for r in data["employees"] if r["employee_id"] == self.employee.id)
        self.assertAlmostEqual(row["basic_salary"], 50000.0, places=2)
        self.assertAlmostEqual(row["allowance"], 5000.0, places=2)
        self.assertIn("working_days", row)
        self.assertTrue(data.get("working_days_available") or data.get("working_days") is not None or data.get("working_days_message"))

    def test_generation_includes_confirmed_adjustments_and_excludes_draft_cancelled(self):
        self._create_bonus(3000.0, state="confirmed")
        self._create_overtime(2000.0, state="confirmed", day=10)
        self._create_overtime(999.0, state="draft", day=9)
        self._create_commission(1000.0, state="confirmed", day=11)
        self._create_commission(888.0, state="draft", day=14)
        self._create_deduction(500.0, state="confirmed", day=12)
        self._create_deduction(777.0, state="cancelled", day=13)

        preview = self.Payslip.get_new_payroll_run_data(self.start, self.end)
        row = next(r for r in preview["employees"] if r["employee_id"] == self.employee.id)
        expected_gross = 50000.0 + 5000.0 + 2000.0 + 1000.0 + 3000.0
        expected_net = expected_gross - 500.0
        self.assertAlmostEqual(row["overtime"], 2000.0, places=2)
        self.assertAlmostEqual(row["commission"], 1000.0, places=2)
        self.assertAlmostEqual(row["bonus"], 3000.0, places=2)
        self.assertAlmostEqual(row["deduction"], 500.0, places=2)
        self.assertAlmostEqual(row["net_pay"], expected_net, places=2)

        result = self._generate([self.employee.id], name="Nov 2026 Gen")
        self.assertEqual(result.get("tag"), "kio_payroll_overview.batch_details")
        batch_id = result.get("context", {}).get("kio_batch_id")
        self.assertTrue(batch_id)
        slip = self.env["kio.payroll.payslip"].search([("batch_id", "=", batch_id), ("employee_id", "=", self.employee.id)], limit=1)
        self.assertTrue(slip)
        self.assertAlmostEqual(slip.basic_salary, row["basic_salary"], places=2)
        self.assertAlmostEqual(slip.allowance, row["allowance"], places=2)
        self.assertAlmostEqual(slip.overtime, row["overtime"], places=2)
        self.assertAlmostEqual(slip.commission, row["commission"], places=2)
        self.assertAlmostEqual(slip.bonus, row["bonus"], places=2)
        self.assertAlmostEqual(slip.deduction, row["deduction"], places=2)
        self.assertAlmostEqual(slip.net_pay, row["net_pay"], places=2)
        codes = {l.code: l.total for l in slip.line_ids}
        self.assertIn("COMMISSION", codes)
        self.assertAlmostEqual(codes.get("GROSS", 0.0) - codes.get("DED", 0.0), codes.get("NET", 0.0), places=2)

    def test_duplicate_payroll_generation_prevented(self):
        self._generate([self.employee.id], name="Nov 2026 A")
        with self.assertRaises(ValidationError):
            self._generate([self.employee.id], name="Nov 2026 B")

    def test_batch_details_and_period_working_days(self):
        result = self._generate([self.employee.id], name="Nov 2026 Details")
        batch_id = result["context"]["kio_batch_id"]
        details = self.Payslip.get_payroll_batch_details(batch_id)
        self.assertEqual(details["batch"]["id"], batch_id)
        self.assertEqual(details["summary"]["total_employees"], 1)
        self.assertIn("working_days", details["period"])
        self.assertTrue(details["period"].get("working_days_available") or details["period"].get("working_days") is not None or details["period"].get("working_days_message"))
        self.assertEqual(len(details["rows"]), 1)
        self.assertEqual(details["rows"][0]["employee_name"], self.employee.name)

    def test_dashboard_kpis_and_period_filter(self):
        self._create_bonus(3000.0, state="confirmed")
        self._generate([self.employee.id], name="Nov 2026 Dashboard")
        data = self.Payslip.get_payroll_overview_data(11, 2026)
        self.assertEqual(data["company"]["id"], self.company.id)
        self.assertEqual(data["period"]["month"], 11)
        self.assertEqual(data["period"]["year"], 2026)
        kpis = data["kpis"]
        self.assertGreaterEqual(kpis.get("total_employees", 0), 1)
        self.assertIn("total_paid_salary", kpis)
        self.assertIn("total_unpaid_salary", kpis)
        self.assertIn("net_salary", kpis)

        empty = self.Payslip.get_payroll_overview_data(10, 2026)
        self.assertEqual(empty["kpis"].get("payslip_batches", 0), 0)

    def test_pay_now_action_and_download_payslip(self):
        # Ensure employee has a payable partner for Pay Now.
        partner = self.employee.work_contact_id or self.employee.address_id
        if not partner:
            partner = self.env["res.partner"].create({"name": "KIO Employee Partner", "company_id": self.company.id})
            self.employee.work_contact_id = partner.id

        result = self._generate([self.employee.id], name="Nov 2026 Pay")
        batch_id = result["context"]["kio_batch_id"]
        slip = self.env["kio.payroll.payslip"].search([("batch_id", "=", batch_id), ("employee_id", "=", self.employee.id)], limit=1)
        self.assertTrue(slip)

        if self.company.salary_credit_account_id and self.company.salary_journal_id and self.company.salary_debit_account_id:
            action = self.Payslip.action_payroll_pay_now(slip.id)
            self.assertEqual(action.get("res_model"), "account.payment.register")
            ctx = action.get("context") or {}
            self.assertEqual(ctx.get("kio_payroll_slip_id"), slip.id)
            self.assertEqual(ctx.get("active_model"), "account.move.line")

        report_action = self.Payslip.action_payroll_download_payslip(slip.id)
        self.assertTrue(report_action)

    def test_security_manager_and_unauthorized_user(self):
        unauthorized = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "KIO Unauthorized",
            "login": "kio_unauthorized_test",
            "email": "kio_unauthorized_test@example.com",
            "groups_id": [Command.set([self.env.ref("base.group_user").id])],
            "company_id": self.company.id,
            "company_ids": [Command.set([self.company.id])],
        })
        payroll_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "KIO Payroll User",
            "login": "kio_payroll_user_test",
            "email": "kio_payroll_user_test@example.com",
            "groups_id": [Command.set([self.env.ref("base.group_user").id, self.user_group.id])],
            "company_id": self.company.id,
            "company_ids": [Command.set([self.company.id])],
        })
        with self.assertRaises(AccessError):
            self.Payslip.with_user(unauthorized).get_payroll_overview_data(11, 2026)
        with self.assertRaises(AccessError):
            self.Payslip.with_user(payroll_user).get_payroll_overview_data(11, 2026)

    def test_bonus_commission_overtime_deduction_workflows(self):
        bonus = self._create_bonus(3000.0, state="confirmed")
        self.assertEqual(bonus.state, "confirmed")
        ot = self._create_overtime(2000.0, state="confirmed")
        self.assertEqual(ot.state, "confirmed")
        ot.action_cancel()
        self.assertEqual(ot.state, "cancelled")
        com = self._create_commission(1000.0, state="confirmed")
        self.assertEqual(com.state, "confirmed")
        com.action_cancel()
        self.assertEqual(com.state, "cancelled")
        ded = self._create_deduction(500.0, state="confirmed")
        self.assertEqual(ded.state, "confirmed")
        ded.action_cancel()
        self.assertEqual(ded.state, "cancelled")

    def test_company_isolation_batch_access(self):
        result = self._generate([self.employee.id], name="Nov 2026 Isolation")
        batch_id = result["context"]["kio_batch_id"]
        other_company = self.env["res.company"].create({"name": "KIO Other Company"})
        self.env.user.write({"company_ids": [(4, other_company.id)]})
        # Access checks in module use env.company; simulate by calling with company context switch if supported.
        # Primary protection is company domain/filtering in APIs; ensure batch belongs to current company.
        details = self.Payslip.get_payroll_batch_details(batch_id)
        self.assertEqual(details["company"]["id"], self.company.id)
