from datetime import date
from unittest.mock import patch

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestDepartmentPayroll(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'Department payroll company'})
        cls.other_company = cls.env['res.company'].create({'name': 'Other payroll company'})
        cls.env.user.write({'groups_id': [Command.link(cls.env.ref(
            'kio_payroll_overview_extension.group_kio_payroll_manager').id)]})
        Department = cls.env['hr.department']
        cls.it = Department.create({'name': 'IT', 'company_id': cls.company.id})
        cls.child = Department.create({'name': 'IT child', 'company_id': cls.company.id, 'parent_id': cls.it.id})
        cls.accounts = Department.create({'name': 'Accounts', 'company_id': cls.company.id})
        cls.empty = Department.create({'name': 'Empty', 'company_id': cls.company.id})
        cls.foreign = Department.create({'name': 'Foreign', 'company_id': cls.other_company.id})
        Employee = cls.env['hr.employee']
        cls.it_employee = Employee.create({'name': 'IT employee', 'company_id': cls.company.id, 'department_id': cls.it.id})
        cls.accounts_employee = Employee.create({'name': 'Accounts employee', 'company_id': cls.company.id, 'department_id': cls.accounts.id})
        cls.child_employee = Employee.create({'name': 'Child employee', 'company_id': cls.company.id, 'department_id': cls.child.id})
        cls.no_department = Employee.create({'name': 'No department employee', 'company_id': cls.company.id})
        cls.no_contract = Employee.create({'name': 'No contract employee', 'company_id': cls.company.id, 'department_id': cls.it.id})
        cls.inactive = Employee.create({'name': 'Inactive employee', 'company_id': cls.company.id, 'department_id': cls.it.id, 'active': False})
        for employee in cls.it_employee | cls.accounts_employee | cls.child_employee | cls.no_department:
            cls.env['hr.contract'].create({
                'name': 'Contract ' + employee.name, 'employee_id': employee.id,
                'company_id': cls.company.id, 'date_start': date(2026, 1, 1),
                'state': 'open', 'wage': 30000,
                'resource_calendar_id': cls.company.resource_calendar_id.id,
            })
        cls.Payslip = cls.env['kio.payroll.payslip'].with_company(cls.company)

    def _preview(self, scope='all', department=False):
        return self.Payslip.get_new_payroll_run_data('2026-11-01', '2026-11-30', scope, department)

    def _generate(self, employee, scope='all', department=False, start='2026-11-01', end='2026-11-30', name='Department test'):
        values = {'name': name, 'payroll_type': 'monthly', 'payment_date': end,
                  'date_start': start, 'date_end': end, 'employee_ids': employee.ids,
                  'payroll_scope': scope, 'department_id': department}
        with patch.object(type(self.Payslip), '_post_batch_salary_entry', return_value=self.env['account.move']):
            self.Payslip.generate_new_payroll_run(values)
        return self.Payslip.search([('employee_id', '=', employee.id), ('date_from', '=', start)], limit=1)

    def test_preview_all_and_exact_department(self):
        all_ids = {r['employee_id'] for r in self._preview()['employees']}
        self.assertEqual(all_ids, set((self.it_employee | self.accounts_employee | self.child_employee | self.no_department).ids))
        it_ids = {r['employee_id'] for r in self._preview('department', self.it.id)['employees']}
        self.assertEqual(it_ids, set(self.it_employee.ids))
        self.assertFalse(self._preview('department', self.empty.id)['employees'])
        with self.assertRaises(ValidationError):
            self._preview('department', False)
        with self.assertRaises(AccessError):
            self._preview('department', self.foreign.id)
        with self.assertRaises(ValidationError):
            self._preview('invalid')

    def test_separate_departments_duplicates_and_transfer(self):
        it_slip = self._generate(self.it_employee, 'department', self.it.id)
        accounts_slip = self._generate(self.accounts_employee, 'department', self.accounts.id)
        self.assertEqual(it_slip.batch_id.department_id, self.it)
        self.assertEqual(accounts_slip.batch_id.department_id, self.accounts)
        self.assertNotEqual(it_slip.batch_id, accounts_slip.batch_id)
        row = self._preview('department', self.it.id)['employees'][0]
        self.assertTrue(row['has_existing_payslip'])
        with self.assertRaises(ValidationError):
            self._generate(self.it_employee, 'department', self.it.id)
        self.it_employee.department_id = self.accounts
        with self.assertRaises(ValidationError):
            self._generate(self.it_employee, 'department', self.it.id)
        with self.assertRaises(ValidationError):
            self._generate(self.it_employee, 'department', self.accounts.id, '2026-11-15', '2026-12-15')
        with self.assertRaises(ValidationError):
            self._generate(self.it_employee)
        self.assertEqual(it_slip.batch_id.department_id, self.it)

    def test_all_generation_and_historical_batch(self):
        historical = self.env['kio.payroll.batch'].with_company(self.company).create({
            'name': 'Historical', 'date_start': '2025-01-01', 'date_end': '2025-01-31', 'state': 'done',
        })
        slip = self._generate(self.no_department)
        self.assertEqual(slip.batch_id.payroll_scope, 'all')
        self.assertFalse(slip.batch_id.department_id)
        self.assertEqual(historical.name, 'Historical')
        self.assertFalse(historical.department_id)
        details = self.Payslip.get_payroll_batch_details(slip.batch_id.id)
        self.assertFalse(details['batch']['department'])

    def test_generated_and_custom_batch_names(self):
        default_name = 'November 2026 Payroll'
        it_slip = self._generate(self.it_employee, 'department', self.it.id, name=default_name)
        self.assertEqual(it_slip.batch_id.name, default_name + ' - IT')
        self.assertEqual(self.Payslip.get_payroll_batch_details(it_slip.batch_id.id)['batch']['name'], it_slip.batch_id.name)
        batches = self.Payslip.get_payroll_overview_data(11, 2026)['recent_batches']
        self.assertEqual(next(batch['name'] for batch in batches if batch['id'] == it_slip.batch_id.id), it_slip.batch_id.name)
        all_slip = self._generate(self.no_department, name=default_name)
        self.assertEqual(all_slip.batch_id.name, default_name)
        named_slip = self._generate(self.accounts_employee, 'department', self.accounts.id, name=default_name + ' - Accounts')
        self.assertEqual(named_slip.batch_id.name, default_name + ' - Accounts')
        custom_slip = self._generate(self.child_employee, 'department', self.child.id, name='Special management payroll')
        self.assertEqual(custom_slip.batch_id.name, 'Special management payroll')

    def test_tampered_employee_and_empty_department(self):
        with self.assertRaises(ValidationError):
            self._generate(self.accounts_employee, 'department', self.it.id)
        with self.assertRaises(ValidationError):
            self._generate(self.it_employee, 'department', False)
        with self.assertRaises(AccessError):
            self._generate(self.it_employee, 'department', self.foreign.id)

    def test_department_bonus_and_pay_now(self):
        bonus = self.env['kio.bonus'].with_company(self.company).create({
            'name': 'Department bonus',
            'bonus_type_id': self.env.ref('kio_payroll_overview_extension.kio_bonus_type_performance').id,
            'company_id': self.company.id, 'payment_scope': 'department',
            'department_id': self.it.id, 'calculation_type': 'fixed', 'amount': 1000,
            'bonus_date': '2026-11-11',
        })
        bonus.action_generate_employees()
        bonus.action_confirm()
        account = self.env['account.account'].with_company(self.company)
        debit = account.create({'name': 'Salary expense', 'code': '900001', 'account_type': 'expense', 'company_id': self.company.id})
        credit = account.create({'name': 'Salary payable', 'code': '200001', 'account_type': 'liability_payable', 'reconcile': True, 'company_id': self.company.id})
        journal = self.env['account.journal'].with_company(self.company).create({'name': 'Salary entries', 'code': 'SAL', 'type': 'general', 'company_id': self.company.id})
        self.company.write({'salary_journal_id': journal.id, 'salary_debit_account_id': debit.id, 'salary_credit_account_id': credit.id})
        partner = self.env['res.partner'].create({'name': 'IT payment contact', 'company_id': self.company.id})
        self.it_employee.work_contact_id = partner
        self.Payslip.generate_new_payroll_run({
            'name': 'IT real accounting', 'payroll_type': 'monthly', 'payment_date': '2026-11-30',
            'date_start': '2026-11-01', 'date_end': '2026-11-30', 'employee_ids': self.it_employee.ids,
            'payroll_scope': 'department', 'department_id': self.it.id,
        })
        slip = self.Payslip.search([('employee_id', '=', self.it_employee.id), ('date_from', '=', date(2026, 11, 1))])
        self.assertEqual(slip.bonus, 1000)
        self.assertEqual(slip.salary_move_id.state, 'posted')
        self.assertEqual(slip._get_kio_salary_payment_info()['payment_state'], 'unpaid')
        action = self.Payslip.action_payroll_pay_now(slip.id)
        self.assertEqual(action['res_model'], 'account.payment.register')
        self.assertEqual(action['context']['kio_payroll_slip_id'], slip.id)
        self.assertTrue(bonus.line_ids.filtered(lambda line: line.employee_id == self.it_employee).applied)
