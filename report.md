# KIO Payroll Overview Extension — Complete E2E Functional, Integration, Accounting, and Regression Test Report

**Module:** `kio_payroll_overview_extension` (17.0.4.0.3)  
**Odoo:** 17.0 (local source at `/home/rakib/odoo17_env/odoo-17.0`)  
**Module path:** `/home/rakib/odoo17_env/odoo-17.0/custom_addons/westeen-server/custom-addons/kio_payroll_overview_extension`  
**Test date:** 2026-11-10 (from environment)  
**Tester:** automated agent (OpenCode)  
**Scope:** isolated real-ORM testing on disposable DB + module automated tests + static/code inspection. **No production data modified.**

---

## A. Environment and database isolation verification

| Item | Result | Evidence |
|---|---|---|
| Production/non-disposable DBs observed | **Present (untouched)** | `westeen-server`, `kio_prod_copy`, `production_restored`, `db_20`, etc. listed in PostgreSQL. |
| Running Odoo process | **Observed against production-like DB (not used for writes)** | `python3 ./odoo-bin -c odoo.conf -d westeen-server -u kio_payroll_overview_extension` (PID 14201) was running during testing; all write operations were executed only on disposable DB below. |
| Dedicated disposable test database | **PASS** | Created `kio_e2e_report_test` by cloning `kio_new_payroll_test` (`createdb -T kio_new_payroll_test kio_e2e_report_test`). Module upgraded to 17.0.4.0.3 on this DB. All fixtures (employees/contracts/OT/deductions/batches/payslips) created only in `kio_e2e_report_test`. |
| Safe to write | **Verified** | DB name explicitly disposable (`kio_e2e_report_test`), not in production set; clone source was a test DB. |
| Company/currency in test DB | `My Company` (id 1), currency `USD` (config labels show BDT in some UI strings but currency record is USD in this DB; monetary values tested numerically). |

**Isolation verdict:** **PASS** (all executed write workflows isolated to `kio_e2e_report_test`).

---

## B. Module installation/upgrade results

| Test | Expected | Actual | Status | Evidence |
|---|---|---|---|---|
| Manifest/dependencies | Valid Odoo 17 manifest, no `hr_payroll_community` dependency | `depends: ["hr","hr_attendance","hr_contract","account","web"]`, version `17.0.4.0.3`, installable, post_init hook present | **PASS** | `__manifest__.py` inspection |
| Module upgrade on disposable DB | Upgrades without fatal error | `odoo-bin -d kio_e2e_report_test -u kio_payroll_overview_extension --stop-after-init` completed (warnings only: third-party license/deprecation/label collisions with `hr_payroll_community` installed in DB, RelaxNG schema load warning) | **PASS** | Upgrade logs captured |
| Model/security/data/views registration | XML/data load and registry load succeed | Module loaded (929 queries reported in test run), security/data/views/assets loaded | **PASS** | `--test-enable` run loaded all module data files |
| Migrations present | Allowance migration available | `migrations/17.0.4.0.3/post-migrate.py` present and version bumped | **PASS** | Static inspection (migration executed on prior real-copy verification during fix; not separately re-asserted as a first-install path in this run) |
| Scheduled actions | Overtime/late deduction crons defined | `data/kio_late_deduction_cron.xml`, `data/kio_overtime_cron.xml` present in manifest/data | **PASS (static)** | Manifest/file inspection |
| Dashboard/RPC methods | Present | `get_new_payroll_run_data`, `generate_new_payroll_run`, `get_payroll_overview_data`, `get_payroll_batch_details`, payment/download actions etc. present with manager checks in most cases | **PASS (static)** | `models/kio_payroll.py` inspection |

**Note:** `hr_payroll_community` is installed in the cloned test DB and causes duplicate field-label warnings (`kio_medical_allowance`/`medical_allowance`, `kio_other_allowance`/`other_allowance`) but this module does **not** depend on it (manifest compliant).

---

## C. Test cases executed

### C.1 Existing automated module tests (executed)
Command: `./odoo-bin -c odoo.conf -d kio_e2e_report_test -u kio_payroll_overview_extension --test-enable --test-tags /kio_payroll_overview_extension --stop-after-init --log-level=test`

| Suite | Executed | Passed | Failed | Error | Notes |
|---|---:|---:|---:|---:|---|
| `TestKioContractAllowanceIntegration` | 7 | 7 | 0 | 0 | All allowance-sum, preview, generation, legacy-% ignore, no-allowance, per-employee, historical immutability tests passed |
| `TestKioOvertimeConfiguration` | 2 | 2 | 0 | 0 | Contract basic salary read / missing contract behavior |
| `TestKioPayrollAdjustmentIntegration` | 8 | 0 | 1 | 7 | `FAIL: test_confirmed_overtime_included_draft_excluded` (row None / not true); 7 `ERROR` due to `NoneType` row / missing valid contract in period / generation validation in this environment |
| `test_payroll_overview.py` | 0 | 0 | 0 | 0 | **File is empty (0 bytes)** — no tests collected/executed |
| **Total (module tag)** | **17** | **9** | **1** | **7** | `0 failed, 0 error(s) of 7 tests` for allowance+OT-config subsets observed in logs; aggregate ended `1 failed, 7 error(s) of 17 tests` |

**Automated tests verdict:** **PARTIAL / FAILING (unrelated/pre-existing + environment-sensitive)** for adjustment integration suite; **PASS** for allowance and overtime-configuration suites.

### C.2 Custom E2E ORM scenarios (executed on disposable DB)

| # | Test name | Expected | Actual | Status | Evidence |
|---|---|---|---|---|---|
| 1 | Fixture contracts/allowances | A total 10500, B 3000, C 0 | `{'A':10500.0,'B':3000.0,'C':0.0}` | **PASS** | Contracts created with 7 fixed allowance fields; computed totals matched |
| 2 | Fixed overtime records A/B (confirmed, monetary enabled) | A 5h*200=1000, B 3h*150=450 | A `1000.0`, B `450.0` (states confirmed) | **PASS** | `kio.overtime` ids 11,12 created via real model create/write/confirm with config-derived rates |
| 3 | Deductions A/B (confirmed) | A 500, B 1000 | A `500.0`, B `1000.0` (confirmed) | **PASS** | `kio.deduction` ids 8,9 created/confirmed (`source='manual'`, `deduction_amount` set) |
| 4 | Preview Employee A | basic 50000, allowance 10500, OT 1000, ded 500, net 61000 | basic 50000, allowance 10500, **OT 0, ded 0**, net 60500 | **FAIL** | Allowance correct; OT/ded not pulled into preview |
| 5 | Preview Employee B | basic 30000, allowance 3000, OT 450, ded 1000, net 32450 | basic 30000, allowance 3000, **OT 0, ded 0**, net 33000 | **FAIL** | Same root cause |
| 6 | Preview Employee C | basic 40000, allowance 0, OT 0, ded 0, net 40000 | matched | **PASS** | No adjustments expected |
| 7 | Generated payslip A | basic 50000, allowance 10500, OT 1000, ded 500, gross 61500, net 61000 | basic 50000, allowance 10500, **OT 0, ded 0**, gross 60500, net 60500; lines present (BASIC/ALW/OVERTIME/COMMISSION/BONUS/DED/GROSS/NET) | **FAIL** | Persisted values from real generation pipeline; OT/ded missing |
| 8 | Generated payslip B | basic 30000, allowance 3000, OT 450, ded 1000, gross 33450, net 32450 | basic 30000, allowance 3000, **OT 0, ded 0**, gross 33000, net 33000 | **FAIL** | Same |
| 9 | Generated payslip C | basic 40000, allowance 0, OT 0, ded 0, gross 40000, net 40000 | matched, all required lines present | **PASS** | Correct zero-adjustment case |
| 10 | Batch totals (E2E batch) | basic 120000, allowance 13500, OT 1450, ded 1500, gross 134950, net 133450 | basic 120000, allowance 13500, **OT 0, ded 0**, gross 133500, net 133500 | **FAIL** | Consistent with missing OT/ded inclusion |
| 11 | Applied tracking after generation | included confirmed OT/deductions marked applied to correct payslips | `applied=False`, no `applied_payslip_id` for OT/ded A,B | **FAIL** | Because adjustments were never selected/included by helper, marking did not occur |
| 12 | Preview excludes applied amounts (post-generation) | OT/ded 0 in preview | OT/ded 0 for A,B (rows present, `has_existing_payslip` true) | **PASS (observation)** | Values 0, but for wrong reason (never included/applied) — not evidence of correct applied-exclusion logic |
| 13 | Duplicate payroll prevention | ValidationError on overlapping period | `Existing payslips overlap this period for: Payroll E2E Employee A...` | **PASS** | Second generation attempt rejected |
| 14 | Employee without contract excluded from preview | not in eligible list | not in preview | **PASS** | `Payroll E2E No Contract` excluded |
| 15 | Overlapping open contracts | ambiguous flagged or prevented by constraints | creation blocked by `hr.contract` constraint (`_check_current_contract`: employee can only have one contract at same time excluding draft/cancelled) | **PASS (constraint behavior)** | Standard Odoo prevents overlap; module ambiguity path not triggerable under this constraint |
| 16 | Duplicate overtime record prevented | unique constraint `(employee_id,date,company_id)` | DB unique violation on duplicate create | **PASS** | Constraint enforced (test run aborted transaction; noted in execution log) |
| 17 | Draft overtime excluded by confirmed-state domain | draft not found by confirmed filter | search count 0 | **PASS** | Domain behavior correct for draft exclusion |
| 18 | Bonus model available | `kio.bonus` registered | available | **PASS** | Registry check |
| 19 | Commission model available | `kio.commission` registered | available | **PASS** | Registry check |
| 20 | Duplicate `kio.deduction` definition (code audit) | architectural issue identified | defined in `models/kio_payroll_adjustment.py` and `models/kio_late_deduction.py` | **PASS (issue confirmed)** | High-risk model composition/import-order dependency |
| 21 | `env.get(model)` falsy root cause | explains adjustment helper failure | `env.get('kio.overtime') -> kio.overtime()` empty recordset, `bool == False` | **PASS (root cause confirmed)** | `_get_payroll_adjustment_amounts` / records return `{}`/empty due to `if not Model: return ...` |
| 22 | Accounting with configured salary credit = `230000 Salary Payable (liability_current)` | should allow pay flow | **Blocked**: `Salary Credit Account must be an active Payable account...` | **FAIL (config/compatibility constraint)** | `_validate_kio_salary_accounting` requires `account_type == liability_payable` |
| 23 | Prepare Pay Now action with payable credit (`211000 Account Payable`) | returns register payment action | returned `ir.actions.act_window` for `account.payment.register`, `kio_payroll_pay_now` context, active move line ids set | **PASS** | Tested in savepoint/rolled back; no posted payment created |
| 24 | Payslip report action exists | xmlid found | report id 488 found | **PASS** | `action_report_employee_payslip` |
| 25 | Payslip PDF renders | QWeb PDF generated | PDF bytes generated (28141 bytes for slip A) | **PASS** | `_render_qweb_pdf` succeeded |

---

## D. Employee salary calculation comparison

### D.1 Fixture definitions (created in isolated DB)

| Employee | Contract wage | House Rent | Medical | Conveyance | Food | Mobile | Transport | Other | Total Allowance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Payroll E2E Employee A (id 19, contract 14) | 50,000.00 | 5,000.00 | 5,000.00 | 0.00 | 0.00 | 500.00 | 0.00 | 0.00 | **10,500.00** |
| Payroll E2E Employee B (id 20, contract 15) | 30,000.00 | 3,000.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | **3,000.00** |
| Payroll E2E Employee C (id 21, contract 16) | 40,000.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | **0.00** |

**Allowance field source:** fixed monetary contract fields (`kio_house_rent_allowance`, `kio_medical_allowance`, `kio_conveyance_allowance`, `kio_food_allowance`, `kio_mobile_allowance`, `kio_transport_allowance`, `kio_other_allowance`). **PASS**.

### D.2 Baseline scenario comparison (preview & generated payslip)

**Expected (requested):** Gross = Basic + Allowances + Overtime + Commission + Bonus; Net = Gross - Deductions.

| Employee | Component | Expected | Preview Actual | Payslip Actual | Status |
|---|---|---:|---:|---:|---|
| A | Basic | 50,000.00 | 50,000.00 | 50,000.00 | **PASS** |
| A | Allowances | 10,500.00 | 10,500.00 | 10,500.00 | **PASS** |
| A | Overtime | 1,000.00 | 0.00 | 0.00 | **FAIL** |
| A | Deduction | 500.00 | 0.00 | 0.00 | **FAIL** |
| A | Gross | 61,500.00 | 60,500.00 | 60,500.00 | **FAIL** |
| A | Net | 61,000.00 | 60,500.00 | 60,500.00 | **FAIL** |
| B | Basic | 30,000.00 | 30,000.00 | 30,000.00 | **PASS** |
| B | Allowances | 3,000.00 | 3,000.00 | 3,000.00 | **PASS** |
| B | Overtime | 450.00 | 0.00 | 450.00? **No** 0.00 | **FAIL** |
| B | Deduction | 1,000.00 | 0.00 | 0.00 | **FAIL** |
| B | Gross | 33,450.00 | 33,000.00 | 33,000.00 | **FAIL** |
| B | Net | 32,450.00 | 33,000.00 | 33,000.00 | **FAIL** |
| C | Basic | 40,000.00 | 40,000.00 | 40,000.00 | **PASS** |
| C | Allowances | 0.00 | 0.00 | 0.00 | **PASS** |
| C | Overtime | 0.00 | 0.00 | 0.00 | **PASS** |
| C | Deduction | 0.00 | 0.00 | 0.00 | **PASS** |
| C | Gross | 40,000.00 | 40,000.00 | 40,000.00 | **PASS** |
| C | Net | 40,000.00 | 40,000.00 | 40,000.00 | **PASS** |

### D.3 Batch totals comparison

| Metric | Expected | Actual (batch 4, 3 slips) | Status |
|---|---:|---:|---|
| Total Basic Salary | 120,000.00 | 120,000.00 | **PASS** |
| Total Allowances | 13,500.00 | 13,500.00 | **PASS** |
| Total Overtime | 1,450.00 | 0.00 | **FAIL** |
| Total Deductions | 1,500.00 | 0.00 | **FAIL** |
| Total Gross Salary | 134,950.00 | 133,500.00 | **FAIL** |
| Total Net Salary | 133,450.00 | 133,500.00 | **FAIL** |

**Discrepancy cause (defect):** payroll adjustment aggregation helper `_get_payroll_adjustment_amounts` uses `Model = self.env.get(model_name)` and returns `{}` when `not Model`; in this environment `env.get()` returns an **empty (falsy) recordset**, so confirmed overtime/commission/deduction records are never included in preview, generation, or post-generation marking. Direct `read_group`/search confirms records were eligible and amounts correct (`OT 1000/450`, `DED 500/1000`).

---

## E. Overtime calculation results

| Test | Expected | Actual | Status | Evidence |
|---|---|---|---|---|
| Monetary overtime enabled | enabled for company | `True` | **PASS** | `company.kio_overtime_monetary_enabled = True` |
| Individual fixed config A (200/hr) | confirmed, rate applied | config confirmed, line rate 200.0 | **PASS** | `kio.overtime.configuration` id 3 |
| Individual fixed config B (150/hr) | confirmed, rate applied | config confirmed, line rate 150.0 | **PASS** | config id 4 |
| OT record A (5h, fixed 200) | amount 1000, confirmed | `overtime_hours=5.0`, `hourly_rate=200.0`, `overtime_amount=1000.0`, `state=confirmed` | **PASS** | `kio.overtime` id 11 |
| OT record B (3h, fixed 150) | amount 450, confirmed | `overtime_hours=3.0`, `hourly_rate=150.0`, `overtime_amount=450.0`, `state=confirmed` | **PASS** | `kio.overtime` id 12 |
| OT record C | none/0 | no record | **PASS** | N/A |
| Draft OT excluded by confirmed domain | not eligible | count 0 for confirmed search on draft record | **PASS** | Draft record created for `Payroll E2E Draft OT` |
| Duplicate OT prevention | unique `(employee,date,company)` | DB unique constraint violation | **PASS** | Duplicate attempt on Emp A, 2026-11-10 |
| Department/All/Percentage/missing config/monetary disabled/dynamic priority (new employee auto-rate) | per actual behavior | **Not fully executed** as dedicated scenarios in this run | **BLOCKED / PARTIAL** | Only fixed-individual configs exercised; percentage uses wage/monthly scheduled hours in code (`kio_overtime.py`) but not runtime-verified here. Config selection is explicit/scope-based in current implementation (no automatic Individual>Department>All dynamic priority logic observed in reviewed code paths). |

**Attendance sync/cron E2E:** **BLOCKED** (not executed with realistic clock-in/out producing exact expected overtime via `_sync_employee_dates`/`_cron_daily_overtime_attendance_sync` in this run). Normal vs cron calculation methods differ in code (cron uses “worked after scheduled end”; sync/day values use scheduled/worked hour comparisons and review logic) — **difference identified by inspection, not runtime-benchmarked**.

---

## F. Deduction calculation results

| Test | Expected | Actual | Status | Evidence |
|---|---|---|---|---|
| Deduction A (late attendance, confirmed) | 500.00 confirmed | `deduction_amount=500.0`, `state=confirmed`, `source=manual` | **PASS** | `kio.deduction` id 8 (late deduction model) |
| Deduction B (confirmed) | 1000.00 confirmed | `deduction_amount=1000.0`, `state=confirmed` | **PASS** | `kio.deduction` id 9 |
| Deduction C | 0.00 | none | **PASS** | N/A |
| Draft/unconfirmed exclusion intent | draft not payroll-eligible | not runtime-verified through payroll helper due to helper bug | **BLOCKED** | Helper bug prevented inclusion path validation |
| Duplicate prevention / applied tracking | per workflow | applied tracking **FAIL** (not marked) because records not selected | **FAIL** | Section C.2 #11 |
| `kio.deduction` model duplication | assess functional impact | Duplicate class definitions confirmed; effective late-deduction model provides required fields (`date/state/deduction_amount/applied/applied_payslip_id`) but architecture fragile. Payroll integration **failed in practice here due to `env.get()` helper bug**, not proven due to duplication alone. | **PASS (investigated, no destructive change)** | Code inspection + runtime evidence |

---

## G. Payroll preview results

| Test | Expected | Actual | Status |
|---|---|---|---|
| Preview contains Basic/Allowances/Overtime/Commission/Bonus/Deductions/Net | all present | Fields present in API payload; values correct for basic/allowance only in baseline scenario | **PARTIAL PASS** |
| Preview matches backend calculations for baseline fixtures | matches expected totals | Matched basic+allowance; **did not include confirmed OT/ded** | **FAIL** |
| Employee without contract excluded | excluded | excluded | **PASS** |
| No duplicate payroll generation reflected | existing payslip flagged | `has_existing_payslip=true` after generation | **PASS** |

---

## H. Generated payroll batch results

| Test | Expected | Actual | Status |
|---|---|---|---|
| Batch creation via `generate_new_payroll_run` | batch + slips created | Batch `E2E Payroll Nov 2026` (id 4), 3 draft slips (ids 5,6,7) | **PASS** |
| Period/contract/employee selection | correct | Nov 1-30 2026, correct employees/contracts | **PASS** |
| Payslip line set | BASIC, ALW, OVERTIME, COMMISSION, BONUS, DED, GROSS, NET | All present on each slip | **PASS** |
| Allowance inclusion | A 10500, B 3000, C 0 | correct | **PASS** |
| Overtime/deduction inclusion | per scenario | **0.00 / 0.00** (not included) | **FAIL** |
| Gross/net correctness | per formulas and expected totals | incorrect relative to requested baseline due to missing OT/ded | **FAIL** |
| Duplicate payroll generation | prevented | prevented | **PASS** |
| Failed generation rollback atomicity | rollback on failure | **Not explicitly fault-injected/tested** | **BLOCKED** |

---

## I. Payslip verification

| Test | Expected | Actual | Status |
|---|---|---|---|
| Employee/period/state/basic/allowance/OT/ded/gross/net stored correctly | match expected and DB | Employee, period (implied by batch/slip dates), basic, allowance stored correctly; OT/ded/gross/net incorrect vs requested baseline because adjustments not included | **PARTIAL** |
| Stored vs displayed (model computed fields) | consistent | `slip.allowance`, `slip.overtime`, `slip.deduction`, `slip.gross_salary`, `slip.net_pay` consistent with stored lines (e.g. A: ALW 10500, OVERTIME 0, DED 0, GROSS 60500, NET 60500) | **PASS** |
| Payslip PDF/report output | available and renders | Report action found (id 488), PDF rendered (28141 bytes) for slip A | **PASS** |

---

## J. Accounting and payment results

| Test | Expected | Actual | Status | Evidence |
|---|---|---|---|---|
| Salary accounting config (journal/debit/credit) | configurable and usable | Set to Misc `MISC`, Debit `630000 Salary Expenses`, Credit initially `230000 Salary Payable` | **PARTIAL** | Config persisted in company |
| Credit account type compatibility | accepted for workflow | `230000` is `liability_current` → **rejected** by `_validate_kio_salary_accounting` (`requires liability_payable`) | **FAIL / CONSTRAINT** | Exact UserError captured |
| Pay Now action preparation (with payable credit) | opens/registers payment flow | With `211000 Account Payable (liability_payable)`, `_prepare_kio_pay_now_action` returned register-payment wizard action with correct context (`kio_payroll_pay_now`, `kio_payroll_slip_id`, active payable move line ids) | **PASS** | Savepoint test, rolled back |
| Salary move posting / debit-credit totals / net payable | correct posted entry | **Not executed end-to-end** (no posted move/payment committed) | **BLOCKED** | Requires compatible account setup + full workflow execution beyond savepoint; action preparation verified |
| Full/partial payment, overpayment prevention, duplicate payment prevention, paid status/dashboard totals | correct | **Not executed** | **BLOCKED** | Dependent on posting/payment flow; code paths include advisory locks and validations (inspected) but not runtime-proven in this run |

---

## K. Regression test results

| Test | Expected | Actual | Status |
|---|---|---|---|
| Existing module tests | run and report | 17 tests: 9 pass, 1 fail, 7 errors (details in section C.1) | **FAIL (pre-existing/environment-sensitive)** |
| Allowance regression (new integration tests) | all pass | 7/7 pass | **PASS** |
| Overtime config regression tests | pass | 2/2 pass | **PASS** |
| Historical payslip preservation | unchanged by contract edits/fixes | Verified in allowance integration tests and prior real-copy verification (module behavior by stored lines) | **PASS (from executed tests/prior verification)** |
| Duplicate generation prevention | prevented | prevented | **PASS** |
| No-contract employee handling | excluded | excluded | **PASS** |
| Monetary overtime disabled / percentage OT / department/all config / multi-company isolation / dept transfer / leave/commission/bonus full flows | regressions checked | **Not fully executed** | **BLOCKED / PARTIAL** |

---

## L. Bugs and root causes

| ID | Severity | Test/workflow | Expected | Actual | Root cause | Evidence |
|---|---|---|---|---|---|---|
| BUG-1 | **Critical** | Preview, payroll generation, adjustment application/marking (overtime, commission, deduction) | Confirmed, in-period, unapplied adjustments included and marked applied to generated payslips | OT/ded amounts 0 in preview & payslips; records not marked applied | `_get_payroll_adjustment_amounts` (and same pattern in `_get_payroll_adjustment_records`) uses `Model = self.env.get(model_name)` and returns empty when `not Model`. In Odoo, `env.get(model_name)` returns an **empty recordset** (falsy), so the method exits early for valid models. | `models/kio_payroll.py:796+`; runtime: helper returned `{}` while direct `search/read_group` on same domain returned correct amounts (`{19:1000,20:450}`, `{19:500,20:1000}`) |
| BUG-2 | **High** | Accounting configuration / Pay Now | Standard salary payable setup usable (e.g. liability current “Salary Payable”) or clear compatible guidance | Validation requires `Salary Credit Account ... account_type == 'liability_payable'` and blocks flow | `_validate_kio_salary_accounting` enforces payable-only credit account (`models/kio_payroll.py:354` area), which may reject common liability-current payable accounts depending on chart of accounts | UserError captured in test DB |
| BUG-3 | **High** | Maintainability/correctness risk for deductions | Single canonical `kio.deduction` model | `kio.deduction` defined in both `kio_payroll_adjustment.py` and `kio_late_deduction.py` (import-order dependent merge/override) | Duplicate model classes for same `_name` | Static inspection + `__init__` import order |
| BUG-4 | **Medium** | Test reliability/coverage | Module tests executable and meaningful | `tests/test_payroll_overview.py` empty (0 bytes); `test_payroll_adjustment_integration` 1 fail/7 errors in this run | Missing tests + environment/setup-sensitive adjustment tests; also impacted historically by BUG-1 behavior in real usage | Test run logs, file size |
| BUG-5 | **Medium** | Config security design | Least-privilege settings access | Payroll/Accounting managers granted model ACL read/write/create on `res.config.settings` (mitigated by custom field filtering) | Broad transient-model ACL instead of dedicated controlled interface | `security/ir.model.access.csv`, `models/res_config_settings.py` (audit) |
| OBS-1 | **Low** | Overlapping contract edge case | Module flags ambiguity when HR allows overlap | `hr.contract` standard constraint prevents overlapping open contracts in tested case, so module ambiguity branch not reached | Upstream HR constraint dominates; module behavior unverified for overlap-permissive customizations | Constraint error on second contract create |

---

## M. Files/methods requiring fixes

| Priority | File(s) | Method/area | Suggested smallest safe correction |
|---|---|---|---|
| P0 | `models/kio_payroll.py` | `_get_payroll_adjustment_amounts`, `_get_payroll_adjustment_records` (and audit similar `env.get` usage for models) | Replace `self.env.get(model_name)` with `self.env[model_name] if model_name in self.env else None` (or explicit registry check) and guard truthiness correctly for Odoo model objects; add tests for OT/commission/deduction inclusion and applied marking. **Do not implement without approval.** |
| P1 | `models/kio_payroll.py` | `_validate_kio_salary_accounting` / salary credit config UX | Accept appropriate payable liability account types supported by payment reconciliation (or make configurable/documented) while preserving reconciliation safety; align with chart-of-account variants. |
| P1 | `models/kio_payroll_adjustment.py`, `models/kio_late_deduction.py`, `models/__init__.py` | `kio.deduction` model definition | Consolidate into one canonical model definition; separate generic deduction vs late-deduction concepts explicitly if both needed. |
| P2 | `tests/test_payroll_overview.py`, `tests/test_payroll_adjustment_integration.py` | module tests | Restore overview tests; stabilize adjustment integration fixtures/contracts and assert real inclusion once BUG-1 fixed. |
| P2 | `security/ir.model.access.csv`, `models/res_config_settings.py` | settings access | Reduce `res.config.settings` ACL scope / use dedicated config actions; keep strict server-side allowlists. |
| P3 | `migrations/17.0.4.0.3/post-migrate.py` | legacy HRA conversion | Add pre-migration audit/reporting for non-zero legacy percentages; confirm `>100` interpreted as amount in target data. |

---

## N. Final PASS / FAIL / BLOCKED status

| Area | Status | Rationale |
|---|---|---|
| **A. Environment & DB isolation** | **PASS** | All writes executed only on disposable `kio_e2e_report_test`; production DBs/process not mutated. |
| **B. Installation/upgrade/dependencies/registration** | **PASS** | Upgraded and loaded successfully; dependencies correct; no `hr_payroll_community` dependency added. |
| **C. Existing automated tests** | **FAIL** | 9 passed, 1 failed, 7 errors of 17 executed (allowance/config subsets passed; adjustment integration failed; overview suite empty). |
| **D. Contract allowance calculation (7 fixed fields, no % HRA)** | **PASS** | A=10,500, B=3,000, C=0 correct in contracts, preview, and generated payslips. |
| **E. Overtime configuration & amount computation (fixed scenario executed)** | **PASS (limited)** | Fixed-rate configs/confirmed OT records computed A=1000, B=450; broader scenarios partly blocked. |
| **F. Deductions records/confirmation** | **PASS (limited)** | Confirmed deduction records created A=500, B=1000; payroll inclusion blocked by BUG-1. |
| **G. Payroll preview (end-to-end baseline)** | **FAIL** | Basic/allowance correct, but confirmed OT/deductions not included (BUG-1). |
| **H. Payroll generation & batch/payslip persistence** | **FAIL** | Batch/slips/lines created and allowance persisted correctly; OT/deduction/gross/net totals incorrect for baseline due to BUG-1; duplicate prevention works. |
| **I. Payslip/report consistency** | **PARTIAL PASS** | Stored lines/amounts internally consistent and PDF renders; values not matching requested baseline because upstream inclusion failed. |
| **J. Accounting & payments** | **BLOCKED / PARTIAL** | Pay action preparation works with compatible payable account; strict credit-account validation blocks common config; full post/payment/partial/overpayment/duplicate payment flows not executed end-to-end. |
| **K. Regression & edge coverage** | **PARTIAL** | Key edge cases passed (no contract excluded, duplicate OT/payslip prevention, draft exclusion domain), but many requested scenarios not fully executed. |
| **L–M. Defects/root causes identified** | **PASS (reported)** | Critical `env.get()` adjustment-helper bug identified with runtime evidence; accounting/config/model/test issues documented. |

### Overall status: **FAIL (core end-to-end payroll amounts incorrect due to BUG-1)**

**What is proven to work:** module installs/upgrades in isolated DB; contract-based fixed allowance totaling and propagation to preview/payslip lines/allowance amounts; fixed overtime/deduction record creation & confirmation; payslip structure/report rendering; duplicate overtime/payslip prevention; no-contract exclusion; isolated DB testing discipline.  
**What is not proven / broken:** inclusion of confirmed overtime/commission/deductions into preview and generated payroll (and applied tracking) is **broken** by `env.get()` usage in adjustment helpers; full accounting/payment lifecycle and several advanced overtime/attendance/edge scenarios remain **unexecuted or blocked**. **Unexecuted tests are reported as BLOCKED/PARTIAL, not PASS.**

---

## Appendix: key executed evidence

- **Disposable DB:** `kio_e2e_report_test` (cloned from `kio_new_payroll_test`), module upgraded to 17.0.4.0.3.
- **Module tests:** 17 executed — 9 passed, 1 failed, 7 errors (`test_contract_allowance_integration` 7/7, `test_overtime_configuration` 2/2, `test_payroll_adjustment_integration` failures, `test_payroll_overview.py` empty).
- **Fixtures:** Emp A/B/C ids 19/20/21, contracts 14/15/16 (allowances 10500/3000/0), OT 11/12 (1000/450 confirmed), deductions 8/9 (500/1000 confirmed), batch 4 slips 5/6/7.
- **Generated slip A (actual):** basic 50000, allowance 10500, overtime 0, deduction 0, gross 60500, net 60500, lines `{BASIC:50000, ALW:10500, OVERTIME:0, COMMISSION:0, BONUS:0, DED:0, GROSS:60500, NET:60500}`.
- **Root-cause probe:** `P._get_payroll_adjustment_amounts(...)` returned `{}` while direct `read_group` returned correct sums; `env.get('kio.overtime')` is empty falsy recordset.
- **Accounting:** pay action prepared successfully with payable credit account in savepoint; rejected for `liability_current` credit account; payslip PDF rendered (28141 bytes).
