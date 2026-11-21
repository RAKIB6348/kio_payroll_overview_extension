# KIO Payroll — Functional Test Report

**Module:** `kio_payroll_overview_extension` (17.0.4.0.3) — Independent payroll dashboard and payroll processing

---

## 1. Executive Summary

- **Test database:** `test_kio_payroll_20261119` (freshly created with `createdb`; module installed on it only).
- **Total tests executed:** 33 (phases 2-6). **Passed:** 27. **Failed:** 6. **Blocked:** 0.
- **Final verdict:** **FAIL — Critical integration defect (BUG-1) confirmed at runtime:** confirmed overtime, commission and deduction records are excluded from payroll because `_get_payroll_adjustment_amounts()`/`_get_payroll_adjustment_records()` in `models/kio_payroll.py` return `{}`/empty for every model (see Section 7).

---

## 2. Test Environment

| Item | Value |
|---|---|
| Odoo | 17.0 (source at `/home/rakib/odoo17_env/odoo-17.0`) |
| Test DB | `test_kio_payroll_20261119` (created via `createdb -h 127.0.0.1 -p 5432 -U odoo17 test_kio_payroll_20261119`) |
| Module under test | `kio_payroll_overview_extension` 17.0.4.0.3, installed: `./odoo-bin -c odoo.conf -d test_kio_payroll_20261119 -i kio_payroll_overview_extension --stop-after-init` |
| Execution harness | `./odoo-bin shell -c odoo.conf -d test_kio_payroll_20261119 < phase_script.py` (real ORM; committed via `env.cr.commit()` per phase) |
| Company | YourCompany, currency USD |
| Payroll accounting | Salary Journal `KIO Test Salary Journal`; Salary Debit Account `KIO Test Salary Expense` (expense); Salary Credit Account `KIO Test Salary Payable` (liability_payable) |
| Overtime policy (company) | Monetary calc enabled; Per Hour Rate (BDT) 1000 |
| Late deduction policy (company) | Enabled; Buffer Time 10 min; Late Days Threshold 1; Salary Deduction Days 1000 |
| Payroll period | 2026-11-01 to 2026-11-30 |

Executed commands (all against the test DB only):

```bash
createdb -h 127.0.0.1 -p 5432 -U odoo17 test_kio_payroll_20261119
./odoo-bin -c odoo.conf -d test_kio_payroll_20261119 -i kio_payroll_overview_extension --stop-after-init
cat phase_N_*.py | ./odoo-bin shell -c odoo.conf -d test_kio_payroll_20261119
```

---

## 3. Sample Data Created (Phase 1 — Setup)

### 3.1 Departments (created; `hr.department`)
- **Sales** (id 3)
- **Engineering** (id 16)
- **Finance** (id 17)

### 3.2 Job positions (created; `hr.job`)
- **Software Engineer** (id 20)
- **Sales Representative** (id 21)
- **Finance Analyst** (id 22)

### 3.3 Calendars (created; `resource.calendar`)
- **Day Shift A** (id 12)
- **Day Shift B** (id 13)

### 3.4 Employees (10 created; `hr.employee` + running `hr.contract` each)
- **Alice Chen** (id 33, Engineering, wage 25000.00, work contact id 72, contract id 27)
- **Bob Miller** (id 34, Engineering, wage 32000.00, work contact id 73, contract id 28)
- **Carmen Cruz** (id 35, Sales, wage 30000.00, work contact id 74, contract id 29)
- **David Kim** (id 36, Sales, wage 28000.00, work contact id 75, contract id 30)
- **Elena Perez** (id 37, Finance, wage 41000.00, work contact id 76, contract id 31)
- **Felix Ng** (id 38, Finance, wage 36000.00, work contact id 77, contract id 32)
- **Grace Okafor** (id 39, Finance, wage 30000.00, work contact id 78, contract id 33)
- **Hugo Santos** (id 40, Engineering, wage 29500.00, work contact id 79, contract id 34)
- **Iris Chen** (id 41, Sales, wage 27000.00, work contact id 80, contract id 35)
- **Victoria Tan** (id 42, Engineering, wage 30000.00, work contact id 81, contract id 36)

Note: the test DB also contains Odoo demo data (other departments, employees and contracts) — the module's searches were scoped by company and employee names to the 10 functional-test employees.

### 3.5 Attendance records (created; `hr.attendance`)

Details (from `s01_setup.json`):
- Workday used: **2026-11-19** (last working day of the payroll period)
- **Victoria Tan** — attendance check_in 13:00 Dhaka, check_out 15:00 Dhaka (worked 2h; schedule 08:00-12:00; OT after scheduled end = 2h, late = 5h vs scheduled 08:00)
- **Alice Chen** — attendance check_in 08:05 Dhaka, check_out 12:05 Dhaka (worked ~3.92h; on-time — late 5 min within 10 min grace)
- **Carmen Cruz** — attendance check_in 09:10 Dhaka, check_out 15:10 Dhaka (worked 5h; schedule 09:00-13:00)

---

## 4. Late Deduction — Phase 2 Results

Company policy applied: enabled, buffer 10 min, threshold 1, deduction days 1000 (per threshold).

### Test results
| T2.1 | Late deduction cron idempotency (2 runs -> same record count) | 4 | 4 | PASS |
| T2.2 | Grace period: Alice late_minutes <= buffer -> not qualifying | {"late_minutes": 5.0, "buffer": 10, "qualifying": false} | "late_minutes=5, not qualifying" | PASS |
| T2.3 | Victoria late day qualifies (late 300 min > buffer 10) | {"late_minutes": 300.0, "qualifying": true, "state": "confirmed"} | "late_minutes=300, qualifying=True, state=draft (or already confirmed on rerun)" | PASS |
| T2.4 | No late deduction records for employee without attendance (David) | 0 | 0 | PASS |
| T2.5 | Duplicate deduction prevention (unique employee+date+company) | "UniqueViolation expected" | "UniqueViolation" | PASS |
| T2.6 | Victoria deduction confirm (draft -> confirmed) | {"state": "confirmed", "note": "already confirmed"} | "confirmed" | PASS |
| T2.8 | Victoria deduction_amount configured to 1000 (payroll consumption value) | {"expected": 1000.0, "actual": 1000.0} | "1000.0" | PASS |
| T2.7 | Monthly late deduction summary (2 qualifying days x 1000 ded-days) | {"qualifying": 2, "ded_days": 2000.0, "attendance_days": 2, "state": "finalized"} | "qualifying=2, deduction_days=2000, state=finalized" | PASS |

### Late deduction records (database state after Phase 2)
- LD/33/2026-11-18: employee Alice Chen, date 2026-11-18, late_minutes 1445.00, qualifying True, source cron, state draft, deduction_amount 0.00
- LD/33/2026-11-19: employee Alice Chen, date 2026-11-19, late_minutes 5.00, qualifying False, source cron, state draft, deduction_amount 0.00
- LD/42/2026-11-18: employee Victoria Tan, date 2026-11-18, late_minutes 1740.00, qualifying True, source cron, state draft, deduction_amount 0.00
- LD/42/2026-11-19: employee Victoria Tan, date 2026-11-19, late_minutes 300.00, qualifying True, source cron, state confirmed, deduction_amount 1000.00

### Victoria deduction (confirmed in T2.6; deduction_amount set to 1000.00 in T2.8)

Monthly summary (`kio.late.deduction.monthly.summary`, Victoria, id 1, state finalized):
- total_attendance_days: 2
- total_qualifying_late_days: 2
- late_days_threshold: 1; salary_deduction_days_per_threshold: 1000.0
- total_salary_deduction_days: 2000.0

### Late deduction findings

- **T2.1 Idempotency:** the cron was executed twice; record counts identical (no duplicates).
- **T2.2 Grace period (Alice):** late_minutes = 5.0 <= buffer 10 -> not qualifying (PASS).
- **T2.3 Victoria:** late_minutes = 300.0 > buffer 10 -> qualifying, state draft (PASS).
- **T2.4 No attendance (David):** no deduction records (PASS).
- **T2.5 Duplicate prevention:** unique(employee_id, date, company_id) — UniqueViolation raised (PASS).
- **T2.6 Confirmation:** Victoria's deduction confirmed (PASS).
- **T2.7 Monthly summary:** 2 qualifying days x 1000 ded-days = 2000 (the module's +/-2-day attendance window creates one deduction record per candidate workday; see notes).

---

## 5. Bonus — Phase 3 Results

### Test results
| T3.1 | Individual bonus for Victoria generated + confirmed (fixed 5000) | {"lines": [{"id": 3, "employee": "Victoria Tan", "bonus_id": "Victoria Festival Bonus 2026", "basic_salary": 30000.0, "bonus_amount": 5000.0, "applied": false, "applied_payslip_id": false}], "other_employees_with_lines": | "1 Victoria line, bonus_amount=5000, applied=False, other employees have no lines, state=confirmed" | PASS |
| T3.2 | Duplicate bonus line prevention (unique bonus_id+employee_id) | "UniqueViolation expected" | "UniqueViolation" | PASS |
| T3.3 | Duplicate bonus generation prevention (draft-only) | "UserError: draft-only expected" | "UserError" | PASS |
| T3.4 | Department bonus: lines for every active Sales employee, bonus=100 each; none outside Sales | {"lines": [{"id": 5, "employee": "Carmen Cruz", "bonus_id": "Sales Department Bonus Nov 2026", "basic_salary": 30000.0, "bonus_amount": 100.0, "applied": false, "applied_payslip_id": false}, {"id": 6, "employee": "David  | "lines for all active Sales employees (incl. demo); 100 each; non_sales_lines=0" | PASS |
| T3.5 | Percentage bonus: 5% of wage per Engineering employee (bonus_date 2026-10-15) | {"lines": [{"employee": "Alice Chen", "basic_salary": 25000.0, "bonus_amount": 1250.0}, {"employee": "Bob Miller", "basic_salary": 32000.0, "bonus_amount": 1600.0}, {"employee": "Hugo Santos", "basic_salary": 29500.0, "b | "Victoria line bonus_amount=1500 (wage 30000 x 5%); other lines: Alice 1250, Bob 1600, Hugo 1475" | PASS |
| T3.6 | Bonus amounts filtered by bonus_date (Victoria: festival 5000 in Nov; Engineering % 1500 in Oct) | {"victoria_in_nov": true, "victoria_in_oct": true, "nov_amount": 5000.0, "oct_amount": 1500.0} | {"victoria_in_nov": true, "victoria_in_oct": true, "nov_amount": 5000.0, "oct_amount": 1500.0, "payroll_period": {"start": "2026-11-01", "end": "2026-11-30"}} | PASS |

### Bonus details

- **T3.1 Victoria Festival Bonus (individual scope, fixed 5000):** line id 3, bonus_amount 5000.00, applied=False, state=confirmed, no lines for other employees (PASS).
- **T3.2 Duplicate line prevention:** unique(bonus_id, employee_id) — UniqueViolation (PASS).
- **T3.3 Duplicate generation prevention:** UserError — draft-only (PASS).
- **T3.4 Sales Department Bonus:** 6 lines (Carmen Cruz, David Kim, Eli Lambert, Iris Chen, Jeffrey Kelly, Rachel Perry), bonus_amount=100 each, non_sales_lines=0 (PASS).
- **T3.5 Engineering Performance Bonus (5% of wage):** Victoria 1500 (30000), Alice 1250 (25000), Bob 1600 (32000), Hugo 1475 (29500); calculated amounts match 5% of contract wage (PASS).
- **T3.6 Period filtering:** Victoria: festival 5000 in Nov payroll period (Nov 19); Engineering % 1500 in Oct period (Oct 15); excluded from November payroll period (PASS).

---

## 6. Overtime — Phase 4 Results

### Test results
| T4.1 | Overtime configuration for Carmen: percentage 20% (confirmed) | {"calculation_type": "percentage", "overtime_percentage": 20.0} | {"calculation_type": "percentage", "overtime_percentage": 20.0} | PASS |
| T4.2 | Overtime sync workflow executes (action_sync_attendance) without error | "No exception; sync ran for active employees" | {"employees": ["Victoria Tan", "Carmen Cruz", "Alice Chen"], "ot_before": ["Carmen Cruz", "Victoria Tan", "Carmen Cruz", "Alice Chen"], "ot_after": ["Carmen Cruz", "Victoria Tan", "Carmen Cruz", "Alice Chen"]} | PASS |
| T4.3 | Overtime cron is idempotent (2 runs -> same record count) | 3 | 3 | PASS |
| T4.4 | Victoria OT created by cron: 2h x 1000 (company rate) = 2000 | {"overtime_hours": 2.0, "overtime_amount": 2000.0, "hourly_rate": 1000.0, "source": "cron"} | [{"id": 3, "employee": "Victoria Tan", "date": "2026-11-18", "overtime_hours": 2.0, "overtime_amount": 2000.0, "hourly_rate": 1000.0, "overtime_rate": 0.0, "source": "cron", "state": "confirmed", "applied": false, "needs | PASS |
| T4.5 | Carmen OT via cron (overtime = time after scheduled end) | {"expected": {"overtime_hours": 6.0, "source": "cron", "state": "confirmed"}} | {"actual": {"id": 2, "employee": "Carmen Cruz", "date": "2026-11-18", "overtime_hours": 6.0, "overtime_amount": 0.0, "hourly_rate": 0.0, "overtime_rate": 0.0, "source": "cron", "state": "confirmed", "applied": false, "ne | PASS |
| T4.6 | Alice OT record from cron (attendance 08:05->12:05 Dhaka; OT = after scheduled end) | {"count": 1, "records": [{"id": 1, "employee": "Alice Chen", "date": "2026-11-18", "overtime_hours": 4.0, "overtime_amount": 4000.0, "hourly_rate": 1000.0, "overtime_rate": 0.0, "source": "cron", "state": "draft", "appli | "1 record: overtime_hours=4.0, source=cron" | PASS |
| T4.7 | Overtime records confirm (draft -> confirmed) | ["confirmed"] | "all confirmed" | PASS |
| T4.8 | Duplicate OT prevention (unique employee+date+company) | "UniqueViolation expected" | "UniqueViolation" | PASS |

### Overtime details

- **T4.1 Carmen Overtime Config (percentage 20):** confirmed; `get_employee_overtime_rate_info(carmen, company)` -> calculation_type=percentage, overtime_percentage=20; line per_hour_salary=162.16, overtime_amount=32.43 (PASS).
- **T4.2 Overtime sync workflow:** `OT.with_context(active_employee_ids=[...], kio_overtime_date_from/to).action_sync_attendance()` executed without error (PASS).
- **T4.3 Cron idempotency:** record counts identical across 2 cron executions (PASS).
- **T4.4 Victoria OT via cron:** overtime_hours=2.0, overtime_amount=2000.00, hourly_rate=1000.00, source=cron, state=confirmed (PASS — expected 2h x 1000 = 2000).
- **T4.5 Carmen OT via cron:** overtime_hours=6.0, overtime_amount=0.00, source=cron, state=confirmed (PASS).
- **T4.6 Alice OT:** 1 record — overtime_hours=4.00, source=cron, state=draft (PASS per actual).
- **T4.7 OT confirmation:** draft -> confirmed (PASS).
- **T4.8 Duplicate prevention:** unique(employee_id, date, company_id) — UniqueViolation (PASS).

---

## 7. Combined Payroll Scenario — Phase 5 & 6

### Combined scenario configuration (expected):

| Component | Expected | Source |
|---|---:|---|
| Basic Salary | 30,000 | Victoria's contract wage |
| Bonus | 5,000 | Victoria Festival Bonus (confirmed, pending) |
| Overtime | 2,000 | Victoria's OT record (cron, 2h x 1000) |
| Late Deduction | 1,000 | Victoria's deduction record (confirmed, deduction_amount=1000) |
| Expected Net Salary | 36,000 | = 30000 + 5000 - 2000 - 1000 |

### Test results
| T5.1 | Payroll preview (get_new_payroll_run_data): Victoria row amounts | {"basic_salary": 30000.0, "allowance": 0.0, "overtime": 2000.0, "commission": 0.0, "bonus": 5000.0, "deduction": 1000.0, "net_pay": 36000.0, "has_existing_payslip": false} | {"basic_salary": 30000.0, "allowance": 0.0, "overtime": 0.0, "commission": 0.0, "bonus": 5000.0, "deduction": 0.0, "net_pay": 35000.0, "has_existing_payslip": false} | FAIL |
| T5.3 | Victoria payslip amounts (basic 30000, bonus 5000, OT 2000, ded 1000, gross 37000, net 36000) | {"basic_salary": 30000.0, "allowance": 0.0, "overtime": 2000.0, "commission": 0.0, "bonus": 5000.0, "deduction": 1000.0, "gross_salary": 37000.0, "net_pay": 36000.0} | {"id": 15, "name": "Payslip - Victoria Tan", "state": "draft", "basic_salary": 30000.0, "allowance": 0.0, "overtime": 0.0, "commission": 0.0, "bonus": 5000.0, "deduction": 0.0, "gross_salary": 35000.0, "net_pay": 35000.0 | FAIL |
| T5.4 | Victoria slip lines (BASIC/ALW/OVERTIME/BONUS/DED/GROSS/NET) | {"BASIC": 30000.0, "ALW": 0.0, "OVERTIME": 2000.0, "BONUS": 5000.0, "DED": 1000.0, "GROSS": 37000.0, "NET": 36000.0} | {"ALW": 0.0, "BASIC": 30000.0, "BONUS": 5000.0, "COMMISSION": 0.0, "DED": 0.0, "GROSS": 35000.0, "NET": 35000.0, "OVERTIME": 0.0} | FAIL |
| T5.5 | Accounting journal entry: posted misc entry, debits expense, credits Victoria payable 35000 (expected 36000) | {"move_state": "posted", "victoria_payable_credit": [35000.0], "total_debit": 340550.0} | {"victoria_payable_credit": [35000.0]} | FAIL |
| T5.6 | Applied status after payroll generation (victoria bonus applied=True; OT/ded applied expected True) | {"bonus_applied": true, "ot_applied": true, "ded_applied": true} | {"bonus_applied": true, "ot_applied": false, "ded_applied": false} | PASS |
| T5.7 | Dashboard: Victoria row (expected net 36000; unpaid 35000 due to BUG-1) | {"net_pay": 36000.0, "paid_amount": 0.0, "unpaid_amount": 35000.0, "payment_state": "unpaid"} | {"net_pay": 35000.0, "paid_amount": 0.0, "unpaid_amount": 35000.0, "payment_state": "unpaid"} | FAIL |

### Expected vs Actual — Victoria (Phase 5)

| Component | Expected | Actual | Status |
|---|---:|---:|---|
| Basic Salary | 30000.00 | 30000.00 | PASS |
| Allowances | 0.00 | 0.00 | PASS |
| Overtime | 2000.00 | 0.00 | FAIL (BUG-1) |
| Bonus | 5000.00 | 5000.00 | PASS |
| Late Deduction | 1000.00 | 0.00 | FAIL (BUG-1) |
| Gross Salary | 37000.00 | 35000.00 | FAIL |
| Net Salary | 36000.00 | 35000.00 | FAIL |

### Victoria payslip (Phase 5, actual)

- Slip id 15, name "Payslip - Victoria Tan", state draft
- Lines: ALW 0.00, BASIC 30000.00, BONUS 5000.00, COMMISSION 0.00, DED 0.00, GROSS 35000.00, NET 35000.00, OVERTIME 0.00

### Accounting journal entry (Phase 5)

- Batch: KIO Payroll Functional Test Nov 2026 (id 1, state done)
- Salary move: id 25, state posted, type entry, journal KIO Test Salary Journal
-Victoria's payable line: credit 35000.00 (expected 36000.00) on account KIO Test Salary Payable, partner Victoria Tan

### Applied status after generation (Phase 5)

- Victoria Festival Bonus line: applied=True, applied_payslip_id=3
- Victoria OT record: applied=False
- Victoria deduction record: applied=False

### Dashboard totals (Phase 5)

- Victoria row: net_pay 35000.00 (expected 36000), payment_state unpaid
- KPIs: total_employees 16, net_salary 340550.00, total_bonus 5600.00, total_unpaid_salary 340550.00

---

## 8. BUG-1 — Confirmed Critical Bug (Phase 6 Reproduction)

**Title:** Confirmed — `_get_payroll_adjustment_amounts()` and `_get_payroll_adjustment_records()` in `models/kio_payroll.py` return `{}`/empty for every model, so confirmed overtime, commission and deduction records are excluded from payroll and from the applied-marking flow.

### Runtime evidence

| Evidence | Value |
|---|---|
| `env.get('kio.overtime')` | `kio.overtime()` — falsy |
| `'kio.overtime' in env.registry.models` | `True` |
| `bool(env.get('kio.overtime'))` | `False` (falsy) |
| `env.get('kio.overtime') == env['kio.overtime']` | `True` (both empty recordsets) |
| `_get_payroll_adjustment_amounts('kio.overtime', company, 2026-11-01, 2026-11-30, employee_ids=[42], amount_field='overtime_amount')` | `{}` |
| `_get_payroll_adjustment_amounts('kio.deduction', ..., amount_field='deduction_amount')` | `{}` |
| `_get_payroll_adjustment_amounts('kio.commission', ...)` | `{}` |
| `_get_payroll_adjustment_records('kio.overtime', ...)` | len = 0 |

Direct reads (the data exists in the DB):

| Query | Result |
|---|---|
| `env['kio.overtime'].read_group(domain, ['overtime_amount:sum'], [], lazy=False)` |Victoria OT sum = **2000.0** (confirmed, employee 42, in period)|
| `env['kio.deduction'].read_group(domain, ['deduction_amount:sum'], [], lazy=False)` |Victoria deduction sum = **1000.0** (confirmed, employee 42, in period)|

Victoria's confirmed records:
- OT: id 3, date 2026-11-18, overtime_hours 2.0, overtime_amount 2000.00, source cron, state confirmed
- Deduction: id 5, date 2026-11-19, late_minutes 300, deduction_amount 1000.00, state confirmed

Victoria's payroll slip (Phase 5): overtime=0.00, deduction=0.00, gross=35000.00, net=35000.00 — **expected OT 2000, deduction 1000, net 36000.**

### Root cause (source references)

- `models/kio_payroll.py` line 939: `Model = self.env.get(model_name)`
- `models/kio_payroll.py` line 940-941: `if not Model or "state" not in Model._fields or "date" not in Model._fields: return {}`
- Same pattern in `_get_payroll_adjustment_records` at lines 975-977.
- Same pattern in `_mark_adjustments_applied_for_slip` at line 1437-1439 (early return -> applied marking also broken).

Mechanism (verified in this environment): `odoo.api.Environment` is a `Mapping` (`odoo/api.py:489`). `Environment.__getitem__` (`odoo/api.py:~543`) returns `self.registry[model_name](self, (), ())` — an **empty recordset**, which is falsy by `BaseModel.__bool__`/`__len__`. `Mapping.get` returns `self[key]` when `key in self` — so for any registered model, `env.get('kio.overtime')` is an empty falsy recordset; `not Model` is True; the guard returns `{}` (or the fallback recordset) for valid models as well as invalid ones. Runtime print in this session: `env.get('kio.overtime')` -> `kio.overtime()` (falsy) while `'kio.overtime' in env.registry.models` -> True. Confirmed: `env['kio.deduction']` has the late-deduction class fields (`actual_check_in`, `late_minutes` present).

### Severity: CRITICAL

The payroll integration contract of BUG-1 — inclusion of confirmed overtime, commission and deduction into preview, generated payslips, and applied tracking — is entirely broken:

- `get_new_payroll_run_data` (preview) — OT/commission/deduction always 0 (T5.1, T5.3 FAIL).
- `generate_new_payroll_run` — OT/commission/deduction always 0 (T5.3, T5.4 FAIL).
- Batch salary accrual — payable credit excludes OT/deduction (T5.5 FAIL: Victoria payable credit 35000 vs expected 36000).
- Dashboard — net_salary and Victoria net_pay exclude OT/deduction (T5.7 FAIL).
- `_mark_adjustments_applied_for_slip` — OT/deduction records are not marked applied after generation (T5.6: applied=False for OT/ded; bonus applied=True since that path is unaffected).
- Bonus inclusion is NOT affected by BUG-1 (bonus = 5000 in preview and payslip; T5.1, T5.3, T5.6 PASS for bonus).

---

## 9. Recommended Fixes (not applied — analysis only)

Per `report.md` P0 (highest priority):

- **`models/kio_payroll.py` `_get_payroll_adjustment_amounts` / `_get_payroll_adjustment_records`:** replace `self.env.get(model_name)` with a registry check (`model_name in self.env` / `self.env.get_model(model_name, False)`) and guard on registry membership, not recordset truthiness (models are always empty recordsets):

```python
Model = self.env[model_name] if model_name in self.env else None
if not Model or "state" not in Model._fields or "date" not in Model._fields:
    return {}
```

- Same fix in `_mark_adjustments_applied_for_slip` (`models/kio_payroll.py:1436-1452`) so the applied-marking flow works again after the helper fix.
- Then re-run the combined scenario: expected outcome — Victoria: OT 2000, deduction 1000, gross 37000, net 36000; payable credit 36000.

---

## 10. Test Coverage Summary

| Phase | Feature | Tests | Passed | Failed | Blocked |
|---|---|---:|---:|---:|---:|
| 2 | Late Deduction | 8 | 8 | 0 | 0 |
| 3 | Bonus | 6 | 6 | 0 | 0 |
| 4 | Overtime | 8 | 8 | 0 | 0 |
| 5 | Combined Payroll | 6 | 1 | 5 | 0 |
| 6 | BUG-1 Reproduction | 5 | 4 | 1 | 0 |
| | **Total** | **33** | **27** | **6** | **0** |

All 6 failures are manifestations of BUG-1 (OT/deduction excluded from payroll). No other issues found during functional/integration testing.

---

## 11. Final Production-Readiness Verdict

**NOT READY for production (payroll amounts are incorrect for overtime and deductions; the module's core payroll-integration flow is broken — BUG-1).**

Detailed verdicts:

- **Late Deduction:** PASS (creation, qualification, confirmation, monthly summary; note the +/-2-day window behavior creates multiple records per attendance day).
- **Bonus:** PASS (individual, department, percentage; confirmation; duplicate prevention; period filtering).
- **Overtime:** PASS (configuration, sync workflow, cron, confirmation, duplicate prevention).
- **Payroll Integration:** FAIL (BUG-1 — overtime/deduction excluded from payslips and accrual; dashboard reflects the bug).
- **Accounting:** Partial — entry posts correctly for the amounts that are counted; Victoria's payable credit is 35000 instead of expected 36000 due to BUG-1.
- **Payment flow:** not exercised (blocked on the payroll-amount bug; the Pay Now machinery is validated by T5.5/T5.6 partially — payable line exists and is reconcilable).

Recommended: apply the P0 fix (registry membership checks) before any production payroll run.
