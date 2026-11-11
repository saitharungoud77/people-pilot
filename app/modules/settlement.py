import datetime

import streamlit as st

from database.connection import (
    get_connection,
    create_settlement_table
)
from modules.payslip import (
    MONTHS,
    month_days,
    parse_joining_date,
    build_monthly_breakdown,
    get_employees_with_salary
)
from modules.leave import get_balance
from modules.salary import GRATUITY_PCT_OF_BASIC


# ============================================================
# FULL & FINAL SETTLEMENT
# ============================================================
# HR processes an employee exit: the final month's pro-rata
# salary, unused Earned Leave encashment, gratuity (when the
# service is 5+ years), notice adjustment and any other
# earnings/recoveries. Saving a settlement marks the employee's
# exit date so payroll stops accruing beyond the exit month.

SETTLEMENT_KEYS = [
    "id",
    "employee_id",
    "last_working_date",
    "notice_period_days",
    "final_month_gross",
    "final_month_pf",
    "final_month_other_deduction",
    "leave_encashment_days",
    "leave_encashment_amount",
    "gratuity_amount",
    "other_earnings",
    "notice_recovery",
    "other_recovery",
    "net_settlement",
    "remarks",
    "created_at",
]

SETTLEMENT_COLUMNS = SETTLEMENT_KEYS[1:-1]  # everything but id/created_at

GRATUITY_MIN_YEARS = 5


def create_settlement_tables():

    create_settlement_table()


# ---------------------------------------------------------
# EXIT / ACCRUAL HELPERS
# ---------------------------------------------------------

def exit_date_for(employee_id):
    """An employee's exit date ('' while still employed)."""

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT exit_date
            FROM employees
            WHERE employee_id = ?
            """,
            (employee_id,)
        ).fetchone()

    finally:

        connection.close()

    return (row[0] if row and row[0] else "")


def set_exit_date(employee_id, value):
    """Set or clear an employee's exit date."""

    connection = get_connection()

    try:

        connection.execute(
            """
            UPDATE employees
            SET exit_date = ?
            WHERE employee_id = ?
            """,
            (str(value or ""), employee_id)
        )

        connection.commit()

    finally:

        connection.close()


def last_accrual_period(employee_id, today=None):
    """(year, month) an employee stops accruing.

    The exit month for an exited employee, otherwise the current
    month. Used by payroll and PF so nothing accrues after exit.
    """

    today = today or datetime.date.today()

    value = exit_date_for(employee_id)

    if value:

        try:

            exit_day = datetime.date.fromisoformat(str(value))

        except ValueError:

            exit_day = None

        if exit_day is not None:

            return min(
                (exit_day.year, exit_day.month),
                (today.year, today.month)
            )

    return (today.year, today.month)


# ---------------------------------------------------------
# COMPUTATION
# ---------------------------------------------------------

def earned_leave_balance(employee_id, year):
    """Unused General Leave days for a year (never negative)."""

    for entry in get_balance(employee_id, year):

        if entry["type"] == "General Leave":

            return max(0.0, float(entry["balance"]))

    return 0.0


def completed_years(joining_date, last_working_date):
    """Whole years of service between two dates."""

    joining = parse_joining_date(joining_date)

    if joining is None or last_working_date <= joining:

        return 0

    return max(
        0,
        (last_working_date - joining).days // 365
    )


def compute_settlement(
    employee_row,
    last_working_date,
    notice_period_days=0,
    leave_encashment_days=0.0,
    other_earnings=0.0,
    other_recovery=0.0
):
    """Compute the full & final settlement components.

    employee_row is a row from get_employees_with_salary().
    """

    breakdown = build_monthly_breakdown(
        employee_row,
        last_working_date.year,
        last_working_date.month
    )

    days_in_month = month_days(
        last_working_date.month,
        last_working_date.year
    )

    days_worked = min(last_working_date.day, days_in_month)

    proration = days_worked / days_in_month

    final_month_gross = round(
        breakdown["gross_monthly"] * proration,
        2
    )

    final_month_pf = round(
        breakdown["employee_pf"] * proration,
        2
    )

    final_month_other_deduction = round(
        breakdown["other_deduction"] * proration,
        2
    )

    per_day_gross = breakdown["gross_monthly"] / days_in_month

    leave_encashment_amount = round(
        per_day_gross * max(0.0, float(leave_encashment_days)),
        2
    )

    years = completed_years(
        employee_row[4],
        last_working_date
    )

    gratuity_amount = 0.0

    if years >= GRATUITY_MIN_YEARS:

        gratuity_amount = round(
            employee_row[8] * GRATUITY_PCT_OF_BASIC * years,
            2
        )

    notice_recovery = round(
        (breakdown["gross_monthly"] / 30.0)
        * max(0, int(notice_period_days)),
        2
    )

    other_earnings = float(other_earnings or 0)

    other_recovery = float(other_recovery or 0)

    earnings_total = round(
        final_month_gross
        + leave_encashment_amount
        + gratuity_amount
        + other_earnings,
        2
    )

    deductions_total = round(
        final_month_pf
        + final_month_other_deduction
        + notice_recovery
        + other_recovery,
        2
    )

    net_settlement = round(
        earnings_total - deductions_total,
        2
    )

    return {
        "employee_id": employee_row[0],
        "employee_name": employee_row[1],
        "department": employee_row[2],
        "designation": employee_row[3],
        "joining_date": employee_row[4],
        "last_working_date": str(last_working_date),
        "days_worked": days_worked,
        "days_in_month": days_in_month,
        "service_years": years,
        "notice_period_days": int(notice_period_days or 0),
        "final_month_gross": final_month_gross,
        "final_month_pf": final_month_pf,
        "final_month_other_deduction": final_month_other_deduction,
        "leave_encashment_days": round(
            float(leave_encashment_days or 0), 2
        ),
        "leave_encashment_amount": leave_encashment_amount,
        "gratuity_amount": gratuity_amount,
        "other_earnings": round(other_earnings, 2),
        "notice_recovery": notice_recovery,
        "other_recovery": round(other_recovery, 2),
        "earnings_total": earnings_total,
        "deductions_total": deductions_total,
        "net_settlement": net_settlement,
    }


# ---------------------------------------------------------
# PERSISTENCE
# ---------------------------------------------------------

def save_settlement(record, remarks=None):
    """Insert or refresh a settlement for (employee, last working)."""

    connection = get_connection()

    try:

        connection.execute(
            f"""
            INSERT INTO settlements
                ({", ".join(SETTLEMENT_COLUMNS)})
            VALUES ({", ".join("?" for _ in SETTLEMENT_COLUMNS)})

            ON CONFLICT(employee_id, last_working_date)
            DO UPDATE SET
                notice_period_days = excluded.notice_period_days,
                final_month_gross = excluded.final_month_gross,
                final_month_pf = excluded.final_month_pf,
                final_month_other_deduction =
                    excluded.final_month_other_deduction,
                leave_encashment_days =
                    excluded.leave_encashment_days,
                leave_encashment_amount =
                    excluded.leave_encashment_amount,
                gratuity_amount = excluded.gratuity_amount,
                other_earnings = excluded.other_earnings,
                notice_recovery = excluded.notice_recovery,
                other_recovery = excluded.other_recovery,
                net_settlement = excluded.net_settlement,
                remarks = excluded.remarks
            """,
            tuple(
                remarks if key == "remarks" else record.get(key)
                for key in SETTLEMENT_COLUMNS
            )
        )

        connection.commit()

    finally:

        connection.close()


def get_settlements(employee_id=None):
    """Saved settlements, newest first, as dicts."""

    connection = get_connection()

    try:

        if employee_id:

            rows = connection.execute(
                f"""
                SELECT {", ".join(SETTLEMENT_KEYS)}
                FROM settlements
                WHERE employee_id = ?
                ORDER BY last_working_date DESC, id DESC
                """,
                (employee_id,)
            ).fetchall()

        else:

            rows = connection.execute(
                f"""
                SELECT {", ".join(SETTLEMENT_KEYS)}
                FROM settlements
                ORDER BY last_working_date DESC, id DESC
                """
            ).fetchall()

    finally:

        connection.close()

    return [dict(zip(SETTLEMENT_KEYS, row)) for row in rows]


def delete_settlement(settlement_id):
    """Remove a saved settlement by id."""

    connection = get_connection()

    try:

        connection.execute(
            "DELETE FROM settlements WHERE id = ?",
            (settlement_id,)
        )

        connection.commit()

    finally:

        connection.close()


# ---------------------------------------------------------
# ON-SCREEN STATEMENT
# ---------------------------------------------------------

def render_settlement_statement(record):
    """Show the earnings / deductions / net for a settlement."""

    st.markdown("#### Earnings")

    st.table([
        {
            "Component": (
                f"Salary for {MONTHS[int(_month(record['last_working_date'])) - 1]} "
                f"(pro-rata {record.get('days_worked', '')} days)"
            ),
            "Amount": record["final_month_gross"]
        },
        {
            "Component": "Leave encashment",
            "Amount": record["leave_encashment_amount"]
        },
        {
            "Component": (
                f"Gratuity ({record.get('service_years', 0)} yr service)"
            ),
            "Amount": record["gratuity_amount"]
        },
        {
            "Component": "Other earnings",
            "Amount": record["other_earnings"]
        },
    ])

    st.markdown("#### Deductions")

    st.table([
        {
            "Component": "Employee PF (final month)",
            "Amount": record["final_month_pf"]
        },
        {
            "Component": "Other deduction (final month)",
            "Amount": record["final_month_other_deduction"]
        },
        {
            "Component": (
                f"Notice recovery "
                f"({record.get('notice_period_days', 0)} day(s))"
            ),
            "Amount": record["notice_recovery"]
        },
        {
            "Component": "Other recovery",
            "Amount": record["other_recovery"]
        },
    ])

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "Total earnings",
            f"₹ {record['earnings_total']:,.2f}",
            border=True
        )

    with col2:

        st.metric(
            "Total deductions",
            f"₹ {record['deductions_total']:,.2f}",
            border=True
        )

    with col3:

        st.metric(
            "Net payable",
            f"₹ {record['net_settlement']:,.2f}",
            border=True
        )


def _month(value):
    """Month number from an ISO date string ('' when unreadable)."""

    try:

        return str(datetime.date.fromisoformat(str(value)).month)

    except ValueError:

        return "1"


def _enrich_for_pdf(record, joining_date):
    """Add joining date and service years to a saved row for the PDF."""

    enriched = dict(record)

    enriched["joining_date"] = joining_date

    try:

        enriched["service_years"] = completed_years(
            joining_date,
            datetime.date.fromisoformat(
                str(record["last_working_date"])
            )
        )

    except (ValueError, KeyError):

        enriched["service_years"] = 0

    return enriched


# ---------------------------------------------------------
# PDF
# ---------------------------------------------------------

def build_settlement_pdf(record, employee_name=""):
    """Return the settlement statement as an A4 PDF (bytes)."""

    # Rows loaded from the database do not carry the derived
    # totals, so fill them in when missing.
    record = dict(record)

    if not record.get("earnings_total"):

        record["earnings_total"] = round(
            float(record["final_month_gross"])
            + float(record["leave_encashment_amount"])
            + float(record["gratuity_amount"])
            + float(record["other_earnings"]),
            2
        )

    if not record.get("deductions_total"):

        record["deductions_total"] = round(
            float(record["final_month_pf"])
            + float(record["final_month_other_deduction"])
            + float(record["notice_recovery"])
            + float(record["other_recovery"]),
            2
        )

    import os

    from fpdf import FPDF

    ACCENT = (124, 58, 237)
    DARK = (17, 24, 39)
    GRAY = (107, 114, 128)
    BORDER = (209, 213, 219)

    arial = r"C:\Windows\Fonts\arial.ttf"
    arial_bold = r"C:\Windows\Fonts\arialbd.ttf"

    use_arial = os.path.exists(arial) and os.path.exists(arial_bold)

    currency = "₹ " if use_arial else "Rs. "

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    if use_arial:

        pdf.add_font("Arial", "", arial)
        pdf.add_font("Arial", "B", arial_bold)

        font = "Arial"

    else:

        font = "Helvetica"

    left = 15
    right = 195

    def text(
        x, y, w, s, size=9, style="", color=DARK, align="L"
    ):

        pdf.set_xy(x, y)
        pdf.set_font(font, style, size)
        pdf.set_text_color(*color)
        pdf.cell(w, max(size * 0.5, 5), s, align=align)

    def money(value):

        return f"{currency}{value:,.2f}"

    text(left, 12, 120, "AIT Solutions", size=22, style="B",
         color=ACCENT)
    text(left, 23, 120, "Hi-Tech City", size=9, color=GRAY)

    text(115, 12, 80, "Full & Final Settlement", size=13,
         style="B", align="R")
    text(115, 20, 80, f"Dated {datetime.date.today():%d %b %Y}",
         size=9, color=GRAY, align="R")

    pdf.set_draw_color(*BORDER)
    pdf.line(left, 30, right, 30)

    rows = [
        ("Employee", employee_name or record["employee_id"]),
        ("Employee ID", record["employee_id"]),
        ("Joining date", record.get("joining_date", "")),
        ("Last working date", record["last_working_date"]),
        ("Service", f"{record.get('service_years', 0)} year(s)"),
    ]

    y = 34

    for label, value in rows:

        text(left, y, 45, label, size=9, color=GRAY)

        text(left + 45, y, 135, str(value), size=9)

        y += 6

    y += 3

    def section(title, y):

        text(left, y, 180, title, size=11, style="B", color=ACCENT)

        return y + 8

    def line(label, amount, y, bold=False):

        text(left + 4, y, 130, label, size=9,
             style="B" if bold else "")

        text(150, y, 45, money(amount), size=9,
             style="B" if bold else "", align="R")

        return y + 6

    y = section("Earnings", y)

    y = line("Salary for final month (pro-rata)", 
             record["final_month_gross"], y)
    y = line("Leave encashment", 
             record["leave_encashment_amount"], y)
    y = line("Gratuity", record["gratuity_amount"], y)
    y = line("Other earnings", record["other_earnings"], y)
    y = line("Total earnings", record["earnings_total"], y, bold=True)

    y += 4

    y = section("Deductions", y)

    y = line("Employee PF (final month)", 
             record["final_month_pf"], y)
    y = line("Other deduction (final month)",
             record["final_month_other_deduction"], y)
    y = line("Notice recovery", record["notice_recovery"], y)
    y = line("Other recovery", record["other_recovery"], y)
    y = line("Total deductions", record["deductions_total"], y,
             bold=True)

    y += 6

    pdf.set_fill_color(243, 244, 246)
    pdf.rect(left, y, right - left, 12, style="F")

    text(left + 4, y + 3, 100, "NET SETTLEMENT PAYABLE", size=11,
         style="B", color=ACCENT)

    text(150, y + 3, 45, money(record["net_settlement"]), size=11,
         style="B", color=ACCENT, align="R")

    if record.get("remarks"):

        text(left, y + 18, 180, f"Remarks: {record['remarks']}",
             size=8, color=GRAY)

    text(
        left,
        285,
        180,
        "This is a computer-generated statement. PF balance is "
        "settled separately via EPFO.",
        size=7,
        color=GRAY
    )

    return bytes(pdf.output())


# ---------------------------------------------------------
# HR PAGE
# ---------------------------------------------------------

def show_settlement_page(go_home=None):
    """HR: process an employee's full & final settlement."""

    create_settlement_tables()

    st.title("Full & final settlement", icon=":material/gavel:")

    st.caption(
        "Process an exit: final month's pro-rata pay, leave "
        "encashment, gratuity, and notice adjustment. Saving marks "
        "the employee as exited so payroll stops beyond that month."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="settlement_back",
        width="content"
    ):

        go_home()

        st.rerun()

    employees = get_employees_with_salary()

    if not employees:

        st.warning(
            "No employees with a salary structure found. "
            "Set up a salary structure first."
        )

        return

    options = {
        f"{row[1]}  ({row[0]})": row
        for row in employees
    }

    selected = st.selectbox(
        "Select Employee",
        list(options.keys()),
        key="settlement_employee"
    )

    employee = options[selected]

    employee_id = employee[0]

    employee_name = employee[1]

    today = datetime.date.today()

    existing_exit = exit_date_for(employee_id)

    flash = st.session_state.pop("settlement_flash", None)

    if flash:

        st.success(flash)

    if existing_exit:

        st.info(
            f"{employee_name} is marked exited on "
            f"**{existing_exit}**. Payroll and PF stop accruing "
            "after that month."
        )

        if st.button(
            "↩️ Clear exit date (re-instate)",
            key=f"clear_exit_{employee_id}",
            width="content"
        ):

            set_exit_date(employee_id, "")

            st.session_state.settlement_flash = (
                f"Exit date cleared for {employee_name}."
            )

            st.rerun()

    with st.container(border=True):

        col1, col2, col3 = st.columns(3)

        with col1:

            st.write(f"**Employee ID:** {employee_id}")

        with col2:

            st.write(f"**Designation:** {employee[3]}")

        with col3:

            st.write(f"**Joining date:** {employee[4]}")

    # -----------------------------------------------------
    # INPUTS
    # -----------------------------------------------------

    st.subheader("Settlement inputs", icon=":material/edit_note:")

    input_col1, input_col2 = st.columns(2)

    with input_col1:

        last_working_date = st.date_input(
            "Last working date",
            value=today,
            key=f"ff_lwd_{employee_id}"
        )

    with input_col2:

        notice_days = st.number_input(
            "Notice shortfall days (recovered)",
            min_value=0,
            max_value=180,
            value=0,
            step=1,
            key=f"ff_notice_{employee_id}"
        )

    default_leave = earned_leave_balance(
        employee_id,
        last_working_date.year
    )

    encash_col1, encash_col2, encash_col3 = st.columns(3)

    with encash_col1:

        leave_days = st.number_input(
            "Leave encashment days (General Leave)",
            min_value=0.0,
            value=float(default_leave),
            step=0.5,
            key=f"ff_leave_{employee_id}_{last_working_date.year}"
        )

    with encash_col2:

        other_earnings = st.number_input(
            "Other earnings (₹)",
            min_value=0.0,
            value=0.0,
            step=100.0,
            key=f"ff_earn_{employee_id}"
        )

    with encash_col3:

        other_recovery = st.number_input(
            "Other recovery (₹)",
            min_value=0.0,
            value=0.0,
            step=100.0,
            key=f"ff_recover_{employee_id}"
        )

    remarks = st.text_input(
        "Remarks",
        placeholder="e.g. Resignation, notice served",
        key=f"ff_remarks_{employee_id}"
    )

    record = compute_settlement(
        employee,
        last_working_date,
        notice_period_days=notice_days,
        leave_encashment_days=leave_days,
        other_earnings=other_earnings,
        other_recovery=other_recovery
    )

    st.caption(
        f"Unused General Leave available: "
        f"{default_leave:,.2f} day(s) · "
        f"completed service: {record['service_years']} year(s) "
        f"(gratuity from {GRATUITY_MIN_YEARS} years)."
    )

    st.divider()

    render_settlement_statement(record)

    st.divider()

    action_col1, action_col2 = st.columns(2)

    with action_col1:

        save_clicked = st.button(
            "Save settlement & mark exit",
            key=f"ff_save_{employee_id}",
            type="primary",
            width="stretch"
        )

    with action_col2:

        st.download_button(
            "Download PDF",
            data=build_settlement_pdf(record, employee_name),
            file_name=(
                f"full_final_{employee_id}_"
                f"{last_working_date}.pdf"
            ),
            mime="application/pdf",
            key=f"ff_pdf_{employee_id}",
            width="stretch"
        )

    if save_clicked:

        try:

            save_settlement(record, remarks.strip() or None)

            set_exit_date(
                employee_id,
                str(last_working_date)
            )

            st.session_state.settlement_flash = (
                f"Settlement saved for {employee_name}. Net payable "
                f"₹ {record['net_settlement']:,.2f}. Exit marked on "
                f"{last_working_date}."
            )

            st.rerun()

        except Exception as exc:

            st.error(f"Unable to save the settlement: {exc}")

    # -----------------------------------------------------
    # SAVED SETTLEMENTS
    # -----------------------------------------------------

    st.divider()

    st.subheader(
        f"Saved settlements — {employee_name}",
        icon=":material/history:"
    )

    saved = get_settlements(employee_id)

    if not saved:

        st.caption("No settlement saved for this employee yet.")

        return

    for row in saved:

        with st.container(border=True):

            head1, head2, head3 = st.columns([2, 2, 1])

            with head1:

                st.write(
                    f"**Last working date:** "
                    f"{row['last_working_date']}"
                )

            with head2:

                st.write(
                    f"**Net payable:** "
                    f"₹ {row['net_settlement']:,.2f}"
                )

            with head3:

                if st.button(
                    "Delete",
                    key=f"del_settlement_{row['id']}",
                    width="stretch"
                ):

                    delete_settlement(row["id"])

                    st.session_state.settlement_flash = (
                        "Settlement record removed."
                    )

                    st.rerun()

            st.caption(
                f"Saved {row['created_at']} · "
                f"Leave encashed: {row['leave_encashment_days']:,.2f} "
                f"day(s) · Gratuity: "
                f"₹ {row['gratuity_amount']:,.2f}"
                + (
                    f" · {row['remarks']}"
                    if row["remarks"] else ""
                )
            )

            st.download_button(
                "Download PDF",
                data=build_settlement_pdf(
                    _enrich_for_pdf(row, employee[4]),
                    employee_name
                ),
                file_name=(
                    f"full_final_{employee_id}_"
                    f"{row['last_working_date']}.pdf"
                ),
                mime="application/pdf",
                key=f"dl_settlement_{row['id']}",
                width="content"
            )
