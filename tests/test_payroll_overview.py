from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPayrollOverview(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.department = cls.env["hr.department"].create({
            "name": "Engineering",
            "company_id": cls.company.id,
        })
        cls.job = cls.env["hr.job"].create({
            "name": "Software Engineer",
            "company_id": cls.company.id,
        })
        cls.employee = cls.env["hr.employee"].create({
            "name": "Payroll Overview Employee",
            "company_id": cls.company.id,
            "identification_id": "EMP-001",
            "department_id": cls.department.id,
            "job_id": cls.job.id,
        })
        cls.contract = cls.env["hr.contract"].create({
            "name": "Payroll Overview Contract",
            "employee_id": cls.employee.id,
            "company_id": cls.company.id,
            "date_start": "2026-01-01",
            "wage": 1000.0,
            "contract_type_id": cls.env.ref("hr.contract_type_permanent").id,
            "struct_id": cls.env.ref("hr_payroll_community.structure_base").id,
        })
        cls.deduction_rule = cls.env["hr.salary.rule"].create({
            "name": "Payroll Overview Deduction",
            "code": "DED",
            "category_id": cls.env.ref("hr_payroll_community.DED").id,
            "amount_select": "fix",
        })
        cls.allowance_rule = cls.env["hr.salary.rule"].create({
            "name": "Payroll Overview Allowance",
            "code": "TEST_ALW",
            "category_id": cls.env.ref("hr_payroll_community.ALW").id,
            "amount_select": "fix",
        })
        cls.overtime_rule = cls.env["hr.salary.rule"].create({
            "name": "Weekend Overtime",
            "code": "OT_WEEKEND",
            # Overtime can legitimately live under ALW; it must still be
            # excluded from the allowance dashboard column.
            "category_id": cls.env.ref("hr_payroll_community.ALW").id,
            "amount_select": "fix",
        })
        cls.bonus_rule = cls.env["hr.salary.rule"].create({
            "name": "Festival Bonus",
            "code": "BONUS_FESTIVAL",
            "category_id": cls.env.ref("hr_payroll_community.ALW").id,
            "amount_select": "fix",
        })
        cls.batch = cls.env["hr.payslip.run"].create({
            "name": "November 2026",
            "date_start": "2026-11-01",
            "date_end": "2026-11-30",
        })
        cls.empty_batch = cls.env["hr.payslip.run"].create({
            "name": "Empty Batch",
            "date_start": "2026-12-01",
            "date_end": "2026-12-31",
        })

        cls.normal_slip = cls._create_payslip("Normal", credit_note=False)
        cls.credit_slip = cls._create_payslip("Refund", credit_note=True)
        cls.draft_slip = cls.env["hr.payslip"].create({
            "name": "Draft",
            "employee_id": cls.employee.id,
            "contract_id": cls.contract.id,
            "company_id": cls.company.id,
            "date_from": "2026-11-01",
            "date_to": "2026-11-30",
            "state": "draft",
        })
        cls.other_company = cls.env["res.company"].create({
            "name": "Payroll Overview Other Company",
        })
        cls.env.user.write({
            "company_ids": [Command.link(cls.other_company.id)],
        })
        other_env = cls.env(context={
            **cls.env.context,
            "allowed_company_ids": [cls.company.id, cls.other_company.id],
        })
        other_employee = other_env["hr.employee"].create({
            "name": "Other Company Employee",
            "company_id": cls.other_company.id,
        })
        cls.other_company_batch = other_env["hr.payslip.run"].create({
            "name": "Other Company Batch",
            "date_start": "2026-11-01",
            "date_end": "2026-11-30",
        })
        other_env["hr.payslip"].create({
            "name": "Other Company Payslip",
            "employee_id": other_employee.id,
            "company_id": cls.other_company.id,
            "date_from": "2026-11-01",
            "date_to": "2026-11-30",
            "state": "done",
            "payslip_run_id": cls.other_company_batch.id,
        })

    @classmethod
    def _create_payslip(cls, name, credit_note):
        slip = cls.env["hr.payslip"].create({
            "name": name,
            "employee_id": cls.employee.id,
            "contract_id": cls.contract.id,
            "company_id": cls.company.id,
            "date_from": "2026-11-01",
            "date_to": "2026-11-30",
            "state": "done",
            "credit_note": credit_note,
            "payslip_run_id": cls.batch.id,
        })
        amount_factor = 0.2 if credit_note else 1.0
        lines = [
            (cls.env.ref("hr_payroll_community.hr_rule_basic"), 600.0 * amount_factor),
            (cls.allowance_rule, 250.0 * amount_factor),
            (cls.env.ref("hr_payroll_community.hr_rule_hra"), 150.0 * amount_factor),
            (cls.overtime_rule, 75.0 * amount_factor),
            (cls.bonus_rule, 50.0 * amount_factor),
            (cls.env.ref("hr_payroll_community.hr_rule_taxable"), 1000.0 * amount_factor),
            (cls.deduction_rule, -100.0 * amount_factor),
            (cls.env.ref("hr_payroll_community.hr_rule_net"), 900.0 * amount_factor),
        ]
        for rule, amount in lines:
            cls.env["hr.payslip.line"].create({
                "name": rule.name,
                "code": rule.code,
                "category_id": rule.category_id.id,
                "salary_rule_id": rule.id,
                "slip_id": slip.id,
                "employee_id": cls.employee.id,
                "contract_id": cls.contract.id,
                "amount": amount,
                "quantity": 1.0,
                "rate": 100.0,
            })
        return slip

    def test_dashboard_aggregates_and_credit_notes(self):
        data = self.env["hr.payslip"].get_payroll_overview_data(11, 2026)

        self.assertEqual(data["period"]["policy"], "full_period")
        self.assertEqual(data["company"]["id"], self.company.id)
        self.assertEqual(data["kpis"]["total_employees"], 1)
        self.assertEqual(data["kpis"]["payslip_batches"], 1)
        self.assertEqual(data["kpis"]["draft_payslips"], 1)
        self.assertEqual(data["kpis"]["done_payslips"], 2)
        self.assertEqual(data["kpis"]["gross_salary"], 800.0)
        self.assertEqual(data["kpis"]["total_deductions"], 80.0)
        self.assertEqual(data["kpis"]["net_salary"], 720.0)
        self.assertTrue(data["salary_reconciliation"]["reconciles"])
        self.assertEqual(data["recent_batches"][0]["payslip_count"], 2)
        details = data["employee_payroll_details"]
        self.assertEqual(len(details["rows"]), 1)
        self.assertEqual(details["rows"][0]["net_pay"], 720.0)

    def test_empty_period(self):
        data = self.env["hr.payslip"].get_payroll_overview_data(10, 2026)
        self.assertEqual(data["kpis"]["total_employees"], 0)
        self.assertEqual(data["kpis"]["gross_salary"], 0.0)
        self.assertFalse(data["recent_batches"])

    def test_batch_selection_and_employee_salary_details(self):
        batches = self.env["hr.payslip"].get_payroll_overview_batches()
        batch_ids = {batch["id"] for batch in batches}
        self.assertIn(self.batch.id, batch_ids)
        self.assertIn(self.empty_batch.id, batch_ids)
        self.assertNotIn(self.other_company_batch.id, batch_ids)

        details = self.env[
            "hr.payslip"
        ].get_payroll_batch_employee_salary_details(self.batch.id)
        self.assertEqual(details["batch"]["name"], self.batch.name)
        self.assertEqual(len(details["rows"]), 1)
        row = details["rows"][0]
        self.assertEqual(row["employee_name"], self.employee.name)
        self.assertEqual(row["employee_identification"], "EMP-001")
        self.assertEqual(row["department"], self.department.name)
        self.assertEqual(row["designation"], self.job.name)
        self.assertEqual(
            row["employee_avatar_url"],
            f"/web/image/hr.employee/{self.employee.id}/avatar_128",
        )
        self.assertEqual(row["basic_salary"], 480.0)
        self.assertEqual(row["allowance"], 320.0)
        self.assertEqual(row["overtime"], 60.0)
        self.assertEqual(row["bonus"], 40.0)
        self.assertEqual(row["deduction"], 80.0)
        self.assertEqual(row["net_pay"], 720.0)
        self.assertNotIn("commission", row)
        self.assertEqual(details["totals"], {
            "basic_salary": 480.0,
            "allowance": 320.0,
            "overtime": 60.0,
            "bonus": 40.0,
            "deduction": 80.0,
            "net_pay": 720.0,
        })

        empty_details = self.env[
            "hr.payslip"
        ].get_payroll_batch_employee_salary_details(self.empty_batch.id)
        self.assertFalse(empty_details["rows"])
        self.assertEqual(empty_details["totals"]["basic_salary"], 0.0)

        # Verify batch details data for the redesign
        batch_details = self.env[
            "hr.payslip"
        ].get_payroll_batch_details_data(self.batch.id)
        self.assertEqual(batch_details["batch"]["id"], self.batch.id)
        self.assertEqual(batch_details["batch"]["name"], self.batch.name)
        self.assertEqual(batch_details["summary"]["total_employees"], 1)
        self.assertEqual(batch_details["summary"]["total_net_salary"], 720.0)
        self.assertEqual(batch_details["summary"]["total_paid_salary"], 0.0)
        self.assertEqual(batch_details["summary"]["total_unpaid_salary"], 720.0)
        self.assertEqual(len(batch_details["employees"]), 1)
        emp_row = batch_details["employees"][0]
        self.assertEqual(emp_row["name"], self.employee.name)
        self.assertEqual(emp_row["basic_salary"], 480.0)
        self.assertEqual(emp_row["net_pay"], 720.0)
        self.assertFalse(emp_row["paid"])
        self.assertEqual(emp_row["payment_state"], "unpaid")

    def test_all_company_batches_are_paged_newest_first(self):
        older_batch = self.env["hr.payslip.run"].create({
            "name": "Older Historical Batch",
            "date_start": "2025-01-01",
            "date_end": "2025-01-31",
        })
        page = self.env["hr.payslip"].get_payroll_overview_batch_page(0, 1)
        self.assertGreaterEqual(page["total"], 3)
        self.assertEqual(len(page["rows"]), 1)
        self.assertEqual(page["rows"][0]["id"], self.empty_batch.id)
        second_page = self.env["hr.payslip"].get_payroll_overview_batch_page(1, 2)
        self.assertEqual(len(second_page["rows"]), 2)
        all_page_rows = page["rows"] + second_page["rows"]
        self.assertNotIn(self.other_company_batch.id, [row["id"] for row in all_page_rows])
        self.assertIn(older_batch.id, [row["id"] for row in all_page_rows])
        self.assertEqual(page["rows"][0]["state_label"], "Draft")

    def test_salary_details_do_not_change_dashboard_kpis(self):
        before = self.env["hr.payslip"].get_payroll_overview_data(11, 2026)["kpis"]
        self.env["hr.payslip"].get_payroll_batch_employee_salary_details(
            self.batch.id
        )
        after = self.env["hr.payslip"].get_payroll_overview_data(11, 2026)["kpis"]
        self.assertEqual(after, before)

    def test_month_details_and_batch_filter(self):
        second_batch = self.env["hr.payslip.run"].create({
            "name": "November 2026 Supplemental",
            "date_start": "2026-11-01",
            "date_end": "2026-11-30",
        })
        second_employee = self.env["hr.employee"].create({
            "name": "Second Payroll Employee",
            "company_id": self.company.id,
        })
        self.env["hr.payslip"].create({
            "name": "Supplemental",
            "employee_id": second_employee.id,
            "company_id": self.company.id,
            "date_from": "2026-11-01",
            "date_to": "2026-11-30",
            "state": "draft",
            "payslip_run_id": second_batch.id,
        })

        all_details = self.env[
            "hr.payslip"
        ].get_payroll_employee_salary_details(11, 2026)
        self.assertEqual(len(all_details["batches"]), 2)
        self.assertEqual(len(all_details["rows"]), 2)

        filtered = self.env[
            "hr.payslip"
        ].get_payroll_employee_salary_details(11, 2026, second_batch.id)
        self.assertEqual(filtered["batch"]["id"], second_batch.id)
        self.assertEqual(len(filtered["rows"]), 1)
        self.assertEqual(filtered["rows"][0]["employee_name"], second_employee.name)

    def test_standard_generation_workflow_and_metadata(self):
        generation_batch = self.env["hr.payslip.run"].create({
            "name": "January 2027",
            "date_start": "2027-01-01",
            "date_end": "2027-01-31",
        })
        employee = self.env["hr.employee"].create({
            "name": "Generation Employee",
            "company_id": self.company.id,
        })
        self.env["hr.contract"].create({
            "name": "Generation Contract",
            "employee_id": employee.id,
            "company_id": self.company.id,
            "date_start": "2026-01-01",
            "wage": 1200.0,
            "state": "open",
            "contract_type_id": self.env.ref("hr.contract_type_permanent").id,
            "struct_id": self.env.ref("hr_payroll_community.structure_base").id,
        })

        metadata = self.env["hr.payslip"].get_payroll_generation_data(
            generation_batch.id
        )
        self.assertEqual(metadata["selected_batch"]["date_start"].isoformat(), "2027-01-01")
        self.assertEqual(metadata["selected_batch"]["existing_payslip_count"], 0)
        self.assertEqual(metadata["selected_batch"]["employee_count"], 1)
        self.assertEqual(metadata["selected_batch"]["employee_count_basis"], "eligible")
        self.assertTrue(metadata["selected_batch"]["can_generate"])

        wizard_action = self.env["hr.payslip"].prepare_payroll_generation(
            generation_batch.id
        )
        self.assertEqual(wizard_action["res_model"], "hr.payslip.employees")
        self.assertEqual(wizard_action["context"]["active_id"], generation_batch.id)
        self.assertTrue(wizard_action["context"]["kio_payroll_generation"])

        before_count = self.env["hr.payslip"].search_count([
            ("payslip_run_id", "=", generation_batch.id),
        ])
        wizard = self.env["hr.payslip.employees"].with_context(
            **wizard_action["context"]
        ).create({"employee_ids": [Command.set([employee.id])]})
        result = wizard.action_compute_sheet()
        generated_slips = self.env["hr.payslip"].search([
            ("payslip_run_id", "=", generation_batch.id),
        ])
        self.assertEqual(len(generated_slips), before_count + 1)
        self.assertEqual(generated_slips.state, "draft")
        self.assertEqual(result["res_id"], generation_batch.id)
        self.assertEqual(result["view_mode"], "form")

    def test_duplicate_generation_is_rejected_without_changes(self):
        before_ids = self.env["hr.payslip"].search([
            ("payslip_run_id", "=", self.batch.id),
        ]).ids
        wizard = self.env["hr.payslip.employees"].with_context(
            active_id=self.batch.id,
            active_ids=self.batch.ids,
            active_model="hr.payslip.run",
            kio_payroll_generation=True,
        ).create({"employee_ids": [Command.set([self.employee.id])]})
        with self.assertRaises(UserError):
            wizard.action_compute_sheet()
        self.assertEqual(self.env["hr.payslip"].search([
            ("payslip_run_id", "=", self.batch.id),
        ]).ids, before_ids)

    def test_closed_batch_generation_is_rejected(self):
        self.batch.close_payslip_run()
        with self.assertRaises(ValidationError):
            self.env["hr.payslip"].prepare_payroll_generation(self.batch.id)

    def test_create_batch_uses_standard_action(self):
        action = self.env["hr.payslip"].get_create_payroll_batch_action()
        self.assertEqual(action["res_model"], "hr.payslip.run")
        self.assertEqual(action["view_mode"], "form")
        self.assertFalse(action["res_id"])

    def test_other_company_batch_is_rejected(self):
        with self.assertRaises(AccessError):
            self.env["hr.payslip"].get_payroll_batch_employee_salary_details(
                self.other_company_batch.id
            )
        with self.assertRaises(AccessError):
            self.env["hr.payslip"].get_payroll_batch_details_data(
                self.other_company_batch.id
            )

    def test_current_company_and_menu_security(self):
        data = self.env["hr.payslip"].get_payroll_overview_data(11, 2026)
        self.assertEqual(data["company"]["id"], self.company.id)
        self.assertEqual(data["kpis"]["done_payslips"], 2)

        menu = self.env.ref(
            "kio_payroll_overview_extension.menu_payroll_overview"
        )
        manager_group = self.env.ref(
            "hr_payroll_community.group_hr_payroll_community_manager"
        )
        self.assertEqual(menu.parent_id, self.env.ref(
            "hr_payroll_community.menu_hr_payroll_community_root"
        ))
        self.assertEqual(menu.sequence, 1)
        self.assertIn(manager_group, menu.groups_id)
        self.assertTrue(self.env.ref("hr_payroll_community.menu_department_tree").exists())

    def test_invalid_period_is_rejected(self):
        with self.assertRaises(ValidationError):
            self.env["hr.payslip"].get_payroll_overview_data(13, 2026)
        with self.assertRaises(ValidationError):
            self.env["hr.payslip"].get_payroll_batch_employee_salary_details(
                "not-a-batch"
            )

    def test_non_manager_rpc_is_rejected(self):
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Payroll Overview Unauthorized User",
            "login": "payroll_overview_unauthorized",
            "email": "payroll-overview-unauthorized@example.com",
            "groups_id": [Command.set([self.env.ref("base.group_user").id])],
        })
        user.write({
            "groups_id": [Command.set([self.env.ref("base.group_user").id])],
        })
        with self.assertRaises(AccessError):
            self.env["hr.payslip"].with_user(user).get_payroll_overview_data(11, 2026)
        with self.assertRaises(AccessError):
            self.env["hr.payslip"].with_user(user).get_payroll_overview_batches()
        with self.assertRaises(AccessError):
            self.env["hr.payslip"].with_user(
                user
            ).get_payroll_batch_employee_salary_details(self.batch.id)
        with self.assertRaises(AccessError):
            self.env["hr.payslip"].with_user(
                user
            ).get_payroll_batch_details_data(self.batch.id)
        with self.assertRaises(AccessError):
            self.env["hr.payslip"].with_user(
                user
            ).get_payroll_employee_salary_details(11, 2026)
        with self.assertRaises(AccessError):
            self.env["hr.payslip"].with_user(
                user
            ).get_payroll_generation_data(self.batch.id)
        with self.assertRaises(AccessError):
            self.env["hr.payslip"].with_user(
                user
            ).prepare_payroll_generation(self.batch.id)
        with self.assertRaises(AccessError):
            self.env["hr.payslip"].with_user(
                user
            ).get_payroll_overview_batch_page(0, 10)

