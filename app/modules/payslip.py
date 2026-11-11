import calendar
import datetime
import html
import os

import altair as alt
import pandas as pd
import streamlit as st

from database.connection import (
    get_connection,
    create_employee_table,
    create_payslip_table
)
from modules.salary import (
    get_structure,
    pf_contributions_for_basic,
    PROFESSIONAL_TAX_MONTHLY,
)
from modules.session import require_employee, employee_details
from modules.notifications import notify_employee
from modules.workdays import working_days_between


# ---------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December"
]


# =========================================================
# DATA HELPERS
# =========================================================

def get_employees_with_salary():
    """Return every employee that already has a salary structure."""

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            e.employee_id,
            e.employee_name,
            e.department,
            e.designation,
            e.joining_date,
            e.location,
            e.employment_type,
            e.annual_ctc,
            s.basic_annual,
            s.hra_annual,
            s.special_allowance_annual,
            s.other_allowance_annual,
            s.employee_pf_annual,
            s.employer_pf_annual,
            s.other_deduction_annual
        FROM employees e
        JOIN salary_structures s
            ON e.employee_id = s.employee_id
        ORDER BY e.employee_name
        """
    )

    employees = cursor.fetchall()

    connection.close()

    return employees


def month_days(month, year):
    """Number of days in the given month/year."""

    return calendar.monthrange(year, month)[1]


def payroll_release_date(year, month):
    """Return month end, moving Saturday/Sunday releases to Friday."""

    release = datetime.date(year, month, month_days(month, year))

    while release.weekday() >= 5:
        release -= datetime.timedelta(days=1)

    return release


def latest_released_payroll_period(today=None):
    """Latest pay period whose scheduled release date has arrived."""

    today = today or datetime.date.today()

    if today >= payroll_release_date(today.year, today.month):
        return today.year, today.month

    if today.month == 1:
        return today.year - 1, 12

    return today.year, today.month - 1


def payroll_day_counts(joining_date, year, month):
    """Calendar paid days and working days payable in one period."""

    period_start = datetime.date(year, month, 1)
    period_end = datetime.date(year, month, month_days(month, year))
    joining = parse_joining_date(joining_date)
    payable_start = max(period_start, joining) if joining else period_start

    if payable_start > period_end:
        paid_days = 0
        working_days = 0.0
    else:
        paid_days = (period_end - payable_start).days + 1
        working_days = working_days_between(payable_start, period_end)

    return {
        "paid_days": paid_days,
        "calendar_days": month_days(month, year),
        "working_days": working_days,
        "total_working_days": working_days_between(period_start, period_end)
    }


def parse_joining_date(value):
    """Parse a joining date stored as YYYY-MM-DD.

    Returns a datetime.date, or None when the value is missing
    or unreadable.
    """

    if not value:

        return None

    try:

        return datetime.date.fromisoformat(str(value).strip())

    except ValueError:

        return None


def lop_days_for_month(employee_id, year, month):
    """Approved \"Loss of Pay\" (unpaid) leave days overlapping
    the given pay period."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT from_date, to_date
            FROM leave_requests
            WHERE employee_id = ?
              AND leave_type = 'Loss of Pay'
              AND status = 'Approved'
            """,
            (employee_id,)
        ).fetchall()

    finally:

        connection.close()

    month_start = datetime.date(year, month, 1)

    month_end = datetime.date(
        year,
        month,
        month_days(month, year)
    )

    total = 0

    for from_value, to_value in rows:

        try:

            start = datetime.date.fromisoformat(
                str(from_value).strip()
            )

            end = datetime.date.fromisoformat(
                str(to_value).strip()
            )

        except ValueError:

            continue

        overlap_start = max(start, month_start)

        overlap_end = min(end, month_end)

        if overlap_end >= overlap_start:

            # Working days, so a Friday-to-Monday LOP costs two
            # days of pay, not four — the same count the leave
            # page shows the employee.
            total += working_days_between(overlap_start, overlap_end)

    return total


def apply_lop(breakdown, month, year, lop_days):
    """Set the LOP days/amount on a breakdown and adjust net pay.

    The LOP amount is prorated using the gross monthly salary
    and the number of days in the month.
    """

    lop_days = max(0, int(lop_days or 0))

    breakdown["lop_days"] = lop_days

    breakdown["lop_amount"] = (
        round(
            (breakdown["gross_monthly"] / month_days(month, year))
            * lop_days,
            2
        )
        if lop_days
        else 0.0
    )

    breakdown["net_pay"] = round(
        breakdown["gross_monthly"]
        - breakdown["total_deductions"]
        - breakdown["lop_amount"],
        2
    )

    return breakdown


def build_monthly_breakdown(
    employee,
    year=None,
    month=None,
    lop_days_override=None
):
    """Turn an annual salary structure into monthly payslip amounts.

    When year/month are given, approved \"Loss of Pay\" leave days
    in that period are applied to the breakdown automatically.
    """

    (
        employee_id,
        employee_name,
        department,
        designation,
        joining_date,
        location,
        employment_type,
        annual_ctc,
        basic_annual,
        hra_annual,
        special_annual,
        other_allowance_annual,
        employee_pf_annual,
        employer_pf_annual,
        other_deduction_annual
    ) = employee

    basic = basic_annual / 12
    hra = hra_annual / 12
    special = special_annual / 12
    other_allowance = other_allowance_annual / 12

    professional_tax = PROFESSIONAL_TAX_MONTHLY
    other_deduction = other_deduction_annual / 12

    day_counts = (
        payroll_day_counts(joining_date, year, month)
        if year is not None and month is not None
        else None
    )

    # Prorate earnings first; apply PF ceilings to wages actually paid.
    proration_factor = 1.0
    if day_counts and joining_date:
        proration_factor = (
            day_counts["paid_days"] / day_counts["calendar_days"]
        )

    basic = round(basic * proration_factor, 2)
    hra = round(hra * proration_factor, 2)
    special = round(special * proration_factor, 2)
    other_allowance = round(other_allowance * proration_factor, 2)

    other_deduction = round(other_deduction * proration_factor, 2)
    pf_contributions = pf_contributions_for_basic(basic)
    employee_pf = pf_contributions["employee_pf"]
    employer_pf = pf_contributions["employer_pf"]

    gross_monthly = (
        basic
        + hra
        + special
        + other_allowance
    )

    total_deductions = (
        employee_pf
        + professional_tax
        + other_deduction
    )

    net_pay = gross_monthly - total_deductions

    lop_days = 0

    lop_amount = 0.0

    if year is not None and month is not None:

        lop_days = (
            max(0, int(lop_days_override))
            if lop_days_override is not None
            else lop_days_for_month(employee_id, year, month)
        )

        lop_amount = (
            round(
                (gross_monthly / month_days(month, year))
                * lop_days,
                2
            )
            if lop_days
            else 0.0
        )

        net_pay = round(
            gross_monthly
            - total_deductions
            - lop_amount,
            2
        )

    return {
        "employee_id": employee_id,
        "employee_name": employee_name,
        "department": department,
        "designation": designation,
        "joining_date": joining_date,
        "location": location,
        "employment_type": employment_type,
        "annual_ctc": annual_ctc,
        "basic": basic,
        "hra": hra,
        "special": special,
        "other_allowance": other_allowance,
        "gross_monthly": gross_monthly,
        "pf_wages": pf_contributions["pf_wages"],
        "employee_pf": employee_pf,
        "employer_pf": employer_pf,
        "professional_tax": professional_tax,
        "other_deduction": other_deduction,
        "total_deductions": total_deductions,
        "lop_days": lop_days,
        "lop_amount": lop_amount,
        "net_pay": net_pay,
        "paid_days": day_counts["paid_days"] if day_counts else None,
        "calendar_days": day_counts["calendar_days"] if day_counts else None,
        "working_days": day_counts["working_days"] if day_counts else None,
        "total_working_days": (
            day_counts["total_working_days"] if day_counts else None
        )
    }


def save_payslip(employee, month, year, breakdown, overwrite=True):
    """Store (or refresh) the generated payslip for a period."""

    pay_date = payroll_release_date(year, month).isoformat()

    conflict_action = (
        """
        DO UPDATE SET
            basic_monthly = excluded.basic_monthly,
            hra_monthly = excluded.hra_monthly,
            special_allowance_monthly = excluded.special_allowance_monthly,
            other_allowance_monthly = excluded.other_allowance_monthly,
            gross_monthly = excluded.gross_monthly,
            employee_pf_monthly = excluded.employee_pf_monthly,
            employer_pf_monthly = excluded.employer_pf_monthly,
            professional_tax_monthly = excluded.professional_tax_monthly,
            other_deduction_monthly = excluded.other_deduction_monthly,
            total_deductions = excluded.total_deductions,
            net_pay = excluded.net_pay,
            lop_days = excluded.lop_days,
            lop_amount = excluded.lop_amount,
            generated_at = excluded.generated_at
        """
        if overwrite
        else "DO NOTHING"
    )

    connection = get_connection()

    try:
        cursor = connection.execute(
            f"""
            INSERT INTO payslips
            (
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
                lop_amount,
                generated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(employee_id, pay_month, pay_year)
            {conflict_action}
            """,
            (
                employee[0],
                month,
                year,
                breakdown["basic"],
                breakdown["hra"],
                breakdown["special"],
                breakdown["other_allowance"],
                breakdown["gross_monthly"],
                breakdown["employee_pf"],
                breakdown["employer_pf"],
                breakdown["professional_tax"],
                breakdown["other_deduction"],
                breakdown["total_deductions"],
                breakdown["net_pay"],
                breakdown.get("lop_days", 0),
                breakdown.get("lop_amount", 0.0),
                pay_date
            )
        )

        connection.commit()
        return cursor.rowcount == 1

    finally:
        connection.close()


def payslip_exists(employee_id, year, month):
    """True when a payslip row already exists for the period."""

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT 1
            FROM payslips
            WHERE employee_id = ? AND pay_year = ? AND pay_month = ?
            """,
            (employee_id, year, month)
        ).fetchone()

    finally:

        connection.close()

    return row is not None


def payroll_stops_after(employee_id):
    """The last (year, month) this employee is paid, or None.

    A saved final settlement or an exit date closes payroll: no
    payslip is generated for a month after the last working month.
    """

    from modules.settlement import exit_date_for, get_settlements

    dates = []

    try:

        for row in get_settlements(employee_id):

            value = str(row["last_working_date"] or "")

            if value:

                try:

                    dates.append(datetime.date.fromisoformat(value))

                except ValueError:

                    continue

        exit_value = str(exit_date_for(employee_id) or "")

        if exit_value:

            try:

                dates.append(datetime.date.fromisoformat(exit_value))

            except ValueError:

                pass

    except Exception:

        return None

    if not dates:

        return None

    last_day = max(dates)

    return (last_day.year, last_day.month)


def generate_payslips_for_month(
    month,
    year,
    employee_ids=None,
    overwrite=False,
    today=None
):
    """Generate one month's payslips for every (or selected) employee.

    ``overwrite`` refreshes payslips that already exist. Employees
    whose final settlement is saved (or who have exited) are skipped
    for any month after their last working month.

    Returns lists of (employee_id, employee_name) under created,
    updated, skipped and blocked.
    """

    today = today or datetime.date.today()

    result = {
        "created": [],
        "updated": [],
        "skipped": [],
        "blocked": [],
        "not_due": False
    }

    if today < payroll_release_date(year, month):
        result["not_due"] = True

        return result

    wanted = set(employee_ids) if employee_ids is not None else None

    for employee in get_employees_with_salary():

        employee_id = employee[0]

        employee_name = employee[1]

        if wanted is not None and employee_id not in wanted:

            continue

        joining = parse_joining_date(employee[4])

        if joining and (year, month) < (joining.year, joining.month):

            continue

        stop = payroll_stops_after(employee_id)

        if stop and (year, month) > stop:

            result["blocked"].append((employee_id, employee_name))

            continue

        exists = payslip_exists(employee_id, year, month)

        if exists and not overwrite:

            result["skipped"].append((employee_id, employee_name))

            continue

        breakdown = build_monthly_breakdown(employee, year, month)

        save_payslip(employee, month, year, breakdown)

        if exists:

            result["updated"].append((employee_id, employee_name))

        else:

            result["created"].append((employee_id, employee_name))

        notify_employee(
            employee_id,
            "Payslip updated" if exists else "Payslip ready",
            f"Your payslip for {MONTHS[month - 1]} {year} is ready "
            "to view. Pay date: "
            f"{payroll_release_date(year, month).strftime('%d %b %Y')}.",
            category="Payslip",
            page="payslips"
        )

    return result


def auto_generate_current_month_payslips(today=None):
    """Create missing payslips from each joining month through the
    latest due period. Existing slips are never overwritten.
    """

    today = today or datetime.date.today()
    target_year, target_month = latest_released_payroll_period(today)
    target_period = (target_year, target_month)

    created = 0

    for employee in get_employees_with_salary():

        joining = parse_joining_date(employee[4])

        if joining is None:

            continue

        employee_start = (joining.year, joining.month)
        stop = payroll_stops_after(employee[0])
        employee_end = min(target_period, stop) if stop else target_period

        if employee_start > employee_end:

            continue

        current_year, current_month = employee_start

        while (current_year, current_month) <= employee_end:

            if not payslip_exists(employee[0], current_year, current_month):
                breakdown = build_monthly_breakdown(
                    employee,
                    current_year,
                    current_month
                )

                if save_payslip(
                    employee,
                    current_month,
                    current_year,
                    breakdown,
                    overwrite=False
                ):
                    notify_employee(
                        employee[0],
                        "Payslip ready",
                        "Your payslip for "
                        f"{datetime.date(current_year, current_month, 1).strftime('%B %Y')}"
                        f" is ready to view. Pay date: "
                        f"{payroll_release_date(current_year, current_month).strftime('%d %b %Y')}.",
                        category="Payslip",
                        page="payslips"
                    )
                    created += 1

            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1

    return created


def get_saved_payslips(limit=20):
    """Return the most recently generated payslips."""

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            p.employee_id,
            e.employee_name,
            p.pay_month,
            p.pay_year,
            p.gross_monthly,
            p.total_deductions,
            p.net_pay,
            p.generated_at
        FROM payslips p
        JOIN employees e
            ON p.employee_id = e.employee_id
        ORDER BY p.generated_at DESC, p.id DESC
        LIMIT ?
        """,
        (limit,)
    )

    rows = cursor.fetchall()

    connection.close()

    return rows


def get_saved_payslip_details(employee_id, pay_year, pay_month):
    """Return one saved payslip row as a dict, or None."""

    connection = get_connection()

    keys = [
        "employee_id",
        "pay_month",
        "pay_year",
        "basic_monthly",
        "hra_monthly",
        "special_allowance_monthly",
        "other_allowance_monthly",
        "gross_monthly",
        "employee_pf_monthly",
        "employer_pf_monthly",
        "professional_tax_monthly",
        "other_deduction_monthly",
        "total_deductions",
        "net_pay",
        "lop_days",
        "lop_amount",
        "generated_at"
    ]

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
                lop_amount,
                generated_at
            FROM payslips
            WHERE employee_id = ?
                AND pay_year = ?
                AND pay_month = ?
            """,
            (employee_id, pay_year, pay_month)
        ).fetchone()

    finally:

        connection.close()

    if row is None:

        return None

    return dict(zip(keys, row))


def breakdown_from_saved(employee_row, saved):
    """Rebuild a payslip breakdown from a stored payslip row and the
    employee row returned by get_employees_with_salary()."""

    day_counts = payroll_day_counts(employee_row[4], saved["pay_year"], saved["pay_month"])

    return {
        "employee_id": employee_row[0],
        "employee_name": employee_row[1],
        "department": employee_row[2],
        "designation": employee_row[3],
        "joining_date": employee_row[4],
        "location": employee_row[5],
        "employment_type": employee_row[6],
        "annual_ctc": employee_row[7],
        "basic": saved["basic_monthly"],
        "hra": saved["hra_monthly"],
        "special": saved["special_allowance_monthly"],
        "other_allowance": saved["other_allowance_monthly"],
        "gross_monthly": saved["gross_monthly"],
        "employee_pf": saved["employee_pf_monthly"],
        "employer_pf": saved["employer_pf_monthly"],
        "professional_tax": saved["professional_tax_monthly"],
        "other_deduction": saved["other_deduction_monthly"],
        "total_deductions": saved["total_deductions"],
        "lop_days": saved["lop_days"],
        "lop_amount": saved["lop_amount"],
        "net_pay": saved["net_pay"],
        **day_counts
    }


# =========================================================
# HTML PAYSLIP (for download)
# =========================================================

def _payslip_bank_details(employee_id):
    """Fetch HR-managed payment identifiers for the payslip."""

    create_employee_table()
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT bank_name, bank_account_number, bank_ifsc, uan_number
            FROM employees
            WHERE employee_id = ?
            """,
            (employee_id,)
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        raise ValueError(f"Employee record not found for {employee_id}.")

    return {
        "bank_name": row[0],
        "bank_account_number": row[1],
        "bank_ifsc": row[2],
        "uan_number": row[3],
    }


def _payslip_ytd_amounts(breakdown, month, year):
    """Return financial-year totals, replacing the selected period with this slip."""

    financial_year_start = year if month >= 4 else year - 1
    start_month = 4
    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT
            COALESCE(SUM(basic_monthly), 0),
            COALESCE(SUM(hra_monthly), 0),
            COALESCE(SUM(special_allowance_monthly), 0),
            COALESCE(SUM(other_allowance_monthly), 0),
            COALESCE(SUM(gross_monthly), 0),
            COALESCE(SUM(employee_pf_monthly), 0),
            COALESCE(SUM(other_deduction_monthly), 0),
            COALESCE(SUM(lop_amount), 0)
        FROM payslips
        WHERE employee_id = ?
          AND (pay_year * 12 + pay_month) >= ?
          AND (pay_year * 12 + pay_month) < ?
        """,
        (
            breakdown["employee_id"],
            financial_year_start * 12 + start_month,
            year * 12 + month,
        ),
    )
    previous_periods = cursor.fetchone()
    connection.close()

    current_period = (
        "basic",
        "hra",
        "special",
        "other_allowance",
        "gross_monthly",
        "employee_pf",
        "other_deduction",
        "lop_amount",
    )
    return {
        key: round(float(previous_periods[index] or 0) +
                   float(breakdown.get(key, 0) or 0), 2)
        for index, key in enumerate(current_period)
    }


def _amount_in_words(amount):
    """Spell a whole-rupee amount using Indian numbering groups."""

    ones = (
        "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
        "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
        "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen",
        "Nineteen",
    )
    tens = (
        "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty",
        "Seventy", "Eighty", "Ninety",
    )

    def under_thousand(number):
        words = []
        if number >= 100:
            words.extend((ones[number // 100], "Hundred"))
            number %= 100
        if number >= 20:
            words.append(tens[number // 10])
            number %= 10
        if number:
            words.append(ones[number])
        return " ".join(words)

    number = max(0, int(round(float(amount or 0))))
    groups = (
        (10_000_000, "Crore"),
        (100_000, "Lakh"),
        (1_000, "Thousand"),
    )
    words = []
    for divisor, label in groups:
        group = number // divisor
        if group:
            words.extend((under_thousand(group), label))
            number %= divisor
    if number:
        words.append(under_thousand(number))
    return "Indian Rupee " + " ".join(words or ("Zero",)) + " Only"


def build_payslip_html(breakdown, month, year):
    """Return a standalone, printable HTML payslip."""

    month_name = MONTHS[month - 1]
    day_counts = payroll_day_counts(
        breakdown.get("joining_date"),
        year,
        month
    )

    bank_details = _payslip_bank_details(breakdown["employee_id"])
    ytd = _payslip_ytd_amounts(breakdown, month, year)
    lop_days = float(breakdown.get("lop_days", 0) or 0)
    lop_amount = round(float(breakdown.get("lop_amount", 0) or 0), 2)
    total_deductions = round(
        float(breakdown["total_deductions"]) + lop_amount, 2
    )
    def money(value):
        return f"{value:,.2f}"

    def table_rows(rows, total_label, total_amount, total_ytd):
        rendered_rows = ""
        for row in rows:
            label, amount = row[:2]
            row_html = (
                "<tr>"
                f"<td>{html.escape(label)}</td>"
                f"<td class=\"amount\">&#8377; {money(amount)}</td>"
            )
            if len(row) == 3:
                row_html += (
                    f"<td class=\"amount\">&#8377; {money(row[2])}</td>"
                )
            rendered_rows += row_html + "</tr>"

        total_ytd_cell = (
            f"<td class=\"amount\">&#8377; {money(total_ytd)}</td>"
            if total_ytd is not None
            else ""
        )
        return (
            rendered_rows
            + "<tr class=\"total\">"
            f"<td>{html.escape(total_label)}</td>"
            f"<td class=\"amount\">&#8377; {money(total_amount)}</td>"
            f"{total_ytd_cell}"
            "</tr>"
        )

    earnings_rows = [
        ("Basic Salary", breakdown["basic"], ytd["basic"]),
        ("House Rent Allowance", breakdown["hra"], ytd["hra"]),
        ("Special Allowance", breakdown["special"], ytd["special"]),
        (
            "Other Allowance",
            breakdown["other_allowance"],
            ytd["other_allowance"],
        ),
    ]
    deduction_rows = [
        ("Employee PF", breakdown["employee_pf"]),
        ("Professional Tax", breakdown["professional_tax"]),
        ("Other Deduction", breakdown["other_deduction"]),
    ]
    if lop_amount or ytd["lop_amount"]:
        deduction_rows.append(("Loss of Pay", lop_amount))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Payslip For the Month {month_name} {year}</title>
<style>
    * {{ box-sizing: border-box; }}

    body {{
        font-family: Arial, Helvetica, sans-serif;
        background: #f3f6f5;
        margin: 0;
        padding: 24px;
        color: #1f2937;
    }}

    .payslip {{
        max-width: 960px;
        margin: 0 auto;
        background: #ffffff;
        padding: 32px 38px;
        border: 1px solid #dfe7e3;
        box-shadow: 0 5px 20px rgba(15, 55, 42, 0.08);
    }}

    .header {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        border-bottom: 2px solid #1d765b;
        padding-bottom: 18px;
    }}

    .company {{
        font-size: 24px;
        font-weight: 800;
        color: #155d47;
    }}

    .company-sub {{
        font-size: 12px;
        color: #6b7280;
        margin-top: 5px;
    }}

    .slip-title {{
        text-align: right;
        color: #6b7280;
        font-size: 13px;
    }}

    .slip-title .period-label {{
        font-size: 13px;
        color: #6b7280;
    }}

    .slip-title .period {{
        margin-top: 4px;
        font-size: 20px;
        font-weight: 700;
        color: #111827;
    }}

    .section-title {{
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.7px;
        color: #155d47;
        margin: 20px 0 9px;
    }}

    .summary {{
        display: grid;
        grid-template-columns: 1.15fr 0.85fr;
        gap: 24px;
        margin-top: 19px;
    }}

    .employee-name {{
        font-size: 18px;
        font-weight: 700;
        color: #17231f;
        margin-bottom: 12px;
    }}

    .info-grid {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 10px 18px;
        font-size: 12px;
    }}

    .info-item span {{
        display: block;
        color: #718078;
        font-size: 10px;
        margin-bottom: 3px;
    }}

    .bank-details {{
        margin-top: 20px;
        padding: 12px 14px;
        border: 1px solid #e1e9e4;
        border-radius: 4px;
        background: #fbfcfb;
    }}

    .bank-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        font-size: 12px;
    }}

    .net {{
        align-self: stretch;
        padding: 16px 18px;
        border: 1px solid #cfe2d7;
        border-radius: 4px;
        background: #f1f8f3;
    }}

    .net-label {{
        color: #557064;
        font-size: 11px;
    }}

    .net-value {{
        font-size: 24px;
        font-weight: 800;
        color: #155d47;
        margin: 4px 0 13px;
    }}

    .day-details {{
        display: flex;
        gap: 28px;
        border-top: 1px solid #d6e5dc;
        padding-top: 10px;
        font-size: 11px;
    }}

    .tables {{
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 22px;
        margin-top: 22px;
    }}

    .table-title {{
        color: #155d47;
        font-weight: 700;
        font-size: 13px;
        margin-bottom: 8px;
    }}

    table {{
        width: 100%;
        border-collapse: collapse;
        font-size: 11px;
    }}

    th, td {{
        padding: 9px 7px;
        border-bottom: 1px solid #e5ebe8;
        text-align: left;
    }}

    th {{
        background: #edf4f0;
        color: #50635a;
        font-size: 9px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.25px;
    }}

    td.amount, th.amount {{
        text-align: right;
        white-space: nowrap;
        font-variant-numeric: tabular-nums;
    }}

    tr.total td {{
        font-weight: 700;
        color: #183d2e;
        background: #f4f8f5;
        border-top: 1px solid #b8c9bf;
    }}

    .words {{
        margin-top: 20px;
        padding: 12px 14px;
        background: #f7f9f8;
        border-left: 3px solid #1d765b;
        font-size: 11px;
        line-height: 1.5;
    }}

    .words strong {{ color: #155d47; }}

    .footer {{
        margin-top: 22px;
        padding-top: 11px;
        border-top: 1px solid #e5ebe8;
        color: #849089;
        text-align: center;
        font-size: 10px;
    }}

    @media (max-width: 720px) {{
        body {{ padding: 10px; }}
        .payslip {{ padding: 20px 16px; }}
        .summary, .tables {{ grid-template-columns: 1fr; }}
        .info-grid {{ gap: 10px; }}
        .bank-grid {{ grid-template-columns: 1fr 1fr; }}
        .tables {{ gap: 16px; }}
    }}

    @media print {{
        body {{ background: #ffffff; padding: 0; }}
        .payslip {{ max-width: none; border: 0; box-shadow: none; }}
    }}
</style>
</head>
<body>

<div class="payslip">

    <div class="header">
        <div>
            <div class="company">AIT Solutions</div>
            <div class="company-sub">
                Hi-Tech City
            </div>
        </div>

        <div class="slip-title">
            <div class="period-label">Payslip For the Month</div>
            <div class="period">{month_name} {year}</div>
        </div>
    </div>

    <div class="summary">
        <div>
            <div class="section-title">Employee Details</div>
            <div class="employee-name">{html.escape(str(breakdown['employee_name']))}</div>
            <div class="info-grid">
                <div class="info-item"><span>Employee ID</span>{html.escape(str(breakdown['employee_id']))}</div>
                <div class="info-item"><span>Designation</span>{html.escape(str(breakdown['designation']))}</div>
                <div class="info-item"><span>Department</span>{html.escape(str(breakdown['department']))}</div>
                <div class="info-item"><span>Date of Joining</span>{html.escape(_payslip_date(breakdown['joining_date']))}</div>
                <div class="info-item"><span>Pay Period</span>{month_name} {year}</div>
                <div class="info-item"><span>Pay Date</span>{payroll_release_date(year, month).strftime("%d/%m/%Y")}</div>
            </div>
        </div>
        <div class="net">
            <div class="net-label">Total Net Pay</div>
            <div class="net-value">&#8377; {money(breakdown['net_pay'])}</div>
            <div class="day-details">
                <div><strong>Paid Days</strong><br>{day_counts['paid_days']}</div>
                <div><strong>LOP Days</strong><br>{lop_days:g}</div>
            </div>
        </div>
    </div>

    <div class="bank-details">
        <div class="table-title">Account and UAN Details</div>
        <div class="bank-grid">
            <div class="info-item"><span>Account number</span>{html.escape(str(bank_details['bank_account_number'] or '—'))}</div>
            <div class="info-item"><span>UAN</span>{html.escape(str(bank_details['uan_number'] or '—'))}</div>
        </div>
    </div>

    <div class="tables">
        <div>
            <div class="table-title">Earnings</div>
            <table>
                <tr><th>Component</th><th class="amount">Amount (&#8377;)</th><th class="amount">YTD (&#8377;)</th></tr>
                {table_rows(earnings_rows, "Total Earnings", breakdown['gross_monthly'], ytd['gross_monthly'])}
            </table>
        </div>
        <div>
            <div class="table-title">Deductions</div>
            <table>
                <tr><th>Component</th><th class="amount">Amount (&#8377;)</th></tr>
                {table_rows(deduction_rows, "Total Deductions", total_deductions, None)}
            </table>
        </div>
    </div>

    <div class="words"><strong>Amount in Words:</strong> {html.escape(_amount_in_words(breakdown['net_pay']))}</div>

    <div class="footer">
        This is a computer-generated payslip and does not require a signature. &nbsp;|&nbsp; AIT Solutions
    </div>

</div>

</body>
</html>
"""


# =========================================================
# PDF PAYSLIP (for download)
# =========================================================

def build_payslip_pdf(breakdown, month, year):
    """Return a printable A4 PDF payslip as bytes.

    Uses Arial (which includes the ₹ glyph) from the Windows
    fonts folder; falls back to Helvetica + "Rs." otherwise.
    """

    from fpdf import FPDF

    month_name = MONTHS[month - 1]

    day_counts = payroll_day_counts(
        breakdown.get("joining_date"),
        year,
        month
    )

    bank_details = _payslip_bank_details(breakdown["employee_id"])
    ytd = _payslip_ytd_amounts(breakdown, month, year)
    lop_days = float(breakdown.get("lop_days", 0) or 0)
    lop_amount = round(float(breakdown.get("lop_amount", 0) or 0), 2)
    total_deductions = round(
        float(breakdown["total_deductions"]) + lop_amount, 2
    )
    ACCENT = (29, 118, 91)
    DARK = (31, 41, 37)
    GRAY = (103, 119, 110)
    LIGHT = (237, 244, 240)
    BORDER = (207, 220, 212)
    PALE_GREEN = (241, 248, 243)

    def money(value):
        return f"{value:,.2f}"

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
        x, y, w, s, size=9, style="", color=DARK, align="L", h=None
    ):

        if h is None:

            h = max(size * 0.5, 5)

        pdf.set_xy(x, y)
        pdf.set_font(font, style, size)
        pdf.set_text_color(*color)
        pdf.cell(w, h, s, align=align)

    # -----------------------------------------------------
    # HEADER
    # -----------------------------------------------------

    text(left, 12, 120, "AIT Solutions", size=22, style="B", color=ACCENT, h=11)
    text(left, 23, 120, "Hi-Tech City", size=9, color=GRAY)

    text(115, 12, 80, "Payslip For the Month", size=9, color=GRAY, align="R")
    text(115, 19, 80, f"{month_name} {year}", size=13, style="B", align="R", h=7)
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(left, 40, right, 40)

    # -----------------------------------------------------
    # EMPLOYEE DETAILS
    # -----------------------------------------------------

    text(left, 45, 180, "Employee Details", size=9, style="B", color=ACCENT)

    detail_rows = [
        [
            ("Employee Name", breakdown["employee_name"]),
            ("Employee ID", breakdown["employee_id"]),
        ],
        [
            ("Department", breakdown["department"]),
            ("Designation", breakdown["designation"]),
        ],
        [
            ("Location", breakdown["location"]),
            ("Employment Type", breakdown["employment_type"]),
        ],
        [
            ("Date of Joining", _payslip_date(breakdown["joining_date"])),
            ("Annual CTC", currency + money(breakdown["annual_ctc"])),
        ],
        [
            ("Pay Period", f"{month_name} {year}"),
            ("Pay Date", payroll_release_date(year, month).strftime("%d/%m/%Y")),
        ],
        [
            ("Account Number", bank_details["bank_account_number"] or "-"),
            ("UAN", bank_details["uan_number"] or "-"),
        ],
        [
            (
                "Working Days",
                f"{day_counts['working_days']:g} / "
                f"{day_counts['total_working_days']:g}"
            ),
        ],
    ]

    y = 51
    row_height = 7
    col_offset = 90
    label_width = 33
    value_width = 57

    for pair in detail_rows:

        for index, (label, value) in enumerate(pair):

            x = left + (index * col_offset)

            text(x, y, label_width, label, size=9, color=GRAY)
            text(x + label_width, y, value_width, str(value), size=9)

        y += row_height

    # -----------------------------------------------------
    # EARNINGS / DEDUCTIONS TABLES
    # -----------------------------------------------------

    def draw_table(x, y, title, rows, total, include_ytd=True):

        text(x, y, 90, title, size=9, style="B", color=ACCENT)

        y += 6

        pdf.set_fill_color(*LIGHT)
        pdf.rect(x, y, 90, 7, style="F")

        component_width = 38 if include_ytd else 58
        amount_x = x + 40 if include_ytd else x + 60
        amount_width = 25 if include_ytd else 28
        text(x + 2, y + 1.5, component_width, "COMPONENT", size=6.5, style="B", color=DARK)
        text(amount_x, y + 1.5, amount_width, "AMOUNT", size=6.2, style="B", align="R")
        if include_ytd:
            text(x + 65, y + 1.5, 23, "YTD", size=6.2, style="B", align="R")

        y += 7

        for row in rows:
            label, value = row[:2]

            text(x + 2, y + 1.5, component_width, label, size=7.2)
            text(amount_x, y + 1.5, amount_width, money(value), size=6.5, align="R")
            if include_ytd:
                text(x + 65, y + 1.5, 23, money(row[2]), size=6.5, align="R")

            pdf.set_draw_color(*BORDER)
            pdf.set_line_width(0.2)
            pdf.line(x, y + 7.5, x + 90, y + 7.5)

            y += 7.5

        pdf.set_draw_color(*BORDER)
        pdf.set_line_width(0.4)
        pdf.line(x, y, x + 90, y)

        pdf.set_fill_color(*LIGHT)
        pdf.rect(x, y, 90, 7.5, style="F")

        text(x + 2, y + 1.5, component_width, total[0], size=7, style="B")
        text(amount_x, y + 1.5, amount_width, money(total[1]), size=6.5, style="B", align="R")
        if include_ytd:
            text(x + 65, y + 1.5, 23, money(total[2]), size=6.5, style="B", align="R")

        return y + 7.5

    earnings_end = draw_table(
        left,
        y + 6,
        "Earnings",
        [
            ("Basic Salary", breakdown["basic"], ytd["basic"]),
            ("House Rent Allowance", breakdown["hra"], ytd["hra"]),
            ("Special Allowance", breakdown["special"], ytd["special"]),
            ("Other Allowance", breakdown["other_allowance"], ytd["other_allowance"]),
        ],
        ("Total Earnings", breakdown["gross_monthly"], ytd["gross_monthly"])
    )

    deductions_end = draw_table(
        left + 90,
        y + 6,
        "Deductions",
        [
            ("Employee PF", breakdown["employee_pf"]),
            ("Professional Tax", breakdown["professional_tax"]),
            ("Other Deduction", breakdown["other_deduction"]),
            *(
                [("Loss of Pay", lop_amount)]
                if lop_amount or ytd["lop_amount"]
                else []
            ),
        ],
        (
            "Total Deductions",
            total_deductions,
        ),
        include_ytd=False,
    )

    # -----------------------------------------------------
    # NET PAY
    # -----------------------------------------------------

    y = max(earnings_end, deductions_end) + 8

    pdf.set_fill_color(*PALE_GREEN)
    pdf.set_draw_color(*BORDER)
    pdf.rect(left, y, 180, 25, style="DF")

    text(left + 5, y + 3, 100, "Total Net Pay", size=9, color=GRAY)
    text(left + 5, y + 8, 170, currency + money(breakdown["net_pay"]),
         size=18, style="B", color=ACCENT, h=9)
    text(left + 5, y + 18, 35, "Paid Days", size=8, color=GRAY)
    text(left + 40, y + 18, 25, str(day_counts["paid_days"]), size=8)
    text(left + 80, y + 18, 35, "LOP Days", size=8, color=GRAY)
    text(
        left + 115, y + 18, 25,
        f"{lop_days:g}",
        size=8
    )

    words_y = y + 31
    pdf.set_fill_color(*LIGHT)
    pdf.rect(left, words_y, 180, 19, style="F")
    text(left + 4, words_y + 2, 172, "Amount in Words", size=7.5, style="B", color=ACCENT)
    pdf.set_xy(left + 4, words_y + 8)
    pdf.set_font(font, "", 8)
    pdf.set_text_color(*DARK)
    pdf.multi_cell(172, 5, _amount_in_words(breakdown["net_pay"]))

    footer_y = words_y + 27

    text(
        left, footer_y, 180,
        "This is a computer-generated payslip and does not "
        "require a signature. | AIT Solutions",
        size=8, color=GRAY, align="C"
    )

    return bytes(pdf.output())


# =========================================================
# ON-SCREEN RENDERING
# =========================================================

def render_payslip_preview(breakdown, month, year):
    """Render the same styled payslip used for HTML downloads."""

    document = build_payslip_html(breakdown, month, year)
    style = document.partition("<style>")[2].partition("</style>")[0]
    markup = document.partition("<body>")[2].partition("</body>")[0]
    st.html(f"<style>{style}</style>{markup}")


# =========================================================
# MAIN PAGE
# =========================================================

def show_payslip():

    create_payslip_table()

    employees = get_employees_with_salary()

    if not employees:

        st.warning(
            "No salary structures found. "
            "Create an employee salary structure first."
        )

        return

    today = datetime.date.today()
    latest_year, latest_month = latest_released_payroll_period(today)
    latest_saved_count = sum(
        1 for employee in employees
        if payslip_exists(employee[0], latest_year, latest_month)
    )
    latest_pay_date = payroll_release_date(latest_year, latest_month)

    st.html(
        f"""
        <style>
            .payroll-overview {{
                position: relative;
                overflow: hidden;
                display: grid;
                grid-template-columns: minmax(0, 1fr) auto;
                gap: 24px;
                align-items: center;
                margin: 4px 0 22px;
                padding: 26px 30px;
                border: 1px solid #d5e6dc;
                border-radius: 16px;
                background:
                    radial-gradient(ellipse at 92% 10%, rgba(255,255,255,.7), transparent 35%),
                    linear-gradient(120deg, #f1f8f3 0%, #ffffff 58%, #eaf5ee 100%);
                box-shadow: 0 10px 30px rgba(27, 86, 62, .08);
                color: #17241e;
                font-family: inherit;
            }}
            .payroll-overview:after {{
                content: "";
                position: absolute;
                width: 210px;
                height: 210px;
                right: -72px;
                bottom: -132px;
                border: 1px solid rgba(29, 118, 91, .12);
                border-radius: 50%;
                box-shadow: 0 0 0 22px rgba(29, 118, 91, .035),
                            0 0 0 46px rgba(29, 118, 91, .025);
                pointer-events: none;
            }}
            .payroll-overview-copy {{ position: relative; z-index: 1; }}
            .payroll-eyebrow {{
                margin-bottom: 8px;
                color: #237457;
                font-size: 11px;
                font-weight: 750;
                letter-spacing: .12em;
                text-transform: uppercase;
            }}
            .payroll-overview h2 {{
                margin: 0;
                color: #183b2c;
                font-size: clamp(24px, 3vw, 32px);
                font-weight: 750;
                letter-spacing: -.035em;
                line-height: 1.15;
            }}
            .payroll-overview p {{
                max-width: 600px;
                margin: 9px 0 0;
                color: #607068;
                font-size: 13px;
                line-height: 1.55;
            }}
            .payroll-overview-stats {{
                position: relative;
                z-index: 1;
                display: grid;
                grid-template-columns: repeat(3, minmax(112px, 1fr));
                gap: 10px;
            }}
            .payroll-stat {{
                min-width: 112px;
                padding: 13px 15px;
                border: 1px solid rgba(205, 223, 212, .9);
                border-radius: 11px;
                background: rgba(255, 255, 255, .76);
                backdrop-filter: blur(6px);
            }}
            .payroll-stat-label {{
                color: #728078;
                font-size: 10px;
                font-weight: 650;
                letter-spacing: .06em;
                text-transform: uppercase;
            }}
            .payroll-stat-value {{
                margin-top: 6px;
                color: #183b2c;
                font-size: 17px;
                font-weight: 750;
                white-space: nowrap;
            }}
            .payroll-stat-note {{
                margin-top: 3px;
                color: #758179;
                font-size: 10px;
            }}
            @media (max-width: 850px) {{
                .payroll-overview {{ grid-template-columns: 1fr; }}
                .payroll-overview-stats {{ grid-template-columns: repeat(3, 1fr); }}
            }}
            @media (max-width: 520px) {{
                .payroll-overview {{ padding: 20px; }}
                .payroll-overview-stats {{ grid-template-columns: 1fr 1fr; }}
            }}
        </style>
        <section class="payroll-overview">
            <div class="payroll-overview-copy">
                <div class="payroll-eyebrow">Payroll workspace</div>
                <h2>Run payroll with clarity.</h2>
                <p>Review the latest released period, generate monthly payslips, and manage employee payroll details from one place.</p>
            </div>
            <div class="payroll-overview-stats">
                <div class="payroll-stat">
                    <div class="payroll-stat-label">Latest period</div>
                    <div class="payroll-stat-value">{MONTHS[latest_month - 1]} {latest_year}</div>
                    <div class="payroll-stat-note">Released payroll</div>
                </div>
                <div class="payroll-stat">
                    <div class="payroll-stat-label">Pay date</div>
                    <div class="payroll-stat-value">{latest_pay_date.strftime("%d %b")}</div>
                    <div class="payroll-stat-note">{latest_pay_date.strftime("%Y")}</div>
                </div>
                <div class="payroll-stat">
                    <div class="payroll-stat-label">Payslips saved</div>
                    <div class="payroll-stat-value">{latest_saved_count} / {len(employees)}</div>
                    <div class="payroll-stat-note">Employees with salary setup</div>
                </div>
            </div>
        </section>
        """
    )

    # -----------------------------------------------------
    # GENERATE ALL PAYSLIPS (ONE CLICK)
    # -----------------------------------------------------
    # HR picks a month and generates that month's payslip for
    # every employee in one go. Existing payslips are kept unless
    # HR ticks "replace". Employees with a saved final settlement
    # or an exit date are skipped after their last working month.

    with st.container(border=True):

        st.markdown("#### Generate all payslips")

        st.caption(
            "One click covers every employee with a salary structure. "
            "Payslips are released at month end (or the preceding "
            "Friday when month end falls on a weekend) and pick up "
            "approved Loss of Pay automatically."
        )

        bulk_col1, bulk_col2, bulk_col3 = st.columns([1, 1, 2])

        with bulk_col1:

            bulk_month = st.selectbox(
                "Pay month",
                list(range(1, 13)),
                index=latest_month - 1,
                format_func=lambda m: MONTHS[m - 1],
                key="bulk_payslip_month"
            )

        with bulk_col2:

            bulk_years = list(range(latest_year - 5, latest_year + 1))

            bulk_year = st.selectbox(
                "Pay year",
                bulk_years,
                index=bulk_years.index(latest_year),
                key="bulk_payslip_year"
            )

        with bulk_col3:

            bulk_due = (bulk_year, bulk_month) <= (
                latest_year,
                latest_month
            )

            overwrite = st.checkbox(
                "Replace payslips that already exist (recalculate them)",
                value=False,
                key="bulk_payslip_overwrite"
            )

            generate_all = st.button(
                "Generate all payslips",
                type="primary",
                width="stretch",
                key="bulk_payslip_generate",
                disabled=not bulk_due
            )

            if not bulk_due:
                st.caption(
                    "This period is not due for release yet. "
                    f"Scheduled pay date: "
                    f"{payroll_release_date(bulk_year, bulk_month):%d %b %Y}."
                )

        existing_count = 0
        closed_count = 0

        for row in employees:

            stop = payroll_stops_after(row[0])

            if stop and (bulk_year, bulk_month) > stop:

                closed_count += 1

            elif payslip_exists(row[0], bulk_year, bulk_month):

                existing_count += 1

        st.caption(
            f"{MONTHS[bulk_month - 1]} {bulk_year}: "
            f"**{len(employees) - closed_count} employee(s)** covered · "
            f"{existing_count} already saved"
            + (
                f" · {closed_count} closed after final settlement"
                if closed_count else ""
            )
        )

        if generate_all:

            result = generate_payslips_for_month(
                bulk_month,
                bulk_year,
                overwrite=overwrite
            )

            # Clear the editor widgets so the page shows the newly
            # generated figures instead of an older unsaved edit.
            for key in list(st.session_state.keys()):

                if str(key).startswith(("edit_", "lop_")):

                    del st.session_state[key]

            st.session_state["payslip_bulk_flash"] = result
            st.session_state["payslip_bulk_period"] = (
                bulk_month,
                bulk_year
            )

            st.rerun()

    bulk_flash = st.session_state.pop("payslip_bulk_flash", None)

    if bulk_flash:

        period = st.session_state.pop("payslip_bulk_period", None)

        label = (
            f"{MONTHS[period[0] - 1]} {period[1]}"
            if period else "Selected month"
        )

        st.success(
            f"{label}: "
            f"{len(bulk_flash['created'])} created · "
            f"{len(bulk_flash['updated'])} updated · "
            f"{len(bulk_flash['skipped'])} already saved · "
            f"{len(bulk_flash['blocked'])} closed after settlement.",
            icon=":material/task_alt:"
        )

        if bulk_flash["blocked"]:

            st.caption(
                "Skipped after final settlement: "
                + ", ".join(
                    f"{name} ({employee_id})"
                    for employee_id, name in bulk_flash["blocked"]
                )
            )

    st.divider()

    # -----------------------------------------------------
    # SELECT EMPLOYEE + PERIOD
    # -----------------------------------------------------

    employee_options = {
        f"{row[1]}  ({row[0]})": row
        for row in employees
    }

    col1, col2, col3 = st.columns([2, 1, 1])

    with col1:

        selected = st.selectbox(
            "Select Employee",
            list(employee_options.keys())
        )

    employee = employee_options[selected]

    joining_date = parse_joining_date(employee[4])

    stop = payroll_stops_after(employee[0])

    # -----------------------------------------------------
    # AVAILABLE PAYSLIP PERIODS
    # -----------------------------------------------------
    # A payslip exists only for months that have already
    # started: from the employee's joining month up to the
    # latest due period. Future periods are never offered.

    employee_latest_year, employee_latest_month = (
        latest_year,
        latest_month
    )

    earliest_year = employee_latest_year - 5

    if joining_date:

        earliest_year = max(
            earliest_year,
            joining_date.year
        )

    if stop and stop < (employee_latest_year, employee_latest_month):
        employee_latest_year, employee_latest_month = stop

    if earliest_year > employee_latest_year:

        st.warning(
            f"{employee[1]} joins on "
            f"{joining_date.strftime('%d %b %Y')}. "
            f"Payslips will be available from that month "
            f"onward."
        )

        return

    year_options = list(
        range(earliest_year, employee_latest_year + 1)
    )

    default_year = employee_latest_year

    with col3:

        year = st.selectbox(
            "Year",
            year_options,
            index=year_options.index(default_year)
        )

    if stop:

        st.info(
            f"Final settlement is saved for {employee[1]}. Payroll "
            f"closes after **{MONTHS[stop[1] - 1]} {stop[0]}** — no "
            "payslip is generated for later months.",
            icon=":material/lock:"
        )

    first_month = 1

    if joining_date and year == joining_date.year:

        first_month = joining_date.month

    last_month = 12

    if year == employee_latest_year:

        last_month = employee_latest_month

    # The settlement month is the last payable month.
    if stop and year == stop[0]:

        last_month = min(last_month, stop[1])

    month_options = list(
        range(first_month, last_month + 1)
    )

    if not month_options:

        joining_label = (
            joining_date.strftime("%b %Y")
            if joining_date
            else "the joining month"
        )

        st.warning(
            f"{employee[1]} joins in {joining_label}. "
            f"Payslips will be available from that month "
            f"onward."
        )

        return

    default_month = (
        employee_latest_month
        if year == employee_latest_year
        and employee_latest_month in month_options
        else month_options[-1]
    )

    with col2:

        month = st.selectbox(
            "Month",
            month_options,
            index=month_options.index(default_month),
            format_func=lambda m: MONTHS[m - 1]
        )

    breakdown = build_monthly_breakdown(employee, year, month)

    # -----------------------------------------------------
    # PERIOD GUARD
    # -----------------------------------------------------

    if joining_date and (year, month) < (
        joining_date.year,
        joining_date.month
    ):

        st.warning(
            f"{breakdown['employee_name']} joined on "
            f"{joining_date.strftime('%d %b %Y')}. "
            f"Payslips are not generated for months before "
            f"the joining date."
        )

        return

    if (year, month) > (latest_year, latest_month):

        st.warning(
            f"{MONTHS[month - 1]} {year} has not reached its "
            "scheduled release date. "
            f"Pay date: {payroll_release_date(year, month):%d %b %Y}."
        )

        return

    if stop and (year, month) > stop:

        st.warning(
            f"Final settlement is saved for "
            f"{employee[1]}. Payroll closed after "
            f"{MONTHS[stop[1] - 1]} {stop[0]}, so no payslip can "
            "be generated for this month.",
            icon=":material/lock:"
        )

        return

    # -----------------------------------------------------
    # EDITABLE PAYSLIP
    # -----------------------------------------------------
    # If the period is already saved, show the stored figures so
    # HR edits the real payslip. Otherwise the figures come from
    # the salary structure. Every component can be changed before
    # saving; totals, LOP and net pay are recalculated here.

    saved = get_saved_payslip_details(employee[0], year, month)

    if saved:

        breakdown = breakdown_from_saved(employee, saved)

        st.caption(
            f"This payslip is already saved for "
            f"{MONTHS[month - 1]} {year}. Edit any component below "
            "and save again to correct it."
        )

    else:

        st.caption(
            f"This payslip is not saved yet for "
            f"{MONTHS[month - 1]} {year}. Adjust anything below, "
            "then save it."
        )

    with st.expander(
        "Edit this payslip",
        expanded=bool(saved),
        icon=":material/edit_note:"
    ):

        earn_col, deduct_col = st.columns(2)

        with earn_col:

            st.markdown("**Earnings (monthly)**")

            basic = st.number_input(
                "Basic",
                min_value=0.0,
                value=round(breakdown["basic"], 2),
                step=100.0,
                key=f"edit_basic_{employee[0]}_{year}_{month}"
            )

            hra = st.number_input(
                "HRA",
                min_value=0.0,
                value=round(breakdown["hra"], 2),
                step=100.0,
                key=f"edit_hra_{employee[0]}_{year}_{month}"
            )

            special = st.number_input(
                "Special allowance",
                min_value=0.0,
                value=round(breakdown["special"], 2),
                step=100.0,
                key=f"edit_special_{employee[0]}_{year}_{month}"
            )

            other_allowance = st.number_input(
                "Other allowance",
                min_value=0.0,
                value=round(breakdown["other_allowance"], 2),
                step=100.0,
                key=f"edit_other_{employee[0]}_{year}_{month}"
            )

        with deduct_col:

            st.markdown("**Deductions (monthly)**")

            employee_pf = st.number_input(
                "Employee PF",
                min_value=0.0,
                value=round(breakdown["employee_pf"], 2),
                step=50.0,
                key=f"edit_epf_{employee[0]}_{year}_{month}"
            )

            employer_pf = st.number_input(
                "Employer PF (shown, not deducted)",
                min_value=0.0,
                value=round(breakdown["employer_pf"], 2),
                step=50.0,
                key=f"edit_rpf_{employee[0]}_{year}_{month}"
            )

            professional_tax = st.number_input(
                "Professional Tax",
                min_value=0.0,
                value=round(breakdown["professional_tax"], 2),
                disabled=True,
                key=f"edit_pt_{employee[0]}_{year}_{month}"
            )

            other_deduction = st.number_input(
                "Other deduction",
                min_value=0.0,
                value=round(breakdown["other_deduction"], 2),
                step=50.0,
                key=f"edit_ded_{employee[0]}_{year}_{month}"
            )

            lop_days_input = st.number_input(
                f"LOP days — {MONTHS[month - 1]} {year}",
                min_value=0,
                max_value=month_days(month, year),
                value=int(breakdown.get("lop_days") or 0),
                step=1,
                key=f"lop_{employee[0]}_{year}_{month}"
            )

        st.caption(
            "LOP defaults to approved 'Loss of Pay' leave in this "
            "month. Its amount is prorated from gross monthly salary "
            "and deducted from net pay."
        )

    breakdown.update(
        {
            "basic": basic,
            "hra": hra,
            "special": special,
            "other_allowance": other_allowance,
            "employee_pf": employee_pf,
            "employer_pf": employer_pf,
            "professional_tax": professional_tax,
            "other_deduction": other_deduction
        }
    )

    breakdown["gross_monthly"] = round(
        basic + hra + special + other_allowance,
        2
    )

    breakdown["total_deductions"] = round(
        employee_pf + professional_tax + other_deduction,
        2
    )

    breakdown = apply_lop(breakdown, month, year, lop_days_input)

    metric_cols = st.columns(4)

    with metric_cols[0]:

        st.metric(
            "Gross",
            f"₹ {breakdown['gross_monthly']:,.2f}",
            icon=":material/trending_up:",
            border=True
        )

    with metric_cols[1]:

        st.metric(
            "Deductions",
            f"₹ {breakdown['total_deductions']:,.2f}",
            icon=":material/trending_down:",
            border=True
        )

    with metric_cols[2]:

        st.metric(
            "LOP",
            f"₹ {breakdown['lop_amount']:,.2f}",
            icon=":material/event_busy:",
            border=True,
            help=f"{breakdown['lop_days']} day(s) of loss of pay."
        )

    with metric_cols[3]:

        st.metric(
            "Net pay",
            f"₹ {breakdown['net_pay']:,.2f}",
            icon=":material/payments:",
            border=True
        )

    # -----------------------------------------------------
    # PREVIEW
    # -----------------------------------------------------

    render_payslip_preview(breakdown, month, year)

    # -----------------------------------------------------
    # EPFO CONTRIBUTION & BALANCE
    # -----------------------------------------------------

    # Imported locally so this module and epfo.py never form a
    # circular dependency (epfo.py builds on this module).
    from modules.epfo import render_epfo_section

    render_epfo_section(employee, year, month)

    # -----------------------------------------------------
    # ACTIONS
    # -----------------------------------------------------

    save_col, download_col = st.columns(2)

    with save_col:

        if st.button(
            "Save Payslip",
            width="stretch"
        ):

            save_payslip(
                employee,
                month,
                year,
                breakdown
            )

            st.success(
                f"Payslip saved for "
                f"{breakdown['employee_name']} "
                f"({MONTHS[month - 1]} {year})."
            )

    with download_col:

        st.download_button(
            "Download Payslip (PDF)",
            data=build_payslip_pdf(
                breakdown,
                month,
                year
            ),
            file_name=(
                f"payslip_{breakdown['employee_id']}_"
                f"{year}{month:02d}.pdf"
            ),
            mime="application/pdf",
            width="stretch"
        )

    # -----------------------------------------------------
    # RECENT PAYSLIPS
    # -----------------------------------------------------

    saved = get_saved_payslips()

    if saved:

        st.divider()

        st.markdown("###  Recent Payslips")

        for (
            employee_id,
            employee_name,
            pay_month,
            pay_year,
            gross,
            deductions,
            net,
            _generated_at
        ) in saved:

            with st.container(border=True):

                row1, row2, row3, row4 = st.columns(4)

                with row1:

                    st.write(
                        f"**{employee_name}**"
                    )

                    st.caption(f"ID: {employee_id}")

                with row2:

                    st.write(
                        f"**Period:** "
                        f"{MONTHS[pay_month - 1]} {pay_year}"
                    )

                    st.caption(
                        f"Pay date: "
                        f"{payroll_release_date(pay_year, pay_month):%d %b %Y}"
                    )

                with row3:

                    st.write(
                        f"**Gross:** "
                        f"₹ {gross:,.2f}"
                    )

                    st.caption(
                        f"Deductions: ₹ {deductions:,.2f}"
                    )

                with row4:

                    st.metric(
                        "Net Pay",
                        f"₹ {net:,.2f}"
                    )

                view_key = (
                    f"view_saved_{employee_id}_"
                    f"{pay_year}_{pay_month}"
                )

                view_on = bool(
                    st.session_state.get(view_key, False)
                )

                if st.button(
                    "Hide details"
                    if view_on
                    else "View payslip",
                    key=f"toggle_{view_key}",
                    width="stretch"
                ):

                    st.session_state[view_key] = not view_on

                    st.rerun()

                if view_on:

                    employee_row = next(
                        (
                            row for row in employees
                            if row[0] == employee_id
                        ),
                        None
                    )

                    saved_row = get_saved_payslip_details(
                        employee_id,
                        pay_year,
                        pay_month
                    )

                    if employee_row and saved_row:

                        st.divider()

                        render_payslip_preview(
                            breakdown_from_saved(
                                employee_row,
                                saved_row
                            ),
                            pay_month,
                            pay_year
                        )


# ============================================================
# PAYSLIP PAGE (header + back button + module)
# ============================================================

def show_payslip_page(go_home=None):
    """Full payslip page, wired up by main.py."""

    st.title("Payroll", icon=":material/payments:")

    st.caption(
        "Monthly payroll operations, employee payslips, and PF details."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="payslip_back",
        width="content"
    ):

        go_home()

        st.rerun()

    show_payslip()


# =========================================================
# MY PAYSLIPS (EMPLOYEE VIEW)
# =========================================================
# The signed-in employee's own released payslips, with PDF downloads and the
# EPFO contribution & balance section after the list.

def _my_payslips(employee_id):
    """All saved payslips for one employee, newest first."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
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
                lop_amount,
                generated_at
            FROM payslips
            WHERE employee_id = ?
            ORDER BY pay_year DESC, pay_month DESC
            """,
            (employee_id,)
        ).fetchall()

    finally:

        connection.close()

    keys = [
        "pay_month",
        "pay_year",
        "basic_monthly",
        "hra_monthly",
        "special_allowance_monthly",
        "other_allowance_monthly",
        "gross_monthly",
        "employee_pf_monthly",
        "employer_pf_monthly",
        "professional_tax_monthly",
        "other_deduction_monthly",
        "total_deductions",
        "net_pay",
        "lop_days",
        "lop_amount",
        "generated_at"
    ]

    return [dict(zip(keys, row)) for row in rows]


def _monthly_breakdown(employee, payslip):
    """Rebuild a payslip breakdown from a stored payslip row."""

    day_counts = payroll_day_counts(
        employee["joining_date"],
        payslip["pay_year"],
        payslip["pay_month"]
    )

    return {
        "employee_id": employee["employee_id"],
        "employee_name": employee["employee_name"],
        "department": employee["department"],
        "designation": employee["designation"],
        "joining_date": employee["joining_date"],
        "location": employee["location"],
        "employment_type": employee["employment_type"],
        "annual_ctc": employee["annual_ctc"],
        "basic": payslip["basic_monthly"],
        "hra": payslip["hra_monthly"],
        "special": payslip["special_allowance_monthly"],
        "other_allowance": payslip["other_allowance_monthly"],
        "gross_monthly": payslip["gross_monthly"],
        "employee_pf": payslip["employee_pf_monthly"],
        "employer_pf": payslip["employer_pf_monthly"],
        "professional_tax": payslip["professional_tax_monthly"],
        "other_deduction": payslip["other_deduction_monthly"],
        "total_deductions": payslip["total_deductions"],
        "lop_days": payslip.get("lop_days", 0),
        "lop_amount": payslip.get("lop_amount", 0.0),
        "net_pay": payslip["net_pay"],
        **day_counts
    }


def _accrual_end(employee_id, today):
    """The latest date this employee's payroll should cover.

    The end of the exit month once the employee has exited,
    otherwise today. Imported locally because settlement.py builds
    on this module and would otherwise form a cycle.
    """

    from modules.settlement import last_accrual_period

    year, month = last_accrual_period(employee_id, today)

    if (year, month) < (today.year, today.month):

        return datetime.date(year, month, month_days(month, year))

    return today


def latest_payslip(employee_id):
    """The employee's newest payslip as a summary, or None.

    Only released and saved payslips are distributed to employees.
    Used by the employee home overview.
    """

    employee = employee_details(employee_id)

    if not employee:

        return None

    today = datetime.date.today()

    saved = {
        (row["pay_year"], row["pay_month"]): row
        for row in _my_payslips(employee_id)
    }

    accrual_end = _accrual_end(employee_id, today)
    latest_period = min(
        latest_released_payroll_period(today),
        (accrual_end.year, accrual_end.month)
    )
    saved = {
        period: record
        for period, record in saved.items()
        if period <= latest_period
    }

    if not saved:

        return None

    (year, month), record = max(saved.items())
    breakdown = _monthly_breakdown(employee, record)
    generated = payroll_release_date(year, month).isoformat()

    return {
        "period": f"{MONTHS[month - 1]} {year}",
        "net_pay": breakdown["net_pay"],
        "gross": breakdown["gross_monthly"],
        "deductions": breakdown["total_deductions"],
        "generated": _nice_date(generated),
        "breakdown": breakdown,
        "month": month,
        "year": year,
    }


def _nice_date(value):
    """'2026-10-01' -> '01 Oct 2026'; other values pass through."""

    if not value:

        return value

    try:

        return datetime.date.fromisoformat(
            str(value)[:10]
        ).strftime("%d %b %Y")

    except ValueError:

        return value


def _payslip_date(value):
    """Format a stored date as DD/MM/YYYY for the payslip."""

    parsed = parse_joining_date(value)

    return parsed.strftime("%d/%m/%Y") if parsed else str(value or "—")


def _financial_year_start(year, month):
    """Return the starting calendar year for an April-to-March FY."""

    return year if month >= 4 else year - 1


def _render_annual_earnings(employee, saved, latest_period):
    """Render the employee's released earnings by financial year/month."""

    joining_date = parse_joining_date(employee.get("joining_date"))
    latest_fy = _financial_year_start(*latest_period)
    financial_years = {
        _financial_year_start(year, month)
        for year, month in saved
        if (year, month) <= latest_period
    }

    if (
        not joining_date
        or (joining_date.year, joining_date.month) <= latest_period
    ):
        financial_years.add(latest_fy)

    if joining_date:
        financial_years = {
            year for year in financial_years
            if year + 1 >= joining_date.year
        }

    if not financial_years:
        return

    options = sorted(financial_years, reverse=True)

    def format_fy(year):
        return f"{year} - {str(year + 1)[-2:]}"

    st.divider()
    st.subheader("Annual earnings", icon=":material/show_chart:")
    selected_fy = st.selectbox(
        "Financial year",
        options,
        format_func=format_fy,
        key=f"annual_earnings_fy_{employee['employee_id']}",
    )

    fiscal_periods = []
    for month in range(4, 13):
        fiscal_periods.append((selected_fy, month))
    for month in range(1, 4):
        fiscal_periods.append((selected_fy + 1, month))

    if joining_date and _financial_year_start(
        joining_date.year,
        joining_date.month,
    ) == selected_fy:
        fiscal_periods = [
            period for period in fiscal_periods
            if period >= (joining_date.year, joining_date.month)
        ]

    released_periods = [
        period for period in fiscal_periods
        if period <= latest_period and period in saved
    ]

    if not released_periods:
        st.info(
            "No released payslips are available for this financial year yet."
        )
        return

    last_generated_period = max(released_periods)
    periods = [
        period for period in fiscal_periods
        if period <= last_generated_period
    ]
    component_fields = [
        ("Basic", "basic_monthly"),
        ("House Rent Allowance", "hra_monthly"),
        ("Special Allowance", "special_allowance_monthly"),
        ("Other Allowance", "other_allowance_monthly"),
        ("Total Earnings", "gross_monthly"),
        ("Total Deductions", "total_deductions"),
        ("Net Pay", "net_pay"),
    ]
    month_labels = [
        f"{MONTHS[month - 1]} {year}"
        for year, month in periods
    ]
    short_labels = [
        f"{MONTHS[month - 1][:3]} {year}"
        for year, month in periods
    ]
    chart_rows = []
    actual_records = []

    for (year, month), label, short_label in zip(periods, month_labels, short_labels):
        record = saved.get((year, month))
        if record:
            total_earnings = float(record["gross_monthly"] or 0)
            net_pay = float(record["net_pay"] or 0)
            actual_records.append(record)
        else:
            total_earnings = None
            net_pay = None

        chart_rows.append({
            "MonthLabel": short_label,
            "FullMonth": label,
            "Total earnings": total_earnings,
            "Net pay": net_pay,
        })

    table_months = list(zip(periods, month_labels))
    table_rows = []
    for label, field in component_fields:
        table_rows.append({
            "Earnings": label,
            "YTD Total": sum(
                float(record[field] or 0) for record in actual_records
            ),
            **{
                month_label: (
                    float(saved[period][field] or 0)
                    if period in saved
                    else None
                )
                for period, month_label in table_months
            },
        })

    st.caption(
        f"Released earnings for FY {format_fy(selected_fy)}. "
        "The chart and table end at the latest generated payslip."
    )
    chart_data = pd.DataFrame(chart_rows)
    x_axis = alt.Axis(
        title=None,
        labelAngle=0,
        labelColor="#748078",
        labelFontSize=11,
        tickColor="#DCE5DF",
        domain=False,
        grid=False,
    )
    y_axis = alt.Axis(
        title="Gross earnings (₹)",
        titleColor="#58675F",
        labelColor="#748078",
        labelFontSize=10,
        tickCount=5,
        format="~s",
        grid=True,
        gridColor="#E8EEEA",
        domain=False,
    )
    chart_base = alt.Chart(chart_data).encode(
        x=alt.X(
            "MonthLabel:O",
            sort=short_labels,
            axis=x_axis,
        ),
        y=alt.Y(
            "Total earnings:Q",
            axis=y_axis,
            scale=alt.Scale(zero=True),
        ),
        tooltip=[
            alt.Tooltip("FullMonth:N", title="Month"),
            alt.Tooltip(
                "Total earnings:Q",
                title="Gross earnings",
                format=",.2f",
            ),
            alt.Tooltip(
                "Net pay:Q",
                title="Net pay",
                format=",.2f",
            ),
        ],
    )
    earnings_chart = alt.layer(
        chart_base.mark_area(
            color="#2F80ED",
            opacity=0.07,
            interpolate="linear",
        ),
        chart_base.mark_line(
            color="#2F80ED",
            strokeWidth=2.5,
            point=alt.OverlayMarkDef(
                filled=True,
                fill="white",
                stroke="#2F80ED",
                strokeWidth=2,
                size=65,
            ),
            interpolate="linear",
        ),
    ).properties(
        height=275,
        background="#FFFFFF",
        padding={"left": 12, "right": 12, "top": 12, "bottom": 8},
    ).configure_view(
        stroke="#D8E1DB",
        strokeWidth=1,
        cornerRadius=4,
    ).configure_axisY(
        labelPadding=8,
        titlePadding=12,
    )
    st.altair_chart(
        earnings_chart,
        width="stretch",
        theme=None,
        key=f"annual_earnings_chart_{employee['employee_id']}_{selected_fy}",
    )

    earnings_table = pd.DataFrame(table_rows)
    st.dataframe(
        earnings_table,
        hide_index=True,
        width="stretch",
        column_config={
            "Earnings": st.column_config.TextColumn(
                "Earnings",
                pinned=True,
            ),
            "YTD Total": st.column_config.NumberColumn(
                "YTD Total",
                format="₹ %.2f",
                pinned=True,
            ),
            **{
                month_label: st.column_config.NumberColumn(
                    month_label,
                    format="₹ %.2f",
                )
                for _, month_label in table_months
            },
        },
    )


def show_my_payslips():

    employee = require_employee()

    if employee is None:

        return

    st.title("My payslips", icon=":material/receipt_long:")

    st.caption(
        "Your released monthly payslips. Download any payslip as a PDF."
    )

    employee_id = employee["employee_id"]

    today = datetime.date.today()

    structure = get_structure(employee_id)
    salary_row = next(
        (
            candidate
            for candidate in get_employees_with_salary()
            if candidate[0] == employee_id
        ),
        None
    )

    saved = {
        (row["pay_year"], row["pay_month"]): row
        for row in _my_payslips(employee_id)
    }

    accrual_end = _accrual_end(employee_id, today)
    latest_period = min(
        latest_released_payroll_period(today),
        (accrual_end.year, accrual_end.month)
    )
    periods = sorted(
        (
            period for period in saved
            if period <= latest_period
        ),
        reverse=True
    )

    if not structure and not saved:

        st.info(
            "Your payslips are not available yet because your "
            "salary structure has not been set up. "
            "Please contact HR."
        )

        return

    if not periods:

        st.info(
            "Your first payslip will appear after the first pay "
            "period has been released."
        )

    _render_annual_earnings(
        employee,
        saved,
        latest_period,
    )

    for year, month in periods:

        record = saved.get((year, month))

        breakdown = _monthly_breakdown(employee, record)
        generated = payroll_release_date(year, month).isoformat()

        period = f"{MONTHS[month - 1]} {year}"

        with st.container(border=True):

            row1, row2, row3, row4 = st.columns(4)

            with row1:

                st.write(f"**{period}**")

                st.caption(
                    f"Pay date: {_nice_date(generated)}"
                    if generated
                    else "Pay date not recorded"
                )

            with row2:

                st.write(
                    f"**Gross:** "
                    f"₹ {breakdown['gross_monthly']:,.2f}"
                )

                st.caption(
                    f"Deductions: "
                    f"₹ {breakdown['total_deductions']:,.2f}"
                )

            with row3:

                st.metric(
                    "Net pay",
                    f"₹ {breakdown['net_pay']:,.2f}"
                )

            with row4:

                view_key = (
                    f"view_ps_{employee_id}_"
                    f"{year}_{month}"
                )

                view_on = bool(
                    st.session_state.get(view_key, False)
                )

                if st.button(
                    "Hide details"
                    if view_on
                    else "View payslip",
                    key=f"toggle_{view_key}",
                    width="stretch"
                ):

                    st.session_state[view_key] = not view_on

                    st.rerun()

                st.download_button(
                    "Download PDF",
                    data=build_payslip_pdf(breakdown, month, year),
                    file_name=(
                        f"payslip_{employee_id}_"
                        f"{year}{month:02d}.pdf"
                    ),
                    mime="application/pdf",
                    key=f"dl_{employee_id}_{year}_{month}",
                    width="stretch"
                )

            if view_on:

                st.divider()

                render_payslip_preview(breakdown, month, year)

    # -------------------------------------------------
    # EPFO STATEMENT (after the payslips)
    # -------------------------------------------------

    if salary_row:

        # Imported locally so this module and epfo.py never form a
        # circular dependency (epfo.py builds on this module).
        from modules.epfo import render_epfo_section

        render_epfo_section(salary_row, today.year, today.month)
    else:
        st.info(
            "PF details are not available because your salary "
            "structure has not been set up."
        )
