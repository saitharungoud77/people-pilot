import datetime

import streamlit as st

from modules.payslip import (
    MONTHS,
    get_employees_with_salary,
    latest_released_payroll_period,
    parse_joining_date,
    payroll_day_counts,
    payroll_stops_after
)
from modules.settlement import last_accrual_period
from database.connection import get_connection
from modules.salary import (
    EPS_RATE,
    EPS_WAGE_CEILING_MONTHLY,
    PF_WAGE_CEILING_MONTHLY,
    PF_RATE,
)


# ============================================================
# PROVIDENT FUND (EPFO) — DATA
# ============================================================
# Month-by-month EPFO statement: employee EPF and employer EPF are
# added to the PF balance; employer EPS is shown separately.

def epfo_components(breakdown):
    """Monthly EPFO split derived from a payslip breakdown."""

    employee_pf = round(float(breakdown["employee_pf"]), 2)
    employer_contribution = round(float(breakdown["employer_pf"]), 2)
    basic = round(float(breakdown["basic"]), 2)
    pensionable_wages = min(
        max(0.0, float(
            breakdown.get("pf_wages", min(basic, PF_WAGE_CEILING_MONTHLY))
        )),
        EPS_WAGE_CEILING_MONTHLY
    )
    expected_employer_contribution = round(
        pensionable_wages * PF_RATE, 2
    )
    employer_eps = (
        round(employer_contribution * (EPS_RATE / PF_RATE), 2)
        if employer_contribution < expected_employer_contribution - 0.01
        else round(pensionable_wages * EPS_RATE, 2)
    )
    employer_epf = round(employer_contribution - employer_eps, 2)

    return {
        "pf_wages": round(pensionable_wages, 2),
        "employee_epf": employee_pf,
        "employee_vpf": 0.0,
        "employer_epf": employer_epf,
        "employer_eps": employer_eps,
        "employer_total": round(employer_contribution, 2),
        "total_contribution": round(
            employee_pf + employer_contribution, 2
        ),
        "monthly_credit": round(employee_pf + employer_epf, 2),
    }


def epfo_statement(employee, year, month):
    """Month-by-month EPFO statement for one employee.

    Includes only released, saved payslips. Each row carries its
    calendar year/month so the caller can group rows into Indian
    financial years (April-March). No interest is applied.
    """

    joining = parse_joining_date(employee[4])
    today = datetime.date.today()
    released_period = latest_released_payroll_period(today)
    exit_period = last_accrual_period(employee[0], today)
    through_period = min((year, month), released_period, exit_period)
    settlement_period = payroll_stops_after(employee[0])

    if settlement_period:
        through_period = min(through_period, settlement_period)

    if (
        joining is None
        or through_period < (joining.year, joining.month)
    ):

        return []

    connection = get_connection()

    try:
        payslips = connection.execute(
            """
            SELECT
                pay_year,
                pay_month,
                basic_monthly,
                employee_pf_monthly,
                employer_pf_monthly
            FROM payslips
            WHERE employee_id = ?
              AND (pay_year < ? OR (pay_year = ? AND pay_month <= ?))
            ORDER BY pay_year, pay_month
            """,
            (
                employee[0],
                through_period[0],
                through_period[0],
                through_period[1]
            )
        ).fetchall()
    finally:
        connection.close()

    rows = []
    balance = 0.0

    for pay_year, pay_month, basic, employee_pf, employer_pf in payslips:
        if (pay_year, pay_month) < (joining.year, joining.month):
            continue

        day_counts = payroll_day_counts(employee[4], pay_year, pay_month)
        proration_factor = (
            day_counts["paid_days"] / day_counts["calendar_days"]
            if day_counts["calendar_days"]
            else 1.0
        )
        unprorated_basic = (
            basic / proration_factor
            if proration_factor
            else 0.0
        )
        pf_wages = min(
            max(0.0, unprorated_basic),
            EPS_WAGE_CEILING_MONTHLY
        ) * proration_factor

        components = epfo_components({
            "basic": basic,
            "pf_wages": pf_wages,
            "employee_pf": employee_pf,
            "employer_pf": employer_pf
        })
        monthly_credit = components["monthly_credit"]
        balance = round(balance + monthly_credit, 2)

        rows.append({
            "period": f"{MONTHS[pay_month - 1]} {pay_year}",
            "year": pay_year,
            "month_number": pay_month,
            "pf_wages": components["pf_wages"],
            "employee_vpf": components["employee_vpf"],
            "employee_epf": components["employee_epf"],
            "employer_epf": components["employer_epf"],
            "employer_eps": components["employer_eps"],
            "total_contribution": components["total_contribution"],
            "balance": balance
        })

    return rows


def epfo_table_rows(rows, include_total=False):
    """Turn statement rows into display-ready table rows.

    Show employee EPF, employer EPF, and employer EPS separately.
    EPS is not included in the running PF balance.
    """

    display = [
        {
            "Period": row["period"],
            "PF Wages": row["pf_wages"],
            "Your EPF (12%)": row["employee_epf"],
            "VPF": row["employee_vpf"],
            "Employer EPF": row["employer_epf"],
            "Employer EPS (8.33%)": row["employer_eps"],
            "Total Contribution": row["total_contribution"]
        }
        for row in rows
    ]

    if include_total and rows:

        display.append({
            "Period": "Total",
            "PF Wages": round(
                sum(row["pf_wages"] for row in rows), 2
            ),
            "Your EPF (12%)": round(
                sum(row["employee_epf"] for row in rows), 2
            ),
            "VPF": round(
                sum(row["employee_vpf"] for row in rows), 2
            ),
            "Employer EPF": round(
                sum(row["employer_epf"] for row in rows), 2
            ),
            "Employer EPS (8.33%)": round(
                sum(row["employer_eps"] for row in rows), 2
            ),
            "Total Contribution": round(
                sum(row["total_contribution"] for row in rows), 2
            )
        })

    return display


def render_epfo_section(employee, year, month):
    """EPFO contribution & balance block shown after the payslip."""

    rows = epfo_statement(employee, year, month)

    if not rows:

        st.info(
            "PF contributions will appear after a payslip has been "
            "released and saved for this employee."
        )

        return

    latest = rows[-1]

    st.markdown("---")

    st.subheader(
        "EPFO — Contribution & Balance",
        icon=":material/account_balance:"
    )

    st.caption(
        f"EPFO split for {latest['period']} and the total "
        "PF balance."
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "Employee EPF",
            f"Rs. {latest['employee_epf']:,.2f}",
            border=True
        )

    with col2:

        st.metric(
            "Employer EPF",
            f"Rs. {latest['employer_epf']:,.2f}",
            border=True
        )

    with col3:

        st.metric(
            "Employer Pension (EPS)",
            f"Rs. {latest['employer_eps']:,.2f}",
            border=True
        )

    with col4:

        st.metric(
            "EPF Balance",
            f"Rs. {latest['balance']:,.2f}",
            border=True
        )

    st.markdown("#### Monthly statement")

    st.table(epfo_table_rows(rows, include_total=True))

    st.caption(
        "Employee EPF and the employer's EPF share build the PF balance. "
        "The employer's EPS pension share is shown separately and is not "
        "included in that balance. EPS is calculated at 8.33% of pension "
        f"wages up to the ₹{EPS_WAGE_CEILING_MONTHLY:,.0f} monthly EPS "
        "ceiling; no interest is applied to the EPF balance."
    )


# ============================================================
# PROVIDENT FUND (EPFO) — PAGES
# ============================================================
# A first-class PF view for both roles. It shows the employee
# and employer contributions, the contribution breakup and the
# accumulated balance from the joining month onward, with a
# financial-year (April-March) slicer to filter the statement.

def _fy_start(year, month):
    """Financial year a month belongs to (FY starts in April)."""

    return year if month >= 4 else year - 1


def _fy_label(start):
    """Human label for a financial year, e.g. FY 2024-25."""

    return f"FY {start}-{str(start + 1)[2:]}"


def _render_pf(employee, year, month):
    """Full PF statement for one employee up to a period."""

    rows = epfo_statement(employee, year, month)

    if not rows:

        st.info(
            "PF contributions will appear after the first payslip has "
            "been released and saved."
        )

        return

    # -----------------------------------------------------
    # FINANCIAL-YEAR SLICER (April - March)
    # -----------------------------------------------------

    fy_starts = sorted(
        {_fy_start(row["year"], row["month_number"]) for row in rows},
        reverse=True
    )

    options = [_fy_label(start) for start in fy_starts]

    # Default to the current financial year; the dropdown lets the
    # user pick any other year the employee has contributions in.
    current_fy = _fy_label(_fy_start(year, month))

    default_index = (
        options.index(current_fy) if current_fy in options else 0
    )

    selected = st.selectbox(
        "Financial year",
        options,
        index=default_index,
        key=f"pf_year_{employee[0]}"
    )

    chosen = int(selected.split()[1].split("-")[0])

    visible = [
        row
        for row in rows
        if _fy_start(row["year"], row["month_number"]) == chosen
    ]

    scope = f"in {selected}"

    latest = visible[-1]

    employee_total = round(
        sum(row["employee_epf"] for row in visible),
        2
    )

    employer_total = round(
        sum(row["employer_epf"] for row in visible),
        2
    )
    pension_total = round(
        sum(row["employer_eps"] for row in visible),
        2
    )

    # The balance is the running, from-joining total through the
    # last month shown (no interest applied).
    total_balance = latest["balance"]

    # -----------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------

    st.subheader("Summary", icon=":material/savings:")

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "Employee contribution",
            f"₹ {employee_total:,.2f}",
            delta=scope,
            delta_color="off",
            border=True
        )

    with col2:

        st.metric(
            "Employer EPF",
            f"₹ {employer_total:,.2f}",
            delta=scope,
            delta_color="off",
            border=True
        )

    with col3:

        st.metric(
            "Employer pension / EPS",
            f"₹ {pension_total:,.2f}",
            delta=scope,
            delta_color="off",
            border=True
        )

    col4, col5 = st.columns(2)

    with col4:

        st.metric(
            "EPF balance",
            f"₹ {total_balance:,.2f}",
            delta=f"as of {latest['period']}",
            delta_color="off",
            border=True
        )

    with col5:

        st.metric(
            "Total contributions incl. EPS",
            f"₹ {employee_total + employer_total + pension_total:,.2f}",
            delta=scope,
            delta_color="off",
            border=True
        )

    st.caption(
        "EPF balance includes employee and employer EPF contributions, "
        "but excludes EPS. Total contributions include EPS; no interest "
        "is applied."
    )

    st.divider()

    st.subheader(
        "Contribution breakup (latest month)",
        icon=":material/pie_chart:"
    )

    st.table([
        {
            "Contribution": "Employee EPF",
            "Amount": latest["employee_epf"]
        },
        {
            "Contribution": "Employer EPF",
            "Amount": latest["employer_epf"]
        },
        {
            "Contribution": "Employer Pension (EPS)",
            "Amount": latest["employer_eps"]
        }
    ])

    st.subheader(
        "Month-by-month statement",
        icon=":material/table_chart:"
    )

    st.caption(f"Showing {selected} only.")

    st.table(epfo_table_rows(visible, include_total=True))

    st.caption(
        f"{len(visible)} month(s) shown · Totals added automatically "
        f"for {scope}. The official EPFO statement remains "
        "authoritative."
    )


# ============================================================
# HR PAGE
# ============================================================

def show_epfo_page(go_home=None):
    """HR view: PF statement for any employee."""

    st.title(
        "Provident Fund (EPFO)",
        icon=":material/account_balance:"
    )

    st.caption(
        "Employee and employer PF contributions with the "
        "accumulated balance from the joining month."
    )

    employees = get_employees_with_salary()

    if not employees:

        st.warning(
            "No salary structures found. "
            "Create an employee salary structure first."
        )

        return

    options = {
        f"{row[1]}  ({row[0]})": row
        for row in employees
    }

    selected = st.selectbox(
        "Select Employee",
        list(options.keys()),
        key="epfo_employee"
    )

    employee = options[selected]

    today = datetime.date.today()

    year, month = last_accrual_period(employee[0], today)

    _render_pf(employee, year, month)


# ============================================================
# EMPLOYEE PAGE
# ============================================================

def show_my_epfo():
    """Employee view: the signed-in employee's own PF statement."""

    user = st.session_state.get("auth_user") or {}

    employee_id = user.get("employee_id")

    if not employee_id:

        return

    st.title(
        "My Provident Fund (EPFO)",
        icon=":material/account_balance:"
    )

    st.caption(
        "Your employee and employer PF contributions with the "
        "accumulated balance from your joining month."
    )

    employee = None

    for candidate in get_employees_with_salary():

        if candidate[0] == employee_id:

            employee = candidate

            break

    if employee is None:

        st.info(
            "PF details are not available yet because your salary "
            "structure has not been set up. Please contact HR."
        )

        return

    today = datetime.date.today()

    year, month = last_accrual_period(employee_id, today)

    _render_pf(employee, year, month)