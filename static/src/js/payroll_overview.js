/** @odoo-module **/

import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class PayrollOverview extends Component {
    static template = "kio_payroll_overview_extension.PayrollOverview";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const today = new Date();
        const context = this.props.action?.context || {};
        const currentYear = today.getFullYear();
        const month = Number(context.kio_payroll_month) || today.getMonth() + 1;
        const year = Number(context.kio_payroll_year) || currentYear;
        this.months = [
            [1, "January"], [2, "February"], [3, "March"],
            [4, "April"], [5, "May"], [6, "June"],
            [7, "July"], [8, "August"], [9, "September"],
            [10, "October"], [11, "November"], [12, "December"],
        ];
        const yearAnchor = year || currentYear;
        this.years = Array.from({ length: 11 }, (_, index) => yearAnchor + 2 - index);
        if (!this.years.includes(year)) {
            this.years.unshift(year);
        }
        this.state = useState({
            month,
            year,
            loading: true,
            error: false,
            data: null,
            showPaidEmployees: false,
            paidSearch: "",
            showUnpaidEmployees: false,
            unpaidSearch: "",
        });
        onWillStart(async () => {
            await this.loadDashboard();
        });
        onWillUpdateProps(async (nextProps) => {
            const nextContext = nextProps.action?.context || {};
            let changed = false;
            if (nextContext.kio_payroll_month && Number(nextContext.kio_payroll_month) !== this.state.month) {
                this.state.month = Number(nextContext.kio_payroll_month);
                changed = true;
            }
            if (nextContext.kio_payroll_year && Number(nextContext.kio_payroll_year) !== this.state.year) {
                this.state.year = Number(nextContext.kio_payroll_year);
                changed = true;
            }
            await this.loadDashboard();
        });
    }

    async loadDashboard() {
        this.state.loading = true;
        this.state.error = false;
        try {
            this.state.data = await this.orm.call(
                "kio.payroll.payslip",
                "get_payroll_overview_data",
                [Number(this.state.month), Number(this.state.year)]
            );
        } catch (error) {
            this.state.error = true;
            this.state.data = null;
            this.notification.add(
                error.data?.message || error.message || "Unable to load Payroll Overview.",
                { type: "danger", title: "Payroll Overview" }
            );
        } finally {
            this.state.loading = false;
        }
    }

    async onFilterChange() {
        await this.loadDashboard();
    }

    openEmployees() {
        return this.action.doAction("hr.open_view_employee_list_my");
    }

    onEmployeeKpiKeydown(event) {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            this.openEmployees();
        }
    }

    togglePaidEmployees() {
        this.state.showUnpaidEmployees = false;
        this.state.showPaidEmployees = !this.state.showPaidEmployees;
    }

    onPaidKpiKeydown(event) {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            this.togglePaidEmployees();
        }
    }

    toggleUnpaidEmployees() {
        this.state.showPaidEmployees = false;
        this.state.showUnpaidEmployees = !this.state.showUnpaidEmployees;
    }

    onUnpaidKpiKeydown(event) {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            this.toggleUnpaidEmployees();
        }
    }

    get unpaidEmployees() {
        return this.state.data?.unpaid_employees || [];
    }

    get filteredUnpaidEmployees() {
        const search = (this.state.unpaidSearch || "").trim().toLowerCase();
        if (!search) {
            return this.unpaidEmployees;
        }
        return this.unpaidEmployees.filter((row) =>
            [
                row.name,
                row.employee_name,
                row.identification_id,
                row.department,
                row.batch_name,
                row.payment_state_label,
            ].some((value) => (value || "").toLowerCase().includes(search))
        );
    }

    get unpaidEmployeesSummary() {
        const rows = this.unpaidEmployees;
        const totalUnpaid = rows.reduce(
            (acc, row) =>
                acc +
                (Number(
                    row.unpaid_amount != null
                        ? row.unpaid_amount
                        : row.net_pay
                ) || 0),
            0
        );
        return {
            count: rows.length,
            total_unpaid: totalUnpaid,
        };
    }

    get filteredUnpaidEmployeesTotals() {
        const rows = this.filteredUnpaidEmployees;
        return {
            basic_salary: rows.reduce(
                (acc, r) => acc + (Number(r.basic_salary) || 0),
                0
            ),
            allowance: rows.reduce(
                (acc, r) => acc + (Number(r.allowance) || 0),
                0
            ),
            bonus: rows.reduce((acc, r) => acc + (Number(r.bonus) || 0), 0),
            deduction: rows.reduce(
                (acc, r) => acc + (Number(r.deduction) || 0),
                0
            ),
            net_pay: rows.reduce((acc, r) => acc + (Number(r.net_pay) || 0), 0),
            unpaid_amount: rows.reduce(
                (acc, r) =>
                    acc +
                    (Number(
                        r.unpaid_amount != null
                            ? r.unpaid_amount
                            : r.net_pay
                    ) || 0),
                0
            ),
        };
    }

    async onPayNow(row) {
        if (!row || !row.slip_id) {
            this.notification.add("No payslip associated with this employee.", {
                type: "danger",
                title: "Pay Now",
            });
            return;
        }
        if (row.paid) {
            this.notification.add(
                `Payment for ${row.name || "this employee"} is already completed.`,
                {
                    type: "warning",
                    title: "Pay Now",
                }
            );
            return;
        }

        try {
            const action = await this.orm.call(
                "kio.payroll.payslip",
                "action_payroll_pay_now",
                [row.slip_id]
            );
            if (action) {
                await this.action.doAction(action, {
                    onClose: async () => {
                        await this.loadDashboard();
                    },
                });
            }
        } catch (error) {
            const message =
                error.data?.message ||
                error.message ||
                "Unable to open payment register wizard.";
            this.notification.add(message, {
                type: "danger",
                title: "Pay Now",
            });
        }
    }

    async onDownloadPayslip(row) {
        if (!row || !row.slip_id) {
            this.notification.add("No payslip associated with this employee.", {
                type: "danger",
                title: "Download Payslip",
            });
            return;
        }

        try {
            const action = await this.orm.call(
                "kio.payroll.payslip",
                "action_payroll_download_payslip",
                [row.slip_id]
            );
            if (action) {
                await this.action.doAction(action);
            }
        } catch (error) {
            const message =
                error.data?.message ||
                error.message ||
                "Unable to download payslip.";
            this.notification.add(message, {
                type: "danger",
                title: "Download Payslip",
            });
        }
    }

    get paidEmployees() {
        return this.state.data?.paid_employees || [];
    }

    get filteredPaidEmployees() {
        const search = (this.state.paidSearch || "").trim().toLowerCase();
        if (!search) {
            return this.paidEmployees;
        }
        return this.paidEmployees.filter((row) =>
            [
                row.name,
                row.employee_name,
                row.identification_id,
                row.department,
                row.batch_name,
                row.payment_state_label,
            ].some((value) => (value || "").toLowerCase().includes(search))
        );
    }

    get paidEmployeesSummary() {
        const rows = this.paidEmployees;
        const totalPaid = rows.reduce(
            (acc, row) => acc + (Number(row.paid_amount) || 0),
            0
        );
        return {
            count: rows.length,
            total_paid: totalPaid,
        };
    }

    get filteredPaidEmployeesTotals() {
        const rows = this.filteredPaidEmployees;
        return {
            net_salary: rows.reduce((acc, r) => acc + (Number(r.net_salary) || 0), 0),
            paid_amount: rows.reduce((acc, r) => acc + (Number(r.paid_amount) || 0), 0),
        };
    }

    formatAmount(value) {
        return new Intl.NumberFormat("en-BD", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(Number(value || 0));
    }

    onAvatarError(event) {
        const fallback = "/web/static/img/user_placeholder.jpg";
        if (!event.currentTarget.src.endsWith(fallback)) {
            event.currentTarget.src = fallback;
        }
    }

    openBatch(batchId) {
        return this.action.doAction({
            type: "ir.actions.client",
            tag: "kio_payroll_overview.batch_details",
            name: "Payroll Batch Details",
            target: "current",
            context: {
                kio_batch_id: batchId,
                kio_payroll_month: this.state.month,
                kio_payroll_year: this.state.year,
            },
        });
    }

    onBatchKeydown(event, batchId) {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            this.openBatch(batchId);
        }
    }

    batchStatusClass(state) {
        const classes = {
            draft: "text-bg-secondary",
            verify: "text-bg-warning",
            close: "text-bg-info",
            done: "text-bg-success",
            paid: "text-bg-success",
            cancel: "text-bg-danger",
        };
        return classes[state] || "text-bg-light text-dark border";
    }

    formatCurrency(value) {
        const amount = Number(value || 0);
        try {
            return new Intl.NumberFormat("en-BD", {
                style: "currency",
                currency: "BDT",
                currencyDisplay: "code",
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            }).format(amount);
        } catch {
            return `BDT ${amount.toFixed(2)}`;
        }
    }

    formatDate(value) {
        if (!value) {
            return "-";
        }
        try {
            const date = new Date(`${String(value).slice(0, 10)}T00:00:00`);
            return new Intl.DateTimeFormat("en-GB", {
                day: "2-digit",
                month: "short",
                year: "numeric",
            }).format(date);
        } catch {
            return String(value);
        }
    }

    openBonusManagement() {
        return this.action.doAction(
            "kio_payroll_overview_extension.action_kio_bonus"
        );
    }

    openNewPayrollGeneration() {
        return this.action.doAction(
            "kio_payroll_overview_extension.action_new_payroll_generation",
            {
                additionalContext: {
                    kio_payroll_month: this.state.month,
                    kio_payroll_year: this.state.year,
                },
            }
        );
    }
}

export class NewPayrollGeneration extends Component {
    static template = "kio_payroll_overview_extension.NewPayrollGeneration";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const today = new Date();
        const context = this.props.action?.context || {};
        const month = Number(context.kio_payroll_month) || today.getMonth() + 1;
        const year = Number(context.kio_payroll_year) || today.getFullYear();
        this.months = [
            [1, "January"], [2, "February"], [3, "March"],
            [4, "April"], [5, "May"], [6, "June"],
            [7, "July"], [8, "August"], [9, "September"],
            [10, "October"], [11, "November"], [12, "December"],
        ];
        this.years = Array.from({ length: 11 }, (_, index) => year + 2 - index);
        const bounds = this.getMonthBounds(year, month);
        this.state = useState({
            month,
            year,
            search: "",
            loading: true,
            generating: false,
            error: false,
            data: null,
            employees: [],
            selectedEmployeeIds: [],
            form: {
                name: this.getDefaultName(month, year),
                payroll_type: "monthly",
                payment_date: bounds.end,
                date_start: bounds.start,
                date_end: bounds.end,
            },
        });
        onWillStart(() => this.loadData());
        onWillUpdateProps(async (nextProps) => {
            const nextContext = nextProps.action?.context || {};
            const nextMonth = Number(nextContext.kio_payroll_month);
            const nextYear = Number(nextContext.kio_payroll_year);
            const monthChanged = Boolean(nextMonth) && nextMonth !== this.state.month;
            const yearChanged = Boolean(nextYear) && nextYear !== this.state.year;
            if (!monthChanged && !yearChanged) {
                return;
            }
            if (monthChanged) {
                this.state.month = nextMonth;
            }
            if (yearChanged) {
                this.state.year = nextYear;
            }
            await this.onMonthYearChange();
        });
    }

    pad(value) {
        return String(value).padStart(2, "0");
    }

    getMonthBounds(year, month) {
        const lastDay = new Date(year, month, 0).getDate();
        return {
            start: `${year}-${this.pad(month)}-01`,
            end: `${year}-${this.pad(month)}-${this.pad(lastDay)}`,
        };
    }

    getDefaultName(month, year) {
        const monthLabel = (this.months.find(([value]) => value === month) || [0, ""])[1];
        return `${monthLabel} ${year} Payroll`;
    }

    get filteredEmployees() {
        const search = this.state.search.trim().toLowerCase();
        if (!search) {
            return this.state.employees;
        }
        return this.state.employees.filter((row) => [
            row.name,
            row.identification_id,
            row.department,
            row.designation,
        ].some((value) => (value || "").toLowerCase().includes(search)));
    }

    get selectedCount() {
        return this.state.selectedEmployeeIds.length;
    }

    get canGenerate() {
        const form = this.state.form;
        return Boolean(
            !this.state.loading
            && !this.state.generating
            && this.state.data
            && this.selectedCount > 0
            && form.name
            && form.name.trim()
            && form.date_start
            && form.date_end
            && form.payment_date
            && form.date_end >= form.date_start
        );
    }

    async loadData(selectEligible = true) {
        const { date_start: dateStart, date_end: dateEnd } = this.state.form;
        if (!dateStart || !dateEnd || dateEnd < dateStart) {
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "kio.payroll.payslip",
                "get_new_payroll_run_data",
                [dateStart, dateEnd]
            );
            const employees = Array.isArray(data.employees) ? data.employees : [];
            this.state.data = data;
            this.state.employees = employees;
            const eligibleIds = [
                ...new Set(
                    employees
                        .filter((row) => row.eligible)
                        .map((row) => row.employee_id)
                ),
            ];
            this.state.selectedEmployeeIds = selectEligible
                ? eligibleIds
                : [...new Set(this.state.selectedEmployeeIds)].filter(
                    (employeeId) => eligibleIds.includes(employeeId)
                );
        } catch (error) {
            this.state.error = error.data?.message || error.message ||
                "Unable to load employees for this payroll period.";
            this.notification.add(this.state.error, {
                type: "danger",
                title: "New Payroll Run",
            });
        } finally {
            this.state.loading = false;
        }
    }

    async onMonthYearChange() {
        const bounds = this.getMonthBounds(this.state.year, this.state.month);
        this.state.form.date_start = bounds.start;
        this.state.form.date_end = bounds.end;
        this.state.form.payment_date = bounds.end;
        this.state.form.name = this.getDefaultName(this.state.month, this.state.year);
        await this.loadData();
    }

    async onPeriodChange() {
        if (this.state.form.date_start && this.state.form.date_end) {
            this.state.form.payment_date = this.state.form.date_end;
        }
        await this.loadData();
    }

    isEmployeeSelected(employeeId) {
        return this.state.selectedEmployeeIds.includes(employeeId);
    }

    toggleEmployee(employeeId, event) {
        const selectedIds = new Set(this.state.selectedEmployeeIds);
        if (event.currentTarget.checked) {
            selectedIds.add(employeeId);
        } else {
            selectedIds.delete(employeeId);
        }
        this.state.selectedEmployeeIds = [...selectedIds];
    }

    selectableEmployees() {
        return this.filteredEmployees.filter((row) => row.eligible);
    }

    areAllEmployeesSelected() {
        const rows = this.selectableEmployees();
        return Boolean(rows.length) && rows.every(
            (row) => this.isEmployeeSelected(row.employee_id)
        );
    }

    toggleAllEmployees(event) {
        const selectedIds = new Set(this.state.selectedEmployeeIds);
        for (const row of this.selectableEmployees()) {
            if (event.currentTarget.checked) {
                selectedIds.add(row.employee_id);
            } else {
                selectedIds.delete(row.employee_id);
            }
        }
        this.state.selectedEmployeeIds = [...selectedIds];
    }

    formatAmount(value) {
        if (value === null || value === undefined || value === "") {
            return "—";
        }
        return new Intl.NumberFormat("en-BD", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(Number(value || 0));
    }

    onAvatarError(event) {
        const fallback = "/web/static/img/user_placeholder.jpg";
        if (!event.currentTarget.src.endsWith(fallback)) {
            event.currentTarget.src = fallback;
        }
    }

    openTotalLoans() {
        if (!this.state.data?.loan_available) {
            this.notification.add("The Loans module is not installed.", {
                type: "warning",
            });
            return;
        }
        const employeeIds = this.state.selectedEmployeeIds.length
            ? this.state.selectedEmployeeIds
            : this.state.employees.map((row) => row.employee_id);
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: "Total Loans",
            res_model: "hr.loan",
            view_mode: "list,form",
            target: "current",
            domain: [
                ["employee_id", "in", employeeIds],
                ["company_id", "=", this.state.data.company.id],
                ["state", "=", "approve"],
            ],
        });
    }

    openLeaveManagement() {
        if (!this.state.data?.leave_available) {
            this.notification.add("Leave Management is not available.", {
                type: "warning",
            });
            return;
        }
        return this.action.doAction(this.state.data.leave_action);
    }

    backToOverview() {
        return this.action.doAction(
            "kio_payroll_overview_extension.action_payroll_overview"
        );
    }

    cancelPayroll() {
        this.state.search = "";
        return this.backToOverview();
    }

    async generatePayroll() {
        const form = this.state.form;
        if (!form.name || !form.name.trim()) {
            this.notification.add("Payroll Name is required.", { type: "danger" });
            return;
        }
        if (!form.date_start || !form.date_end || !form.payment_date) {
            this.notification.add("Pay Period and Payment Date are required.", {
                type: "danger",
            });
            return;
        }
        if (form.date_end < form.date_start) {
            this.notification.add(
                "The payroll end date must be on or after the start date.",
                { type: "danger" }
            );
            return;
        }
        if (!this.state.selectedEmployeeIds.length) {
            this.notification.add("Select at least one employee.", {
                type: "danger",
            });
            return;
        }
        this.state.generating = true;
        try {
            await this.orm.call(
                "kio.payroll.payslip",
                "generate_new_payroll_run",
                [{
                    name: form.name.trim(),
                    payroll_type: form.payroll_type,
                    payment_date: form.payment_date,
                    date_start: form.date_start,
                    date_end: form.date_end,
                    employee_ids: this.state.selectedEmployeeIds,
                }]
            );
            const periodDate = new Date(`${String(form.date_start).slice(0, 10)}T00:00:00`);
            this.notification.add("Payroll batch generated successfully.", {
                type: "success",
                title: "New Payroll Run",
            });
            await this.action.doAction(
                "kio_payroll_overview_extension.action_payroll_overview",
                {
                    additionalContext: {
                        kio_payroll_month: periodDate.getMonth() + 1,
                        kio_payroll_year: periodDate.getFullYear(),
                    },
                }
            );
        } catch (error) {
            this.notification.add(
                error.data?.message || error.message ||
                "Payroll generation failed. Please review the payroll period and employees.",
                { type: "danger", title: "New Payroll Run" }
            );
        } finally {
            this.state.generating = false;
        }
    }
}

export class PayrollBatchDetails extends Component {
    static template = "kio_payroll_overview_extension.PayrollBatchDetails";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        const context = this.props.action?.context || {};
        this.batchId = Number(context.kio_batch_id) || Number(context.active_id) || Number(this.props.action?.res_id) || false;
        this.month = Number(context.kio_payroll_month) || false;
        this.year = Number(context.kio_payroll_year) || false;

        this.state = useState({
            loading: true,
            error: false,
            search: "",
            data: null,
            employees: [],
        });

        onWillStart(() => this.loadData());
    }

    async loadData() {
        if (!this.batchId) {
            this.state.error = "No payroll batch selected.";
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        this.state.error = false;
        try {
            const data = await this.orm.call(
                "kio.payroll.payslip",
                "get_payroll_batch_details",
                [this.batchId]
            );
            this.state.data = data;
            const rows = data.employees || data.rows || [];
            this.state.employees = rows.map((row) => ({
                ...row,
                name: row.name || row.employee_name,
                identification_id: row.identification_id || row.employee_identification || "-",
                avatar_url: row.avatar_url || row.employee_avatar_url,
            }));
        } catch (error) {
            this.state.error = error.data?.message || error.message ||
                "Unable to load payroll batch details.";
            this.notification.add(this.state.error, {
                type: "danger",
                title: "Payroll Batch Details",
            });
        } finally {
            this.state.loading = false;
        }
    }

    get filteredEmployees() {
        const search = (this.state.search || "").trim().toLowerCase();
        if (!search) {
            return this.state.employees;
        }
        return this.state.employees.filter((row) => [
            row.name,
            row.identification_id,
            row.department,
            row.designation,
        ].some((value) => (value || "").toLowerCase().includes(search)));
    }

    formatCurrency(value) {
        const amount = Number(value || 0);
        try {
            return new Intl.NumberFormat("en-BD", {
                style: "currency",
                currency: "BDT",
                currencyDisplay: "code",
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            }).format(amount);
        } catch {
            return `BDT ${amount.toFixed(2)}`;
        }
    }

    formatAmount(value) {
        return new Intl.NumberFormat("en-BD", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
        }).format(Number(value || 0));
    }

    formatDate(value) {
        if (!value) {
            return "-";
        }
        try {
            const date = new Date(`${String(value).slice(0, 10)}T00:00:00`);
            return new Intl.DateTimeFormat("en-GB", {
                day: "2-digit",
                month: "short",
                year: "numeric",
            }).format(date);
        } catch {
            return String(value);
        }
    }

    batchStatusClass(state) {
        const classes = {
            draft: "text-bg-secondary",
            verify: "text-bg-warning",
            close: "text-bg-info",
            done: "text-bg-success",
            paid: "text-bg-success",
            cancel: "text-bg-danger",
        };
        return classes[state] || "text-bg-light text-dark border";
    }

    onAvatarError(event) {
        const fallback = "/web/static/img/user_placeholder.jpg";
        if (!event.currentTarget.src.endsWith(fallback)) {
            event.currentTarget.src = fallback;
        }
    }

    backToOverview() {
        return this.action.doAction(
            "kio_payroll_overview_extension.action_payroll_overview",
            {
                additionalContext: {
                    kio_payroll_month: this.month,
                    kio_payroll_year: this.year,
                },
            }
        );
    }

    async openPayNow(row) {
        return this.onPayNow(row);
    }

    async onPayNow(row) {
        if (!row || !row.slip_id) {
            this.notification.add("No payslip associated with this employee.", {
                type: "danger",
                title: "Pay Now",
            });
            return;
        }
        if (row.paid) {
            this.notification.add(
                `Payment for ${row.name || "this employee"} is already completed.`,
                {
                    type: "warning",
                    title: "Pay Now",
                }
            );
            return;
        }

        try {
            const action = await this.orm.call(
                "kio.payroll.payslip",
                "action_payroll_pay_now",
                [row.slip_id]
            );
            if (action) {
                await this.action.doAction(action, {
                    onClose: async () => {
                        await this.loadData();
                    },
                });
            }
        } catch (error) {
            const message = error.data?.message || error.message ||
                "Unable to open payment register wizard.";
            this.notification.add(message, {
                type: "danger",
                title: "Pay Now",
            });
        }
    }

    async onDownloadPayslip(row) {
        if (!row || !row.slip_id) {
            this.notification.add("No payslip associated with this employee.", {
                type: "danger",
                title: "Download Payslip",
            });
            return;
        }

        try {
            const action = await this.orm.call(
                "kio.payroll.payslip",
                "action_payroll_download_payslip",
                [row.slip_id]
            );
            if (action) {
                await this.action.doAction(action);
            }
        } catch (error) {
            const message =
                error.data?.message ||
                error.message ||
                "Unable to download payslip.";
            this.notification.add(message, {
                type: "danger",
                title: "Download Payslip",
            });
        }
    }

    async onShowPayments(row) {
        if (!row || !row.slip_id) {
            this.notification.add("No payslip associated with this employee.", {
                type: "danger",
                title: "Show Payment",
            });
            return;
        }
        try {
            const action = await this.orm.call(
                "kio.payroll.payslip",
                "action_payroll_show_payments",
                [row.slip_id]
            );
            if (action) {
                await this.action.doAction(action);
            }
        } catch (error) {
            const message = error.data?.message || error.message ||
                "Unable to open payments linked to this payslip.";
            this.notification.add(message, {
                type: "danger",
                title: "Show Payment",
            });
        }
    }

}

registry.category("actions").add(
    "kio_payroll_overview.payroll_overview",
    PayrollOverview
);
registry.category("actions").add(
    "kio_payroll_overview.new_payroll_generation",
    NewPayrollGeneration
);
registry.category("actions").add(
    "kio_payroll_overview.batch_details",
    PayrollBatchDetails
);
