# Payroll Module Full Audit Report

**Module:** `kio_payroll_overview_extension`  
**Path:** `/home/rakib/odoo17_env/odoo-17.0/custom_addons/westeen-server/custom-addons/kio_payroll_overview_extension`  
**Audit type:** Static code review + safe automated checks + targeted tracing (no code changes, no DB writes, no install/upgrade/uninstall).  
**Audit date:** 2026-11-09 (environment date)  
**Auditor mode:** Read-only source inspection; Odoo runtime tests attempted but blocked by environment DB access.

## A. Executive Summary
The module is an **independent Odoo 17 payroll** implementation (`hr`, `hr_attendance`, `hr_contract`, `account`, `web`; **no `hr_payroll_community` dependency** in manifest). Core structure is present (models, views, security, data/crons, OWL dashboard, migrations, tests). Static checks passed: **all module Python files compiled** (`python3 -m py_compile`) and **all XML files parsed** successfully.

**Overall condition:** **NOT READY** for production confidence without targeted fixes and runtime validation. There are confirmed defects in automated tests/legacy test alignment, a high-risk late-deduction cron schedule, and significant functional/integration gaps (confirmed overtime/commission/deduction adjustment records are not pulled into generated KIO payslip amounts; basic-salary sources are fragmented). Odoo functional/runtime tests could not be executed in this environment due to PostgreSQL access refusal.

**Major findings**
- **Critical (test/runtime alignment):** `tests/test_payroll_overview.py` targets `hr.payslip`/`hr.payslip.run`/`hr_payroll_community` APIs and menu/groups that do not match this independent module; it is incompatible and will fail/error in the current module context.
- **High (operations/performance risk):** `data/kio_late_deduction_cron.xml` schedules “Daily Late Attendance Sync” every **1 minute** (`interval_number=1`, `interval_type=minutes`, active, noupdate) — likely unintended load risk.
- **High (functional integration gap):** `generate_new_payroll_run` / `_prepare_payslip_lines` include **bonus** amounts (pending bonus lines) but set **overtime, commission, deduction** payslip line amounts to `0.0`; confirmed `kio.overtime` / `kio.commission` / `kio.deduction` records are not integrated into generated payslip totals.
- **Medium (consistency/accounting risk):** Basic salary sources differ by feature (contract wage vs `kio.payroll.salary.config`), bonus percentage uses salary config, and accrual duplicate detection uses heuristic matching.
- **Verified recent fixes (static):** Overtime Configuration now supports scope + multi-employee individual selection, contract-wage-based `basic_salary`/`per_hour_salary`/`overtime_amount` (read-only computes), and Payroll Batch Details/New Payroll Run working-days logic is computed from `resource.calendar` scheduled attendances (not hardcoded calendar days), with batch details API/XML updated.

## B. Module Inventory
**Manifest:** `__manifest__.py` (v17.0.4.0.0, LGPL-3, `installable`, post-init hook).  
**Dependencies:** `hr`, `hr_attendance`, `hr_contract`, `account`, `web`.

**Python / models (`models/`)**
- `__init__.py` imports: `kio_payroll_salary_config`, `kio_payroll`, `kio_payroll_adjustment`, `kio_overtime`, `kio_overtime_configuration`, `kio_late_deduction`, `hr_attendance`, `kio_bonus_type`, `kio_bonus`, `res_company`, `res_config_settings`, `account_payment_register`.
- `kio_payroll.py`: `kio.payroll.batch`, `kio.payroll.payslip`, `kio.payroll.payslip.line`; dashboard/new payroll run/generation/batch details/payment/download RPC methods.
- `kio_payroll_adjustment.py`: abstract `kio.payroll.adjustment`, `kio.commission`, `kio.deduction`.
- `kio_overtime.py`: attendance-based overtime records/cron/sync logic.
- `kio_overtime_configuration.py`: overtime rate config (`kio.overtime.configuration`, `.line`) with scope, multi-employee individual selection, contract wage, per-hour salary, overtime amount.
- `kio_late_deduction.py`: late deduction/attendance sync logic and cron target behavior.
- `kio_bonus_type.py`, `kio_bonus.py`: bonus types, bonus management, bonus lines, payroll bonus amount APIs.
- `kio_payroll_salary_config.py`: employee salary config (basic/allowance/working_days).
- `hr_attendance.py`: attendance integration extensions.
- `res_company.py`, `res_config_settings.py`: payroll accounting/overtime/late deduction settings.
- `account_payment_register.py`: Pay Now / Register Payment integration and payroll payment validation/sync.

**Views/XML (`views/`)**: `payroll_overview_views.xml`, `payroll_report_views.xml`, `kio_bonus_views.xml`, `kio_bonus_type_views.xml`, `kio_payroll_adjustment_views.xml`, `kio_payroll_views.xml`, `kio_overtime_configuration_views.xml`, `res_config_settings_views.xml`.

**Security**
- `security/kio_payroll_security.xml`: module category/groups (`Payroll User`, `Payroll Manager`) and multi-company record rules for batches/payslips/lines/salary config/bonus/overtime/commission/deduction/late summary/overtime config/lines.
- `security/ir.model.access.csv`: manager/user access for listed models; `res.config.settings` access for payroll manager and accounting manager.

**Data/crons**: `data/kio_bonus_type_data.xml`, `data/kio_late_deduction_cron.xml`, `data/kio_overtime_cron.xml`.

**Frontend (OWL/assets)**: `static/src/js/payroll_overview.js`, `static/src/xml/payroll_overview.xml`, `static/src/scss/payroll_overview.scss`.

**Tests**: `tests/test_payroll_overview.py`, `tests/test_overtime_configuration.py` (new, added in working tree context), registered in `tests/__init__.py`.

**Migrations/hooks**: `migrations/17.0.1.1.0/post-migrate.py`, `migrations/17.0.1.2.0/post-migrate.py`; manifest `post_init_hook` sets overtime config scope defaults and legacy `employee_id`→`employee_ids` migration.

**Other observations (inventory)**
- Stale `__pycache__` files exist for source files not currently present in `models/`/`tests/` (e.g., `hr_payslip*`, `kio_payroll_payment/mixins/rule/run/slip/structure/input`, `test_kio_payroll_phase1`). `git status` is clean in this working tree; these pycache artifacts are not imported by current `models/__init__.py`.

## C. Testing Results

| Feature | Test Case | Result | Evidence |
|---|---|---|---|
| Module structure | Manifest/dependency review, no `hr_payroll_community` | PASS (static) | `__manifest__.py:8-9` depends `hr, hr_attendance, hr_contract, account, web`; grep found no `hr_payroll_community` refs in manifest/models/security/views. |
| Python syntax | Compile all module Python files | PASS | `python3 -m py_compile` over module `*.py`/`**/*.py` completed with no output/errors. |
| XML validity | Parse all module XML files | PASS | `xml.etree.ElementTree.parse` over all module XML: `XML_PARSE_OK`. |
| Security model | Manager checks on payroll RPC methods | PASS (static) | `kio.payroll.payslip._check_payroll_overview_manager` (`models/kio_payroll.py:180`) requires `kio_payroll_overview_extension.group_kio_payroll_manager`; called by dashboard/batch/run/pay/payment/download RPCs (e.g., 536,555,762,935,1068,1211,1371,1378,1390). |
| SQL safety | Raw SQL review | PASS (static) | Parameterized advisory locks only: `pg_advisory_xact_lock(%s,%s)` in `models/kio_payroll.py:1001` and `models/account_payment_register.py:22-24`; no string-formatted SQL found. |
| Overtime Configuration | Scope/multi-employee, wage-based salary, per-hour salary, overtime amount, column visibility | PASS (static) / NOT TESTED (runtime) | `models/kio_overtime_configuration.py`: `employee_scope`, `employee_ids` M2M, legacy `employee_id` compat, `_get_applicable_contract` uses `hr.employee._get_contracts(..., states=['open'])` + ORM fallback, `basic_salary`/`per_hour_salary`/`overtime_amount` computes, `column_invisible` on `overtime_amount` in `views/kio_overtime_configuration_views.xml`. Runtime not executed. |
| Overtime config regression tests | Existing line reads running contract; missing contract marked | NOT TESTED (blocked) | Added `tests/test_overtime_configuration.py`. Attempted `odoo-bin --test-enable --stop-after-init -i kio_payroll_overview_extension --test-tags ...test_overtime_configuration -d kio_audit_disposable_check --db_host=127.0.0.1 --db_port=1 ...` failed: `psycopg2.OperationalError: connection to server at "127.0.0.1", port 1 failed: Connection refused`. No disposable DB/Postgres access available. |
| Existing automated suite | `tests/test_payroll_overview.py` alignment with independent module | FAIL (static review) | Test imports/uses `hr.payslip`, `hr.payslip.run`, `hr_payroll_community` refs/rules/groups, and calls methods not present/misaligned (`get_payroll_batch_details_data`, `get_payroll_batch_employee_salary_details`, `get_payroll_employee_salary_details`, `prepare_payroll_generation` behavior differs). Conflicts with manifest/no-community design. |
| Payroll Dashboard | KPI calculations, filtering, company/wage sourcing, paid/unpaid sync, duplicates/currency | NOT TESTED (runtime) / PARTIAL (static) | `get_payroll_overview_data` (`models/kio_payroll.py:1068+`) aggregates active employees, contract wages (open contracts overlapping period), draft+done KIO payslips, bonus totals from `kio.bonus.line`. Requires DB/runtime to verify numbers and UI. |
| Bonus Management | Scope/generation/fixed+percentage/confirm/integration | NOT TESTED (runtime) / PARTIAL (static) | `kio_bonus.py`: scopes, `kio.payroll.salary.config` eligibility/basic, confirm/cancel, duplicate line constraint, `_get_payroll_bonus_amounts` pending_only/period by `bonus_date`; generation marks applied payslip in `kio_payroll.py:1046+`. Basic-salary source differs from contract wage. |
| Overtime Management | Attendance integration, schedule/hours, rates, approvals, duplicates | NOT TESTED (runtime) / PARTIAL (static) | `kio_overtime.py` has sql constraints and `_cron_daily_overtime_attendance_sync` (598+); uses confirmed overtime config/company rates. Large module not fully runtime-validated. |
| Commission/Deduction | CRUD/validation/confirm/cancel/payroll integration | NOT TESTED (runtime) / PARTIAL (static) | `kio_payroll_adjustment.py` provides abstract workflow + `kio.commission`/`kio.deduction`. Generated payslip amounts do not consume confirmed commission/deduction records (see confirmed bug). |
| New Payroll Run | Dates/employees/eligibility/working days/generate | PASS (static for working-days logic) / NOT TESTED (runtime) | `get_new_payroll_run_data` computes company batch working days + per-employee working days via `_count_scheduled_working_days`; excludes ineligible/missing/invalid running contracts; JS `onMonthYearChange`/`onPeriodChange` reload data. `generate_new_payroll_run` uses advisory lock and overlap checks. Runtime generation not executed. |
| Payroll Batch Details | Totals, working days, employee list, search, pay/download actions | PASS (static for working-days/API wiring) / NOT TESTED (runtime) | `get_payroll_batch_details` computes batch/period working days from company default calendar and per-employee schedule; returns availability fields. XML shows period working days with fallback. JS calls `get_payroll_batch_details`, `action_payroll_pay_now`, `action_payroll_download_payslip`. |
| Payroll Payment | Register Payment wizard, mapping, accounts, posting, sync, duplicate prevention, partials | NOT TESTED (runtime) / PARTIAL (static) | `action_payroll_pay_now` builds standard wizard on payable lines; `account_payment_register` validates amount/unpaid (advisory lock), syncs state after `super()`. Supports partial by residual. Full accounting behavior not executed. |
| Payslip/report download | Generation, calculations, PDF, layout, net salary | NOT TESTED | Report/PDF rendering and download action require Odoo runtime. |
| Payroll Configuration | Salary journal/debit/credit, overtime/late settings save/load/validate/apply | NOT TESTED (runtime) / PARTIAL (static) | `res.company`/`res.config.settings` define fields, constraints, config params; `execute()` bypasses global pipeline for non-admin payroll/accounting managers after persisting payroll fields. |
| Late deduction cron | Schedule correctness | FAIL (static/config review) | `data/kio_late_deduction_cron.xml:4-13` name "Daily Late Attendance Sync" but `interval_number=1`, `interval_type=minutes`. Overtime cron is daily at 15:00 UTC (21:00 Asia/Dhaka). |
| Data integrity/concurrency | Duplicate payroll/payment prevention, state transitions | PARTIAL (static) | Advisory locks for payroll generation and payment validation/payable accrual; payslip unique `(employee_id,company_id,date_from,date_to)`; bonus line unique per bonus+employee; confirmed-state write protections present. Multi-user/runtime race tests not executed. |

## D. Confirmed Bugs

### BUG-001
- **Severity:** Critical
- **Module/feature:** Automated tests / module compatibility
- **File:** `tests/test_payroll_overview.py:1-448` (registered by `tests/__init__.py:1-2`)
- **Description:** The test suite is written for `hr.payslip`/`hr.payslip.run` and depends on `hr_payroll_community` structures, salary rules, groups, and menus. It also calls methods/endpoints not matching the current independent KIO payroll implementation.
- **Steps to reproduce:** Run module tests in an Odoo 17 environment with `kio_payroll_overview_extension` installed/loaded (`--test-enable -i kio_payroll_overview_extension` or module tag). Observe imports/references to `hr_payroll_community` and `hr.payslip` model APIs.
- **Expected result:** Automated tests validate the current independent KIO payroll models (`kio.payroll.batch`, `kio.payroll.payslip`, dashboard RPCs) and run against declared dependencies.
- **Actual result (static evidence):** Test uses `hr.payslip.run`, `hr.payslip`, refs `hr_payroll_community.*` (e.g., lines 34,35,39,45,53,59,128-135,312-313,389-400), and asserts methods like `get_payroll_batch_details_data`, `get_payroll_batch_employee_salary_details`, `get_payroll_employee_salary_details`, `prepare_payroll_generation` on `hr.payslip` (177,185,215,222,256,284,290,325,366,376,380,406,423+). Current JS/backend use `get_payroll_batch_details` (`static/src/js/payroll_overview.js:765`, `models/kio_payroll.py:1211`); `prepare_payroll_generation` raises `UserError` at `models/kio_payroll.py:1395-1397`.
- **Root cause:** Legacy test suite not migrated to the independent `kio_payroll_*` architecture.
- **Recommended fix:** Replace/rewrite tests to target `kio.payroll.*` models and current RPC contracts; remove `hr_payroll_community` dependencies from tests; keep tests isolated and compatible with manifest dependencies.

### BUG-002
- **Severity:** High
- **Module/feature:** Late deduction scheduler / cron configuration
- **File:** `data/kio_late_deduction_cron.xml:3-13`
- **Description:** The cron is named "Daily Late Attendance Sync" but is configured to run every minute.
- **Steps to reproduce:** Open Scheduled Actions for `ir_cron_kio_daily_late_attendance_sync` or inspect `data/kio_late_deduction_cron.xml`.
- **Expected result:** A daily sync runs on an intended daily schedule (or the name/behavior should clearly match minute-level processing if truly required).
- **Actual result:** `<field name="interval_number">1</field>` and `<field name="interval_type">minutes</field>` (`lines 8-9`), `active=True`, `numbercall=-1`; `noupdate="1"` means existing installations may retain the bad schedule.
- **Root cause:** Cron interval misconfigured relative to name/intent.
- **Recommended fix:** Correct interval to the intended schedule (e.g., daily) or rename/design as minute-level with safeguards; add migration/data update for existing databases because record is `noupdate`.

### BUG-003
- **Severity:** High
- **Module/feature:** Payroll generation / overtime-commission-deduction integration
- **File:** `models/kio_payroll.py:809-833,847-855,946-957,1012-1037`
- **Description:** New payroll generation computes/includes pending bonus amounts but does not load confirmed overtime, commission, or deduction adjustments into payslip amounts/lines.
- **Steps to reproduce (static/code path):** Review `get_new_payroll_run_data` row creation (sets `overtime = 0.0`, `commission = 0.0`, `deduction = 0.0`; only `bonus` from pending bonuses) and `generate_new_payroll_run` + `_prepare_payslip_lines` (passes bonus/basic/allowance only; `_prepare_payslip_lines` hardcodes overtime/deduction/commission-related values to 0.0 except bonus).
- **Expected result:** If the module provides Overtime/Commission/Deduction records and includes these columns in payroll generation/payslip totals, confirmed/applicable records for the payroll period/company/employee should be aggregated and reflected consistently (subject to business rules).
- **Actual result:** `get_new_payroll_run_data` returns rows with `overtime/commission/deduction` zeroed (`lines 847-855,868-871` in the inspected block). `_prepare_payslip_lines` creates `OVERTIME` and `DED` lines with `0.0` and no commission line (`809-833`). `generate_new_payroll_run` only fetches `bonus_amounts` (`1012-1015`) and does not fetch `kio.overtime`, `kio.commission`, or `kio.deduction`.
- **Root cause:** Independent payroll generation path not wired to adjustment/overtime models.
- **Recommended fix:** Define and implement period/employee/company/state rules for consuming `kio.overtime` (attendance-based), `kio.commission`, and `kio.deduction`; aggregate amounts safely (no duplicate counting), populate generation preview and payslip lines, and add regression tests.

## E. Potential Risks

| ID | Severity | Area | Evidence | Risk |
|---|---|---|---|---|
| RISK-001 | Medium | Basic salary source fragmentation | Bonus uses `kio.payroll.salary.config` basic (`models/kio_bonus.py:165-174,180-184`); overtime config uses `hr.contract.wage` (`models/kio_overtime_configuration.py` contract lookup/compute); new payroll run uses `contract.wage` and config allowances (`models/kio_payroll.py` generation path). | Dashboard/payroll/bonus/overtime values may disagree for the same employee/period; percentage bonus may not match contract wage. |
| RISK-002 | Medium | Salary config `working_days` confusion | `kio.payroll.salary.config.working_days` default 22.0 (`models/kio_payroll_salary_config.py:33`) vs batch/new-run working days computed from `resource.calendar`. | Users may confuse configuration working days with schedule-derived payroll working days. |
| RISK-003 | Medium | Accrual duplicate heuristic | `_find_kio_existing_salary_move` matches posted entries by payable account/partner/credit/date range and totals (`models/kio_payroll.py:350-389`). | Could attach to an unrelated manual entry sharing characteristics; mitigated partly by specific account/partner/amount/date checks and advisory lock, but still heuristic. |
| RISK-004 | Medium | Payment sync source-line timing | `account.payment.register.action_create_payments` captures `source_lines = self.line_ids` before `super()` and uses them to locate slips by `salary_move_id` (`models/account_payment_register.py:73-77,46-70`). | Usually safe if source payable lines remain associated, but reconciliation/payment flow changes in Odoo/accounting customizations could desynchronize status updates. Needs runtime validation. |
| RISK-005 | Low/Med | `res.config.settings.execute` bypass | Non-admin payroll/accounting managers get reload without global `super().execute()` after custom persistence (`models/res_config_settings.py:183-196`). | Prevents unrelated settings pipeline side effects (intentional), but settings on the same page managed by other `set_values` implementations may not be saved for those users. |
| RISK-006 | Low | Stale pycache/source mismatch | `models/__pycache__` and `tests/__pycache__` contain compiled files for absent sources (e.g., `hr_payslip*`, `kio_payroll_payment*`, `test_kio_payroll_phase1`). | No runtime effect if not imported; can confuse audits/debugging. Safe to clean in a maintenance change. |
| RISK-007 | Medium | Overtime/bonus KPI semantics | Dashboard `total_bonus` uses confirmed bonus totals (`kio.bonus.line`) for period; payslip rows use `slip.bonus`; payroll generation preview uses pending bonuses. | Users may see expected semantic differences as inconsistencies without clear UI labeling. |
| RISK-008 | Medium | RPC authorization scope | Most `kio.payroll.payslip` model RPCs check payroll manager; record rules also protect company data. Frontend calls ORM directly. | Adequate for manager-only flows, but any new non-manager UI/API exposure would need explicit ACLs and tests. |

## F. Calculation Verification

| Area | Scenario | Expected | Actual (verified) | Result | Evidence |
|---|---|---|---|---|---|
| Overtime config (percentage) | Per Hour Salary 297.62, Overtime Rate 150% | 446.43 BDT | Formula `per_hour_salary * overtime_percentage / 100` implemented | PASS (static arithmetic) | `models/kio_overtime_configuration.py` `_compute_overtime_amount`; monetary/currency rounding via computed monetary field context. |
| Overtime config (fixed) | Fixed Per Hour Rate configured | Overtime Amount = Per Hour Rate | `overtime_amount = line.per_hour_rate or 0.0` for fixed | PASS (static) | `models/kio_overtime_configuration.py` `_compute_overtime_amount`. |
| Basic salary / per-hour salary | Running contract wage 50,000; monthly scheduled hours 208 | Basic 50,000.00; Per Hour 240.38 BDT | Uses `hr.contract.wage` / `monthly scheduled hours` from `resource.calendar` (no hardcoded month hours) | PASS (static/code path) | `models/kio_overtime_configuration.py` `_get_applicable_contract`, `_get_monthly_scheduled_hours`, `_compute_contract_salary_info`. Runtime confirmation blocked. |
| Batch working days | Nov 2026, 01–30 Nov 2026, company default schedule with weekly off-days | Scheduled working dates from calendar (e.g., Mon–Fri scheduled days in month), **not 30** | `_count_scheduled_working_days` counts attendance-backed dates excluding lunch/resource-filtered schedules/weekly off-days | PASS (static) | `models/kio_payroll.py:686+`, `get_payroll_batch_details` now computes period/batch working days; `static/src/xml/payroll_overview.xml` batch details period card updated. Exact count depends on actual company calendar. |
| New payroll run net | Basic 1000, Allowance 250, Bonus 50, Overtime/Deduction/Commission 0 (current logic) | Net 1300 (by current line design) | `_prepare_payslip_lines` computes gross/net from passed components; overtime/deduction hardcoded 0 | PASS (static, current design) / RISK due to BUG-003 integration gap | `models/kio_payroll.py:809-833,946-957`. |
| Bonus percentage | Config basic 20,000, 10% | 2,000 | `basic * percentage / 100`, currency rounded | PASS (static) | `models/kio_bonus.py:177-184`. Note uses salary config basic, not contract wage (RISK-001). |
| Payroll payment amounts | Unpaid residual on payable lines | Paid = net - residual (clamped), supports partial | Reconciliation residual drives `paid/unpaid/payment_state`; register validates overpayment | PASS (static) / NOT TESTED (runtime) | `models/kio_payroll.py:243-295,456-465,467-535`, `models/account_payment_register.py:15-77`. |
| Legacy `test_payroll_overview` salary expectations | Independent module compatibility | N/A for current architecture | Not comparable; test suite targets different models/APIs | FAIL | `tests/test_payroll_overview.py` (BUG-001). |

## G. Security and Accounting Findings

**Access control / RPC**
- Payroll overview/RPC methods check `group_kio_payroll_manager` (`models/kio_payroll.py:180-184` and call sites). Company scoping is applied in searches/domains (`company_id = env.company` / authorized batch checks).
- ACLs grant read for payroll users and full CRUD for managers on main payroll/bonus/overtime/commission/deduction/late/overtime-config models; `res.config.settings` limited to payroll manager and accounting manager (`security/ir.model.access.csv`).
- Multi-company global rules exist for core models including overtime configuration and lines (`security/kio_payroll_security.xml`).

**Accounting/payments**
- Salary accrual requires configured salary journal (general), expense debit account, and payable credit account; validates company/account constraints (`models/kio_payroll.py:299-349`, `res.company` constraints).
- Payable accrual is created/posted with advisory lock and duplicate lookup; Register Payment opened on payable move lines with `kio_payroll_slip_id` context.
- Payment wizard validates >0 and <= unpaid amount, blocks overpayment, and uses advisory lock (`models/account_payment_register.py:15-45`).
- Post-payment sync updates slip paid/payment fields from reconciliation (`_sync_kio_payment_state` / register hook). Runtime posting/reconciliation must be validated in disposable DB.

**Potential accounting/data-integrity concerns**
- Heuristic accrual reuse (RISK-003) and payment sync timing assumptions (RISK-004) require runtime/accounting-flow tests.
- `sudo().write(...)` is used for internal payment/accrual state sync; acceptable if limited to controlled fields, but review during fixes.

**Injection/safety**
- No unsafe raw SQL interpolation observed; parameterized `pg_advisory_xact_lock` only.
- No controllers added; exposure is mainly ORM model methods.

## H. Untested Areas
- **All Odoo runtime/functional tests in a live Odoo+Postgres environment** (blocked): disposable DB creation/execution failed due to DB access — `psycopg2.OperationalError: connection to server at "127.0.0.1", port 1 failed: Connection refused` when attempting `odoo-bin ... -d kio_audit_disposable_check --db_host=127.0.0.1 --db_port=1 ...`. No `sudo -u postgres` access; no usable Odoo 17 DB config found.
- Dashboard KPI correctness with real data (month/year, multi-batch, draft/done, paid/unpaid, currency, duplicate counting).
- New Payroll Run generation end-to-end (employee eligibility, contracts, ambiguous overlaps, bonus marking, payslip creation, idempotency/overlaps).
- Batch Details UI behavior, search, Pay Now/Register Payment wizard, Download Payslip PDF/report layout.
- Actual accounting journal entries, reconciliation, partial/failed/cancelled payment flows.
- Overtime Management attendance integration, cron execution, approval/state transitions, duplicate prevention in runtime.
- Commission/deduction runtime behavior and (currently missing) payslip integration.
- Late deduction cron runtime behavior and performance impact of 1-minute schedule.
- Multi-company behavior under real company switching/record rules.
- Multi-user concurrency under real DB transactions (beyond static lock review).
- Access tests for non-manager/payroll-user/unauthorized RPC in runtime.

## I. Recommended Fix Priority
1. **P0 – Critical:** Fix/replace `tests/test_payroll_overview.py` (BUG-001) to match independent KIO payroll models; remove `hr_payroll_community` assumptions. Keep CI/runtime tests meaningful.
2. **P1 – High:** Correct late deduction cron schedule/name and add migration for existing `noupdate` cron (BUG-002).
3. **P1 – High:** Implement and test integration of confirmed overtime/commission/deduction into payroll generation/payslip calculations with clear period/state/duplicate rules (BUG-003).
4. **P2 – Medium:** Unify/document basic-salary sources (contract wage vs `kio.payroll.salary.config`) and align bonus/overtime/payroll semantics (RISK-001, RISK-007).
5. **P2 – Medium:** Runtime-validate payment/accrual flows (RISK-003, RISK-004), including duplicate accrual matching and post-reconciliation sync.
6. **P2 – Medium:** Review `res.config.settings.execute` impact on co-located settings (RISK-005).
7. **P3 – Low:** Clarify salary-config `working_days` vs schedule-derived working days (RISK-002); clean stale pycache/artifacts (RISK-006).

## J. Final Assessment
- **Total tests executed:** 3 static/safe checks (Python compile-all, XML parse-all, targeted code/security tracing) + 1 blocked Odoo runtime test attempt.
- **Passed tests:** 3 (static checks passed; selected static behavior reviews passed where noted).
- **Failed tests:** 1 confirmed by static review (`tests/test_payroll_overview.py` incompatible, BUG-001) + 1 config/scheduler failure by static review (late deduction cron mis-schedule, BUG-002).
- **Blocked/not-tested cases:** 1 runtime test attempt blocked by DB access; most functional/accounting/UI/runtime scenarios not executed (see Section H/C).
- **Critical issues:** 1 (BUG-001).
- **High-priority issues:** 2 (BUG-002, BUG-003).
- **Medium-priority issues:** 6 risk items documented (RISK-001–005, RISK-007) plus runtime validation gaps.
- **Low-priority issues:** 2 (RISK-002 overlap/UX clarity aspects, RISK-006).

**Production readiness:** **NOT READY** (static evidence shows critical/high issues and key runtime/accounting flows are unverified in this environment). Address P0/P1 items and execute full disposable-DB functional/accounting/regression tests before production use.
