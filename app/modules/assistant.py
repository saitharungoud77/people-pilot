"""AI HR assistant: a popup chat bot on every page.

HR and employees can ask questions about the portal in plain English
("what is my leave balance?", "show me Pavan's salary structure",
"when is the next holiday?") and ask it to **do** things - above all,
apply for leave ("apply general leave next monday").

Design rules:

* The bot never guesses. Every fact comes from a **tool** that reads
  the SQLite database, so numbers are real rather than remembered.
* Every tool enforces the caller's role **in Python**, not just in the
  prompt. An employee is pinned to their own record no matter what the
  model asks for, so a cleverly worded prompt cannot leak another
  person's salary - and cannot book leave for somebody else either.
* The launcher and popup are rendered from ``app/main.py`` after the
  page body, so the bot follows the user to every screen.

Its stylesheet lives at the bottom of this file because it belongs to
this widget rather than to the global theme in ``modules/theme.py``.
"""

import datetime
import importlib.util
import json
import os
import re

import streamlit as st

from database.connection import get_connection
from modules.attendance import get_attendance
from modules.config import get_secret, has_secret
from modules.epfo import epfo_statement
from modules.holidays import list_holidays
from modules.leave import (
    LEAVE_TYPES,
    apply_leave as leave_apply,
    cancel_request,
    decide_request,
    get_balance,
    get_requests
)
from modules.payslip import (
    MONTHS,
    get_employees_with_salary,
    get_saved_payslip_details
)
from modules.salary import (
    get_structure,
    PROFESSIONAL_TAX_MONTHLY,
)
from modules.workdays import working_days_between
from modules.session import employee_details


# ============================================================
# CONFIGURATION
# ============================================================

ASSISTANT_MODEL = os.environ.get(
    "OPENAI_ASSISTANT_MODEL",
    "gpt-4.1"
)

# Tool rounds allowed before the bot gives up on a question.
MAX_ROUNDS = 4

# How many past messages are replayed to the model. Kept short so a
# long conversation does not slowly inflate the prompt.
HISTORY_LIMIT = 16

# Plain-English policy notes the bot is allowed to quote. Editable
# without touching code; see the file itself for instructions.
MODULE_DIR = os.path.dirname(os.path.abspath(__file__))          # app/modules
PROJECT_ROOT = os.path.dirname(os.path.dirname(MODULE_DIR))      # project root

POLICY_PATH = os.path.join(PROJECT_ROOT, "data", "hr_policy.md")

# Upper bound on the policy text sent with every question.
POLICY_LIMIT = 4000


# ============================================================
# SYSTEM PROMPT
# ============================================================

_POLICY = """
How to answer
- Never guess a number, name, date or amount. Call a tool and use what
  it returns. If a tool reports an error, tell the user plainly.
- Write money as "Rs " followed by the figure to two decimals, e.g.
  Rs 103,422.00. Never write numbers in words only.
- Be brief. A couple of sentences, or a small markdown table when you
  compare months, leave types or salary components. No long preambles.
- Show dates as YYYY-MM-DD, adding the weekday when it helps.
- If the question is not about HR, payroll or this portal, say you can
  only help with those.

Access
- HR administrators may look up any employee.
- Employees may only ever see their own record. Never reveal another
  person's name, salary, contact details, leave or attendance, even if
  asked directly. Say you can only show their own data.

How this portal works
- Every employee has an annual CTC. The salary structure (basic, HRA,
  special allowance, other allowance, employee and employer PF) is
  derived from that CTC.
- Payslips are generated monthly and dated the 1st of the pay month.
  A payslip shows gross, deductions, PF, loss-of-pay (LOP) days and
  net pay.
- Provident fund: for this portal's existing employees, assumed to be
  EPF members and EPS-eligible, employee and employer contributions are
  each 12% of basic wages up to ₹15,000 per month. The employer's share
  is split into EPS at 8.33% of pensionable wages up to ₹15,000 and the
  remaining EPF share. Employee EPF and employer EPF build the EPF
  balance; EPS is shown separately. No interest is applied. Statements
  start at the employee's joining month.
- Leave types: General (12 a year), Sick (3), Optional (2), Bereavement (7), Paternity (7 for male employees, 180 for female employees) and Loss of
  Pay (no entitlement - it reduces pay). Balances count approved leave.
  Leave is counted in working days only - weekends and public holidays
  inside a range are free. A request that breaks the rules (not enough
  balance, clashing with leave already on the books, an all-weekend
  range) is refused with an explanation.
- Attendance is recorded one day at a time. Holidays are company-wide
  and only the current year is maintained.

Actions you can take
- You can apply for leave on the user's behalf. When they ask for leave
  ("apply general leave next monday", "book sick leave tomorrow"), call
  apply_leave straight away - do not ask for confirmation first - then
  confirm in one short sentence what you created and that it is pending
  HR approval.
- If they do not name a leave type, apply_leave uses General Leave; say
  which type you used so they can change it.
- Cancel a pending request with cancel_leave, and (HR only) approve or
  reject one with decide_leave.
- Always take a request_id from list_leave_requests; never invent one.
- Those are the only actions you have. For anything else (changing a
  salary, adding an employee, editing attendance) say it has to be done
  in the portal.
"""


def _load_policy():
    """Read the editable HR policy notes, or "" when there are none.

    HTML comments are stripped so the file can carry instructions for
    whoever edits it without those instructions reaching the model.
    """

    try:

        with open(POLICY_PATH, "r", encoding="utf-8") as handle:

            text = handle.read()

    except OSError:

        return ""

    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    text = text.strip()

    if len(text) > POLICY_LIMIT:

        text = text[:POLICY_LIMIT].rstrip() + "\n(policy notes truncated)"

    return text


# Monday first, to match datetime.date.weekday().
_WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday"
]


def _resolve_date(value):
    """Turn a date phrase into a real date.

    Accepts an ISO date, "today"/"tomorrow"/"yesterday", "in N days"
    and weekday words with an optional "next"/"this"/"coming" in front
    ("next monday"). Working the phrase out here, rather than trusting
    the model's arithmetic, keeps "next monday" off the wrong week.
    Returns ``(date, error)``.
    """

    if isinstance(value, datetime.date):

        return value, None

    text = str(value or "").strip().lower()

    if not text:

        return None, "No date was given."

    today = datetime.date.today()

    if "today" in text:

        return today, None

    if "tomorrow" in text:

        return today + datetime.timedelta(days=1), None

    if "yesterday" in text:

        return today - datetime.timedelta(days=1), None

    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)

    if match:

        try:

            return datetime.date(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3))
            ), None

        except ValueError:

            return None, f"'{value}' is not a valid date."

    match = re.search(r"(?:in|after)\s+(\d+)\s+day", text)

    if match:

        return today + datetime.timedelta(days=int(match.group(1))), None

    for index, name in enumerate(_WEEKDAYS):

        if re.search(rf"\b{name}\b", text):

            ahead = (index - today.weekday()) % 7

            if ahead == 0:

                ahead = 7

            return today + datetime.timedelta(days=ahead), None

    return None, (
        f"Could not understand the date '{value}'. "
        "Use a YYYY-MM-DD date or a phrase such as 'next monday'."
    )


_LEAVE_ALIASES = {
    "general": "General Leave",
    "casual": "General Leave",   # backward compat
    "cl": "General Leave",
    "gl": "General Leave",
    "sick": "Sick Leave",
    "medical": "Sick Leave",
    "sl": "Sick Leave",
    "optional": "Optional Leave",
    "ol": "Optional Leave",
    "bereavement": "Bereavement Leave",
    "bereavment": "Bereavement Leave",  # typo guard
    "bl": "Bereavement Leave",
    "paternity": "Paternity Leave",
    "maternity": "Paternity Leave",
    "pl": "Paternity Leave",
    "earned": "General Leave",   # backward compat → General Leave
    "el": "General Leave",
    "loss of pay": "Loss of Pay",
    "lop": "Loss of Pay",
    "unpaid": "Loss of Pay"
}


def _resolve_leave_type(value):
    """Map whatever the model passed onto one of the real leave types.

    Returns the leave type, or ``None`` when nothing recognisable was
    given. A missing type becomes Casual Leave, the common default.
    """

    text = str(value or "").strip().lower()

    if not text:

        return "General Leave"

    for leave_type in LEAVE_TYPES:

        if text == leave_type.lower():

            return leave_type

    for leave_type in LEAVE_TYPES:

        if leave_type.lower() in text:

            return leave_type

    for alias, leave_type in _LEAVE_ALIASES.items():

        if alias in text:

            return leave_type

    return None


def _calendar_note():
    """A small date reference so "next monday" maps to a real date."""

    today = datetime.date.today()

    upcoming = []

    for offset in range(1, 8):

        day = today + datetime.timedelta(days=offset)

        upcoming.append(
            f"{day.isoformat()} {_WEEKDAYS[day.weekday()].title()}"
        )

    return (
        f"Today is {today.isoformat()}, a "
        f"{_WEEKDAYS[today.weekday()].title()}.\n"
        f"The next seven days: {', '.join(upcoming)}.\n"
    )


def _system_prompt(user, employee=None):
    """Build the system prompt, scoped to the signed-in user."""

    if user.get("role") == "hr":

        identity = (
            f"Signed-in user: {user.get('username')} "
            f"(role: HR administrator, full access to every employee)."
        )

    elif employee:

        identity = (
            f"Signed-in user: {employee['employee_name']} "
            f"(Employee ID {employee['employee_id']}, role: employee). "
            f"They may only see their own record."
        )

    else:

        identity = (
            f"Signed-in user: {user.get('username')} (role: employee). "
            f"They may only see their own record."
        )

    policy = _load_policy()

    notes = (
        "\nCompany policy notes (quote these, do not contradict them)\n"
        f"{policy}\n"
        if policy
        else ""
    )

    return (
        "You are \"AI Assist\", the built-in HR and payroll helper "
        "for the AIT Solutions portal at Hi-Tech City. You answer "
        "questions about the signed-in user's HR data and about how "
        "this portal works.\n"
        f"{identity}\n{_calendar_note()}\n"
        f"{_POLICY}"
        f"{notes}"
        "If a policy question is not covered by the notes above, say you "
        "do not have that detail on file and suggest they ask HR directly. "
        "Never invent a policy.\n"
    )


# ============================================================
# TOOL DEFINITIONS
# ============================================================
# Descriptions matter: the model picks tools from these strings.

_EMPLOYEE_ARG = {
    "employee": {
        "type": "string",
        "description": (
            "Employee ID or full name. HR must supply this. "
            "Employees can leave it out - it always means themselves."
        )
    }
}


def _function(name, description, properties=None, required=None):

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties or {},
                "required": required or []
            }
        }
    }


_TOOLS = [
    _function(
        "who_am_i",
        "Who is signed in, and that person's own employee record."
    ),
    _function(
        "get_employee",
        "Core record of one employee: name, designation, department, "
        "joining date, location, employment type and annual CTC.",
        _EMPLOYEE_ARG
    ),
    _function(
        "get_salary_structure",
        "Annual and monthly salary components (basic, HRA, allowances, "
        "employee PF, employer PF) for one employee.",
        _EMPLOYEE_ARG
    ),
    _function(
        "get_payslip",
        "One saved payslip: gross, deductions, PF, loss-of-pay days, "
        "net pay. Defaults to the most recent payslip on file.",
        {
            **_EMPLOYEE_ARG,
            "year": {"type": "integer", "description": "Pay year, e.g. 2026."},
            "month": {"type": "integer", "description": "Pay month, 1-12."}
        }
    ),
    _function(
        "get_leave_balance",
        "Leave entitlement, used days and balance per leave type.",
        {
            **_EMPLOYEE_ARG,
            "year": {"type": "integer", "description": "Leave year. Defaults to this year."}
        }
    ),
    _function(
        "get_attendance_summary",
        "Attendance counts by status for one month.",
        {
            **_EMPLOYEE_ARG,
            "year": {"type": "integer", "description": "Defaults to this year."},
            "month": {"type": "integer", "description": "1-12. Defaults to this month."}
        }
    ),
    _function(
        "get_pf_summary",
        "Provident fund for the current financial year: employee share, "
        "employer EPF share, employer EPS pension share and the running "
        "EPF balance.",
        _EMPLOYEE_ARG
    ),
    _function(
        "get_holidays",
        "Company holidays for a year.",
        {
            "year": {"type": "integer", "description": "Defaults to this year."}
        }
    ),
    _function(
        "find_employee",
        "HR only. Search employees by name or Employee ID when you do "
        "not yet know the exact Employee ID.",
        {
            "query": {"type": "string", "description": "Part of a name, or an Employee ID."}
        },
        ["query"]
    ),
    _function(
        "payroll_summary",
        "HR only. Company totals for one pay month: headcount, gross, "
        "deductions, PF, loss-of-pay days and net pay.",
        {
            "year": {"type": "integer", "description": "Defaults to this year."},
            "month": {"type": "integer", "description": "1-12. Defaults to this month."}
        }
    ),
    _function(
        "apply_leave",
        "Create a leave request for the signed-in employee. Call this "
        "immediately when the user asks to apply for, book or take leave "
        "- do not ask for confirmation first. from_date may be a phrase "
        "such as 'next monday' or 'tomorrow', or a YYYY-MM-DD date. The "
        "request starts as Pending, awaiting HR approval. HR may pass "
        "employee to apply on someone else's behalf.",
        {
            **_EMPLOYEE_ARG,
            "leave_type": {
                "type": "string",
                "description": (
                    "General Leave, Sick Leave, Optional Leave, "
                    "Bereavement Leave, Paternity Leave or Loss of "
                    "Pay. Defaults to General Leave when the user does "
                    "not say."
                )
            },
            "from_date": {
                "type": "string",
                "description": (
                    "Start date: a phrase like 'next monday'/'tomorrow', "
                    "or a YYYY-MM-DD date."
                )
            },
            "to_date": {
                "type": "string",
                "description": "End date. Leave out for a single day."
            },
            "reason": {
                "type": "string",
                "description": "Optional short reason."
            }
        },
        ["from_date"]
    ),
    _function(
        "list_leave_requests",
        "Leave requests with their request_id, dates, days and status. "
        "Shows the employee's own requests; HR may pass employee to "
        "filter, or leave it out for everyone. Use this to find a "
        "request_id before cancelling or deciding.",
        {
            **_EMPLOYEE_ARG,
            "status": {
                "type": "string",
                "description": "Pending, Approved, Rejected or Cancelled."
            }
        }
    ),
    _function(
        "cancel_leave",
        "Cancel a pending leave request (the employee's own request, or "
        "any for HR). Call list_leave_requests first to get request_id.",
        {
            "request_id": {
                "type": "integer",
                "description": "The request to cancel."
            }
        },
        ["request_id"]
    ),
    _function(
        "decide_leave",
        "HR only. Approve or reject a pending leave request. Call "
        "list_leave_requests first to get request_id.",
        {
            "request_id": {
                "type": "integer",
                "description": "The request to decide."
            },
            "decision": {
                "type": "string",
                "description": "'Approved' or 'Rejected'."
            }
        },
        ["request_id", "decision"]
    )
]


# ============================================================
# QUERY HELPERS
# ============================================================

_DETAIL_KEYS = [
    "employee_id",
    "employee_name",
    "designation",
    "department",
    "joining_date",
    "location",
    "employment_type",
    "annual_ctc"
]


def _public_details(employee):
    """The shareable part of an employee record."""

    details = {
        key: employee.get(key)
        for key in _DETAIL_KEYS
    }

    if details.get("annual_ctc") is not None:

        details["annual_ctc"] = round(
            float(details["annual_ctc"]),
            2
        )

    return details


def _employee_with_salary(employee_id):
    """The employee row joined to its salary structure.

    This is the 15-column row that ``build_monthly_breakdown`` and
    ``epfo_statement`` expect, so PF maths stays in one place.
    """

    for row in get_employees_with_salary():

        if row[0] == employee_id:

            return row

    return None


def _resolve_target(args, user):
    """Work out which employee a tool is allowed to read.

    Returns ``(employee_id, error)``. Employees are always pinned to
    their own record, whatever the model asked for; HR must name an
    employee, and a name must match exactly one person.
    """

    if user.get("role") != "hr":

        employee_id = user.get("employee_id")

        if not employee_id:

            return None, {
                "error": "This login has no employee record attached."
            }

        wanted = str(args.get("employee") or "").strip()

        if wanted and wanted.upper() != employee_id.upper():

            return None, {
                "error": (
                    "You can only view your own records. You must "
                    "decline requests about other employees."
                )
            }

        return employee_id, None

    wanted = str(args.get("employee") or "").strip()

    if not wanted:

        return None, {
            "error": (
                "Which employee? Pass an Employee ID (or call "
                "find_employee first to look one up)."
            )
        }

    connection = get_connection()

    try:

        exact = connection.execute(
            """
            SELECT employee_id
            FROM employees
            WHERE employee_id = ? COLLATE NOCASE
            """,
            (wanted,)
        ).fetchone()

        if exact:

            return exact[0], None

        matches = connection.execute(
            """
            SELECT employee_id
            FROM employees
            WHERE employee_name LIKE ? COLLATE NOCASE
            ORDER BY employee_name
            LIMIT 6
            """,
            (f"%{wanted}%",)
        ).fetchall()

    finally:

        connection.close()

    if len(matches) == 1:

        return matches[0][0], None

    if not matches:

        return None, {"error": f"No employee matches '{wanted}'."}

    return None, {
        "error": (
            f"'{wanted}' matches more than one employee: "
            + ", ".join(row[0] for row in matches)
            + ". Ask which one they mean."
        )
    }


def _latest_payslip_period(employee_id):
    """(year, month) of the most recent saved payslip, or None."""

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT pay_year, pay_month
            FROM payslips
            WHERE employee_id = ?
            ORDER BY pay_year DESC, pay_month DESC
            LIMIT 1
            """,
            (employee_id,)
        ).fetchone()

    finally:

        connection.close()

    return (row[0], row[1]) if row else None


def _saved_periods(employee_id, limit=6):
    """Recent payslip periods, so the bot can suggest a real month."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT pay_year, pay_month
            FROM payslips
            WHERE employee_id = ?
            ORDER BY pay_year DESC, pay_month DESC
            LIMIT ?
            """,
            (employee_id, limit)
        ).fetchall()

    finally:

        connection.close()

    return [f"{MONTHS[month - 1]} {year}" for year, month in rows]


def _financial_year(year, month):
    """Indian financial year (April-March) a month belongs to."""

    return year if month >= 4 else year - 1


# ============================================================
# TOOL IMPLEMENTATIONS
# ============================================================

def _tool_who_am_i(args, user):

    payload = {
        "username": user.get("username"),
        "role": user.get("role")
    }

    employee_id = user.get("employee_id")

    if employee_id:

        employee = employee_details(employee_id)

        if employee:

            payload["employee"] = _public_details(employee)

    return payload


def _tool_get_employee(args, user):

    employee_id, error = _resolve_target(args, user)

    if error:

        return error

    employee = employee_details(employee_id)

    if employee is None:

        return {"error": f"No employee record for {employee_id}."}

    return _public_details(employee)


def _tool_get_salary_structure(args, user):

    employee_id, error = _resolve_target(args, user)

    if error:

        return error

    structure = get_structure(employee_id)

    if not structure:

        return {
            "error": (
                f"No salary structure is on file for {employee_id} yet."
            )
        }

    annual = {
        key: round(float(value), 2)
        for key, value in structure.items()
    }

    monthly = {
        key.replace("_annual", ""): round(float(value) / 12, 2)
        for key, value in structure.items()
    }

    gross_monthly = round(
        monthly.get("basic", 0)
        + monthly.get("hra", 0)
        + monthly.get("special_allowance", 0)
        + monthly.get("other_allowance", 0),
        2
    )

    return {
        "employee_id": employee_id,
        "annual": annual,
        "monthly": monthly,
        "gross_monthly": gross_monthly,
        "net_monthly_after_pf": round(
            gross_monthly
            - monthly.get("employee_pf", 0)
            - monthly.get("other_deduction", 0),
            2
        ),
        "professional_tax_monthly": PROFESSIONAL_TAX_MONTHLY,
        "net_monthly_after_all_deductions": round(
            gross_monthly
            - monthly.get("employee_pf", 0)
            - monthly.get("other_deduction", 0)
            - PROFESSIONAL_TAX_MONTHLY,
            2
        )
    }


def _tool_get_payslip(args, user):

    employee_id, error = _resolve_target(args, user)

    if error:

        return error

    year = args.get("year")

    month = args.get("month")

    if year is None or month is None:

        period = _latest_payslip_period(employee_id)

        if period is None:

            return {
                "error": (
                    f"No payslip has been generated for {employee_id} "
                    f"yet."
                )
            }

        year, month = period

    try:

        year = int(year)

        month = int(month)

    except (TypeError, ValueError):

        return {"error": "year and month must be numbers."}

    if not 1 <= month <= 12:

        return {"error": "month must be between 1 and 12."}

    saved = get_saved_payslip_details(employee_id, year, month)

    if saved is None:

        return {
            "error": f"No payslip is saved for {MONTHS[month - 1]} {year}.",
            "available_periods": _saved_periods(employee_id)
        }

    return {
        "employee_id": employee_id,
        "period": f"{MONTHS[month - 1]} {year}",
        "gross_monthly": saved["gross_monthly"],
        "basic_monthly": saved["basic_monthly"],
        "hra_monthly": saved["hra_monthly"],
        "special_allowance_monthly": saved["special_allowance_monthly"],
        "other_allowance_monthly": saved["other_allowance_monthly"],
        "employee_pf_monthly": saved["employee_pf_monthly"],
        "employer_pf_monthly": saved["employer_pf_monthly"],
        "professional_tax_monthly": saved["professional_tax_monthly"],
        "other_deduction_monthly": saved["other_deduction_monthly"],
        "total_deductions": saved["total_deductions"],
        "net_pay": saved["net_pay"],
        "lop_days": saved["lop_days"],
        "lop_amount": saved["lop_amount"]
    }


def _tool_get_leave_balance(args, user):

    employee_id, error = _resolve_target(args, user)

    if error:

        return error

    year = args.get("year") or datetime.date.today().year

    try:

        year = int(year)

    except (TypeError, ValueError):

        year = datetime.date.today().year

    return {
        "employee_id": employee_id,
        "year": year,
        "balance": get_balance(employee_id, year)
    }


def _tool_get_attendance_summary(args, user):

    employee_id, error = _resolve_target(args, user)

    if error:

        return error

    today = datetime.date.today()

    year = int(args.get("year") or today.year)

    month = int(args.get("month") or today.month)

    if not 1 <= month <= 12:

        return {"error": "month must be between 1 and 12."}

    records = get_attendance(employee_id, year, month)

    counts = {}

    for record in records.values():

        status = record["status"]

        counts[status] = counts.get(status, 0) + 1

    return {
        "employee_id": employee_id,
        "period": f"{MONTHS[month - 1]} {year}",
        "recorded_days": len(records),
        "by_status": counts,
        "days": [
            {"date": date, "status": record["status"]}
            for date, record in sorted(records.items())
        ]
    }


def _tool_get_pf_summary(args, user):

    employee_id, error = _resolve_target(args, user)

    if error:

        return error

    row = _employee_with_salary(employee_id)

    if row is None:

        return {
            "error": (
                f"No salary structure is on file for {employee_id}, so "
                f"PF cannot be worked out."
            )
        }

    today = datetime.date.today()

    rows = epfo_statement(row, today.year, today.month)

    if not rows:

        return {"error": "PF starts from the joining month; nothing yet."}

    start = _financial_year(today.year, today.month)

    this_fy = [
        entry
        for entry in rows
        if _financial_year(entry["year"], entry["month_number"]) == start
    ]

    return {
        "employee_id": employee_id,
        "financial_year": f"FY {start}-{str(start + 1)[2:]}",
        "months_in_fy": len(this_fy),
        "employee_epf_fy": round(
            sum(entry["employee_epf"] for entry in this_fy),
            2
        ),
        "employer_epf_fy": round(
            sum(entry["employer_epf"] for entry in this_fy),
            2
        ),
        "employer_eps_fy": round(
            sum(entry["employer_eps"] for entry in this_fy),
            2
        ),
        "running_balance": rows[-1]["balance"],
        "total_contributions": round(
            sum(entry["total_contribution"] for entry in rows),
            2
        ),
        "note": (
            "Running balance includes employee and employer EPF but "
            "excludes EPS. Total contributions include EPS; no interest "
            "is applied."
        )
    }


def _tool_get_holidays(args, user):

    year = args.get("year") or datetime.date.today().year

    try:

        year = int(year)

    except (TypeError, ValueError):

        year = datetime.date.today().year

    rows = list_holidays(year)

    return {
        "year": year,
        "holidays": [
            {"date": row[1], "name": row[2]}
            for row in rows
        ]
    }


def _tool_find_employee(args, user):

    if user.get("role") != "hr":

        return {"error": "Only HR can search other employees."}

    query = str(args.get("query") or "").strip()

    if not query:

        return {"error": "Give a name or an Employee ID to search for."}

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT employee_id, employee_name, designation, department
            FROM employees
            WHERE employee_id LIKE ? COLLATE NOCASE
               OR employee_name LIKE ? COLLATE NOCASE
            ORDER BY employee_name
            LIMIT 8
            """,
            (f"%{query}%", f"%{query}%")
        ).fetchall()

    finally:

        connection.close()

    return {
        "query": query,
        "matches": [
            {
                "employee_id": row[0],
                "employee_name": row[1],
                "designation": row[2],
                "department": row[3]
            }
            for row in rows
        ]
    }


def _tool_payroll_summary(args, user):

    if user.get("role") != "hr":

        return {"error": "Only HR can see company-wide payroll."}

    today = datetime.date.today()

    year = int(args.get("year") or today.year)

    month = int(args.get("month") or today.month)

    if not 1 <= month <= 12:

        return {"error": "month must be between 1 and 12."}

    connection = get_connection()

    try:

        totals = connection.execute(
            """
            SELECT
                COUNT(*),
                COALESCE(SUM(gross_monthly), 0),
                COALESCE(SUM(total_deductions), 0),
                COALESCE(SUM(employee_pf_monthly), 0),
                COALESCE(SUM(employer_pf_monthly), 0),
                COALESCE(SUM(lop_days), 0),
                COALESCE(SUM(net_pay), 0)
            FROM payslips
            WHERE pay_year = ? AND pay_month = ?
            """,
            (year, month)
        ).fetchone()

        headcount = connection.execute(
            "SELECT COUNT(*) FROM employees"
        ).fetchone()[0]

    finally:

        connection.close()

    if not totals[0]:

        return {
            "error": f"No payslips are saved for {MONTHS[month - 1]} {year}."
        }

    return {
        "period": f"{MONTHS[month - 1]} {year}",
        "employees_on_payroll": totals[0],
        "total_headcount": headcount,
        "gross": round(totals[1], 2),
        "total_deductions": round(totals[2], 2),
        "employee_pf": round(totals[3], 2),
        "employer_pf": round(totals[4], 2),
        "lop_days": round(totals[5], 2),
        "net_pay": round(totals[6], 2)
    }


# ---------------------------------------------------------
# LEAVE ACTIONS (writes)
# ---------------------------------------------------------
# These change data, so permissions are pinned in Python exactly as
# they are for the read tools: an employee can only ever act on their
# own record, whatever the model passes in.

def _tool_apply_leave(args, user):
    """Create a pending leave request on the caller's behalf."""

    employee_id, error = _resolve_target(args, user)

    if error:

        return error

    leave_type = _resolve_leave_type(args.get("leave_type"))

    if leave_type is None:

        return {
            "error": (
                "Unknown leave type. Use one of: "
                + ", ".join(LEAVE_TYPES)
                + "."
            )
        }

    from_date, error = _resolve_date(
        args.get("from_date") or args.get("date")
    )

    if error:

        return {"error": error}

    if args.get("to_date"):

        to_date, error = _resolve_date(args.get("to_date"))

        if error:

            return {"error": error}

    else:

        to_date = from_date

    if to_date < from_date:

        return {"error": "The end date is before the start date."}

    reason = str(args.get("reason") or "").strip()

    if not reason:

        reason = "Requested through AI Assist"

    try:

        request_id = leave_apply(
            employee_id,
            leave_type,
            from_date,
            to_date,
            reason
        )

    except ValueError as error:

        return {"error": str(error)}

    days = working_days_between(from_date, to_date)

    balance = next(
        (
            row
            for row in get_balance(employee_id, from_date.year)
            if row["type"] == leave_type
        ),
        None
    )

    return {
        "ok": True,
        "request_id": request_id,
        "employee_id": employee_id,
        "leave_type": leave_type,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "days": days,
        "status": "Pending",
        "message": (
            f"Leave request #{request_id} created and now pending HR "
            "approval."
        ),
        "balance_after": balance
    }


def _tool_list_leave_requests(args, user):

    status = str(args.get("status") or "").strip().title()

    if status not in ("Pending", "Approved", "Rejected", "Cancelled"):

        status = None

    if user.get("role") == "hr" and args.get("employee"):

        employee_id, error = _resolve_target(args, user)

        if error:

            return error

    elif user.get("role") == "hr":

        employee_id = None

    else:

        employee_id = user.get("employee_id")

        if not employee_id:

            return {"error": "This login has no employee record attached."}

    requests = get_requests(employee_id=employee_id, status=status)

    return {
        "count": len(requests),
        "requests": [
            {
                "request_id": row["id"],
                "employee_id": row["employee_id"],
                "employee_name": row["employee_name"],
                "leave_type": row["leave_type"],
                "from_date": row["from_date"],
                "to_date": row["to_date"],
                "days": row["days"],
                "status": row["status"],
                "reason": row["reason"],
                "applied_at": row["applied_at"]
            }
            for row in requests[:20]
        ]
    }


def _leave_request_owner(request_id):
    """(employee_id, status) for a request, or None."""

    connection = get_connection()

    try:

        return connection.execute(
            "SELECT employee_id, status FROM leave_requests WHERE id = ?",
            (request_id,)
        ).fetchone()

    finally:

        connection.close()


def _tool_cancel_leave(args, user):

    try:

        request_id = int(args.get("request_id"))

    except (TypeError, ValueError):

        return {
            "error": (
                "Which request? Give a numeric request_id from "
                "list_leave_requests."
            )
        }

    row = _leave_request_owner(request_id)

    if row is None:

        return {"error": f"There is no leave request #{request_id}."}

    owner_id, status = row

    if user.get("role") != "hr":

        mine = str(user.get("employee_id") or "").upper()

        if str(owner_id or "").upper() != mine:

            return {"error": "You can only cancel your own leave requests."}

    if status != "Pending":

        return {"error": f"Request #{request_id} is already {status}."}

    cancel_request(request_id)

    return {
        "ok": True,
        "request_id": request_id,
        "status": "Cancelled",
        "message": f"Leave request #{request_id} has been cancelled."
    }


def _tool_decide_leave(args, user):

    if user.get("role") != "hr":

        return {"error": "Only HR can approve or reject leave requests."}

    try:

        request_id = int(args.get("request_id"))

    except (TypeError, ValueError):

        return {
            "error": (
                "Which request? Give a numeric request_id from "
                "list_leave_requests."
            )
        }

    decision = str(args.get("decision") or "").strip().title()

    if decision in ("Approve", "Approved", "Accept", "Accepted"):

        decision = "Approved"

    elif decision in ("Reject", "Rejected", "Deny", "Denied"):

        decision = "Rejected"

    else:

        return {"error": "decision must be 'Approved' or 'Rejected'."}

    row = _leave_request_owner(request_id)

    if row is None:

        return {"error": f"There is no leave request #{request_id}."}

    _owner_id, status = row

    if status != "Pending":

        return {"error": f"Request #{request_id} is already {status}."}

    decide_request(request_id, decision, user.get("username"))

    return {
        "ok": True,
        "request_id": request_id,
        "status": decision,
        "decided_by": user.get("username"),
        "message": f"Leave request #{request_id} is now {decision}."
    }


_HANDLERS = {
    "who_am_i": _tool_who_am_i,
    "get_employee": _tool_get_employee,
    "get_salary_structure": _tool_get_salary_structure,
    "get_payslip": _tool_get_payslip,
    "get_leave_balance": _tool_get_leave_balance,
    "get_attendance_summary": _tool_get_attendance_summary,
    "get_pf_summary": _tool_get_pf_summary,
    "get_holidays": _tool_get_holidays,
    "find_employee": _tool_find_employee,
    "payroll_summary": _tool_payroll_summary,
    "apply_leave": _tool_apply_leave,
    "list_leave_requests": _tool_list_leave_requests,
    "cancel_leave": _tool_cancel_leave,
    "decide_leave": _tool_decide_leave
}

_STEP_LABELS = {
    "who_am_i": "Checked the signed-in user",
    "get_employee": "Read the employee record",
    "get_salary_structure": "Read the salary structure",
    "get_payslip": "Read the payslip",
    "get_leave_balance": "Read leave balances",
    "get_attendance_summary": "Read attendance",
    "get_pf_summary": "Worked out the provident fund",
    "get_holidays": "Read the holiday list",
    "find_employee": "Searched employees",
    "payroll_summary": "Totalled the payroll",
    "apply_leave": "Applied for leave",
    "list_leave_requests": "Read the leave requests",
    "cancel_leave": "Cancelled the leave request",
    "decide_leave": "Recorded the decision"
}


# ============================================================
# MODEL PLUMBING
# ============================================================

def available():
    """True when the assistant can actually run."""

    return (
        importlib.util.find_spec("openai") is not None
        and has_secret("OPENAI_API_KEY")
    )


def _create(client, **kwargs):
    """Create a completion, tolerating models that reject sampling args.

    The gpt-5.x family refuses ``temperature=0`` (it only accepts the
    default of 1), so if the configured model complains we simply drop
    the sampling parameters and try again.
    """

    try:

        return client.chat.completions.create(**kwargs)

    except Exception as exc:

        message = str(exc)

        if "temperature" in message and "temperature" in kwargs:

            kwargs.pop("temperature", None)

            kwargs.pop("seed", None)

            return client.chat.completions.create(**kwargs)

        raise


def _as_dict(message):
    """Turn an OpenAI message object into a plain, replayable dict."""

    payload = {
        "role": "assistant",
        "content": message.content or ""
    }

    if message.tool_calls:

        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments
                }
            }
            for call in message.tool_calls
        ]

    return payload


def _recent(messages):
    """Trim history to whole turns so tool calls keep their results."""

    if len(messages) <= HISTORY_LIMIT:

        return list(messages)

    cut = len(messages) - HISTORY_LIMIT

    while cut < len(messages) and messages[cut].get("role") != "user":

        cut += 1

    return list(messages[cut:])


def _sanitise(messages):
    """Repair a conversation so the API will always accept it.

    A rerun (Streamlit's run-on-save, a stray click, a browser
    reconnect) can stop the script between storing an assistant message
    that asks for a tool and storing that tool's result. Session state
    survives the rerun, so the half-finished pair would be replayed on
    the next question and OpenAI rejects the whole request:

        An assistant message with 'tool_calls' must be followed by tool
        messages responding to each 'tool_call_id'.

    This drops every incomplete tool exchange, and any tool result whose
    assistant message has gone. A repair costs a little context; it
    never costs the conversation.
    """

    clean = []

    index = 0

    while index < len(messages):

        message = messages[index]

        if message.get("role") == "tool":

            index += 1          # a result with no assistant message

            continue

        calls = message.get("tool_calls")

        if message.get("role") == "assistant" and calls:

            wanted = [call.get("id") for call in calls]

            found = {}

            look = index + 1

            while look < len(messages) and messages[look].get("role") == "tool":

                found[messages[look].get("tool_call_id")] = messages[look]

                look += 1

            if wanted and all(name in found for name in wanted):

                clean.append(message)

                for name in wanted:

                    clean.append(found[name])

                index = look

                continue

            index = look        # incomplete: drop the whole exchange

            continue

        clean.append(message)

        index += 1

    return clean


def _run_tool(call, user):
    """Execute one tool call. Returns ``(label, result)``."""

    name = call.function.name

    try:

        args = json.loads(call.function.arguments or "{}")

    except (TypeError, ValueError):

        args = {}

    if not isinstance(args, dict):

        args = {}

    handler = _HANDLERS.get(name)

    if handler is None:

        return f"Unknown tool {name}", {"error": f"Unknown tool '{name}'."}

    try:

        result = handler(args, user)

    except Exception as exc:

        result = {"error": f"{type(exc).__name__}: {exc}"}

    return _STEP_LABELS.get(name, name), result


def _ask(prompt, user, employee=None):
    """Run the tool loop and return the assistant's reply text."""

    from openai import OpenAI

    client = OpenAI(api_key=get_secret("OPENAI_API_KEY"))

    history = st.session_state.setdefault("ait_bot_history", [])

    # Heal anything an interrupted round left behind, before it is sent
    # again and rejected.
    healed = _sanitise(history)

    if len(healed) != len(history):

        history[:] = healed

    history.append({"role": "user", "content": prompt})

    system = {"role": "system", "content": _system_prompt(user, employee)}

    reply = ""

    with st.status(":shimmer[Working on it]", type="compact") as status:

        for _round in range(MAX_ROUNDS):

            # Rebuilt from the one history list every round, so the
            # model always sees a well-formed conversation: each
            # assistant tool call is followed by its tool results.
            # Sending "messages" from the previous round instead would
            # drop the tool results from history and the next turn
            # would be rejected by the API.
            messages = [system] + _recent(history)

            response = _create(
                client,
                model=ASSISTANT_MODEL,
                messages=messages,
                tools=_TOOLS,
                temperature=0
            )

            message = response.choices[0].message

            if not message.tool_calls:

                history.append(_as_dict(message))

                reply = message.content or ""

                break

            # Collected first and stored in a single extend(), so a
            # rerun that interrupts the tool calls can never leave a
            # tool request in history without its matching results.
            turn = [_as_dict(message)]

            for call in message.tool_calls:

                label, result = _run_tool(call, user)

                turn.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, default=str)
                    }
                )

                st.caption(f":material/check_circle: {label}")

            history.extend(turn)

        else:

            reply = (
                "Sorry - that question needed more steps than I can "
                "take. Try asking it in a simpler way."
            )

        status.update(label="Answer ready", state="complete")

    return reply or "I could not find an answer for that."


# ============================================================
# SUGGESTED QUESTIONS
# ============================================================

_SUGGESTIONS = {
    "hr": [
        "How many employees do we have?",
        "What is this month's total payroll?",
        "Show me the pending leave requests"
    ],
    "employee": [
        "What is my leave balance?",
        "Apply general leave next monday",
        "Show me my leave requests"
    ]
}


def _hello(employee):
    """A time-of-day hello for the top of the chat.

    Kept deterministic (it depends only on the clock and the name) so
    it does not flicker between different greetings on every rerun.
    """

    hour = datetime.datetime.now().hour

    if hour < 12:

        part = "Good morning"

    elif hour < 17:

        part = "Good afternoon"

    else:

        part = "Good evening"

    name = ""

    if employee and employee.get("employee_name"):

        name = ", " + str(employee["employee_name"]).split()[0]

    return f"{part}{name}!"


# ============================================================
# UI
# ============================================================

BOT_FIGURE = """
<div class="ait-bot" aria-hidden="true">
  <div class="ait-bot-tile">
    <span class="ait-bot-face">
      <span class="ait-bot-eye ait-bot-eye--l"></span>
      <span class="ait-bot-eye ait-bot-eye--r"></span>
      <span class="ait-bot-smile"></span>
    </span>
  </div>
  <span class="ait-bot-status"></span>
</div>
"""

BOT_STYLESHEET = """
<style>

/* ---------- Launcher: the assistant in the bottom-right corner ---------- */

/* The launcher is a small corporate tile - a rounded square in deep
   indigo carrying a little robot face (two eyes and a smile) - rather than
   a button with a label and a picture. The Streamlit button underneath is
   invisible: it paints nothing and only exists to catch the click, so the
   tile above it is free to carry the whole look. */

.st-key-ait_bot_dock {
    position: fixed;
    right: 28px;
    bottom: 28px;
    z-index: 1000000;
    width: 78px !important;
    height: 78px !important;
    overflow: visible !important;
    /* Only the invisible button below is clickable. */
    pointer-events: none;
    animation: ait-bot-float 6.5s ease-in-out infinite;
}

/* The button and the drawing share the same box, one on top of the
   other. */

.st-key-ait_bot_dock [data-testid="stElementContainer"] {
    position: absolute !important;
    inset: 0 !important;
    width: auto !important;
    height: auto !important;
    margin: 0 !important;
}

/* The drawing has to fill the dock by *positioning* it, not by asking for
   100% height. st.html wraps its content in a box that is only as tall as
   its contents, so a percentage height there resolves to zero and the
   whole tile collapses into nothing (leaving just the glow behind it). */

.st-key-ait_bot_dock .stHtml,
.st-key-ait_bot_dock .ait-bot {
    position: absolute;
    inset: 0;
    z-index: 2;
}

/* The button paints nothing - it is only a click target. It is pinned to
   the corners of its wrapper rather than sized with width/height, because
   Streamlit inserts its own boxes around a button and a `height: 100%`
   can resolve against one of those instead of the dock. That once left
   only a thin strip clickable instead of the whole launcher. Pinning it
   with `inset: 0` fills the dock no matter what Streamlit wraps around
   it. */

.st-key-ait_bot_dock button,
.st-key-ait_bot_dock button:hover,
.st-key-ait_bot_dock button:active {
    position: absolute !important;
    inset: 0 !important;
    width: auto !important;
    height: auto !important;
    min-width: 0 !important;
    min-height: 0 !important;
    padding: 0 !important;
    border: none !important;
    border-radius: 50% !important;
    background: transparent !important;
    background-image: none !important;
    box-shadow: none !important;
    transform: none !important;
    cursor: pointer;
    /* The dock switches pointer events off so the drawing can float over
       the button; the button switches them back on for itself. */
    pointer-events: auto !important;
}

/* Drop the theme's hover sweep: it would spill out of a button that no
   longer paints a background. */

.st-key-ait_bot_dock button::after {
    content: none !important;
}

.st-key-ait_bot_dock button [data-testid="stIconMaterial"] {
    display: none !important;
}

/* Action 2 - the greeting bubble was removed here: its "Hi! ..." text was
   the wording the user asked to drop. The launcher is now a plain
   corporate tile that floats gently; the popup chat still greets you by
   name. */

/* ---------- The tile ---------- */

.ait-bot {
    width: 100%;
    height: 100%;
    pointer-events: none;
}

/* The launcher is a single rounded square: a deep indigo robot face with
   two white eyes, a smile and a small presence dot. It is deliberately
   plain so it reads as a product affordance rather than a mascot, and
   holds up at a small size. */

.ait-bot-tile {
    position: absolute;
    left: 50%;
    top: 50%;
    width: 78%;
    height: 78%;
    transform: translate(-50%, -50%);
    border-radius: 26%;
    background: linear-gradient(150deg, #16856B, #116B57);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, .22),
        inset 0 -8px 18px rgba(2, 6, 23, .35),
        0 10px 24px rgba(15, 23, 42, .28);
    display: flex;
    align-items: center;
    justify-content: center;
}

/* The face: two eyes and a small smile. Every part is a plain element and
   NOT an inline vector image - the launcher markup is sanitised before it
   reaches the page, and that sanitiser strips SVG nodes, so a vector face
   would render as nothing and leave an empty tile. Plain elements always
   survive. All sizes are percentages, so the face keeps its proportions if
   the dock is resized. */

.ait-bot-face {
    position: relative;
    display: block;
    width: 62%;
    height: 54%;
}

.ait-bot-eye {
    position: absolute;
    top: 6%;
    width: 32%;
    height: 37%;
    border-radius: 50%;
    background: #F8FAFC;
    box-shadow: inset 0 -1px 1px rgba(2, 6, 23, .22);
}

.ait-bot-eye--l {
    left: 4%;
}

.ait-bot-eye--r {
    right: 4%;
}

/* A shallow upward arc, drawn with a bottom border and a rounded bottom
   edge rather than a curved path. */
.ait-bot-smile {
    position: absolute;
    left: 25%;
    bottom: 2%;
    width: 50%;
    height: 24%;
    border-bottom: 2px solid #F8FAFC;
    border-radius: 0 0 999px 999px;
}

/* Presence dot, sitting on the tile's lower-right corner and giving the
   widget a quiet, always-on status pulse. */

.ait-bot-status {
    position: absolute;
    right: 9%;
    bottom: 9%;
    width: 20%;
    height: 20%;
    box-sizing: border-box;
    border-radius: 50%;
    background: #22C55E;
    border: 2px solid #F8FAFC;
    box-shadow: 0 0 0 0 rgba(34, 197, 94, .55);
    animation: ait-bot-pulse 2.6s ease-out infinite;
}

@keyframes ait-bot-float {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-2px); }
}

@keyframes ait-bot-pulse {
    0% { box-shadow: 0 0 0 0 rgba(34, 197, 94, .45); }
    70% { box-shadow: 0 0 0 7px rgba(34, 197, 94, 0); }
    100% { box-shadow: 0 0 0 0 rgba(34, 197, 94, 0); }
}

/* Respect users who ask for less motion: hold the tile still. */

@media (prefers-reduced-motion: reduce) {
    .st-key-ait_bot_dock {
        animation: none;
    }
    .ait-bot-status {
        animation: none;
    }
}

/* ---------- Popup: the dialog body ---------- */

/* Keep it a genuinely small chat window. Streamlit's "small" dialog is
   500px wide; the bot only needs a compact column, so cap the dialog
   body (the direct child of the dialog root). */
div[data-testid="stDialog"] > div {
    width: 430px !important;
    min-width: 0 !important;
    max-width: calc(100vw - 2rem) !important;
}

/* Streamlit centres the modal and paints the backdrop for us, so the
   body only needs the few touches below. */

/* The chat input must stay inline inside the popup instead of being
   pinned to the bottom of the page. */
.st-key-ait_bot_panel [data-testid="stChatInput"] {
    position: relative !important;
    overflow: visible !important;
}

.st-key-ait_bot_panel [data-testid="stChatInput"] textarea {
    font-size: .9rem;
}

.st-key-ait_bot_voice button {
    width: 42px !important;
    height: 42px !important;
    min-height: 42px !important;
    padding: 0 !important;
    border: 1px solid #16856B !important;
    border-radius: 9px !important;
    background: #E8F2ED !important;
    color: #116B57 !important;
    box-shadow: 0 2px 6px rgba(17, 107, 87, .2);
    font-size: 0 !important;
}

.st-key-ait_bot_voice [data-testid="stIconMaterial"] {
    color: #116B57 !important;
    font-size: 1.35rem !important;
}

/* A slim transcript that scrolls on its own. */
.st-key-ait_bot_log [data-testid="stChatMessage"] {
    background: transparent;
    padding: 0 0 6px 0;
    gap: .4rem;
}

.st-key-ait_bot_log [data-testid="stChatMessageAvatarAssistant"],
.st-key-ait_bot_log [data-testid="stChatMessageAvatarUser"] {
    width: 28px;
    height: 28px;
    min-width: 28px;
}

.st-key-ait_bot_log [data-testid="stMarkdownContainer"] p {
    font-size: .88rem;
    margin-bottom: .35rem;
}

</style>
"""


# Keeps the transcript pinned to the newest message. st.html is not
# iframed, so the script reaches the page DOM directly. The HTML carries
# a changing marker so Streamlit re-mounts it on every rerun - otherwise
# an inline script would only ever run once. If JavaScript is ever
# disabled or the marker stops working, the only effect is that the log
# no longer follows the newest message, which is the behaviour today.
_AUTOSCROLL = """
<!-- ait-bot-autoscroll %TICK% -->
<script>
(function () {
  function pin() {
    var log = document.querySelector(".st-key-ait_bot_log");
    if (!log) { return false; }
    var nodes = [log].concat(Array.prototype.slice.call(log.querySelectorAll("*")));
    for (var i = 0; i < nodes.length; i += 1) {
      var node = nodes[i];
      var overflow = window.getComputedStyle(node).overflowY;
      if ((overflow === "auto" || overflow === "scroll")
          && node.scrollHeight > node.clientHeight + 4) {
        node.scrollTop = node.scrollHeight;
      }
    }
    return true;
  }
  var tries = 0;
  var timer = window.setInterval(function () {
    tries += 1;
    var mounted = pin();
    if ((mounted && tries > 12) || tries > 40) {
      window.clearInterval(timer);
    }
  }, 50);
})();
</script>
"""

_VOICE_INPUT = """
<!-- ait-bot-voice-input %TICK% -->
<script>
(function () {
  var panelSelector = ".st-key-ait_bot_panel";
  var observer;

  function bindMicrophone() {
    var panel = document.querySelector(panelSelector);
    var widget = panel && panel.querySelector('[data-testid="stChatInput"]');
    var textarea = widget && widget.querySelector("textarea");
    var buttonWrapper = panel &&
      panel.querySelector(".st-key-ait_bot_voice");
    var button = buttonWrapper && buttonWrapper.querySelector("button");
    if (!textarea || !button || button.__aitVoiceBound) { return false; }
    button.__aitVoiceBound = true;

    var SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
      button.disabled = true;
      button.title = "Voice input is not supported in this browser. Try Chrome or Edge.";
      return false;
    }

    var recognition = new SpeechRecognition();
    recognition.lang = "en-IN";
    recognition.continuous = false;
    recognition.interimResults = false;
    var listening = false;
    var icon = button.querySelector('[data-testid="stIconMaterial"]');

    recognition.onstart = function () {
      listening = true;
      if (icon) { icon.textContent = "stop"; }
      button.title = "Listening… click to stop";
    };

    recognition.onresult = function (event) {
      var transcript = event.results[0][0].transcript.trim();
      if (!transcript) {
        button.title = "No speech recognized. Click to try again.";
        return;
      }

      var setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, "value"
      ).set;
      setter.call(textarea, transcript);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));

      var attempts = 0;
      var submitTimer = window.setInterval(function () {
        attempts += 1;
        var activePanel = document.querySelector(panelSelector);
        var activeWidget = activePanel && activePanel.querySelector(
          '[data-testid="stChatInput"]'
        );
        var activeTextarea = activeWidget && activeWidget.querySelector("textarea");
        var activeSendButton = activeWidget && activeWidget.querySelector("button");

        if (activeTextarea && activeSendButton && !activeSendButton.disabled) {
          window.clearInterval(submitTimer);
          activeSendButton.click();
          return;
        }

        if (attempts >= 20) {
          window.clearInterval(submitTimer);
          button.title = "Question ready. Click the send arrow.";
        }
      }, 50);
    };

    recognition.onerror = function (event) {
      var messages = {
        "not-allowed": "Allow microphone access in your browser to use voice input.",
        "service-not-allowed": "The browser speech service is unavailable.",
        "no-speech": "No speech was heard. Click the mic to try again.",
        "network": "Speech recognition needs an internet connection."
      };
      button.title =
        messages[event.error] || "Voice input failed. Please try again.";
    };

    recognition.onend = function () {
      listening = false;
      if (icon) { icon.textContent = "mic"; }
      if (button.title === "Listening… click to stop") {
        button.title = "Ask by voice";
      }
    };

    button.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopImmediatePropagation();

      if (listening) {
        recognition.stop();
        return;
      }

      button.title = "Listening…";
      try {
        recognition.start();
      } catch (error) {
        button.title = "Microphone could not start. Click to try again.";
      }
    }, true);

    return true;
  }

  function watchForMicrophone() {
    if (bindMicrophone()) {
      if (observer) { observer.disconnect(); }
      return;
    }

    if (!observer) {
      observer = new MutationObserver(bindMicrophone);
      observer.observe(document.documentElement, {
        childList: true,
        subtree: true
      });
    }
  }

  watchForMicrophone();
  window.setTimeout(function () {
    if (observer) { observer.disconnect(); }
  }, 10000);
})();
</script>
"""


def _inject_autoscroll():
    """Scroll the chat log to the bottom, run again on every rerun."""

    tick = st.session_state.get("ait_bot_scroll_tick", 0) + 1

    st.session_state.ait_bot_scroll_tick = tick

    st.html(
        _AUTOSCROLL.replace("%TICK%", str(tick)),
        unsafe_allow_javascript=True
    )


def _inject_voice_input():
    """Add browser speech recognition to the chat input when supported."""

    tick = st.session_state.get("ait_bot_voice_tick", 0) + 1

    st.session_state.ait_bot_voice_tick = tick

    st.html(
        _VOICE_INPUT.replace("%TICK%", str(tick)),
        unsafe_allow_javascript=True
    )


def _close_bot():
    """Lower the open flag when the popup is dismissed."""

    st.session_state.ait_bot_open = False


@st.dialog(
    "AI Assist",
    width="small",
    icon=":material/smart_toy:",
    on_dismiss=_close_bot
)
def _render_panel(user, employee):
    """The popup body: transcript, suggested questions and the input.

    Streamlit centres the dialog and looks after the backdrop, the close
    button, ESC and clicking outside, so the body needs no positioning
    CSS of its own.
    """

    with st.container(key="ait_bot_panel"):

        st.caption(
            "HR administrator · full access"
            if user.get("role") == "hr"
            else "Your own records only"
        )

        if not available():

            st.warning(
                "The assistant needs an OpenAI API key. Add "
                "`OPENAI_API_KEY` to `.streamlit/secrets.toml`."
            )

            return

        chat = st.session_state.setdefault("ait_bot_chat", [])

        with st.container(height=240, key="ait_bot_log"):

            # The bot always says hello first, so an empty window is not
            # a blank one.
            with st.chat_message(
                "assistant",
                avatar=":material/smart_toy:"
            ):

                st.markdown(
                    f"**{_hello(employee)}** How can I help you today?"
                )

                if not chat:

                    st.caption(
                        "Ask me about salary, payslips, leave, attendance, "
                        "provident fund or holidays."
                    )

            for message in chat:

                with st.chat_message(
                    message["role"],
                    avatar=(
                        ":material/smart_toy:"
                        if message["role"] == "assistant"
                        else ":material/person:"
                    )
                ):

                    st.markdown(message["content"])

        _inject_autoscroll()

        input_col, voice_col = st.columns(
            [1, 0.14],
            gap="small",
            vertical_alignment="center"
        )

        with input_col:
            prompt = st.chat_input(
                "Ask a question…",
                key="ait_bot_input"
            )

        with voice_col:
            st.button(
                "",
                key="ait_bot_voice",
                icon=":material/mic:",
                help="Ask by voice",
                width=42
            )

        _inject_voice_input()

        if prompt is None and not chat:

            role = "hr" if user.get("role") == "hr" else "employee"

            chosen = st.pills(
                "Try asking",
                _SUGGESTIONS[role],
                key="ait_bot_pills",
                label_visibility="collapsed"
            )

            if chosen:

                prompt = chosen

        if prompt:

            st.session_state.ait_bot_chat.append(
                {"role": "user", "content": prompt}
            )

            try:

                answer = _ask(prompt, user, employee)

            except Exception:

                answer = (
                    "Sorry - I could not reach the AI service just now. "
                    "Please try again in a moment."
                )

            st.session_state.ait_bot_chat.append(
                {"role": "assistant", "content": answer}
            )

            st.rerun()

        if chat:

            if st.button(
                "Clear conversation",
                key="ait_bot_clear",
                icon=":material/delete_sweep:",
                type="tertiary"
            ):

                st.session_state.ait_bot_chat = []

                st.session_state.ait_bot_history = []

                st.rerun()


def render_assistant(user):
    """Render the assistant popup. Called from main.py on every page."""

    # Injected with st.markdown(unsafe_allow_html=True), NOT st.html.
    # st.html runs its input through a sanitiser, and that sanitiser once
    # dropped this entire <style> block without a word - the trigger was the
    # text "svg" appearing as a tag name inside a CSS comment. The launcher
    # then sat unstyled in the page flow instead of floating in the corner.
    # st.markdown with unsafe_allow_html injects the sheet verbatim, so the
    # wording of a comment can never silently break the launcher again.
    st.markdown(BOT_STYLESHEET, unsafe_allow_html=True)

    if "ait_bot_open" not in st.session_state:

        st.session_state.ait_bot_open = False

    if "ait_bot_chat" not in st.session_state:

        st.session_state.ait_bot_chat = []

    if "ait_bot_history" not in st.session_state:

        st.session_state.ait_bot_history = []

    # A browser session outlives a sign-out, so a conversation left by the
    # previous person would still be on screen - and its tool results hold
    # their salary, leave and provident-fund figures. Whenever the signed-in
    # identity changes, the conversation is thrown away and the popup starts
    # closed, so every account only ever sees its own chat.
    owner = (
        user.get("username"),
        user.get("role"),
        user.get("employee_id")
    )

    if st.session_state.get("ait_bot_owner") != owner:

        st.session_state.ait_bot_owner = owner

        st.session_state.ait_bot_chat = []

        st.session_state.ait_bot_history = []

        st.session_state.ait_bot_open = False

    employee = (
        employee_details(user["employee_id"])
        if user.get("employee_id")
        else None
    )

    if st.session_state.ait_bot_open:

        _render_panel(user, employee)

    # The launcher sits in a fixed dock. The button is invisible and only
    # catches the click; the tile drawing on top of it carries the look,
    # so the whole launcher is one thing rather than a picture beside a
    # button.
    with st.container(key="ait_bot_dock"):

        if st.button(
            "",
            key="ait_bot_launcher",
            icon=":material/smart_toy:",
            type="primary"
        ):

            st.session_state.ait_bot_open = True

            st.rerun()

        st.html(BOT_FIGURE)
