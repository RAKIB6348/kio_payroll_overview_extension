import calendar
from collections import Counter
from datetime import date

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class KioPayrollBatch(models.Model):
    _name = "kio.payroll.batch"
    _description = "Payroll Batch"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_start desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    date_start = fields.Date(required=True, tracking=True)
    date_end = fields.Date(required=True, tracking=True)
    payroll_type = fields.Selection(
        [("monthly", "Monthly Payroll")],
        default="monthly",
        required=True,
    )
    payment_date = fields.Date()
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
            ("cancel", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    payslip_ids = fields.One2many(
        "kio.payroll.payslip", "batch_id", string="Payslips"
    )
    payslip_count = fields.Integer(compute="_compute_payslip_stats")
    employee_count = fields.Integer(compute="_compute_payslip_stats")
    total_net = fields.Monetary(
        string="Total Net", compute="_compute_payslip_stats", currency_field="currency_id"
    )
    note = fields.Text()

    @api.depends("payslip_ids", "payslip_ids.employee_id", "payslip_ids.net_pay")
    def _compute_payslip_stats(self):
        for batch in self:
            slips = batch.payslip_ids
            batch.payslip_count = len(slips)
            batch.employee_count = len(slips.mapped("employee_id"))
            batch.total_net = sum(slips.mapped("net_pay"))

    @api.constrains("date_start", "date_end")
    def _check_dates(self):
        for batch in self:
            if batch.date_start and batch.date_end and batch.date_end < batch.date_start:
                raise ValidationError(_("The end date must be on or after the start date."))


class KioPayrollPayslip(models.Model):
    _name = "kio.payroll.payslip"
    _description = "Payroll Payslip"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date_from desc, id desc"
    _check_company_auto = True

    name = fields.Char(required=True)
    number = fields.Char(copy=False, readonly=True)
    batch_id = fields.Many2one(
        "kio.payroll.batch",
        string="Payroll Batch",
        ondelete="cascade",
        index=True,
        check_company=True,
    )
    employee_id = fields.Many2one(
        "hr.employee",
        required=True,
        index=True,
        check_company=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        related="company_id.currency_id",
        store=True,
        readonly=True,
    )
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done"), ("cancel", "Cancelled")],
        default="draft",
        required=True,
        tracking=True,
    )
    line_ids = fields.One2many("kio.payroll.payslip.line", "payslip_id", string="Lines")
    note = fields.Text()

    basic_salary = fields.Monetary(compute="_compute_amounts", store=True)
    allowance = fields.Monetary(compute="_compute_amounts", store=True)
    overtime = fields.Monetary(compute="_compute_amounts", store=True)
    bonus = fields.Monetary(compute="_compute_amounts", store=True)
    deduction = fields.Monetary(compute="_compute_amounts", store=True)
    gross_salary = fields.Monetary(compute="_compute_amounts", store=True)
    net_pay = fields.Monetary(compute="_compute_amounts", store=True)

    paid = fields.Boolean(string="Paid", copy=False, default=False)
    payment_date = fields.Date(string="Payment Date", copy=False)
    payment_journal_id = fields.Many2one(
        "account.journal", string="Payment Journal", copy=False, check_company=True
    )
    payment_move_id = fields.Many2one(
        "account.move", string="Payment Entry", copy=False, readonly=True, check_company=True
    )
    kio_payment_move_id = fields.Many2one(
        "account.move", string="Salary Payment Entry", copy=False, readonly=True, check_company=True
    )

    _sql_constraints = [
        (
            "kio_payroll_payslip_employee_period_company_uniq",
            "unique(employee_id, company_id, date_from, date_to)",
            "A payslip already exists for this employee and period.",
        ),
    ]

    @api.depends("line_ids.total", "line_ids.code")
    def _compute_amounts(self):
        for slip in self:
            totals = Counter()
            for line in slip.line_ids:
                totals[(line.code or "").upper()] += line.total
            basic = totals.get("BASIC", 0.0)
            allowance = totals.get("ALW", 0.0)
            overtime = totals.get("OVERTIME", 0.0) or totals.get("OT", 0.0)
            bonus = totals.get("BONUS", 0.0)
            deduction = abs(totals.get("DED", 0.0) or totals.get("DEDUCTION", 0.0))
            gross = totals.get("GROSS", 0.0)
            if not gross:
                gross = basic + allowance + overtime + bonus
            net = totals.get("NET", 0.0)
            if not net:
                net = gross - deduction
            slip.basic_salary = basic
            slip.allowance = allowance
            slip.overtime = overtime
            slip.bonus = bonus
            slip.deduction = deduction
            slip.gross_salary = gross
            slip.net_pay = net

    # ------------------------------------------------------------------
    # Helpers used by dashboard / JS / report
    # ------------------------------------------------------------------
    @api.model
    def _check_payroll_overview_manager(self):
        if not self.env.user.has_group(
            "kio_payroll_overview_extension.group_kio_payroll_manager"
        ):
            raise AccessError(_("Only Payroll Managers can access Payroll Overview."))

    def _get_kio_net_pay_amount(self):
        self.ensure_one()
        return self.company_id.currency_id.round(self.net_pay)

    def _is_kio_salary_paid(self):
        self.ensure_one()
        move = self.payment_move_id or self.kio_payment_move_id
        return bool(self.paid or (move and move.state == "posted"))

    @api.model
    def _get_payroll_overview_period(self, month, year):
        try:
            month = int(month)
            year = int(year)
        except (TypeError, ValueError):
            raise ValidationError(_("Month and year must be valid numbers."))
        if month not in range(1, 13) or year not in range(1, 10000):
            raise ValidationError(_("Month must be between 1 and 12 and year must be valid."))
        return (
            month,
            year,
            date(year, month, 1),
            date(year, month, calendar.monthrange(year, month)[1]),
        )

    @api.model
    def _get_authorized_payroll_batch(self, batch_id, write=False):
        try:
            batch_id = int(batch_id)
        except (TypeError, ValueError):
            raise ValidationError(_("A valid payslip batch is required."))
        if batch_id <= 0:
            raise ValidationError(_("A valid payslip batch is required."))
        batch_model = self.env["kio.payroll.batch"]
        batch_model.check_access_rights("write" if write else "read")
        batch = batch_model.search([
            ("id", "=", batch_id),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not batch:
            raise AccessError(_("The selected payroll batch is unavailable for the current company."))
        return batch

    @api.model
    def _get_employee_salary_config(self, employees, company):
        config_model = self.env["kio.payroll.salary.config"]
        configs = config_model.search([
            ("employee_id", "in", employees.ids),
            ("company_id", "=", company.id),
            ("active", "=", True),
        ])
        return {cfg.employee_id.id: cfg for cfg in configs}

    @api.model
    def _get_employee_contracts(self, employees, company, date_start, date_end):
        """Return the most relevant contract per employee for the period.

        A contract is applicable when it overlaps the payroll period:
        date_start <= payroll end and (date_end is empty or date_end >=
        payroll start). Draft and cancelled contracts are ignored, while
        all active/running/closed contracts are kept because they may still
        cover part of the selected period.
        """
        if not employees or "hr.contract" not in self.env.registry.models:
            return {}
        contracts = self.env["hr.contract"].search([
            ("employee_id", "in", employees.ids),
            ("company_id", "=", company.id),
            ("active", "=", True),
            ("date_start", "<=", date_end),
            "|",
            ("date_end", "=", False),
            ("date_end", ">=", date_start),
            ("state", "not in", ("draft", "cancel", "cancelled")),
        ], order="employee_id, date_start desc, id desc")
        contract_by_employee = {}
        for contract in contracts:
            employee_id = contract.employee_id.id
            if employee_id not in contract_by_employee:
                contract_by_employee[employee_id] = contract
        return contract_by_employee

    @api.model
    def _get_payroll_bonus_amounts(self, company, date_start, date_end, employee_ids=None):
        if "kio.bonus.line" not in self.env.registry.models:
            return {}
        return self.env["kio.bonus.line"]._get_payroll_bonus_amounts(
            company, date_start, date_end, employee_ids=employee_ids, pending_only=True
        )

    @api.model
    def get_new_payroll_run_data(self, date_start, date_end):
        self._check_payroll_overview_manager()
        try:
            date_start = fields.Date.to_date(date_start)
            date_end = fields.Date.to_date(date_end)
        except (TypeError, ValueError):
            raise ValidationError(_("Enter valid payroll start and end dates."))
        if not date_start or not date_end or date_end < date_start:
            raise ValidationError(_("The end date must be on or after the start date."))

        company = self.env.company
        currency = company.currency_id
        employees = self.env["hr.employee"].search([
            ("company_id", "=", company.id),
            ("active", "=", True),
        ], order="name, id")
        configs = self._get_employee_salary_config(employees, company)
        contracts = self._get_employee_contracts(
            employees, company, date_start, date_end
        )
        pending_bonuses = self._get_payroll_bonus_amounts(
            company, date_start, date_end, employee_ids=employees.ids
        )
        existing_payslips = self.search([
            ("employee_id", "in", employees.ids),
            ("company_id", "=", company.id),
            ("date_from", "<=", date_end),
            ("date_to", ">=", date_start),
            ("state", "!=", "cancel"),
        ]) if employees else self.browse()
        existing_by_employee = {s.employee_id.id for s in existing_payslips}

        rows = []
        working_days_values = []
        seen_employee_ids = set()
        missing_contract_count = 0
        missing_wage_count = 0
        for employee in employees:
            if employee.id in seen_employee_ids:
                continue
            seen_employee_ids.add(employee.id)

            cfg = configs.get(employee.id)
            contract = contracts.get(employee.id)
            contract_wage = contract.wage if contract else None
            has_wage = contract is not None and (contract_wage or 0.0) > 0
            eligible = has_wage

            eligibility_reason = False
            contract_status = contract.state if contract else False
            contract_status_label = False
            if contract:
                contract_status_label = dict(
                    contract._fields["state"].selection
                ).get(contract.state, contract.state)
            if not contract:
                missing_contract_count += 1
                eligibility_reason = _(
                    "No active contract overlaps this payroll period."
                )
            elif not has_wage:
                missing_wage_count += 1
                eligibility_reason = _(
                    "The applicable contract has no valid wage."
                )

            working_days = (cfg.working_days or 0.0) if cfg else 0.0
            if eligible:
                basic = contract_wage or 0.0
                allowance = (cfg.allowance or 0.0) if cfg else 0.0
                overtime = 0.0
                commission = 0.0
                bonus = pending_bonuses.get(employee.id, 0.0)
                deduction = 0.0
                net_pay = basic + allowance + overtime + commission + bonus - deduction
                working_days_values.append(working_days)
                amounts = {
                    "basic_salary": currency.round(basic),
                    "allowance": currency.round(allowance),
                    "overtime": currency.round(overtime),
                    "commission": currency.round(commission),
                    "bonus": currency.round(bonus),
                    "deduction": currency.round(deduction),
                    "net_pay": currency.round(net_pay),
                }
            else:
                # Never invent a salary for a missing/invalid contract.
                amounts = {
                    "basic_salary": None,
                    "allowance": None,
                    "overtime": None,
                    "commission": None,
                    "bonus": None,
                    "deduction": None,
                    "net_pay": None,
                }

            rows.append({
                "employee_id": employee.id,
                "name": employee.display_name,
                "identification_id": employee.identification_id or "-",
                "avatar_url": f"/web/image/hr.employee/{employee.id}/avatar_128",
                "department": employee.department_id.display_name or "-",
                "designation": employee.job_id.display_name or "-",
                **amounts,
                "working_days": round(working_days, 2),
                "eligible": eligible,
                "eligibility_reason": eligibility_reason,
                "has_contract": bool(contract),
                "contract_id": contract.id if contract else False,
                "contract_name": contract.name if contract else False,
                "contract_status": contract_status,
                "contract_status_label": contract_status_label,
                "has_existing_payslip": employee.id in existing_by_employee,
            })

        eligible_employee_count = sum(1 for row in rows if row["eligible"])
        average_working_days = (
            sum(working_days_values) / len(working_days_values)
            if working_days_values else 0.0
        )
        return {
            "company": {"id": company.id, "name": company.display_name},
            "currency": {
                "id": currency.id,
                "name": currency.name,
                "symbol": currency.symbol,
                "position": currency.position,
                "decimal_places": currency.decimal_places,
            },
            "date_start": date_start,
            "date_end": date_end,
            "default_name": "%s Payroll" % date_end.strftime("%B %Y"),
            "payment_date": date_end,
            "employee_count": eligible_employee_count,
            "eligible_employee_count": eligible_employee_count,
            "total_employee_count": len(rows),
            "missing_contract_count": missing_contract_count,
            "missing_wage_count": missing_wage_count,
            "working_days": round(average_working_days, 2),
            "employees": rows,
            "loan_count": 0,
            "loan_available": False,
            "leave_available": False,
            "leave_action": False,
        }

    @api.model
    def _prepare_payslip_lines(self, employee, cfg=None, bonus_amount=0.0,
                               basic=None, allowance=None):
        if basic is None:
            basic = (cfg.basic_salary or 0.0) if cfg else 0.0
        if allowance is None:
            allowance = (cfg.allowance or 0.0) if cfg else 0.0
        overtime = 0.0
        bonus = bonus_amount or 0.0
        deduction = 0.0
        gross = basic + allowance + overtime + bonus
        net = gross - deduction
        return [
            Command.create({"name": _("Basic Salary"), "code": "BASIC", "sequence": 1, "amount": basic, "total": basic}),
            Command.create({"name": _("Allowances"), "code": "ALW", "sequence": 5, "amount": allowance, "total": allowance}),
            Command.create({"name": _("Overtime"), "code": "OVERTIME", "sequence": 10, "amount": overtime, "total": overtime}),
            Command.create({"name": _("Bonus"), "code": "BONUS", "sequence": 15, "amount": bonus, "total": bonus}),
            Command.create({"name": _("Deductions"), "code": "DED", "sequence": 90, "amount": deduction, "total": deduction}),
            Command.create({"name": _("Gross"), "code": "GROSS", "sequence": 100, "amount": gross, "total": gross}),
            Command.create({"name": _("Net"), "code": "NET", "sequence": 200, "amount": net, "total": net}),
        ]

    @api.model
    def generate_new_payroll_run(self, values):
        self._check_payroll_overview_manager()
        if not isinstance(values, dict):
            raise ValidationError(_("Payroll run data is invalid."))
        name = (values.get("name") or "").strip()
        payroll_type = values.get("payroll_type") or "monthly"
        try:
            payment_date = fields.Date.to_date(values.get("payment_date"))
            date_start = fields.Date.to_date(values.get("date_start"))
            date_end = fields.Date.to_date(values.get("date_end"))
        except (TypeError, ValueError):
            raise ValidationError(_("Enter valid payroll dates."))
        if not name or not payment_date or not date_start or not date_end:
            raise ValidationError(_("Payroll name, payment date, start date, and end date are required."))
        if payroll_type != "monthly":
            raise ValidationError(_("Unsupported payroll type."))
        if date_end < date_start:
            raise ValidationError(_("The end date must be on or after the start date."))
        try:
            employee_ids = list(dict.fromkeys(int(v) for v in values.get("employee_ids", [])))
        except (TypeError, ValueError):
            raise ValidationError(_("Employee selection is invalid."))
        if not employee_ids:
            raise ValidationError(_("Select at least one eligible employee."))

        company = self.env.company
        employees = self.env["hr.employee"].browse(employee_ids).exists()
        configs = self._get_employee_salary_config(employees, company)
        contracts = self._get_employee_contracts(
            employees, company, date_start, date_end
        )
        ineligible = [
            emp.display_name
            for emp in employees
            if emp.company_id != company
            or emp.id not in contracts
            or (contracts[emp.id].wage or 0.0) <= 0
        ]
        if ineligible:
            raise ValidationError(_(
                "The following employees do not have a valid contract wage for this period: %s."
            ) % ", ".join(ineligible))

        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", (0x4B494F, company.id))
        duplicates = self.search([
            ("employee_id", "in", employees.ids),
            ("company_id", "=", company.id),
            ("date_from", "<=", date_end),
            ("date_to", ">=", date_start),
            ("state", "!=", "cancel"),
        ])
        if duplicates:
            raise ValidationError(_(
                "Existing payslips overlap this period for: %s. No new payroll was created."
            ) % ", ".join(duplicates.mapped("employee_id.display_name")))

        batch = self.env["kio.payroll.batch"].create({
            "name": name,
            "date_start": date_start,
            "date_end": date_end,
            "payment_date": payment_date,
            "payroll_type": payroll_type,
            "company_id": company.id,
            "state": "draft",
        })
        bonus_amounts = self._get_payroll_bonus_amounts(
            company, date_start, date_end, employee_ids=employees.ids
        )
        payslip_vals = []
        for employee in employees:
            cfg = configs.get(employee.id)
            contract = contracts[employee.id]
            payslip_vals.append({
                "name": _("Payslip - %s") % employee.display_name,
                "batch_id": batch.id,
                "employee_id": employee.id,
                "company_id": company.id,
                "date_from": date_start,
                "date_to": date_end,
                "state": "draft",
                "line_ids": self._prepare_payslip_lines(
                    employee,
                    cfg,
                    bonus_amount=bonus_amounts.get(employee.id, 0.0),
                    basic=contract.wage or 0.0,
                    allowance=(cfg.allowance or 0.0) if cfg else 0.0,
                ),
            })
        slips = self.create(payslip_vals)
        self._mark_bonuses_applied(slips)
        return {
            "type": "ir.actions.client",
            "tag": "kio_payroll_overview.batch_details",
            "name": _("Payroll Batch Details"),
            "target": "current",
            "context": {
                "kio_batch_id": batch.id,
                "kio_payroll_month": date_start.month,
                "kio_payroll_year": date_start.year,
            },
        }

    @api.model
    def _mark_bonuses_applied(self, slips):
        if "kio.bonus.line" not in self.env.registry.models or not slips:
            return
        bonus_model = self.env["kio.bonus.line"]
        for slip in slips:
            bonus_lines = bonus_model.search([
                ("company_id", "=", slip.company_id.id),
                ("bonus_id.state", "=", "confirmed"),
                ("employee_id", "=", slip.employee_id.id),
                ("bonus_id.bonus_date", ">=", slip.date_from),
                ("bonus_id.bonus_date", "<=", slip.date_to),
                ("applied", "=", False),
            ])
            if bonus_lines:
                bonus_lines.write({"applied": True, "applied_payslip_id": slip.id})

    @api.model
    def get_payroll_overview_data(self, month, year):
        self._check_payroll_overview_manager()
        month, year, period_start, period_end = self._get_payroll_overview_period(month, year)
        company = self.env.company
        payslip_domain = [
            ("company_id", "=", company.id),
            ("date_from", ">=", period_start),
            ("date_to", "<=", period_end),
            ("state", "in", ("draft", "done")),
        ]
        payslips = self.search(payslip_domain)
        batches = self.env["kio.payroll.batch"].search([
            ("company_id", "=", company.id),
            ("date_start", ">=", period_start),
            ("date_end", "<=", period_end),
        ], order="date_start desc, id desc")
        total_employees_count = self.env["hr.employee"].search_count([
            ("company_id", "=", company.id),
            ("active", "=", True),
        ])
        basic_salary = 0.0
        if "hr.contract" in self.env.registry.models:
            employees = self.env["hr.employee"].search([
                ("company_id", "=", company.id),
                ("active", "=", True),
            ])
            if employees:
                contracts = self.env["hr.contract"].search([
                    ("employee_id", "in", employees.ids),
                    ("company_id", "=", company.id),
                    ("state", "=", "open"),
                    ("date_start", "<=", period_end),
                    "|",
                    ("date_end", "=", False),
                    ("date_end", ">=", period_start),
                ], order="employee_id, date_start desc, id desc")
                wage_by_employee = {}
                for contract in contracts:
                    emp_id = contract.employee_id.id
                    if emp_id not in wage_by_employee:
                        wage_by_employee[emp_id] = contract.wage or 0.0
                basic_salary = sum(wage_by_employee.values())

        total_allowance = sum(payslips.mapped("allowance"))
        gross_salary = sum(payslips.mapped("gross_salary"))
        total_deductions = sum(payslips.mapped("deduction"))
        net_salary = sum(payslips.mapped("net_pay"))
        total_paid_salary = sum(p.net_pay for p in payslips if p._is_kio_salary_paid())
        total_unpaid_salary = sum(p.net_pay for p in payslips if not p._is_kio_salary_paid())
        cur = company.currency_id
        confirmed_bonus_total = 0.0
        if "kio.bonus.line" in self.env.registry.models:
            confirmed_bonus_total = self.env["kio.bonus.line"]._get_payroll_bonus_total(
                company, period_start, period_end, pending_only=False
            )

        recent_batches = []
        for batch in batches[:10]:
            batch_slips = payslips.filtered(lambda s: s.batch_id.id == batch.id)
            recent_batches.append({
                "id": batch.id,
                "name": batch.name,
                "date_start": batch.date_start,
                "date_end": batch.date_end,
                "payment_date": batch.payment_date,
                "payslip_count": len(batch_slips),
                "total_employees": len(batch_slips.mapped("employee_id")),
                "total_net_pay": cur.round(sum(batch_slips.mapped("net_pay"))),
                "state": batch.state,
                "state_label": dict(batch._fields["state"].selection).get(batch.state, batch.state),
            })

        detail_rows = []
        for slip in payslips.sorted(key=lambda s: (s.employee_id.name or "", s.id)):
            emp = slip.employee_id
            detail_rows.append({
                "employee_id": emp.id,
                "employee_name": emp.display_name,
                "department": emp.department_id.display_name or "-",
                "designation": emp.job_id.display_name or "-",
                "basic_salary": cur.round(slip.basic_salary),
                "allowance": cur.round(slip.allowance),
                "overtime": cur.round(slip.overtime),
                "bonus": cur.round(slip.bonus),
                "deduction": cur.round(slip.deduction),
                "net_pay": cur.round(slip.net_pay),
            })

        return {
            "period": {"month": month, "year": year, "date_start": period_start, "date_end": period_end, "policy": "full_period"},
            "company": {"id": company.id, "name": company.display_name},
            "currency": {"id": cur.id, "name": cur.name, "symbol": cur.symbol, "position": cur.position, "decimal_places": cur.decimal_places},
            "kpis": {
                "total_employees": total_employees_count,
                "basic_salary": cur.round(basic_salary),
                "total_allowance": cur.round(total_allowance),
                "payslip_batches": len(batches),
                "draft_payslips": len(payslips.filtered(lambda s: s.state == "draft")),
                "done_payslips": len(payslips.filtered(lambda s: s.state == "done")),
                "gross_salary": cur.round(gross_salary),
                "total_deductions": cur.round(total_deductions),
                "net_salary": cur.round(net_salary),
                "total_salary": cur.round(net_salary),
                "total_paid_salary": cur.round(total_paid_salary),
                "total_unpaid_salary": cur.round(total_unpaid_salary),
                "total_bonus": cur.round(confirmed_bonus_total),
            },
            "recent_batches": recent_batches,
            "employee_payroll_details": {
                "rows": detail_rows,
                "totals": {
                    "overtime": cur.round(sum(r["overtime"] for r in detail_rows)),
                    "bonus": cur.round(confirmed_bonus_total),
                },
            },
        }

    @api.model
    def get_payroll_batch_details(self, batch_id):
        self._check_payroll_overview_manager()
        batch = self._get_authorized_payroll_batch(batch_id)
        company = self.env.company
        currency = company.currency_id
        slips = self.search([
            ("batch_id", "=", batch.id),
            ("company_id", "=", company.id),
        ], order="employee_id, id")
        rows = []
        total_net = 0.0
        total_paid = 0.0
        for slip in slips:
            net_pay = slip._get_kio_net_pay_amount()
            is_paid = slip._is_kio_salary_paid()
            total_net += net_pay
            if is_paid:
                total_paid += net_pay
            emp = slip.employee_id
            rows.append({
                "slip_id": slip.id,
                "employee_id": emp.id,
                "employee_name": emp.display_name,
                "employee_identification": emp.identification_id or "-",
                "employee_avatar_url": f"/web/image/hr.employee/{emp.id}/avatar_128",
                "department": emp.department_id.display_name or "-",
                "designation": emp.job_id.display_name or "-",
                "basic_salary": currency.round(slip.basic_salary),
                "allowance": currency.round(slip.allowance),
                "overtime": currency.round(slip.overtime),
                "bonus": currency.round(slip.bonus),
                "deduction": currency.round(slip.deduction),
                "net_pay": currency.round(net_pay),
                "payslip_number": slip.number or slip.name or "-",
                "payment_state": "paid" if is_paid else "unpaid",
                "can_pay": not is_paid and slip.state == "done",
            })
        total_unpaid = currency.round(total_net - total_paid)
        date_start = batch.date_start
        totals = {
            "total_employees": len(slips.mapped("employee_id")),
            "total_net_salary": currency.round(total_net),
            "total_paid_salary": currency.round(total_paid),
            "total_unpaid_salary": total_unpaid,
        }
        employees = [
            dict(
                r,
                name=r.get("employee_name"),
                identification_id=r.get("employee_identification"),
                avatar_url=r.get("employee_avatar_url"),
                paid=r.get("payment_state") == "paid",
            )
            for r in rows
        ]
        batch_data = {
            "id": batch.id,
            "name": batch.name,
            "payroll_type": batch.payroll_type,
            "payroll_type_label": dict(batch._fields["payroll_type"].selection).get(batch.payroll_type, batch.payroll_type),
            "payment_date": batch.payment_date,
            "date_start": batch.date_start,
            "date_end": batch.date_end,
            "month": date_start.month if date_start else False,
            "year": date_start.year if date_start else False,
            "state": batch.state,
            "state_label": dict(batch._fields["state"].selection).get(batch.state, batch.state),
            "total_employees": len(slips.mapped("employee_id")),
            "working_days": 0.0,
        }
        return {
            "company": {"id": company.id, "name": company.display_name},
            "currency": {"id": currency.id, "name": currency.name, "symbol": currency.symbol, "position": currency.position, "decimal_places": currency.decimal_places},
            "batch": batch_data,
            "period": {"date_start": batch.date_start, "date_end": batch.date_end},
            "totals": totals,
            "summary": totals,
            "rows": rows,
            "employees": employees,
        }

    # Stub compatibility methods used by older code paths (not required for clean install)
    @api.model
    def get_payroll_overview_batches(self):
        self._check_payroll_overview_manager()
        batches = self.env["kio.payroll.batch"].search([("company_id", "=", self.env.company.id)], order="date_start desc, id desc")
        return [{"id": b.id, "name": b.name, "date_start": b.date_start, "date_end": b.date_end, "state": b.state,
                 "state_label": dict(b._fields["state"].selection).get(b.state, b.state)} for b in batches]

    @api.model
    def get_payroll_overview_batch_page(self, offset=0, limit=20):
        self._check_payroll_overview_manager()
        offset = max(int(offset or 0), 0)
        limit = max(min(int(limit or 20), 100), 1)
        domain = [("company_id", "=", self.env.company.id)]
        total = self.env["kio.payroll.batch"].search_count(domain)
        batches = self.env["kio.payroll.batch"].search(domain, order="date_start desc, id desc", offset=offset, limit=limit)
        return {"total": total, "offset": offset, "limit": limit, "rows": [
            {"id": b.id, "name": b.name, "date_start": b.date_start, "date_end": b.date_end, "state": b.state,
             "state_label": dict(b._fields["state"].selection).get(b.state, b.state)} for b in batches]}

    @api.model
    def get_payroll_generation_data(self, batch_id=False):
        self._check_payroll_overview_manager()
        data = {"company": {"id": self.env.company.id, "name": self.env.company.display_name}, "batches": self.get_payroll_overview_batches(), "selected_batch": False}
        return data

    @api.model
    def prepare_payroll_generation(self, batch_id):
        raise UserError(_("Payroll generation is handled by the independent payroll workflow."))

    @api.model
    def get_create_payroll_batch_action(self):
        return {"type": "ir.actions.client", "tag": "kio_payroll_overview.new_payroll_generation", "target": "current"}

    def get_payslip_report_data(self):
        # Minimal compatibility for custom report template; preserve existing keys where possible.
        self.ensure_one()
        cur = self.company_id.currency_id
        is_paid = self._is_kio_salary_paid()
        def fmt(v):
            return "%s %.2f" % (cur.symbol or cur.name or "", v or 0.0)
        return {
            "company_name": self.company_id.display_name,
            "employee_name": self.employee_id.display_name,
            "employee_id": self.employee_id.identification_id or "-",
            "designation": self.employee_id.job_id.display_name or "-",
            "department": self.employee_id.department_id.display_name or "-",
            "period": "%s - %s" % (self.date_from or "", self.date_to or ""),
            "batch_name": self.batch_id.name or "-",
            "payment_status": _("Paid") if is_paid else _("Unpaid"),
            "payment_state": "paid" if is_paid else "unpaid",
            "payment_date": self.payment_date or (self.batch_id.payment_date if self.batch_id else False) or "-",
            "basic_salary": self.basic_salary,
            "allowance": self.allowance,
            "overtime": self.overtime,
            "bonus": self.bonus,
            "deduction": self.deduction,
            "net_salary_formatted": fmt(self.net_pay),
            "basic_salary_formatted": fmt(self.basic_salary),
            "allowance_formatted": fmt(self.allowance),
            "overtime_formatted": fmt(self.overtime),
            "bonus_formatted": fmt(self.bonus),
            "deduction_formatted": fmt(self.deduction),
            "paid_amount_formatted": fmt(self.net_pay if is_paid else 0.0),
            "unpaid_amount_formatted": fmt(0.0 if is_paid else self.net_pay),
        }


class KioPayrollPayslipLine(models.Model):
    _name = "kio.payroll.payslip.line"
    _description = "Payroll Payslip Line"
    _order = "sequence, id"
    _check_company_auto = True

    payslip_id = fields.Many2one(
        "kio.payroll.payslip", required=True, ondelete="cascade", index=True
    )
    employee_id = fields.Many2one(
        related="payslip_id.employee_id", store=True, readonly=True
    )
    company_id = fields.Many2one(
        related="payslip_id.company_id", store=True, readonly=True
    )
    currency_id = fields.Many2one(
        related="payslip_id.currency_id", store=True, readonly=True
    )
    name = fields.Char(required=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    amount = fields.Monetary()
    quantity = fields.Float(default=1.0)
    rate = fields.Float(default=100.0)
    total = fields.Monetary(required=True)
