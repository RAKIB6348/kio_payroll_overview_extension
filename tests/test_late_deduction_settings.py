from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLateDeductionSettings(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env["res.company"].create({
            "name": "Late Policy Defaults Test Company",
        })

    def test_new_company_late_policy_defaults_are_zero_and_disabled(self):
        company = self.company
        self.assertFalse(company.kio_late_deduction_enabled)
        self.assertEqual(company.kio_late_buffer_minutes, 0)
        self.assertEqual(company.kio_late_days_threshold, 0)
        self.assertEqual(company.kio_late_salary_deduction_days, 0.0)

        policy = self.env["kio.deduction"]._get_late_deduction_policy(company)
        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["buffer_minutes"], 0)
        self.assertEqual(policy["late_days_threshold"], 0)
        self.assertEqual(policy["salary_deduction_days"], 0.0)

    def test_settings_persist_and_load_late_policy_values(self):
        settings = self.env["res.config.settings"].create({
            "company_id": self.company.id,
            "kio_late_deduction_enabled": True,
            "kio_late_buffer_minutes": 0,
            "kio_late_days_threshold": 3,
            "kio_late_salary_deduction_days": 1.0,
        })

        self.company.invalidate_recordset()
        self.assertTrue(self.company.kio_late_deduction_enabled)
        self.assertEqual(self.company.kio_late_buffer_minutes, 0)
        self.assertEqual(self.company.kio_late_days_threshold, 3)
        self.assertAlmostEqual(self.company.kio_late_salary_deduction_days, 1.0)

        self.assertTrue(settings.kio_late_deduction_enabled)
        self.assertEqual(settings.kio_late_buffer_minutes, 0)
        self.assertEqual(settings.kio_late_days_threshold, 3)
        self.assertAlmostEqual(settings.kio_late_salary_deduction_days, 1.0)

        reloaded_values = self._reload_policy_values(self.company)
        self.assertTrue(reloaded_values["kio_late_deduction_enabled"])
        self.assertEqual(reloaded_values["kio_late_buffer_minutes"], 0)
        self.assertEqual(reloaded_values["kio_late_days_threshold"], 3)
        self.assertAlmostEqual(reloaded_values["kio_late_salary_deduction_days"], 1.0)

        settings.write({
            "kio_late_deduction_enabled": True,
            "kio_late_buffer_minutes": 5,
            "kio_late_days_threshold": 4,
            "kio_late_salary_deduction_days": 0.5,
        })
        settings.invalidate_recordset()
        self.assertEqual(settings.kio_late_buffer_minutes, 5)
        self.assertEqual(settings.kio_late_days_threshold, 4)
        self.assertAlmostEqual(settings.kio_late_salary_deduction_days, 0.5)

        reloaded_values = self._reload_policy_values(self.company)
        self.assertTrue(reloaded_values["kio_late_deduction_enabled"])
        self.assertEqual(reloaded_values["kio_late_buffer_minutes"], 5)
        self.assertEqual(reloaded_values["kio_late_days_threshold"], 4)
        self.assertAlmostEqual(reloaded_values["kio_late_salary_deduction_days"], 0.5)

    def test_late_policy_settings_are_isolated_by_company(self):
        second_company = self.env["res.company"].create({
            "name": "Second Late Policy Test Company",
        })
        first_settings = self.env["res.config.settings"].create({
            "company_id": self.company.id,
            "kio_late_deduction_enabled": True,
            "kio_late_buffer_minutes": 0,
            "kio_late_days_threshold": 3,
            "kio_late_salary_deduction_days": 1.0,
        })
        second_values = self._reload_policy_values(second_company)
        self.assertTrue(first_settings.kio_late_deduction_enabled)
        self.assertFalse(second_values["kio_late_deduction_enabled"])
        self.assertEqual(second_values["kio_late_buffer_minutes"], 0)
        self.assertEqual(second_values["kio_late_days_threshold"], 0)
        self.assertEqual(second_values["kio_late_salary_deduction_days"], 0.0)

    def test_payroll_manager_execute_persists_policy(self):
        manager = self.env["res.users"].create({
            "name": "Late Policy Settings Manager",
            "login": "late-policy-settings-manager",
            "company_id": self.company.id,
            "company_ids": [(6, 0, [self.company.id])],
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("kio_payroll_overview_extension.group_kio_payroll_manager").id,
            ])],
        })
        settings = self.env["res.config.settings"].with_user(manager).create({
            "company_id": self.company.id,
            "kio_late_deduction_enabled": True,
            "kio_late_buffer_minutes": 0,
            "kio_late_days_threshold": 3,
            "kio_late_salary_deduction_days": 1.0,
        })

        action = settings.execute()
        self.assertEqual(action["tag"], "reload")
        values = self._reload_policy_values(self.company)
        self.assertTrue(values["kio_late_deduction_enabled"])
        self.assertEqual(values["kio_late_buffer_minutes"], 0)
        self.assertEqual(values["kio_late_days_threshold"], 3)
        self.assertAlmostEqual(values["kio_late_salary_deduction_days"], 1.0)

    def _reload_policy_values(self, company):
        fields_to_load = [
            "company_id",
            "kio_late_deduction_enabled",
            "kio_late_buffer_minutes",
            "kio_late_days_threshold",
            "kio_late_salary_deduction_days",
        ]
        return self.env["res.config.settings"].with_context(
            default_company_id=company.id,
        ).default_get(fields_to_load)

    def test_disabled_policy_allows_zero_threshold_and_deduction_days(self):
        self.company.write({
            "kio_late_deduction_enabled": False,
            "kio_late_buffer_minutes": 0,
            "kio_late_days_threshold": 0,
            "kio_late_salary_deduction_days": 0.0,
        })
        self.assertFalse(self.company.kio_late_deduction_enabled)

        employee = self.env["hr.employee"].create({
            "name": "Disabled Late Policy Employee",
            "company_id": self.company.id,
        })
        values = self.env["kio.late.deduction.monthly.summary"]._calculate_month_values(
            employee, date(2026, 1, 1), date(2026, 1, 31), self.company
        )
        self.assertEqual(values["total_salary_deduction_days"], 0.0)

    def test_enabled_policy_requires_positive_threshold_and_deduction_days(self):
        with self.assertRaises(ValidationError):
            self.company.write({
                "kio_late_deduction_enabled": True,
                "kio_late_buffer_minutes": 0,
                "kio_late_days_threshold": 0,
                "kio_late_salary_deduction_days": 1.0,
            })

        with self.assertRaises(ValidationError):
            self.company.write({
                "kio_late_deduction_enabled": True,
                "kio_late_buffer_minutes": 0,
                "kio_late_days_threshold": 3,
                "kio_late_salary_deduction_days": 0.0,
            })

    def test_zero_buffer_is_valid_when_policy_is_enabled(self):
        self.company.write({
            "kio_late_deduction_enabled": True,
            "kio_late_buffer_minutes": 0,
            "kio_late_days_threshold": 3,
            "kio_late_salary_deduction_days": 1.0,
        })
        self.assertEqual(self.company.kio_late_buffer_minutes, 0)
