# Payroll Post-Fix Audit & Regression Report

**Module:** `kio_payroll_overview_extension`  
**Path:** `/home/rakib/odoo17_env/odoo-17.0/custom_addons/westeen-server/custom-addons/kio_payroll_overview_extension`  
**Previous report:** `PAYROLL_MODULE_FULL_AUDIT_REPORT.md`  
**Audit type:** Read-only post-fix re-audit (static source review, syntax/XML validation, targeted tracing). **No application code, DB records, or existing payroll data modified.** No install/upgrade/uninstall performed in any production database.  
**Audit date:** 2026-11-09 (environment)  
**Environment constraint:** PostgreSQL/Odoo runtime access unavailable (`psycopg2.OperationalError: connection to server at "127.0.0.1", port 1 failed: Connection refused`; `sudo -n -u postgres` unavailable). Runtime/functional/accounting tests on a disposable DB were **NOT EXECUTED**.

## 1. Executive Summary
Post-fix static review shows **meaningful implementation progress** on the three previously reported bugs: legacy test files were refactored toward the independent KIO architecture (BUG-001), the late-attendance cron/dispatcher was reworked with a 15-minute schedule + migration and per-employee due-time logic (BUG-002), and payroll preview/generation now aggregates confirmed overtime/commission/deduction adjustments with applied-tracking logic and a new integration test file (BUG-003). **No runtime verification was possible in this environment**, so none of these fixes can be declared fully fixed by executed behavior.

**Overall condition:** **NOT PRODUCTION-READY** based on available evidence. Remaining concerns include: duplicate/conflicting `kio.deduction` model definitions (newly discovered structural defect), allowance source fragmentation (`hr.contract` KIO allowances vs `kio.payroll.salary.config` allowances used by payroll generation), unverified payment posting/reconciliation/state sync under real accounting flows, unverified cron timing across real timezones/shifts/DST/overnight boundaries, and incomplete runtime security/record-rule validation.

## 2. Previous Bugs Verification

| Bug ID | Previous Problem | Current Status | Evidence |
|---|---|---|---|
| BUG-001 | Legacy Tests (`hr_payroll_community`/`hr.payslip*`) | **PARTIAL** (static fix present; runtime blocked) | `tests/test_payroll_overview.py` rewritten to use `kio.payroll.payslip/batch/line`, `kio.bonus`, `kio.overtime`, `kio.commission`, `kio.deduction`, `kio.payroll.salary.config`; tagged `@tagged("post_install","-at_install")`, `TransactionCase` (`tests/test_payroll_overview.py:1-314`). No functional `hr_payroll_community`/`hr.payslip.run`/`'hr.payslip'` refs found by scan; only non-functional docstring: `tests/test_payroll_overview.py:10` states “no hr_payroll_community”. `tests/__init__.py:1-3` imports `test_payroll_overview`, `test_overtime_configuration`, `test_payroll_adjustment_integration`. `tests/test_overtime_configuration.py` preserved. **Runtime tests NOT EXECUTED (blocked).** |
| BUG-002 | Late Deduction Cron mis-scheduled (1 minute) | **PARTIAL** (static fix present; runtime blocked) | Cron now 15 minutes: `data/kio_late_deduction_cron.xml:3-13` (`Late Attendance Dispatcher`, `model._cron_daily_late_attendance_sync()`, `interval_number=15`, `interval_type=minutes`, `noupdate=1`). Existing-DB migration: `migrations/17.0.4.0.1/post-migrate.py:1-31` updates only target XMLID, preserves unrelated settings (active/doall/nextcall not altered), fixes legacy interval/name/code. Dispatcher: `models/kio_late_deduction.py:358-408` uses `pg_try_advisory_xact_lock(2017040001)`, 7-day lookback, per-employee tz/calendar day start, threshold `scheduled_utc + 30 minutes` (`kio_late_deduction.py:395-396`), skips confirmed/cancelled/manual/processed, `allow_no_checkin=False`; `_process_employee_workday` returns when no attendances (`kio_late_deduction.py:333-349`), supporting “no absent marking when attendance not yet synchronized”. **Runtime timing across shifts/timezones/DST/overnight, missed-run recovery, and cron performance NOT EXECUTED.** |
| BUG-003 | Payroll Calculation Integration (overtime/commission/deduction not pulled in) | **PARTIAL** (static implementation present; runtime blocked; structural concern found) | Preview aggregates confirmed adjustments: `models/kio_payroll.py:849-861,892-905,939-942` loads `kio.overtime.overtime_amount`, `kio.commission.amount`, `kio.deduction.deduction_amount` via `_get_payroll_adjustment_amounts` (excludes applied-to-non-cancelled payslips when `applied`/`applied_payslip_id` exist, `kio_payroll.py:770-787,820-823`). Generation passes same amounts to `_prepare_payslip_lines` and marks adjustments applied after successful creation: `kio_payroll.py:1130-1143,1143,1176-1207`. `_prepare_payslip_lines` computes gross/net including overtime/commission/deduction and includes `COMMISSION` line (`kio_payroll.py:1000-1053` area; static trace confirms commission/adjustment wiring). Comments state monthly late deduction summaries are not combined (`kio_payroll.py:850-852,1198-1201`). Integration tests added: `tests/test_payroll_adjustment_integration.py:1-192` (confirmed/draft/cancelled, aggregation, formula, period/company, preview-generation match, duplicate prevention via `applied`, missing adjustments zero). **Runtime NOT EXECUTED.** Newly discovered structural issue: duplicate `kio.deduction` definitions (see Newly Discovered Bugs). |

## 3. Regression Test Results
Static regression inspection only (runtime blocked).

| Area | Result | Evidence / Notes |
|---|---|---|
| Payroll Overview Dashboard | **NOT TESTED (runtime) / PARTIAL (static)** | Dashboard/payroll RPCs still concentrated in `kio.payroll.payslip` (`models/kio_payroll.py`); manager checks present (`_check_payroll_overview_manager` call sites). KPI math/filters/company behavior require runtime data. |
| New Payroll Run | **NOT TESTED (runtime) / PARTIAL (static)** | Preview now includes adjustment amounts and working-days/calendar logic; generation uses advisory lock, overlap checks, server-side amounts, marks bonuses/adjustments applied (`kio_payroll.py:1088,1130-1143`). Runtime generation idempotency/amounts unverified. |
| Payroll Batch Details | **NOT TESTED (runtime) / PARTIAL (static)** | Batch details path present; working-days handling previously updated (prior report). UI/runtime behavior unverified. |
| Working Days | **NOT TESTED (runtime) / PARTIAL (static)** | Calendar-based logic remains in payroll/overtime/late deduction areas; exact counts depend on runtime calendars/timezones. |
| Bonus Management | **NOT TESTED (runtime) / PARTIAL (static)** | Bonus integration preserved via `kio.bonus.line` pending amounts (`kio_payroll.py:846-847,1106-1115`) and applied marking; tests include bonus helpers. Basic-salary source still uses `kio.payroll.salary.config` in bonus logic (prior RISK-001). |
| Overtime Configuration | **NOT TESTED (runtime) / PARTIAL (static)** | `tests/test_overtime_configuration.py` preserved/compiled; prior static implementation still present. Runtime unverified. |
| Overtime Management | **NOT TESTED (runtime) / PARTIAL (static)** | `kio.overtime` has `applied/applied_payslip_id` (`models/kio_overtime.py:112-126`) and manager-guarded actions. Attendance/cron behavior unverified. |
| Commission Management | **NOT TESTED (runtime) / PARTIAL (static)** | `kio.commission` defined in `models/kio_payroll_adjustment.py:96-116` with `applied` fields; integrated into payroll amounts. Runtime workflow unverified. |
| Deduction Management | **PARTIAL / RISK** | `kio.deduction` integrated by payroll (`kio_payroll.py` uses `deduction_amount`), but model is defined in both `models/kio_payroll_adjustment.py:118-120` and `models/kio_late_deduction.py:10-11` (same `_name`). Load order imports adjustment before late deduction (`models/__init__.py:3,6`). Runtime behavior/field/mixin consistency unverified; structural conflict is a confirmed defect. |
| Payroll Payment | **NOT TESTED (runtime) / PARTIAL (static)** | `account_payment_register.py` and payslip Pay Now/download RPCs present; static safety checks unchanged from prior tracing scope. Posting, reconciliation, partial/excess/duplicate payment behavior unverified. |
| Payslip Generation | **NOT TESTED (runtime) / PARTIAL (static)** | Preview/generation integration added; overlap/duplicate checks and locks present. End-to-end totals/lines/states unverified. |
| Accounting Integration | **NOT TESTED (runtime) / BLOCKED** | Requires disposable DB + accounting config and runtime posting. |
| Payroll Settings | **NOT TESTED (runtime) / PARTIAL (static)** | `res.company`/`res.config.settings` unchanged in this audit pass except prior context; no syntax errors. Save/load/apply side effects unverified. |
| Security and Access Rights | **NOT TESTED (runtime) / PARTIAL (static)** | Payroll RPCs guarded by manager checks in `kio.payroll.payslip` (prior evidence, still present by pattern). Overtime/late deduction actions guarded (`models/kio_overtime.py:163+`, `models/kio_late_deduction.py:157+`). `kio.commission`/`kio.deduction` workflow comes from adjustment mixin patterns (`kio_payroll_adjustment.py`); late deduction overrides actions. ACLs/record rules not exhaustively revalidated against every model field/operation at runtime. |

## 4. Remaining Confirmed Bugs
1. **BUG-001 remains PARTIAL (not fully verified).** Static refactor removed functional legacy dependencies and targets KIO models, but automated Odoo runtime tests were **NOT EXECUTED**. Refactored tests may still need runtime adjustment (field/API/fixture nuances).
2. **BUG-002 remains PARTIAL (not fully verified).** Cron/migration/dispatcher logic is present statically, but actual execution timing (scheduled start + 30 min), employee-specific shifts/calendars, timezones/DST, overnight schedules, duplicate prevention under repeated runs, missed-run recovery, and performance are **NOT EXECUTED**.
3. **BUG-003 remains PARTIAL (not fully verified).** Integration logic and tests are present statically, but preview/generation totals, `COMMISSION` line/report compatibility, duplicate prevention across real payslip states/cancellations, and accounting impact are **NOT EXECUTED**.

## 5. Newly Discovered Bugs

| Severity | Feature | File/Line | Root cause | Reproduction (static/code path) | Recommended fix |
|---|---|---|---|---|---|
| **High** | Deduction model definition conflict | `models/kio_payroll_adjustment.py:118-120`; `models/kio_late_deduction.py:10-11`; import order `models/__init__.py:3,6` | `kio.deduction` is defined twice with the same `_name`: once as `_inherit=["mail.thread","mail.activity.mixin","kio.payroll.adjustment"]` in `kio_payroll_adjustment.py` (no `deduction_amount`/late schema/applied fields shown in that class) and again as a full standalone model in `kio_late_deduction.py` (includes `deduction_amount`, `amount` compute, `applied`/`applied_payslip_id`, unique `(employee_id,date,company_id)`, cron/attendance logic). Duplicate definitions create fragile model merging/MRO/mixin behavior and upgrade risk. | Inspect both files; load module registry (runtime) and compare effective `kio.deduction` fields/inherits/constraints; run deduction creation/confirm/payroll integration/cancel tests. | Consolidate to a single authoritative `kio.deduction` definition (or explicit `_inherit` chain) that includes required mixins, payroll-adjustment semantics, `deduction_amount`/`amount`, `applied` tracking, and late-deduction fields/constraints without duplicate `_name` base classes. Add migration-safe tests. |
| **Medium** | Allowance source inconsistency (contract vs payroll config) | `models/hr_contract.py:21-78` (`kio_medical_allowance`, computed totals); `views/hr_contract_allowance_views.xml:9-30`; payroll uses `models/kio_payroll.py:620-621,841,891,938,1001,1006-1007,1136` (`kio.payroll.salary.config.allowance`) | Contract allowances (`kio_*` on `hr.contract`) were added/simplified, but payroll preview/generation still sources `allowance` from `kio.payroll.salary.config` (and basic from contract wage). | Create contract with KIO allowances but salary config allowance different/zero; run preview/generation. Totals may not reflect contract allowances. | Define a single source of truth for payroll allowances (contract-derived vs salary config) and align preview/generation/dashboard/payslip line semantics; add regression tests. |
| **Low/Medium** | Legacy reference remains in docstring (non-functional) | `tests/test_payroll_overview.py:10` | Docstring states “no hr_payroll_community”. Not a dependency, but contains the legacy module name text. | Search for `hr_payroll_community` in tests. | Optional cleanup: rephrase docstring to avoid the legacy module identifier if strict text removal is desired. |

## 6. Previous Risks Status

| Risk | Previous | Current Status | Evidence / Notes |
|---|---|---|---|
| RISK-001 Basic Salary Source Consistency | Medium | **UNRESOLVED / WORSENED VISIBILITY** | Payroll basic uses `hr.contract.wage` (`kio_payroll.py` generation/contract paths) while allowances use `kio.payroll.salary.config` (`kio_payroll.py:841,891`); bonus logic historically uses salary config basic; new `hr.contract` KIO allowances exist (`models/hr_contract.py`) but are not consumed by payroll generation. Fragmentation remains. |
| RISK-002 Working Days Source Consistency | Medium | **UNRESOLVED** | Schedule-derived working days remain in payroll logic; salary config `working_days` semantics may still confuse users. Runtime/UI not revalidated. |
| RISK-003 Salary Accrual Duplicate Detection | Medium | **UNRESOLVED / UNVERIFIED** | Heuristic matching still requires runtime accounting-flow validation (not re-audited line-by-line in this pass; no code change claim). |
| RISK-004 Payment Status Synchronization | Medium | **UNRESOLVED / UNVERIFIED** | `account_payment_register.py` integration and payslip sync still require runtime posting/reconciliation/partial payment verification. |
| RISK-005 Payroll Settings Save Behavior | Low/Med | **UNRESOLVED / UNVERIFIED** | No targeted change reviewed; runtime settings-page behavior for non-admin payroll/accounting managers remains unverified. |
| RISK-006 Stale Python Cache | Low | **UNRESOLVED** | `__pycache__` artifacts not cleaned (read-only audit). No runtime effect if imports are correct, but can confuse debugging. |
| RISK-007 Bonus KPI and Payslip Consistency | Medium | **UNRESOLVED / UNVERIFIED** | Dashboard/payroll bonus semantics still depend on pending/confirmed/applied bonus flows; runtime verification blocked. |
| RISK-008 RPC Authorization | Medium | **PARTIALLY MITIGATED / UNVERIFIED** | Manager guards exist on payroll slip RPCs and on overtime/late deduction action methods (`models/kio_overtime.py:163+`, `kio_late_deduction.py:157+`). Full RPC/controller/record-rule coverage for all models and all direct ORM calls from OWL under non-manager users remains **NOT TESTED**. |

## 7. Calculation Verification

| Area | Scenario | Expected | Actual (verified) | Result | Evidence |
|---|---|---|---|---|---|
| BUG-003 formula (static) | Basic + Allowances + Overtime + Commission + Bonus; Net = Gross - Deductions | Confirmed adjustments aggregated by period/company/employee; draft/cancelled excluded | Preview computes components and net accordingly; generation passes same components and marks applied after creation | **PASS (static) / NOT TESTED (runtime)** | `models/kio_payroll.py:849-861,892-905,1002-1014,1130-1143`; `tests/test_payroll_adjustment_integration.py:109-121,133-162` |
| Duplicate adjustment prevention (static) | Applied to non-cancelled payslip excluded; cancelled payslip does not block reuse | Domain includes `applied=False OR applied_payslip_id.state='cancel'` when fields exist | Implemented in adjustment selection and marking | **PASS (static) / NOT TESTED (runtime)** | `models/kio_payroll.py:784-786,820-822,1176-1193`; `tests/test_payroll_adjustment_integration.py:163-186` |
| Late deduction dispatcher threshold (static) | Evaluate after scheduled start + 30 minutes | `now < scheduled_utc + timedelta(minutes=30)` => skip | Implemented | **PASS (static) / NOT TESTED (runtime)** | `models/kio_late_deduction.py:395-396` |
| No absent marking when no attendance (static) | Missing attendance should not create absent/false deduction in dispatcher path | `_process_employee_workday` returns when no attendances and `allow_no_checkin=False`; dispatcher uses `False` | Implemented | **PASS (static) / NOT TESTED (runtime)** | `models/kio_late_deduction.py:333-349,406-408` |
| Contract HRA/allowances (static) | HRA % of wage; Medical fixed; totals/gross | `hra = wage * percent/100`; `medical = kio_medical_allowance`; totals/gross computed & currency-rounded | Implemented on `hr.contract` | **PASS (static) / NOT TESTED (runtime)** | `models/hr_contract.py:7-78`; `views/hr_contract_allowance_views.xml:10-28`; migration `migrations/17.0.4.0.2/pre-migrate.py:1-33` |
| Payroll uses contract allowances (static) | Contract KIO allowances reflected in payroll generation | Expected if contract is source of truth | Payroll currently uses `salary_config.allowance` | **FAIL (integration gap/risk)** | `models/kio_payroll.py:891,938,1006-1007,1136` vs `models/hr_contract.py` |
| Legacy automated tests compatibility (static) | Target current KIO models/APIs | No `hr_payroll_community`/`hr.payslip*` runtime deps | Refactored to KIO models; syntax valid | **PASS (static) / NOT TESTED (runtime)** | `tests/test_payroll_overview.py`, `tests/__init__.py` |
| Odoo runtime totals/accounting/payments | Real data, journal entries, reconciliation, report PDF | Correct amounts, states, entries, reports | Not executed | **BLOCKED** | Environment DB unavailable |

## 8. Accounting and Security Findings
- **Accounting/payments (static):** Pay Now/report/download/payment registration paths remain in module (prior tracing + `account_payment_register.py` present). SQL safety remains parameterized for advisory locks observed earlier and in late deduction dispatcher (`pg_try_advisory_xact_lock`). **No runtime posting/reconciliation/partial/excess/duplicate payment tests executed.** Risk remains that payment state sync/timing and accrual duplicate heuristics can behave unexpectedly under real flows (RISK-003/004).
- **Security (static):** Manager group checks are present for payroll manager RPC pattern (prior evidence) and for overtime/late deduction manager actions. ACLs/record rules exist (inventory unchanged). **Not runtime-verified:** unauthorized RPC calls across all exposed model methods, record rules under multi-company/allowed-company contexts, payroll-user read-only/denied behaviors, and OWL direct ORM calls by non-managers.
- **Company isolation:** Adjustment selection includes `company_id`; tests added for period/company isolation in integration suite (`tests/test_payroll_adjustment_integration.py:123-131`) but **NOT EXECUTED**. `kio.deduction` duplicate model definitions may affect effective constraints/rules (UNVERIFIED).
- **Data integrity:** Applied-tracking domains consider cancelled payslips. **Unverified:** behavior when a generated payslip/batch is cancelled after marking adjustments (whether applied flags/links are reset or safely reusable) — current eligibility domain may allow re-inclusion, but operational semantics need runtime validation.

## 9. Tests Executed / Passed / Failed / Blocked

| Test / Check | Status | Evidence |
|---|---|---|
| Python syntax: compile all module `*.py` (excluding `__pycache__`) | **PASS** | `python3 -m py_compile` over discovered module Python files returned exit `0` |
| XML parse: all module XML files | **PASS** | `xml.etree.ElementTree.parse` over all `*.xml`: `XML_OK=14 ERR=0` |
| Targeted test-file syntax compile (`test_payroll_overview.py`, `test_overtime_configuration.py`, `test_payroll_adjustment_integration.py`, `tests/__init__.py`) | **PASS** | `py_compile` exit `0` (reconfirmed) |
| Legacy reference scan (tests) for functional `hr_payroll_community`/`hr.payslip.run`/`hr.payslip` | **PASS (functional refs removed)** | Scan found only docstring mention `tests/test_payroll_overview.py:10` (“no hr_payroll_community”); no functional legacy model/module refs |
| Static verification of BUG-002 cron/migration/dispatcher code paths | **PASS (static evidence present)** | `data/kio_late_deduction_cron.xml`, `migrations/17.0.4.0.1/post-migrate.py`, `models/kio_late_deduction.py:358-408,333-349` |
| Static verification of BUG-003 integration code paths | **PASS (static evidence present)** | `models/kio_payroll.py` adjustment aggregation/marking/line prep; `tests/test_payroll_adjustment_integration.py` present |
| Odoo automated tests: `--test-tags /kio_payroll_overview_extension` (disposable DB) | **BLOCKED** | No Postgres/Odoo runtime access; prior attempts failed with connection refused (`127.0.0.1:1`) |
| Targeted Odoo tests: `test_payroll_overview`, `test_overtime_configuration`, `test_payroll_adjustment_integration` | **BLOCKED** | Same environment constraint |
| Cron scheduling/runtime behavior (real cron runs, shifts/timezones/DST/overnight) | **BLOCKED** | Requires Odoo runtime + time-controlled or real environment |
| Payroll calculation runtime regression (preview vs generated, payslip states, bonuses/adjustments end-to-end) | **BLOCKED** | Requires disposable DB/runtime |
| Accounting/payment posting, reconciliation, partial/excess/duplicate payments | **BLOCKED** | Requires disposable DB + accounting runtime |
| Security/ACL/record-rule runtime tests (unauthorized RPC, company isolation, manager/user roles) | **BLOCKED** | Requires Odoo runtime |
| Functional regression (dashboard, batch details, OWL flows, reports/downloads) | **BLOCKED** | Requires Odoo runtime/UI |

**Totals (this audit):** Executed = 6 static checks/scans; **Passed = 6**; **Failed = 0** static checks (but confirmed defects/risks documented from review); **Blocked = 8** runtime/functional test categories.

## 10. Production Readiness Assessment
**Assessment: NOT PRODUCTION-READY (evidence insufficient + confirmed structural/functional risks remain).**

### Fixed (with evidence)
- **BUG-001 (static):** functional legacy test dependencies removed; KIO-targeted tests added/refactored and compile; `test_overtime_configuration.py` preserved.
- **BUG-002 (static):** 1-minute cron replaced by 15-minute dispatcher config + noupdate migration; dispatcher code adds 30-minute threshold, 7-day recovery, lock, timezone/calendar-aware processing, and no-attendance skip.
- **BUG-003 (static):** preview/generation now include confirmed overtime/commission/deduction aggregation with cancelled-payslip-aware applied eligibility and post-creation marking; integration tests added.

### Remaining / unverified
- **BUG-001/002/003 runtime behavior:** all **BLOCKED/UNVERIFIED** — no disposable-DB test execution.
- **Newly discovered High defect:** duplicate/conflicting `kio.deduction` model definitions (`kio_payroll_adjustment.py:118-120` vs `kio_late_deduction.py:10-11`) require consolidation and runtime validation.
- **Allowance integration gap:** `hr.contract` KIO allowances are not used by payroll generation (uses `kio.payroll.salary.config.allowance`).
- **Prior risks unresolved:** RISK-001–007 largely unresolved/unverified; RISK-008 partially mitigated but unverified at runtime.
- **Accounting/payment/security UI flows:** unverified under real Odoo runtime.

### Required before production use
1. Run module upgrade/migrations and full test suite on a **disposable Odoo 17 + PostgreSQL** environment: `--test-tags /kio_payroll_overview_extension` (and targeted tags).
2. Fix/validate the duplicate `kio.deduction` model definition; re-test deduction creation, confirmation, cancellation, payroll inclusion, applied tracking, and late-deduction cron/manual sync.
3. Runtime-verify BUG-002 dispatcher against real shifts/calendars/timezones/DST/overnight cases and missed-run recovery.
4. Runtime-verify BUG-003 totals in preview, generated payslips, `COMMISSION`/adjustment lines, payslip reports, and behavior when payslips are cancelled/regenerated.
5. Decide and implement a consistent allowance/basic-salary source strategy (contract vs salary config) and test payroll/dashboard/bonus alignment.
6. Validate Pay Now/Register Payment posting, reconciliation, payslip paid/unpaid state sync, partial/excess/duplicate handling, and company/security/record rules.
7. Clean stale `__pycache__` in a maintenance pass (separately, with normal change controls).

**Final summary:** Previous bugs have **partial static fixes** but are **not fully verified**; at least **one newly discovered high-severity structural defect** (`kio.deduction` duplicate definition) and an allowance integration gap remain. No runtime tests were actually executed in this environment. The module is **not production-ready** until the above runtime validations and defect remediations are completed.