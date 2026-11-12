from datetime import date
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestBonusEligibility(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Bonus eligibility company'})
        cls.other_company = cls.env['res.company'].create({'name': 'Other bonus company'})
        cls.env.user.write({'groups_id': [Command.link(cls.env.ref(
            'kio_payroll_overview_extension.group_kio_payroll_manager').id)]})
        cls.department = cls.env['hr.department'].create({'name': 'Bonus department', 'company_id': cls.company.id})
        cls.employees = cls.env['hr.employee'].create([
            {'name': 'Bonus employee %02d' % i, 'company_id': cls.company.id,
             'department_id': cls.department.id if i < 2 else False}
            for i in range(29)
        ])
        cls.inactive = cls.env['hr.employee'].create({'name': 'Inactive bonus employee', 'company_id': cls.company.id, 'active': False})
        cls.other = cls.env['hr.employee'].create({'name': 'Other company employee', 'company_id': cls.other_company.id})
        cls.contract = cls.env['hr.contract'].create({
            'name': 'Bonus contract', 'employee_id': cls.employees[0].id,
            'company_id': cls.company.id, 'date_start': date(2026, 1, 1),
            'wage': 50000, 'state': 'open',
            'resource_calendar_id': cls.company.resource_calendar_id.id,
        })
        cls.zero_contract = cls.env['hr.contract'].create({
            'name': 'Zero bonus contract', 'employee_id': cls.employees[1].id,
            'company_id': cls.company.id, 'date_start': date(2026, 1, 1),
            'wage': 0, 'state': 'open',
            'resource_calendar_id': cls.company.resource_calendar_id.id,
        })
        cls.bonus_type = cls.env.ref('kio_payroll_overview_extension.kio_bonus_type_performance')

    def _bonus(self, **values):
        return self.env['kio.bonus'].create(dict({
            'name': 'Test bonus', 'bonus_type_id': self.bonus_type.id,
            'company_id': self.company.id, 'bonus_date': date(2026, 11, 11),
            'payment_scope': 'all', 'calculation_type': 'fixed', 'amount': 1000,
        }, **values))

    def test_fixed_all_and_regeneration(self):
        self.assertFalse(self.env['kio.payroll.salary.config'].search([('company_id', '=', self.company.id)]))
        bonus = self._bonus()
        bonus.action_generate_employees()
        self.assertEqual(set(bonus.line_ids.employee_id.ids), set(self.employees.ids))
        self.assertEqual(len(bonus.line_ids), 29)
        self.assertTrue(all(line.bonus_amount == 1000 for line in bonus.line_ids))
        self.assertEqual(bonus.line_ids.filtered(lambda l: l.employee_id == self.employees[0]).basic_salary, 50000)
        self.assertEqual(bonus.line_ids.filtered(lambda l: l.employee_id == self.employees[2]).basic_salary, 0)
        bonus.action_generate_employees()
        self.assertEqual(len(bonus.line_ids), 29)
        bonus.action_confirm()
        old = {line.id: (line.basic_salary, line.bonus_amount) for line in bonus.line_ids}
        self.contract.wage = 60000
        with self.assertRaises(UserError):
            bonus.action_generate_employees()
        self.assertEqual(old, {line.id: (line.basic_salary, line.bonus_amount) for line in bonus.line_ids})

    def test_department_and_individual_scope(self):
        bonus = self._bonus(payment_scope='department', department_id=self.department.id)
        bonus.action_generate_employees()
        self.assertEqual(set(bonus.line_ids.employee_id.ids), set(self.employees[:2].ids))
        individual = self._bonus(payment_scope='individual', employee_ids=[Command.set([self.employees[2].id, self.inactive.id])])
        individual.action_generate_employees()
        self.assertEqual(individual.line_ids.employee_id, self.employees[2])
        individual.employee_ids = [Command.set([self.other.id])]
        with self.assertRaises(UserError):
            individual.action_generate_employees()

    def test_percentage_contract_date_and_wage(self):
        bonus = self._bonus(calculation_type='percentage', percentage=10)
        bonus.action_generate_employees()
        self.assertEqual(bonus.line_ids.employee_id, self.employees[0])
        self.assertEqual(bonus.line_ids.basic_salary, 50000)
        self.assertEqual(bonus.line_ids.bonus_amount, 5000)
        self.contract.date_start = date(2026, 12, 1)
        with self.assertRaises(UserError):
            bonus.action_generate_employees()

    def test_ambiguous_contracts_rejected_for_percentage(self):
        bonus = self._bonus(calculation_type='percentage', percentage=10)
        model_class = type(self.env['kio.payroll.payslip'])
        with patch.object(model_class, '_get_employee_contracts', return_value=({}, {self.employees[0].id})):
            with self.assertRaisesRegex(UserError, 'overlapping running contracts'):
                bonus.action_generate_employees()
            fixed = self._bonus()
            fixed.action_generate_employees()
            self.assertEqual(fixed.line_ids.filtered(lambda l: l.employee_id == self.employees[0]).basic_salary, 0)

    def test_fixed_bonus_does_not_require_contract_read_access(self):
        model_class = type(self.env['kio.payroll.payslip'])
        with patch.object(model_class, '_get_employee_contracts', side_effect=AccessError('No contract access')):
            fixed = self._bonus()
            fixed.action_generate_employees()
            self.assertEqual(len(fixed.line_ids), 29)
            self.assertFalse(any(fixed.line_ids.mapped('basic_salary')))
            with self.assertRaises(AccessError):
                self._bonus(calculation_type='percentage', percentage=10).action_generate_employees()

    def test_confirmed_bonus_flows_into_payroll(self):
        bonus = self._bonus(payment_scope='individual', employee_ids=[Command.set(self.employees[0].ids)])
        bonus.action_generate_employees()
        bonus.action_confirm()
        payslips = self.env['kio.payroll.payslip'].with_company(self.company)
        model_class = type(payslips)
        with patch.object(model_class, '_post_batch_salary_entry', return_value=self.env['account.move']):
            payslips.generate_new_payroll_run({
                'name': 'Bonus integration', 'payroll_type': 'monthly',
                'payment_date': '2026-11-30', 'date_start': '2026-11-01',
                'date_end': '2026-11-30', 'employee_ids': self.employees[0].ids,
            })
        slip = payslips.search([('employee_id', '=', self.employees[0].id), ('date_from', '=', date(2026, 11, 1))])
        self.assertEqual(slip.bonus, 1000)
        self.assertTrue(bonus.line_ids.applied)
        self.assertEqual(bonus.line_ids.applied_payslip_id, slip)
