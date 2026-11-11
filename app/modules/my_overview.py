import datetime

import streamlit as st

from modules.attendance import get_attendance
from modules.avatar import render_avatar
from modules.epfo import epfo_statement
from modules.holidays import holiday_dates, upcoming_holidays
from modules.leave import get_balance
from modules.payslip import (
    build_payslip_pdf,
    get_employees_with_salary,
    latest_payslip,
    render_payslip_preview,
)

from modules.projects import render_my_projects
from modules.salary import (
    get_structure,
    structure_summary
)
from modules.session import require_employee
from modules.theme import hero


# ============================================================
# MY OVERVIEW (EMPLOYEE HOME)
# ============================================================
# The employee's landing dashboard. It leads with an identity
# card (photo, role, how long they've been with the company),
# then two short rows of figures: pay on top, day-to-day things
# (leave, attendance, next holiday) underneath. The sidebar holds
# shortcuts to employee pages and external portals.


def _tenure(joining_date, today):
    """Human "2 years 3 months" of service, or "" if unreadable."""

    try:

        joined = datetime.date.fromisoformat(str(joining_date))

    except (TypeError, ValueError):

        return ""

    days = (today - joined).days

    if days < 0:

        return ""

    # Under a month, months read as a flat "0 months"; use days.
    if days < 31:

        return f"{days} day" + ("" if days == 1 else "s")

    months = (
        (today.year - joined.year) * 12
        + (today.month - joined.month)
    )

    if today.day < joined.day:

        months -= 1

    years, rest = divmod(months, 12)

    parts = []

    if years:

        parts.append(f"{years} year" + ("" if years == 1 else "s"))

    if rest or not parts:

        parts.append(f"{rest} month" + ("" if rest == 1 else "s"))

    return " ".join(parts)


def _plural(value, word):
    """'36 days' / '1 day' for a (possibly fractional) count."""

    return f"{value:g} {word}" + ("" if value == 1 else "s")


def _working_days_to_date(year, month, day):
    """Weekdays (Mon-Fri), minus holidays, from the 1st up to day."""

    skip = holiday_dates()

    total = 0

    for number in range(1, day + 1):

        current = datetime.date(year, month, number)

        if current.weekday() < 5 and current.isoformat() not in skip:

            total += 1

    return total


def _profile_card(employee, today):
    """Photo on the left, role and facts on the right."""

    with st.container(border=True, key="lift_profile"):

        avatar_col, name_col, facts_col = st.columns(
            [1.1, 3, 4],
            vertical_alignment="center"
        )

        with avatar_col:

            render_avatar(
                employee["employee_name"],
                employee["employee_id"],
                size=108
            )

        with name_col:

            st.markdown(f"#### {employee['employee_name']}")

            st.caption(employee["designation"])

            st.badge(
                employee["employment_type"],
                icon=":material/badge:",
                color="violet"
            )

            tenure = _tenure(employee["joining_date"], today)

            if tenure:

                st.badge(
                    f"{tenure} at AIT",
                    icon=":material/timelapse:",
                    color="blue"
                )

        with facts_col:

            left, right = st.columns(2)

            with left:

                st.caption("EMPLOYEE ID")
                st.markdown(f"**{employee['employee_id']}**")

                st.space("small")

                st.caption("LOCATION")
                st.markdown(f"**{employee['location']}**")

                st.space("small")

                st.caption("HEALTH INSURANCE")
                st.badge(
                    (
                        "Opted"
                        if employee["health_insurance_opted"]
                        else "Not opted"
                    ),
                    icon=":material/health_and_safety:",
                    color=(
                        "green"
                        if employee["health_insurance_opted"]
                        else "gray"
                    )
                )

            with right:

                st.caption("DEPARTMENT")
                st.markdown(f"**{employee['department']}**")

                st.space("small")

                st.caption("JOINING DATE")
                st.markdown(f"**{employee['joining_date']}**")


def _key_figures(employee, today):
    """Pay at a glance: CTC, take-home and PF balance."""

    structure = get_structure(employee["employee_id"])

    net_monthly = 0.0

    if structure:

        _gross, _deductions, net_annual = structure_summary(structure)

        net_monthly = net_annual / 12

    latest = latest_payslip(employee["employee_id"])
    if latest:
        net_monthly = latest["net_pay"]

    # PF balance, auto-computed from the joining month to now.
    pf_balance = None
    total_pf_contributions = None

    for candidate in get_employees_with_salary():

        if candidate[0] == employee["employee_id"]:

            statement = epfo_statement(
                candidate,
                today.year,
                today.month
            )

            if statement:

                pf_balance = statement[-1]["balance"]
                total_pf_contributions = round(
                    sum(row["total_contribution"] for row in statement),
                    2
                )

            break

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "Annual CTC",
            f"₹ {employee['annual_ctc'] / 100000:,.2f} L",
            icon=":material/payments:",
            border=True,
            help="Your total annual cost to company."
        )

    with col2:

        st.metric(
            "Latest net pay" if latest else "Estimated net monthly",
            f"₹ {net_monthly:,.2f}",
            icon=":material/savings:",
            border=True,
            help=(
                f"Take-home from the {latest['period']} released payslip."
                if latest
                else "Estimated take-home from your current salary structure."
            )
        )

    with col3:

        st.metric(
            "EPF balance (excludes EPS)",
            f"₹ {pf_balance:,.2f}" if pf_balance is not None else "—",
            icon=":material/account_balance:",
            border=True,
            help="Employee and employer EPF contributions; excludes EPS."
        )

    with col4:

        st.metric(
            "Total PF contributions",
            (
                f"₹ {total_pf_contributions:,.2f}"
                if total_pf_contributions is not None
                else "—"
            ),
            icon=":material/account_balance:",
            border=True,
            help="Cumulative employee and employer contributions, including EPS."
        )


def _at_a_glance(employee, today, balances):
    """Day-to-day things: leave, attendance and the next holiday."""

    year = today.year

    entitled = sum(row["entitled"] for row in balances)
    used = sum(row["used"] for row in balances)
    left = entitled - used

    entries = get_attendance(
        employee["employee_id"],
        year,
        today.month
    )

    attended = 0.0

    for entry in entries.values():

        if entry["status"] in ("Present", "Work From Home"):

            attended += 1

        elif entry["status"] == "Half Day":

            attended += 0.5

    month_working = _working_days_to_date(
        year,
        today.month,
        today.day
    )

    upcoming = upcoming_holidays(today, limit=1)

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "Leave balance",
            _plural(left, "day"),
            delta=f"of {entitled:g} this year",
            delta_color="off",
            icon=":material/event_available:",
            border=True,
            help="Leave still available after approved leave."
        )

    with col2:

        st.metric(
            "Attendance this month",
            f"{attended:g} / {month_working:g} days",
            delta=(
                f"{attended / month_working * 100:.0f}% so far"
                if month_working
                else None
            ),
            delta_color="off",
            icon=":material/fact_check:",
            border=True,
            help=(
                "Present and work-from-home days against this month's "
                "working days so far (weekends and holidays excluded); "
                "half days count as 0.5."
            )
        )

    with col3:

        if upcoming:

            holiday_date, name = upcoming[0]

            away = (holiday_date - today).days

            if away == 0:

                note = "Today"

            elif away == 1:

                note = "Tomorrow"

            else:

                note = f"in {away} days"

            st.metric(
                "Next holiday",
                name,
                delta=note,
                delta_color="off",
                icon=":material/celebration:",
                border=True,
                help=f"Falls on {holiday_date.strftime('%d %b %Y')}."
            )

        else:

            st.metric(
                "Next holiday",
                "None upcoming",
                icon=":material/event_busy:",
                border=True
            )


def _latest_payslip(employee):
    """Show the newest payslip and provide view and download actions."""

    latest = latest_payslip(employee["employee_id"])
    preview_key = f"overview_payslip_preview_{employee['employee_id']}"
    show_preview = bool(st.session_state.get(preview_key, False))

    with st.container(border=True):

        st.markdown("**Latest payslip**")

        if not latest:

            st.caption("No payslip is available yet.")

            return

        st.metric(
            latest["period"],
            f"₹ {latest['net_pay']:,.2f}",
            delta=f"Gross ₹ {latest['gross']:,.2f}",
            delta_color="off",
            icon=":material/receipt_long:"
        )

        note = f"Deductions ₹ {latest['deductions']:,.2f}"

        if latest["generated"]:

            note += f" · generated {latest['generated']}"

        st.caption(note)

        view_col, download_col = st.columns(2)

        with view_col:
            if st.button(
                "View payslip" if not show_preview else "Hide payslip",
                key=f"overview_view_payslip_{employee['employee_id']}",
                icon=":material/visibility:",
                width="stretch",
            ):
                st.session_state[preview_key] = not show_preview
                st.rerun()

        with download_col:
            st.download_button(
                "Download PDF",
                data=build_payslip_pdf(
                    latest["breakdown"],
                    latest["month"],
                    latest["year"],
                ),
                file_name=(
                    f"payslip_{employee['employee_id']}_"
                    f"{latest['year']}{latest['month']:02d}.pdf"
                ),
                mime="application/pdf",
                key=f"overview_download_payslip_{employee['employee_id']}",
                icon=":material/download:",
                width="stretch",
            )

    if latest and show_preview:
        render_payslip_preview(
            latest["breakdown"],
            latest["month"],
            latest["year"],
        )


def show_portal_home():

    employee = require_employee()

    if employee is None:

        return

    today = datetime.date.today()

    hero(
        f"Welcome back, {employee['employee_name']}",
        f"{employee['designation']} at AIT Solutions",
        icon="waving_hand",
        badges=[
            ("My salary", "payments"),
            ("My payslips", "receipt_long"),
            ("My leave", "event_available"),
            ("My PF", "account_balance"),
        ]
    )

    balances = get_balance(employee["employee_id"], today.year)

    # -----------------------------------------------------
    # WHO YOU ARE
    # -----------------------------------------------------

    _profile_card(employee, today)

    # -----------------------------------------------------
    # PAY
    # -----------------------------------------------------

    _key_figures(employee, today)

    # -----------------------------------------------------
    # EVERYDAY
    # -----------------------------------------------------

    _at_a_glance(employee, today, balances)

    # -----------------------------------------------------
    # PROJECTS
    # -----------------------------------------------------

    render_my_projects(employee["employee_id"])

    # -----------------------------------------------------
    # PAYSLIP
    # -----------------------------------------------------

    _latest_payslip(employee)

    st.caption(
        "Your employment and salary records are managed by HR. "
        "You can update your personal details (contact, family) "
        "anytime from “My details”."
    )
