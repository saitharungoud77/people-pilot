import csv
import datetime
import io
import os

import streamlit as st

from database.connection import get_connection

from modules.config import get_secret, has_secret

from modules.offer_letter import ai_available

from modules.payslip import (
    MONTHS,
    build_monthly_breakdown,
    get_employees_with_salary,
    month_days
)

from modules.workdays import holiday_date_set, is_working_day
from modules.salary import PF_RATE, PF_WAGE_CEILING_MONTHLY


# ============================================================
# AI PAYROLL AUDIT
# ============================================================
# Before payroll is locked, HR wants one screen that answers a
# simple question: "what looks wrong this month?".
#
# Every check below is plain arithmetic on data the app already
# stores (salary structure, payslips, attendance, leave, bills).
# The AI never decides whether something is wrong - it only reads
# the findings and writes a short brief in plain English, so a
# wrong answer can never hide a real problem.

# How far a number may drift before it is called a mismatch.
# One rupee of rounding is not a payroll issue.
TOLERANCE = 1.0

SEVERITY_ORDER = {
    "High": 0,
    "Medium": 1,
    "Low": 2
}

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")


# ---------------------------------------------------------
# SMALL HELPERS
# ---------------------------------------------------------

def _period(year, month):
    """'2026-10' for the given pay period."""

    return f"{year}-{month:02d}"


def _month_bounds(year, month):

    start = datetime.date(year, month, 1)

    end = datetime.date(year, month, month_days(month, year))

    return start, end


def _nice(day):
    """'05 Oct' for a date or ISO string."""

    if isinstance(day, str):

        try:

            day = datetime.date.fromisoformat(day)

        except ValueError:

            return str(day)

    return day.strftime("%d %b")


def _money(value):

    return f"{float(value or 0):,.2f}"


def _as_date(value):

    if isinstance(value, datetime.date):

        return value

    try:

        return datetime.date.fromisoformat(str(value).strip())

    except (TypeError, ValueError):

        return None


def _previous_period(year, month):

    if month == 1:

        return year - 1, 12

    return year, month - 1


# ---------------------------------------------------------
# DATA
# ---------------------------------------------------------

def _active_employees(year, month):
    """Employees on roll in the period, with their salary structure.

    Returns (rows, missing_structure) where each row is the tuple
    ``build_monthly_breakdown`` expects. Employees who do not have
    a structure yet are returned separately so the audit can flag
    them instead of silently skipping them.
    """

    start, _ = _month_bounds(year, month)

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                e.employee_id,
                e.employee_name,
                e.joining_date,
                COALESCE(e.exit_date, '') AS exit_date,
                s.id
            FROM employees e
            LEFT JOIN salary_structures s
                ON e.employee_id = s.employee_id
            ORDER BY e.employee_name
            """
        ).fetchall()

    finally:

        connection.close()

    on_roll = []

    missing = []

    for employee_id, name, joining, exit_date, structure_id in rows:

        joined = _as_date(joining)

        left = _as_date(exit_date) if exit_date else None

        # Anyone joining after this month, or already gone before it,
        # is not part of this payroll run.
        if joined and joined > _month_bounds(year, month)[1]:

            continue

        if left and left < start:

            continue

        on_roll.append(employee_id)

        if structure_id is None:

            missing.append((employee_id, name))

    structures = {
        row[0]: row
        for row in get_employees_with_salary()
    }

    entries = [
        structures[employee_id]
        for employee_id in on_roll
        if employee_id in structures
    ]

    return entries, missing


def _payslip(employee_id, year, month):
    """The saved payslip row as a dict, or None."""

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT
                employee_id,
                pay_month,
                pay_year,
                basic_monthly,
                hra_monthly,
                special_allowance_monthly,
                other_allowance_monthly,
                gross_monthly,
                employee_pf_monthly,
                employer_pf_monthly,
                professional_tax_monthly,
                other_deduction_monthly,
                total_deductions,
                net_pay,
                lop_days,
                lop_amount
            FROM payslips
            WHERE employee_id = ?
              AND pay_year = ?
              AND pay_month = ?
            """,
            (employee_id, year, month)
        ).fetchone()

    finally:

        connection.close()

    if row is None:

        return None

    keys = [
        "employee_id",
        "pay_month",
        "pay_year",
        "basic",
        "hra",
        "special",
        "other_allowance",
        "gross",
        "employee_pf",
        "employer_pf",
        "professional_tax",
        "other_deduction",
        "total_deductions",
        "net_pay",
        "lop_days",
        "lop_amount"
    ]

    return dict(zip(keys, row))


def _attendance_for_month(year, month):
    """Every attendance row in the period, keyed by employee."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT employee_id, att_date, status, in_time, out_time
            FROM attendance
            WHERE substr(att_date, 1, 7) = ?
            """,
            (_period(year, month),)
        ).fetchall()

    finally:

        connection.close()

    by_employee = {}

    for employee_id, att_date, status, in_time, out_time in rows:

        by_employee.setdefault(employee_id, []).append(
            {
                "date": att_date,
                "status": status,
                "in_time": in_time,
                "out_time": out_time
            }
        )

    return by_employee


def _approved_leave_dates(year, month):
    """Working dates covered by approved leave, per employee."""

    start, end = _month_bounds(year, month)

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT employee_id, from_date, to_date, leave_type
            FROM leave_requests
            WHERE status = 'Approved'
              AND from_date <= ?
              AND to_date >= ?
            """,
            (end.isoformat(), start.isoformat())
        ).fetchall()

    finally:

        connection.close()

    skip = holiday_date_set({year})

    covered = {}

    for employee_id, from_value, to_value, leave_type in rows:

        first = _as_date(from_value)

        last = _as_date(to_value)

        if first is None or last is None:

            continue

        first = max(first, start)

        last = min(last, end)

        day = first

        one_day = datetime.timedelta(days=1)

        while day <= last:

            if is_working_day(day, skip):

                covered.setdefault(employee_id, set()).add(
                    day.isoformat()
                )

            day += one_day

    return covered


def _working_dates(year, month, joined=None, today=None):
    """Working dates in the period, up to yesterday when it is current.

    Today itself is left out: the employee may still be at work, so
    an empty record is not yet a missing day.
    """

    start, end = _month_bounds(year, month)

    if joined and joined > start:

        start = joined

    if today and today < end:

        end = today - datetime.timedelta(days=1)

        if end < start:

            return []

    skip = holiday_date_set({year})

    dates = []

    day = start

    one_day = datetime.timedelta(days=1)

    while day <= end:

        if is_working_day(day, skip):

            dates.append(day.isoformat())

        day += one_day

    return dates


def _duplicate_bills():
    """Open claims that look like the same bill filed twice."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                employee_id,
                amount,
                expense_date,
                COUNT(*) AS claims,
                GROUP_CONCAT(category, ', ') AS categories
            FROM reimbursements
            WHERE status IN ('Pending', 'Approved')
            GROUP BY employee_id, amount, expense_date
            HAVING COUNT(*) > 1
            """
        ).fetchall()

    finally:

        connection.close()

    return rows


def _employee_names():
    """employee_id -> name, for messages about bills."""

    connection = get_connection()

    try:

        return {
            row[0]: row[1]
            for row in connection.execute(
                "SELECT employee_id, employee_name FROM employees"
            ).fetchall()
        }

    finally:

        connection.close()


# ---------------------------------------------------------
# CHECKS
# ---------------------------------------------------------

def _finding(severity, employee_id, name, check, detail, action):

    return {
        "severity": severity,
        "employee_id": employee_id or "",
        "employee_name": name or "",
        "check": check,
        "detail": detail,
        "action": action
    }


def _audit_employee(
    employee,
    year,
    month,
    payslip,
    previous,
    attendance,
    leave_dates,
    today
):
    """Run every per-employee check. Returns a list of findings."""

    findings = []

    (
        employee_id,
        name,
        _department,
        _designation,
        joining_date,
        _location,
        _employment_type,
        _annual_ctc,
        *_rest
    ) = employee

    joined = _as_date(joining_date)

    expected = build_monthly_breakdown(employee, year, month)

    # --- no payslip -------------------------------------------

    if payslip is None:

        findings.append(
            _finding(
                "High",
                employee_id,
                name,
                "No payslip",
                f"No payslip exists for {MONTHS[month - 1]} {year}, "
                f"so this employee would be missed on payday.",
                "Open Payslips and generate this month's payslip."
            )
        )

        # Without a payslip there is nothing to compare, so the
        # remaining money checks are skipped for this person.
        return findings, expected

    # --- payslip out of sync with the salary structure --------

    net_gap = float(payslip["net_pay"] or 0) - float(
        expected["net_pay"] or 0
    )

    if abs(net_gap) > TOLERANCE:

        findings.append(
            _finding(
                "High",
                employee_id,
                name,
                "Payslip out of date",
                f"The saved payslip nets {_money(payslip['net_pay'])} "
                f"but the current salary structure and approved leave "
                f"give {_money(expected['net_pay'])} "
                f"({'+' if net_gap > 0 else ''}{_money(net_gap)}).",
                "Regenerate the payslip so it matches the structure."
            )
        )

    # --- LOP spike --------------------------------------------

    lop_days = float(payslip["lop_days"] or 0)

    previous_lop = float(previous["lop_days"] or 0) if previous else 0.0

    if lop_days >= 5:

        findings.append(
            _finding(
                "Medium",
                employee_id,
                name,
                "High loss of pay",
                f"{lop_days:g} LOP day(s) this month, so "
                f"{_money(payslip['lop_amount'])} is being deducted.",
                "Check the approved Loss of Pay leave and attendance "
                "before locking payroll."
            )
        )

    elif previous and lop_days - previous_lop >= 3:

        findings.append(
            _finding(
                "Medium",
                employee_id,
                name,
                "LOP jump",
                f"LOP rose from {previous_lop:g} day(s) last month to "
                f"{lop_days:g} this month.",
                "Confirm the absence is real and was approved."
            )
        )

    # The payslip's LOP must match the approved unpaid leave.
    if abs(lop_days - float(expected["lop_days"] or 0)) > 0.01:

        findings.append(
            _finding(
                "Medium",
                employee_id,
                name,
                "LOP mismatch",
                f"Payslip shows {lop_days:g} LOP day(s); approved "
                f"Loss of Pay leave in the month is "
                f"{float(expected['lop_days'] or 0):g}.",
                "Approve or correct the leave, then regenerate the payslip."
            )
        )

    # --- PF mismatch ------------------------------------------

    basic = float(payslip["basic"] or 0)

    saved_pf = float(payslip["employee_pf"] or 0)

    capped_pf = min(basic, PF_WAGE_CEILING_MONTHLY) * PF_RATE

    pf_is_valid = abs(saved_pf - capped_pf) <= TOLERANCE

    if not pf_is_valid:

        findings.append(
            _finding(
                "High",
                employee_id,
                name,
                "PF mismatch",
                f"Employee PF on the payslip is {_money(saved_pf)}; "
                f"the expected 12% contribution up to the "
                f"₹{PF_WAGE_CEILING_MONTHLY:,.0f} PF wage ceiling is "
                f"{_money(capped_pf)}.",
                "Correct the PF in Salary & payroll, then regenerate."
            )
        )

    # --- impossible net pay -----------------------------------

    net = float(payslip["net_pay"] or 0)

    gross = float(payslip["gross"] or 0)

    deductions = float(payslip["total_deductions"] or 0)

    if net <= 0:

        findings.append(
            _finding(
                "High",
                employee_id,
                name,
                "Zero or negative pay",
                f"Net pay is {_money(net)} on a gross of {_money(gross)}.",
                "Fix the deductions or LOP before running payroll."
            )
        )

    elif gross > 0 and deductions > gross * 0.5:

        findings.append(
            _finding(
                "Medium",
                employee_id,
                name,
                "Deductions above 50%",
                f"Deductions of {_money(deductions)} are more than half "
                f"of the {_money(gross)} gross.",
                "Check for an unusually large PF, LOP or other deduction."
            )
        )

    # --- corrupt components -----------------------------------

    parts = [
        float(payslip["basic"] or 0),
        float(payslip["hra"] or 0),
        float(payslip["special"] or 0),
        float(payslip["other_allowance"] or 0)
    ]

    if abs(sum(parts) - gross) > TOLERANCE:

        findings.append(
            _finding(
                "High",
                employee_id,
                name,
                "Broken salary split",
                f"Components add up to {_money(sum(parts))} but the "
                f"payslip gross is {_money(gross)}.",
                "Regenerate the payslip and check the salary structure."
            )
        )

    # --- attendance not recorded ------------------------------

    rows = attendance.get(employee_id, [])

    recorded = {row["date"] for row in rows}

    leave = leave_dates.get(employee_id, set())

    expected_days = _working_dates(year, month, joined=joined, today=today)

    missing_days = [
        day
        for day in expected_days
        if day not in recorded and day not in leave
    ]

    if missing_days:

        shown = ", ".join(_nice(day) for day in missing_days[:4])

        if len(missing_days) > 4:

            shown += f" +{len(missing_days) - 4} more"

        findings.append(
            _finding(
                "High" if len(missing_days) >= 3 else "Medium",
                employee_id,
                name,
                "Missing attendance",
                f"{len(missing_days)} working day(s) have no attendance "
                f"record and no approved leave ({shown}).",
                "Ask the employee to regularise, or HR can add the day."
            )
        )

    # --- present but no clock times ---------------------------

    no_times = [
        row
        for row in rows
        if row["status"] in ("Present", "Work From Home")
        and not (row["in_time"] or "").strip()
    ]

    if no_times:

        findings.append(
            _finding(
                "Low",
                employee_id,
                name,
                "Clock times missing",
                f"{len(no_times)} present day(s) have no clock-in time.",
                "Ask the employee to use Clock in, or HR can correct it."
            )
        )

    return findings, expected


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

def run_audit(year, month, today=None):
    """Audit one pay period. Returns findings plus counters."""

    today = today or datetime.date.today()

    now_period = _period(today.year, today.month)

    this_period = _period(year, month)

    employees, missing_structure = _active_employees(year, month)

    attendance = _attendance_for_month(year, month)

    leave_dates = _approved_leave_dates(year, month)

    attendance_used = bool(attendance)

    findings = []

    for employee_id, name in missing_structure:

        findings.append(
            _finding(
                "High",
                employee_id,
                name,
                "No salary structure",
                "This employee is on roll but has no salary structure, "
                "so no payslip or PF can be calculated.",
                "Create a salary structure in Salary & payroll."
            )
        )

    for employee in employees:

        employee_id = employee[0]

        payslip = _payslip(employee_id, year, month)

        previous_year, previous_month = _previous_period(year, month)

        previous = _payslip(employee_id, previous_year, previous_month)

        if not attendance_used:

            # If nobody has attendance for the month, the module was
            # not in use; flagging every day for every person would
            # be noise, not an audit.
            employee_findings, _expected = _audit_employee(
                employee,
                year,
                month,
                payslip,
                previous,
                {},
                leave_dates,
                today if this_period == now_period else None
            )

            employee_findings = [
                item
                for item in employee_findings
                if item["check"] != "Missing attendance"
            ]

        else:

            employee_findings, _expected = _audit_employee(
                employee,
                year,
                month,
                payslip,
                previous,
                attendance,
                leave_dates,
                today if this_period == now_period else None
            )

        findings.extend(employee_findings)

    # --- duplicate bills (not tied to one employee's payslip) ---

    names = _employee_names()

    for employee_id, amount, expense_date, claims, categories in _duplicate_bills():

        findings.append(
            _finding(
                "Medium",
                employee_id,
                names.get(employee_id, employee_id),
                "Possible duplicate bills",
                f"{claims} open claims of {_money(amount)} on "
                f"{_nice(expense_date)} ({categories}).",
                "Open Reimbursements and compare the receipts before paying."
            )
        )

    findings.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(item["severity"], 9),
            item["employee_name"]
        )
    )

    counts = {
        "High": sum(1 for item in findings if item["severity"] == "High"),
        "Medium": sum(1 for item in findings if item["severity"] == "Medium"),
        "Low": sum(1 for item in findings if item["severity"] == "Low")
    }

    return {
        "year": year,
        "month": month,
        "employees": len(employees) + len(missing_structure),
        "findings": findings,
        "counts": counts,
        "attendance_used": attendance_used,
        "missing_structure": missing_structure
    }


# ---------------------------------------------------------
# AI BRIEF
# ---------------------------------------------------------

AUDIT_PROMPT = """You are the payroll auditor for AIT Solutions, an Indian
company. Below are the findings from an automated audit of one pay period.

Write a short brief for the HR manager:
- One sentence overall verdict (clean, or how serious it is).
- Then at most 5 bullets, most serious first, in plain English.
- End with the single most important next action.
- Use only the findings. Do not invent numbers, names or causes.
- Keep it under 130 words. No headings, no markdown tables."""


def audit_brief(result, model=DEFAULT_MODEL):
    """Ask the model to summarise the findings in plain English."""

    from openai import OpenAI

    findings = result["findings"]

    if not findings:

        return (
            "The audit found no issues for this period. Payslips match "
            "the salary structures, PF is correct and attendance is "
            "complete. You can lock payroll."
        )

    lines = [
        f"- [{item['severity']}] {item['employee_name']} "
        f"({item['employee_id']}): {item['check']} — {item['detail']}"
        for item in findings
    ]

    client = OpenAI(api_key=get_secret("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": AUDIT_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Pay period: {MONTHS[result['month'] - 1]} "
                    f"{result['year']}\n"
                    f"Employees audited: {result['employees']}\n"
                    f"High: {result['counts']['High']}, "
                    f"Medium: {result['counts']['Medium']}, "
                    f"Low: {result['counts']['Low']}\n\n"
                    + "\n".join(lines)
                )
            }
        ]
    )

    return (response.choices[0].message.content or "").strip()


# ---------------------------------------------------------
# EXPORT
# ---------------------------------------------------------

def findings_csv(result):
    """The findings as a UTF-8 CSV ready for Excel."""

    buffer = io.StringIO()

    writer = csv.writer(buffer)

    writer.writerow(
        ["Severity", "Employee ID", "Employee", "Check", "Detail", "Action"]
    )

    for item in result["findings"]:

        writer.writerow(
            [
                item["severity"],
                item["employee_id"],
                item["employee_name"],
                item["check"],
                item["detail"],
                item["action"]
            ]
        )

    return buffer.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------
# PAGE
# ---------------------------------------------------------

def show_payroll_audit_page(go_home=None):
    """HR: audit the month with plain arithmetic plus an AI brief."""

    user = st.session_state.get("auth_user") or {}

    if user.get("role") != "hr":

        st.error("This screen is only available to HR.")

        st.stop()

    st.title("AI payroll audit", icon=":material/troubleshoot:")

    st.caption(
        "Every check runs on your own payroll data before you lock it. "
        "AI then writes the brief — it never changes a number."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="audit_back",
        width="content"
    ):

        go_home()

        st.rerun()

    today = datetime.date.today()

    available, reason = ai_available()

    if not available:

        st.info(
            reason + " The audit table below still works without it."
        )

    # -----------------------------------------------------
    # PERIOD
    # -----------------------------------------------------

    col1, col2 = st.columns([2, 1])

    with col1:

        month = st.selectbox(
            "Pay month",
            list(range(1, 13)),
            index=today.month - 1,
            format_func=lambda value: MONTHS[value - 1],
            key="audit_month"
        )

    with col2:

        years = list(range(today.year, today.year - 4, -1))

        year = st.selectbox(
            "Pay year",
            years,
            index=0,
            key="audit_year"
        )

    result = run_audit(year, month)

    findings = result["findings"]

    period = _period(year, month)

    # -----------------------------------------------------
    # NUMBERS
    # -----------------------------------------------------

    st.space("small")

    with st.container(horizontal=True):

        st.metric(
            "Employees audited",
            result["employees"],
            icon=":material/groups:",
            border=True
        )

        st.metric(
            "High priority",
            result["counts"]["High"],
            icon=":material/error:",
            border=True
        )

        st.metric(
            "Medium priority",
            result["counts"]["Medium"],
            icon=":material/warning:",
            border=True
        )

        st.metric(
            "Low priority",
            result["counts"]["Low"],
            icon=":material/info:",
            border=True
        )

    if not result["attendance_used"]:

        st.info(
            "No attendance was recorded in this month, so the "
            "missing-attendance check was skipped."
        )

    # -----------------------------------------------------
    # AI BRIEF
    # -----------------------------------------------------

    brief = st.session_state.get("audit_brief")

    if st.session_state.get("audit_brief_period") != period:

        brief = None

    if st.button(
        "Write the AI brief",
        key="audit_brief_button",
        type="primary",
        disabled=not available
    ):

        with st.spinner("Reading the findings…"):

            try:

                brief = audit_brief(result)

                st.session_state.audit_brief = brief

                st.session_state.audit_brief_period = period

            except Exception as exc:  # noqa: BLE001

                st.error(f"AI brief failed: {exc}")

    if brief:

        with st.container(border=True):

            st.markdown("**Audit brief**")

            st.markdown(brief)

    # -----------------------------------------------------
    # FINDINGS
    # -----------------------------------------------------

    st.divider()

    if not findings:

        st.success(
            "No issues found. Payslips, PF, attendance and bills all "
            "look consistent for this period."
        )

    else:

        st.subheader(
            f"Findings ({len(findings)})",
            icon=":material/rule:"
        )

        rows = [
            {
                "Severity": item["severity"],
                "Employee": item["employee_name"],
                "ID": item["employee_id"],
                "Check": item["check"],
                "What we found": item["detail"],
                "Suggested action": item["action"]
            }
            for item in findings
        ]

        st.dataframe(
            rows,
            hide_index=True,
            width="stretch",
            column_config={
                "Severity": st.column_config.TextColumn(width="small"),
                "Employee": st.column_config.TextColumn(width="medium"),
                "ID": st.column_config.TextColumn(width="small"),
                "Check": st.column_config.TextColumn(width="small"),
                "What we found": st.column_config.TextColumn(width="large"),
                "Suggested action": st.column_config.TextColumn(width="large")
            }
        )

        st.download_button(
            "Download findings (CSV)",
            data=findings_csv(result),
            file_name=f"payroll-audit-{period}.csv",
            mime="text/csv",
            icon=":material/download:"
        )
