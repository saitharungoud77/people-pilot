import datetime
import re
import smtplib

import streamlit as st

from database.connection import (
    get_connection,
    create_leave_request_table,
    create_leave_entitlement_table
)
from modules.notifications import notify_hr, notify_employee
from modules.email_notifications import send_leave_request_email
from modules.request_tracking import record_request_event
from modules.payslip import MONTHS
from modules.theme import hero
from modules.workdays import (
    holiday_date_set,
    span_description,
    working_days_between
)


# ============================================================
# LEAVE MANAGEMENT
# ============================================================
# A corporate leave desk, not a school leave-letter register.
#
# Three things separate the two:
#
#   1. Leave is counted in WORKING DAYS. Friday to Monday is two
#      days off, not four. A weekend or a public holiday inside the
#      range is never deducted from anyone's balance.
#
#   2. A request is checked against policy before it is created:
#      the balance has to actually cover it, the range cannot
#      collide with leave already on the books, and a half day has
#      to be a single day.
#
#   3. HR sees the impact before deciding — what the request costs
#      the balance, and who else is already off on those days.
#
# Balances are per calendar year and count approved leave only.
# "Loss of Pay" carries no entitlement; it is unpaid leave and so
# is never blocked for running out.

LEAVE_TYPES = [
    "General Leave",
    "Sick Leave",
    "Optional Leave",
    "Bereavement Leave",
    "Paternity Leave",
    "Loss of Pay"
]

CUSTOM_REASON = "Custom reason"

LEAVE_REASONS = {
    "General Leave": [
        "Personal appointment or errands",
        "Attending a family function or ritual",
        "Attending a wedding or social ceremony",
        "Outstation travel for a personal commitment",
        "Personal or family commitment",
        "Home-related appointment or urgent maintenance",
        "Important personal administrative work",
        "Childcare or school-related commitment",
        "Relocation or household arrangements",
        "Religious or community commitment",
        "Rest or personal wellbeing",
        CUSTOM_REASON
    ],
    "Sick Leave": [
        "Health recovery and rest",
        "Medical appointment for self or family member",
        "Sudden illness or injury",
        "Hospitalization or medical treatment",
        "Care for an ill family member",
        "Diagnostic tests or medical procedures",
        "Follow-up consultation or treatment",
        "Recovery after surgery",
        "Mental health or wellbeing support",
        "Caregiving during a family member's recovery",
        CUSTOM_REASON
    ],
    "Optional Leave": [
        "Religious or cultural observance",
        "Regional or optional festival",
        "Personal observance or celebration",
        "Community or cultural event",
        "Local festival or traditional celebration",
        "Family observance or ceremony",
        "Volunteer or community service",
        "Cultural event or performance",
        CUSTOM_REASON
    ],
    "Bereavement Leave": [
        "Death of an immediate family member",
        "Attending funeral or memorial services",
        "Supporting family after a bereavement",
        "Travel related to a family bereavement",
        "Making funeral or memorial arrangements",
        "Supporting a close relative after a loss",
        "Attending religious rites following a bereavement",
        CUSTOM_REASON
    ],
    "Paternity Leave": [
        "Welcoming a newborn child",
        "Supporting spouse during childbirth or recovery",
        "Newborn care and family support",
        "Adoption or placement of a child",
        "Hospital visits related to childbirth",
        "Assisting with postnatal care",
        "Completing adoption or placement arrangements",
        "Bonding and caregiving for a new child",
        CUSTOM_REASON
    ],
    "Loss of Pay": [
        "Personal commitment requiring extended time off",
        "Additional recovery or medical time",
        "Family responsibility",
        "Unpaid leave after available balance is used",
        "Extended caregiving responsibility",
        "Personal matter requiring an extended absence",
        "Unpaid time off for travel or relocation",
        "Other approved unpaid absence",
        CUSTOM_REASON
    ]
}

DEFAULT_ENTITLEMENT = {
    "General Leave": 12,
    "Sick Leave": 3,
    "Optional Leave": 2,
    "Bereavement Leave": 7,
    "Paternity Leave": 7,  # Default for males; female employees receive 180 (6 months)
    "Loss of Pay": 0
}

_FEMALE_FIRST_NAMES = {
    'naveena', 'priya', 'ananya', 'meera', 'sneha', 'ishita', 'neha', 'pooja',
    'deepika', 'swathi', 'shreya', 'divya', 'aarti', 'anjali', 'lakshmi', 'radha',
    'geeta', 'sunita', 'rekha', 'meena', 'pallavi', 'bhavana', 'sravani', 'ramya',
    'lavanya', 'keerthi', 'harini', 'sushma', 'meghana', 'aditi', 'rupa', 'nisha',
    'tanvi', 'aishwarya', 'smitha', 'preethi', 'mary', 'sarah', 'kavya', 'fatima'
}

def is_female_employee(employee_id):
    """Check whether employee is female by database gender or female first name."""
    if not employee_id:
        return False
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT employee_name, gender FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()
        if not row:
            return False
        name, gender = row[0] or "", row[1] or ""
        g = gender.strip().lower()
        if g in ('female', 'f', 'woman', 'girl'):
            return True
        first = name.strip().split()[0].lower() if name else ''
        if first in _FEMALE_FIRST_NAMES:
            return True
        prefixes = ('mrs.', 'ms.', 'miss ')
        if any(name.strip().lower().startswith(p) for p in prefixes):
            return True
        return False
    finally:
        connection.close()

def default_entitlement_for(leave_type, employee_id=None):
    """Return default days: 180 (6 months) for female paternity/maternity, 7 (1 week) for male."""
    if leave_type == "Paternity Leave":
        if is_female_employee(employee_id):
            return 180  # 6 months for female employees
        return 7        # 1 week for male employees
    return DEFAULT_ENTITLEMENT.get(leave_type, 0)

STATUS_COLORS = {
    "Pending": "orange",
    "Needs information": "yellow",
    "Approved": "green",
    "Rejected": "red",
    "Cancelled": "gray"
}

STATUS_ICONS = {
    "Pending": ":material/hourglass_top:",
    "Needs information": ":material/help:",
    "Approved": ":material/check_circle:",
    "Rejected": ":material/cancel:",
    "Cancelled": ":material/remove_circle:"
}

# The short policy shown next to every leave type, on both pages.
LEAVE_POLICY = {
    "General Leave": {
        "icon": ":material/beach_access:",
        "blurb": "Personal & planned time off for errands, appointments & personal plans.",
        "rule": (
            "12 days per calendar year. Request at least a day ahead where possible."
        )
    },
    "Sick Leave": {
        "icon": ":material/healing:",
        "blurb": "Time off for illness, medical emergencies or recovery.",
        "rule": (
            "3 days per calendar year. Can be raised on the same day."
        )
    },
    "Optional Leave": {
        "icon": ":material/event_note:",
        "blurb": "Floating holidays and optional cultural festival time off.",
        "rule": (
            "2 days per calendar year. Pick from optional festivals or cultural observances."
        )
    },
    "Bereavement Leave": {
        "icon": ":material/sentiment_very_dissatisfied:",
        "blurb": "Compassionate leave for grieving the loss of an immediate family member.",
        "rule": (
            "7 days per calendar year. Notify HR or your reporting manager."
        )
    },
    "Paternity Leave": {
        "icon": ":material/child_care:",
        "blurb": "Parental leave for welcoming a new child into the family.",
        "rule": (
            "6 months (180 days) for female employees; 1 week (7 days) for male employees."
        )
    },
    "Loss of Pay": {
        "icon": ":material/money_off:",
        "blurb": "Unpaid leave once other balances are exhausted.",
        "rule": (
            "No entitlement cap, but each day taken is deducted from monthly salary."
        )
    }
}

# Leave that is unpaid is not capped by an entitlement.
_UNPAID = "Loss of Pay"


# ---------------------------------------------------------
# SETUP
# ---------------------------------------------------------

def create_leave_tables():

    create_leave_request_table()

    create_leave_entitlement_table()


def list_employees():
    """Return (employee_id, employee_name) pairs, sorted by name."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT employee_id, employee_name
            FROM employees
            ORDER BY employee_name
            """
        ).fetchall()

    finally:

        connection.close()

    return rows


def _as_date(value):
    """A date from a date or an ISO string, else None."""

    if isinstance(value, datetime.date):

        return value

    try:

        return datetime.date.fromisoformat(str(value).strip())

    except (TypeError, ValueError):

        return None


# ---------------------------------------------------------
# ENTITLEMENTS
# ---------------------------------------------------------

def _ensure_entitlements(employee_id, year):
    """Create or update default entitlement rows for an employee/year."""

    connection = get_connection()

    try:

        # 1. Remove old Earned Leave
        connection.execute(
            """
            DELETE FROM leave_entitlements
            WHERE employee_id = ? AND year = ? AND leave_type = 'Earned Leave'
            """,
            (employee_id, year)
        )

        # 2. Rename Casual Leave to General Leave
        connection.execute(
            """
            UPDATE leave_entitlements
            SET leave_type = 'General Leave', entitled = 12
            WHERE employee_id = ? AND year = ? AND leave_type = 'Casual Leave'
            """,
            (employee_id, year)
        )
        connection.execute(
            """
            UPDATE leave_requests
            SET leave_type = 'General Leave'
            WHERE employee_id = ? AND leave_type = 'Casual Leave'
            """,
            (employee_id,)
        )

        # 3. Update old Sick Leave default (12) to new requested default (3)
        connection.execute(
            """
            UPDATE leave_entitlements
            SET entitled = 3
            WHERE employee_id = ? AND year = ? AND leave_type = 'Sick Leave' AND entitled = 12
            """,
            (employee_id, year)
        )

        # 4. Insert or update the new types
        for leave_type in LEAVE_TYPES:

            def_days = default_entitlement_for(leave_type, employee_id)

            connection.execute(
                """
                INSERT OR IGNORE INTO leave_entitlements
                    (employee_id, leave_type, year, entitled)
                VALUES (?, ?, ?, ?)
                """,
                (
                    employee_id,
                    leave_type,
                    year,
                    def_days
                )
            )

            # Ensure Paternity Leave matches 180 for female and 7 for male
            if leave_type == "Paternity Leave":

                correct_days = 180 if is_female_employee(employee_id) else 7

                connection.execute(
                    """
                    UPDATE leave_entitlements
                    SET entitled = ?
                    WHERE employee_id = ? AND year = ? AND leave_type = 'Paternity Leave' AND entitled != ?
                    """,
                    (correct_days, employee_id, year, correct_days)
                )

        connection.commit()

    finally:

        connection.close()


def ensure_all_entitlements(year=None):
    """Seed default entitlements for every employee for a year."""

    year = year or datetime.date.today().year

    for employee_id, _name in list_employees():

        _ensure_entitlements(employee_id, year)


def get_entitlements(employee_id, year):
    """Return {leave_type: entitled_days}."""

    _ensure_entitlements(employee_id, year)

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT leave_type, entitled
            FROM leave_entitlements
            WHERE employee_id = ? AND year = ?
            """,
            (employee_id, year)
        ).fetchall()

    finally:

        connection.close()

    stored = {row[0]: row[1] for row in rows}

    return {
        leave_type: stored.get(
            leave_type,
            default_entitlement_for(leave_type, employee_id)
        )
        for leave_type in LEAVE_TYPES
    }


def set_entitlement(employee_id, leave_type, year, entitled):

    _ensure_entitlements(employee_id, year)

    connection = get_connection()

    try:

        connection.execute(
            """
            UPDATE leave_entitlements
            SET entitled = ?
            WHERE employee_id = ?
              AND leave_type = ?
              AND year = ?
            """,
            (entitled, employee_id, leave_type, year)
        )

        connection.commit()

    finally:

        connection.close()


def get_used_days(employee_id, year):
    """Approved leave days per type for a year."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT leave_type, COALESCE(SUM(days), 0)
            FROM leave_requests
            WHERE employee_id = ?
              AND status = 'Approved'
              AND substr(from_date, 1, 4) = ?
            GROUP BY leave_type
            """,
            (employee_id, str(year))
        ).fetchall()

    finally:

        connection.close()

    used = {leave_type: 0.0 for leave_type in LEAVE_TYPES}

    for leave_type, total in rows:

        used[leave_type] = used.get(leave_type, 0.0) + total

    return used


def get_balance(employee_id, year):
    """Return a list of {type, entitled, used, balance} dicts."""

    entitled = get_entitlements(employee_id, year)

    used = get_used_days(employee_id, year)

    return [
        {
            "type": leave_type,
            "entitled": entitled[leave_type],
            "used": used[leave_type],
            "balance": entitled[leave_type] - used[leave_type]
        }
        for leave_type in LEAVE_TYPES
    ]


def balance_for(employee_id, leave_type, year):
    """Days still available of one leave type."""

    for row in get_balance(employee_id, year):

        if row["type"] == leave_type:

            return row["balance"]

    return 0.0


# ---------------------------------------------------------
# POLICY CHECKS
# ---------------------------------------------------------

def validate_request(
    employee_id,
    leave_type,
    from_date,
    to_date,
    portion="Full day"
):
    """Check a request against policy. Returns ``(ok, message)``.

    This is the difference between a leave desk and a diary: the
    system refuses a request the balance cannot cover, one that
    collides with leave already on the books, and one made up of
    nothing but weekends.
    """

    if leave_type not in LEAVE_TYPES:

        return False, f"Unknown leave type. Use one of: {', '.join(LEAVE_TYPES)}."

    start = _as_date(from_date)

    end = _as_date(to_date)

    if start is None or end is None:

        return False, "Those dates could not be read."

    if end < start:

        return False, "The end date cannot be before the start date."

    if portion not in ("Full day", "First half", "Second half"):

        portion = "Full day"

    if portion != "Full day" and start != end:

        return False, (
            "A half day only applies to a single day. "
            "Pick the same start and end date."
        )

    if portion != "Full day" and leave_type == _UNPAID:

        return False, (
            "Loss of Pay is taken in full days only — a half day "
            "is available for paid leave types."
        )

    days = working_days_between(start, end, portion)

    if days == 0:

        return False, (
            "That range is only weekends or public holidays, so "
            "there is nothing here to deduct from your balance."
        )

    # Leave cannot be raised for days that have already gone. HR
    # can still record one from the HR page.
    today = datetime.date.today()

    if end < today:

        return False, (
            "That range is entirely in the past. Speak to HR if a "
            "past day needs recording."
        )

    if leave_type != _UNPAID:

        available = balance_for(employee_id, leave_type, start.year)

        if days > available:

            return False, (
                f"You have {available:g} {leave_type} day(s) left for "
                f"{start.year} and this request needs {days:g}. "
                "Shorten the range, pick another leave type, or use "
                "Loss of Pay for the difference."
            )

    # Nothing may overlap leave that is already pending or approved.
    clash = _overlapping_request(
        employee_id,
        start,
        end,
        statuses=("Pending", "Approved")
    )

    if clash:

        return False, (
            f"This overlaps your {clash['status'].lower()} "
            f"{clash['leave_type']} "
            f"({format_range(clash['from_date'], clash['to_date'])}, "
            f"request #{clash['id']}). "
            "Adjust the dates or cancel that request first."
        )

    return True, f"{days:g} working day(s)"


def _overlapping_request(employee_id, start, end, statuses):
    """The first pending/approved request clashing with a range."""

    for request in get_requests(employee_id=employee_id):

        if request["status"] not in statuses:

            continue

        other_start = _as_date(request["from_date"])

        other_end = _as_date(request["to_date"])

        if other_start is None or other_end is None:

            continue

        if other_start <= end and start <= other_end:

            return request

    return None


def colleagues_off(from_date, to_date, employee_id=None, statuses=("Approved",)):
    """Everyone else on leave across a range.

    Used by HR to see coverage before approving: approving a request
    when three people are already out is a staffing decision, not a
    formality.
    """

    start = _as_date(from_date)

    end = _as_date(to_date)

    if start is None or end is None:

        return []

    off = []

    for request in get_requests():

        if request["status"] not in statuses:

            continue

        if employee_id and request["employee_id"] == employee_id:

            continue

        other_start = _as_date(request["from_date"])

        other_end = _as_date(request["to_date"])

        if other_start is None or other_end is None:

            continue

        if other_start <= end and start <= other_end:

            off.append(request)

    return off


def who_is_off(day):
    """Approved leave covering one date, as request dicts."""

    day = _as_date(day)

    if day is None:

        return []

    return colleagues_off(day, day, statuses=("Approved",))


# ---------------------------------------------------------
# REQUESTS
# ---------------------------------------------------------

def apply_leave(
    employee_id,
    leave_type,
    from_date,
    to_date,
    reason,
    portion="Full day",
    manager_email=""
):
    """Create a pending leave request. Returns the request id.

    Working days, not calendar days, are stored on the request, so
    the balance, the payslip and the HR view all agree on what a
    request costs. Raises ValueError when policy rejects it.
    """

    ok, message = validate_request(
        employee_id,
        leave_type,
        from_date,
        to_date,
        portion
    )

    if not ok:

        raise ValueError(message)

    days = working_days_between(from_date, to_date, portion)

    connection = get_connection()

    try:

        row = connection.execute(
            "SELECT employee_name FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()

        employee_name = row[0] if row else employee_id

        cursor = connection.execute(
            """
            INSERT INTO leave_requests
                (
                    employee_id,
                    leave_type,
                    from_date,
                    to_date,
                    days,
                    portion,
                    reason,
                    manager_email
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                leave_type,
                str(from_date),
                str(to_date),
                days,
                portion,
                reason,
                manager_email
            )
        )

        connection.commit()

        request_id = cursor.lastrowid

    finally:

        connection.close()

    notify_hr(
        "New leave request",
        f"{employee_name} requested {days:g} working day(s) of "
        f"{leave_type} — {span_description(from_date, to_date, portion)}.",
        category="Leave",
        page="leave"
    )
    record_request_event(
        "Leave",
        request_id,
        employee_id,
        "Pending",
        actor=employee_id,
        comment=reason
    )

    return request_id


def get_requests(employee_id=None, status=None):
    """Return leave requests (optionally filtered)."""

    query = """
        SELECT
            r.id,
            r.employee_id,
            e.employee_name,
            r.leave_type,
            r.from_date,
            r.to_date,
            r.days,
            r.reason,
            r.status,
            r.applied_at,
            r.decided_at,
            r.decided_by,
            r.portion,
            r.decision_note,
            r.manager_email,
            r.employee_reply
        FROM leave_requests r
        JOIN employees e
            ON r.employee_id = e.employee_id
        WHERE 1 = 1
    """

    params = []

    if employee_id is not None:

        query += " AND r.employee_id = ?"

        params.append(employee_id)

    if status is not None:

        query += " AND r.status = ?"

        params.append(status)

    query += " ORDER BY r.applied_at DESC, r.id DESC"

    connection = get_connection()

    try:

        rows = connection.execute(query, params).fetchall()

    finally:

        connection.close()

    keys = [
        "id",
        "employee_id",
        "employee_name",
        "leave_type",
        "from_date",
        "to_date",
        "days",
        "reason",
        "status",
        "applied_at",
        "decided_at",
        "decided_by",
        "portion",
        "decision_note",
        "manager_email",
        "employee_reply"
    ]

    return [dict(zip(keys, row)) for row in rows]


def reply_to_leave_request(request_id, employee_id, reply):
    """Employee responds to an HR request for more information."""

    reply = (reply or "").strip()
    if not reply:
        raise ValueError("Enter a response before submitting.")

    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE leave_requests
            SET employee_reply = ?,
                status = 'Pending',
                decided_at = NULL,
                decided_by = NULL
            WHERE id = ?
              AND employee_id = ?
              AND status = 'Needs information'
            """,
            (reply, request_id, employee_id)
        )
        connection.commit()
        updated = cursor.rowcount > 0
    finally:
        connection.close()

    if updated:
        record_request_event(
            "Leave",
            request_id,
            employee_id,
            "Pending",
            actor=employee_id,
            comment=reply
        )
        notify_hr(
            "Employee responded to leave request",
            f"{employee_id} replied to leave request #{request_id}: {reply}",
            category="Leave",
            page="leave"
        )

    return updated


def decide_request(request_id, status, decided_by, note=None):
    """Update a leave request and notify its employee."""

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT
                r.employee_id,
                e.employee_name,
                r.leave_type,
                r.from_date,
                r.to_date,
                r.days
            FROM leave_requests r
            JOIN employees e
                ON r.employee_id = e.employee_id
            WHERE r.id = ?
            """,
            (request_id,)
        ).fetchone()

        connection.execute(
            """
            UPDATE leave_requests
            SET status = ?,
                decided_at = CURRENT_TIMESTAMP,
                decided_by = ?,
                decision_note = ?
            WHERE id = ?
            """,
            (status, decided_by, note or None, request_id)
        )

        connection.commit()

    finally:

        connection.close()

    # Tell the employee their request was decided.
    if row:
        record_request_event(
            "Leave",
            request_id,
            row[0],
            status,
            actor=decided_by,
            comment=note
        )

        body = (
            f"Your {row[2]} leave ({format_range(row[3], row[4])}, "
            f"{row[5]:g} day(s)) is now: {status}."
        )

        if note:

            body += f" Note: {note}"

        notify_employee(
            row[0],
            f"Leave {status.lower()}",
            body,
            category="Leave",
            page="leave"
        )

        return True

    return False


def cancel_request(request_id):
    """Cancel a request (employee)."""

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT
                r.employee_id,
                e.employee_name,
                r.leave_type,
                r.from_date,
                r.to_date,
                r.days
            FROM leave_requests r
            JOIN employees e
                ON r.employee_id = e.employee_id
            WHERE r.id = ?
            """,
            (request_id,)
        ).fetchone()

        cursor = connection.execute(
            """
            UPDATE leave_requests
            SET status = 'Cancelled',
                decided_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('Pending', 'Needs information')
            """,
            (request_id,)
        )

        changed = cursor.rowcount

        connection.commit()

    finally:

        connection.close()

    # Only tell HR when a request really was cancelled.
    if changed and row:

        record_request_event(
            "Leave",
            request_id,
            row[0],
            "Cancelled",
            actor=row[0],
            comment="Employee cancelled the request."
        )
        notify_hr(
            "Leave request cancelled",
            f"{row[1]} cancelled their {row[2]} leave "
            f"({format_range(row[3], row[4])}, {row[5]:g} day(s)).",
            category="Leave",
            page="leave"
        )

    return bool(changed)


def pending_count():
    """Number of pending requests (for HR badges)."""

    connection = get_connection()

    try:

        row = connection.execute(
            "SELECT COUNT(*) FROM leave_requests "
            "WHERE status = 'Pending'"
        ).fetchone()

    finally:

        connection.close()

    return row[0] if row else 0


# ---------------------------------------------------------
# SHARED RENDERING
# ---------------------------------------------------------

def _portion_of(request):
    """'Half day — first half' or '' for a full-day request."""

    portion = request.get("portion") or "Full day"

    if portion == "First half":

        return "Half day — first half"

    if portion == "Second half":

        return "Half day — second half"

    return ""


def _policy_card(leave_type):
    """The policy line for one leave type."""

    policy = LEAVE_POLICY.get(leave_type)

    if not policy:

        return

    st.caption(policy["blurb"])

    st.caption(policy["rule"])


def _balance_table(balances):

    st.dataframe(
        [
            {
                "Leave type": row["type"],
                "Entitled": row["entitled"],
                "Used": row["used"],
                "Balance": row["balance"]
            }
            for row in balances
        ],
        width="stretch",
        hide_index=True
    )


def _balance_cards(balances, year, selected_type=None):
    """Entitlement, usage and what is left in a scrollable card."""

    # Build inner leave-type cards HTML
    cards_html = ""
    for row in balances:
        leave_name = row["type"].upper()
        total = int(row["entitled"]) if row["entitled"] == int(row["entitled"]) else row["entitled"]
        remaining = row["balance"]
        remaining_display = int(remaining) if remaining == int(remaining) else remaining
        is_selected = row["type"] == selected_type

        # Colour the remaining value red if 0, orange if low, green if good
        if row["entitled"] == 0:
            rem_color = "#68716F"
        elif remaining <= 0:
            rem_color = "#B42318"
        elif row["entitled"] > 0 and remaining / row["entitled"] < 0.3:
            rem_color = "#9A6700"
        else:
            rem_color = "#16856B"

        card_border = (
            "1px solid #16856B"
            if is_selected
            else "1px solid #E1E5DF"
        )
        selected_label = (
            '<span style="float:right; color:#116B57; font-size:10px; '
            'font-weight:700; letter-spacing:.04em;">SELECTED</span>'
            if is_selected
            else ""
        )

        cards_html += f"""
        <div style="
            background: #FFFFFF;
            border-radius: 10px;
            padding: 14px 16px;
            margin-bottom: 10px;
            border: {card_border};
        ">
            <div style="
                color: #34413B;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1.4px;
                text-transform: uppercase;
                margin-bottom: 12px;
                border-bottom: 1px solid #E1E5DF;
                padding-bottom: 8px;
            ">{leave_name}{selected_label}</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr;">
                <div style="
                    border-right: 1px solid #E1E5DF;
                    padding-right: 18px;
                ">
                    <div style="color: #64748B; font-size: 11px; font-weight: 500; margin-bottom: 4px;">Total</div>
                    <div style="color: #252A2A; font-size: 26px; font-weight: 800; line-height: 1;">{total}</div>
                </div>
                <div style="padding-left: 18px;">
                    <div style="color: #64748B; font-size: 11px; font-weight: 500; margin-bottom: 4px;">Remaining</div>
                    <div style="color: {rem_color}; font-size: 26px; font-weight: 800; line-height: 1;">{remaining_display}</div>
                </div>
            </div>
        </div>
        """

    st.html(f"""
    <div style="
        background: #F0F0E9;
        border-radius: 14px;
        padding: 20px 16px 12px 16px;
        border: 1px solid #E1E5DF;
        box-shadow: 0 8px 24px rgba(37,42,42,0.08);
    ">
        <div style="
            color: #252A2A;
            font-size: 18px;
            font-weight: 800;
            letter-spacing: 0.3px;
            margin-bottom: 14px;
            display: flex;
            align-items: center;
            gap: 8px;
        ">
            Total Leaves
            <span style="margin-left:auto; font-size:11px; color:#64748B; font-weight:500;">Year {year}</span>
        </div>
        <div style="
            max-height: 520px;
            overflow-y: auto;
            padding-right: 4px;
            scrollbar-width: thin;
            scrollbar-color: #B7C0B9 #F0F0E9;
        ">
            {cards_html}
        </div>
    </div>
    """)


def _status_badge(request):
    """The status chip, with the icon that belongs to it."""

    st.badge(
        request["status"],
        icon=STATUS_ICONS.get(request["status"]),
        color=STATUS_COLORS.get(request["status"], "gray")
    )


def _request_card(request, actions=False, decided_by=None):
    """One request, with the context HR needs to decide it."""

    with st.container(border=True):

        head, badge = st.columns([4, 1])

        with head:

            st.write(
                f"**{request['employee_name']}** "
                f"({request['employee_id']})"
            )

            st.caption(
                f"{request['leave_type']} · "
                f"{span_description(request['from_date'], request['to_date'], request.get('portion') or 'Full day')}"
            )

            portion = _portion_of(request)

            if portion:

                st.caption(portion)

            if request["reason"]:

                st.caption(f"Note: {request['reason']}")

            if request.get("manager_email"):

                st.caption(
                    f"Manager/team email: {request['manager_email']}"
                )

            if request["status"] != "Pending" and request["decided_by"]:

                line = (
                    f"{request['status']} by {request['decided_by']}"
                )

                if request["decided_at"]:

                    line += f" ({str(request['decided_at'])[:10]})"

                st.caption(line)

                if request.get("decision_note"):

                    st.caption(
                        f"Decision note: {request['decision_note']}"
                    )

        with badge:

            _status_badge(request)

        if actions and request["status"] == "Pending":

            _approval_context(request)

            _approval_actions(request, decided_by)


def _approval_context(request):
    """What approving this actually costs, before HR commits.

    Balance impact and coverage are the two things a rubber-stamp
    misses. A request that empties someone's balance, or lands on a
    day when half the team is already out, deserves a second look.
    """

    year = _as_date(request["from_date"])

    year = year.year if year else datetime.date.today().year

    available = balance_for(
        request["employee_id"],
        request["leave_type"],
        year
    )

    after = available - (request["days"] or 0)

    if request["leave_type"] == _UNPAID:

        st.caption("Unpaid leave — no balance is spent.")

    else:

        st.caption(
            f"Balance: {available:g} → {after:g} "
            f"{request['leave_type']} day(s) for {year}."
        )

    off = colleagues_off(
        request["from_date"],
        request["to_date"],
        employee_id=request["employee_id"]
    )

    if off:

        names = ", ".join(
            f"{row['employee_name']} ({row['leave_type']})"
            for row in off[:5]
        )

        if len(off) > 5:

            names += f" and {len(off) - 5} more"

        st.caption(f"Also off in this range: {names}.")


def _approval_actions(request, decided_by):
    """Approve, decline, or request more information."""

    with st.form(f"leave_decide_{request['id']}"):

        note = st.text_input(
            "Note to the employee (optional)",
            key=f"leave_note_{request['id']}",
            label_visibility="collapsed",
            placeholder="Note to the employee (optional)"
        )

        approve_col, reject_col, info_col = st.columns(3)

        with approve_col:

            approve = st.form_submit_button(
                "Approve",
                icon=":material/check_circle:",
                type="primary",
                width="stretch"
            )

        with reject_col:

            reject = st.form_submit_button(
                "Decline",
                icon=":material/cancel:",
                width="stretch"
            )

        with info_col:

            needs_info = st.form_submit_button(
                "Need info",
                icon=":material/help:",
                width="stretch"
            )

    if approve or reject or needs_info:

        next_status = (
            "Approved" if approve
            else "Rejected" if reject
            else "Needs information"
        )
        if next_status == "Needs information" and not note.strip():
            st.error("Add a note explaining what information is needed.")
        else:
            decide_request(
                request["id"],
                next_status,
                decided_by,
                note=note
            )
            st.rerun()


# ---------------------------------------------------------
# HR PAGE
# ---------------------------------------------------------

def show_leave_page(go_home=None):
    """HR leave desk: decide requests, watch coverage, set entitlements."""

    today = datetime.date.today()

    ensure_all_entitlements(today.year)

    pending = pending_count()

    off_today = who_is_off(today)

    hero_rows = []

    if pending:

        hero_rows.append((f"{pending} awaiting approval", "pending_actions"))

    hero_rows.append((f"{len(off_today)} off today", "groups"))

    hero(
        "Leave",
        "Approve or decline requests, keep an eye on coverage, and "
        "set each person's entitlement.",
        icon="beach_access",
        badges=hero_rows or [("Nothing pending", "task_alt")]
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="leave_back",
        width="content"
    ):

        go_home()

        st.rerun()

    queue_tab, coverage_tab, balances_tab = st.tabs(
        ["Approval queue", "Coverage", "Entitlements & balances"]
    )

    # -----------------------------------------------------
    # APPROVAL QUEUE
    # -----------------------------------------------------

    with queue_tab:

        status_filter = st.segmented_control(
            "Show",
            [
                "Pending", "Needs information", "Approved",
                "Rejected", "Cancelled", "All"
            ],
            default="Pending",
            key="leave_status_filter"
        ) or "Pending"

        requests = get_requests(
            status=None if status_filter == "All" else status_filter
        )

        if not requests:

            st.info(
                f"No {status_filter.lower()} leave requests.",
                icon=":material/task_alt:"
            )

        else:

            st.caption(
                f"{len(requests)} {status_filter.lower()} request(s). "
                "Each pending request shows what it costs the "
                "balance and who else is off."
            )

            for request in requests:

                _request_card(
                    request,
                    actions=True,
                    decided_by=st.session_state.auth_user["username"]
                )

    # -----------------------------------------------------
    # COVERAGE
    # -----------------------------------------------------
    # Who is actually out, and when. Approving leave is a staffing
    # decision, so this view exists to make collisions visible.

    with coverage_tab:

        col1, col2 = st.columns(2)

        with col1:

            month = st.selectbox(
                "Month",
                list(range(1, 13)),
                index=today.month - 1,
                format_func=lambda m: MONTHS[m - 1],
                key="leave_coverage_month"
            )

        with col2:

            year = st.number_input(
                "Year",
                min_value=2000,
                max_value=2100,
                value=today.year,
                step=1,
                key="leave_coverage_year"
            )

        approved = get_requests(status="Approved")

        month_start = datetime.date(year, month, 1)

        month_end = (
            datetime.date(year, 12, 31)
            if month == 12
            else datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
        )

        in_month = []

        for request in approved:

            start = _as_date(request["from_date"])

            end = _as_date(request["to_date"])

            if start is None or end is None:

                continue

            if start <= month_end and month_start <= end:

                in_month.append(request)

        in_month.sort(key=lambda r: str(r["from_date"]))

        total_days = sum(row["days"] or 0 for row in in_month)

        col1, col2, col3 = st.columns(3)

        with col1:

            st.metric(
                "Approved requests",
                len(in_month),
                icon=":material/event_available:",
                border=True,
                help=f"Across everyone in {MONTHS[month - 1]} {year}."
            )

        with col2:

            st.metric(
                "Leave days",
                f"{total_days:g}",
                icon=":material/schedule:",
                border=True,
                help="Working days only — weekends and holidays are free."
            )

        with col3:

            st.metric(
                "Off today",
                len(off_today) if (year, month) == (today.year, today.month) else "—",
                icon=":material/groups:",
                border=True
            )

        if not in_month:

            st.info(
                "No approved leave in this month.",
                icon=":material/event_busy:"
            )

        else:

            rows = [
                {
                    "Employee": row["employee_name"],
                    "Employee ID": row["employee_id"],
                    "Type": row["leave_type"],
                    "Dates": format_range(
                        row["from_date"], row["to_date"]
                    ),
                    "Days": row["days"],
                    "Day type": _portion_of(row) or "Full day"
                }
                for row in in_month
            ]

            st.dataframe(rows, width="stretch", hide_index=True)

        st.space("medium")

        st.markdown("#### Off today")

        today_off = who_is_off(today)

        if not today_off:

            st.caption("Everyone is in today.")

        else:

            for request in today_off:

                st.write(
                    f"**{request['employee_name']}** — "
                    f"{request['leave_type']} · "
                    f"{format_range(request['from_date'], request['to_date'])}"
                )

    # -----------------------------------------------------
    # BALANCES
    # -----------------------------------------------------

    with balances_tab:

        employees = list_employees()

        if not employees:

            st.info("No employees yet.")

            return

        options = {
            f"{name}  ({employee_id})": employee_id
            for employee_id, name in employees
        }

        col1, col2 = st.columns([3, 1])

        with col1:

            selected = st.selectbox(
                "Employee",
                list(options.keys()),
                key="leave_hr_employee"
            )

        with col2:

            balance_year = st.number_input(
                "Year",
                min_value=2000,
                max_value=2100,
                value=today.year,
                step=1,
                key="leave_balance_year"
            )

        employee_id = options[selected]

        balances = get_balance(employee_id, balance_year)

        _balance_cards(balances, balance_year)

        st.space("small")

        _balance_table(balances)

        with st.expander(
            "Adjust entitlements",
            icon=":material/tune:",
            type="compact"
        ):

            with st.form(
                f"entitlements_{employee_id}_{balance_year}"
            ):

                new_values = {}

                cols = st.columns(len(LEAVE_TYPES))

                for index, leave_type in enumerate(LEAVE_TYPES):

                    with cols[index]:

                        current = get_entitlements(
                            employee_id,
                            balance_year
                        )[leave_type]

                        st.caption(leave_type)

                        new_values[leave_type] = st.number_input(
                            leave_type,
                            min_value=0.0,
                            value=float(current),
                            step=1.0,
                            key=f"ent_{leave_type}_{employee_id}_{balance_year}",
                            label_visibility="collapsed"
                        )

                saved = st.form_submit_button(
                    "Save entitlements",
                    icon=":material/save:",
                    width="stretch"
                )

            if saved:

                for leave_type, value in new_values.items():

                    set_entitlement(
                        employee_id,
                        leave_type,
                        balance_year,
                        value
                    )

                st.success("Entitlements updated.")


# ---------------------------------------------------------
# EMPLOYEE HISTORY HELPERS
# ---------------------------------------------------------

def format_range(from_date, to_date):
    """Readable date range, e.g. '22 – 23 Oct 2026'."""

    try:

        start = datetime.date.fromisoformat(str(from_date))
        end = datetime.date.fromisoformat(str(to_date))

    except (TypeError, ValueError):

        return f"{from_date} → {to_date}"

    if start == end:

        return start.strftime("%d %b %Y")

    if start.year == end.year:

        return (
            f"{start.strftime('%d %b')} – "
            f"{end.strftime('%d %b %Y')}"
        )

    return (
        f"{start.strftime('%d %b %Y')} – "
        f"{end.strftime('%d %b %Y')}"
    )


def _my_request_card(request):
    """One leave-history card — kept for HR view compatibility."""

    with st.container(border=True):

        head, badge, action = st.columns([4, 1, 1])

        with head:

            st.write(f"**{request['leave_type']}**")

            st.caption(
                span_description(
                    request["from_date"],
                    request["to_date"],
                    request.get("portion") or "Full day"
                )
            )

            portion = _portion_of(request)

            if portion:

                st.caption(portion)

            if request["reason"]:

                st.caption(f"Note: {request['reason']}")

            if (
                request["status"] in ("Approved", "Rejected")
                and request["decided_by"]
            ):

                when = (
                    f" on {str(request['decided_at'])[:10]}"
                    if request["decided_at"]
                    else ""
                )

                st.caption(
                    f"{request['status']} by "
                    f"{request['decided_by']}{when}"
                )

                if request.get("decision_note"):

                    st.caption(
                        f"HR note: {request['decision_note']}"
                    )

        with badge:

            _status_badge(request)

        with action:

            if request["status"] == "Pending":

                if st.button(
                    "Withdraw",
                    key=f"cancel_{request['id']}",
                    icon=":material/undo:",
                    width="stretch",
                    help="Withdraw this request before HR decides it."
                ):

                    cancel_request(request["id"])

                    st.session_state["leave_flash"] = (
                        f"Request #{request['id']} withdrawn."
                    )

                    st.rerun()


def _show_leave_request_details(request):
    """Show selected leave request details inside its history popover."""

    left, right = st.columns(2)

    with left:
        st.markdown(f"**Leave type**  \n{request['leave_type']}")
        st.markdown(
            f"**Dates**  \n{format_range(request['from_date'], request['to_date'])}"
        )
        st.markdown(f"**Working days**  \n{request['days']:g}")

    with right:
        st.markdown(f"**Status**  \n{request['status']}")
        st.markdown(
            f"**Reviewer**  \n"
            f"{request.get('decided_by') or ('Awaiting HR review' if request['status'] == 'Pending' else 'HR')}"
        )
        st.markdown(f"**Applied**  \n{request.get('applied_at') or '—'}")

    st.divider()
    st.markdown("**Reason**")
    st.write(request.get("reason") or "No reason provided.")

    if request.get("decision_note"):
        st.markdown("**HR note**")
        st.write(request["decision_note"])

    if request.get("employee_reply"):
        st.markdown("**Employee response**")
        st.write(request["employee_reply"])

    if request["status"] == "Needs information":
        with st.form(f"leave_reply_{request['id']}"):
            reply = st.text_area(
                "Reply to HR",
                key=f"leave_reply_text_{request['id']}"
            )
            submitted = st.form_submit_button("Send response")
        if submitted:
            try:
                replied = reply_to_leave_request(
                    request["id"],
                    request["employee_id"],
                    reply
                )
            except ValueError as error:
                st.error(str(error))
            else:
                if replied:
                    st.success("Your response was sent to HR.")
                    st.rerun()
                st.warning("This request is no longer awaiting information.")


def _history_panel(requests):
    """Show status-filtered leave history with actions and pagination."""

    status_styles = {
        "Approved": ("#16A34A", "#FFFFFF"),
        "Pending": ("#D97706", "#FFFFFF"),
        "Needs information": ("#CA8A04", "#FFFFFF"),
        "Rejected": ("#DC2626", "#FFFFFF"),
        "Cancelled": ("#475569", "#CBD5E1"),
    }
    status_labels = {
        "Approved": "APPROVED",
        "Pending": "PENDING",
        "Needs information": "NEEDS INFORMATION",
        "Rejected": "REJECTED",
        "Cancelled": "CANCELLED",
    }

    page_key = "lhist_page"
    perpage_key = "lhist_perpage"

    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    perpage_options = [5, 10, 20, 50]

    if perpage_key not in st.session_state:
        st.session_state[perpage_key] = 10

    statuses = [
        "All", "Approved", "Pending", "Needs information",
        "Rejected", "Cancelled"
    ]
    chosen_filter = st.segmented_control(
        "Filter leave history",
        statuses,
        default="All",
        key="lhist_filter",
        label_visibility="collapsed"
    ) or "All"

    visible = (
        list(requests)
        if chosen_filter == "All"
        else [request for request in requests if request["status"] == chosen_filter]
    )

    total_rows = len(visible)
    perpage = st.session_state[perpage_key]
    total_pages = max(1, (total_rows + perpage - 1) // perpage)
    page = min(st.session_state[page_key], total_pages - 1)
    st.session_state[page_key] = page
    page_rows = visible[page * perpage : (page + 1) * perpage]

    st.caption(f"{total_rows} request(s)")

    column_widths = [1.15, 1.15, 0.7, 1.0, 1.15, 1.2, 1.35]
    header = st.columns(column_widths)
    for column, label in zip(
        header,
        ["Start Date", "End Date", "Total Days", "Status", "Approver", "Leave Type", "Action"]
    ):
        with column:
            st.markdown(f"**{label}**")

    st.divider()

    if not page_rows:
        st.info("No leave requests match this filter.")

    for request in page_rows:
        row = st.columns(column_widths, vertical_alignment="center")
        start_date = _as_date(request["from_date"])
        end_date = _as_date(request["to_date"])
        start_label = start_date.strftime("%d/%b/%Y") if start_date else str(request["from_date"])
        end_label = end_date.strftime("%d/%b/%Y") if end_date else str(request["to_date"])
        days_label = f"{request['days']:g}"
        status_color, text_color = status_styles.get(
            request["status"], ("#475569", "#FFFFFF")
        )
        status_label = status_labels.get(request["status"], "UNKNOWN")

        with row[0]:
            st.write(start_label)
        with row[1]:
            st.write(end_label)
        with row[2]:
            st.write(days_label)
        with row[3]:
            st.html(
                f'<span style="display:inline-block;background:{status_color};'
                f'color:{text_color};border-radius:7px;padding:5px 10px;'
                f'font-size:11px;font-weight:700;letter-spacing:.04em;">'
                f'{status_label}</span>'
            )
        with row[4]:
            st.write(request.get("decided_by") or "—")
        with row[5]:
            st.write(request.get("leave_type") or "—")
        with row[6]:
            view_col, cancel_col = st.columns(2)
            with view_col:
                with st.popover(
                    "View",
                    key=f"view_lhist_{request['id']}"
                ):
                    _show_leave_request_details(request)
            with cancel_col:
                if st.button(
                    "Cancel",
                    key=f"cancel_lhist_{request['id']}",
                    disabled=request["status"] != "Pending",
                    width="stretch",
                    help="Cancel this request while it is pending."
                ):
                    if cancel_request(request["id"]):
                        st.session_state["leave_flash"] = (
                            f"Request #{request['id']} cancelled."
                        )
                    else:
                        st.session_state["leave_flash"] = (
                            f"Request #{request['id']} was already updated."
                        )
                    st.rerun()

        st.divider()

    pg_left, pg_mid, pg_right = st.columns([3, 5, 3])

    with pg_left:
        new_perpage = st.selectbox(
            "Rows per page",
            perpage_options,
            index=perpage_options.index(perpage),
            key="lhist_perpage_sel",
            label_visibility="visible"
        )

        if new_perpage != perpage:
            st.session_state[perpage_key] = new_perpage
            st.session_state[page_key] = 0
            st.rerun()

    with pg_mid:
        controls = st.columns(4)

        with controls[0]:
            if st.button("First", disabled=page == 0, key="lhist_first"):
                st.session_state[page_key] = 0
                st.rerun()

        with controls[1]:
            if st.button("Previous", disabled=page == 0, key="lhist_prev"):
                st.session_state[page_key] = page - 1
                st.rerun()

        with controls[2]:
            if st.button(
                "Next",
                disabled=page >= total_pages - 1,
                key="lhist_next"
            ):
                st.session_state[page_key] = page + 1
                st.rerun()

        with controls[3]:
            if st.button(
                "Last",
                disabled=page >= total_pages - 1,
                key="lhist_last"
            ):
                st.session_state[page_key] = total_pages - 1
                st.rerun()

    with pg_right:
        st.markdown(
            f"<div style='text-align:right;padding-top:8px;'>"
            f"Page <b>{page + 1}</b> of <b>{total_pages}</b></div>",
            unsafe_allow_html=True
        )


def _recent_leave_panel(requests):
    """Show the five most recent requests below the employee leave form."""

    st.markdown("### Recent Leaves")

    if not requests:
        st.info("No leave requests yet.")
        return

    status_styles = {
        "Approved": ("#16A34A", "#FFFFFF"),
        "Pending": ("#D97706", "#FFFFFF"),
        "Needs information": ("#CA8A04", "#FFFFFF"),
        "Rejected": ("#DC2626", "#FFFFFF"),
        "Cancelled": ("#475569", "#CBD5E1"),
    }

    for request in requests[:5]:
        start = _as_date(request["from_date"])
        end = _as_date(request["to_date"])
        date_label = (
            format_range(start, end)
            if start and end
            else f"{request['from_date']} – {request['to_date']}"
        )
        status_color, text_color = status_styles.get(
            request["status"], ("#475569", "#FFFFFF")
        )
        status_label = request["status"].upper()

        with st.container(border=True):
            leave_col, date_col, days_col, status_col = st.columns(
                [1.35, 1.5, 0.65, 1]
            )

            with leave_col:
                st.write(f"**{request['leave_type']}**")

            with date_col:
                st.write(date_label)

            with days_col:
                st.write(f"{request['days']:g} day(s)")

            with status_col:
                st.html(
                    f'<span style="display:inline-block;background:{status_color};'
                    f'color:{text_color};border-radius:7px;padding:5px 10px;'
                    f'font-size:11px;font-weight:700;letter-spacing:.04em;">'
                    f'{status_label}</span>'
                )


# ---------------------------------------------------------
# EMPLOYEE PAGE
# ---------------------------------------------------------

def show_my_leave():
    """Employee leave self-service — two-column corporate layout."""

    user = st.session_state.auth_user

    employee_id = user["employee_id"]

    today = datetime.date.today()

    booking_start = _as_date(
        st.session_state.get("book_from")
    ) or today
    balance_year = booking_start.year

    _ensure_entitlements(employee_id, balance_year)

    balances = get_balance(employee_id, balance_year)

    flash = st.session_state.pop("leave_flash", None)
    email_error = st.session_state.pop("leave_email_error", None)

    if flash:

        st.success(flash, icon=":material/task_alt:")

    if email_error:

        st.warning(email_error, icon=":material/mail:")

    requests = get_requests(employee_id=employee_id)

    balance_col, details_col = st.columns([1, 2.7], gap="medium")

    with balance_col:
        selected_type = st.session_state.get(
            "book_leave_type",
            LEAVE_TYPES[0]
        )
        if selected_type not in LEAVE_TYPES:
            selected_type = LEAVE_TYPES[0]

        _balance_cards(balances, balance_year, selected_type)

    with details_col:
        with st.container(border=True):
            title_col, holiday_col, history_col = st.columns(
                [3, 1.1, 1.1],
                vertical_alignment="center"
            )

            with title_col:
                st.markdown("### Leave Details")

            with holiday_col:
                if st.button(
                    "Holiday List",
                    key="leave_holiday_list",
                    width="stretch"
                ):
                    st.session_state.current_page = "holidays"
                    st.rerun()

            with history_col:
                if st.button(
                    "Leave History",
                    key="leave_history_open",
                    type="primary",
                    width="stretch"
                ):
                    st.session_state.current_page = "leave_history"
                    st.rerun()

        with st.container(border=True):
            st.markdown("### Apply for Leave")
            _booking_panel(employee_id, balances, balance_year)

        st.space("small")
        with st.container(border=True):
            _recent_leave_panel(requests)

    # ---------------------------------------------------------
    # POLICY section below (full width, collapsible)
    # ---------------------------------------------------------

    st.space("medium")

    with st.expander("Leave Policy", expanded=False):

        st.caption(
            "How leave works at AIT Solutions. Entitlements are set "
            "by HR and reset each January."
        )

        for leave_type in LEAVE_TYPES:

            policy = LEAVE_POLICY[leave_type]

            with st.container(border=True):

                title_col, days_col = st.columns([4, 1])

                with title_col:

                    st.write(f"**{leave_type}** — {policy['blurb']}")

                    st.caption(policy["rule"])

                with days_col:

                    row = next(
                        r for r in balances if r["type"] == leave_type
                    )

                    st.metric(
                        "Yours",
                        f"{row['balance']:g}",
                        delta=(
                            None
                            if row["entitled"] == 0
                            else f"of {row['entitled']:g}"
                        ),
                        delta_color="off",
                        icon=policy["icon"],
                        border=True,
                        help=(
                            "Unpaid — no annual entitlement."
                            if row["entitled"] == 0
                            else f"{row['entitled']:g} day(s) a year."
                        )
                    )

        st.caption(
            "Leave is counted in working days. A weekend or a public "
            "holiday inside your range is never deducted. Approved "
            "leave only counts towards the used total."
        )


def show_my_leave_history():
    """Show the signed-in employee's leave history as a full page."""

    user = st.session_state.auth_user
    employee_id = user["employee_id"]

    if st.button(
        "← Back to leave",
        key="leave_history_back",
        width="content"
    ):
        st.session_state.current_page = "leave"
        st.rerun()

    st.title("Leave History", icon=":material/history:")
    st.caption(
        "Review your leave requests, current status, and HR decisions."
    )

    _history_panel(get_requests(employee_id=employee_id))


def _booking_panel(employee_id, balances, year):
    """Raise a request, with the cost worked out as the dates change.

    The point of this panel is that the employee sees what the
    request will actually take before submitting: how many working
    days, what the range skips, and what the balance becomes.
    """

    remaining = {row["type"]: row["balance"] for row in balances}

    leave_col, start_col, portion_col = st.columns([1.5, 1, 1])

    with leave_col:

        leave_type = st.selectbox(
            "Leave type",
            LEAVE_TYPES,
            key="book_leave_type",
            format_func=lambda t: f"{t} — {remaining[t]:g} left"
        )

    with start_col:

        from_date = st.date_input(
            "Start date",
            value=datetime.date.today(),
            key="book_from",
            format="DD/MM/YYYY"
        )

    with portion_col:

        if leave_type == _UNPAID:

            portion = "Full day"

            st.text_input("Day type", value=portion, disabled=True)

        else:

            portion = st.selectbox(
                "Day type",
                ["Full day", "First half", "Second half"],
                key="book_portion",
                help=(
                    "A half day is half a day's entitlement — useful for "
                    "an appointment. Only available for a single day."
                )
            ) or "Full day"

    end_col, days_col, balance_col = st.columns([1, 1, 1])

    with end_col:

        to_date = st.date_input(
            "End date",
            value=datetime.date.today(),
            key="book_to",
            format="DD/MM/YYYY"
        )

    days = working_days_between(from_date, to_date, portion)

    with days_col:
        st.text_input(
            "Total days",
            value=f"{days:g} day(s)",
            key="book_total_days_display",
            disabled=True,
            help="Working days only. Weekends and holidays are excluded."
        )

    with balance_col:
        balance = remaining.get(leave_type, 0)
        st.text_input(
            "Leave balance",
            value=f"{balance:g} day(s)",
            key="book_leave_balance_display",
            disabled=True,
            help="Current balance for the selected leave type."
        )

    with st.expander("Leave type policy"):
        _policy_card(leave_type)

    # -------------------------------------------------
    # The cost, shown before the employee commits.
    # -------------------------------------------------

    if to_date < from_date:

        st.error("The end date cannot be before the start date.")

    elif days == 0:

        st.warning(
            f"{span_description(from_date, to_date, portion)} — "
            "nothing in this range is deducted from your balance."
        )

    else:

        available = remaining.get(leave_type, 0)

        after = available - days

        if leave_type == _UNPAID:

            st.info(
                f"{span_description(from_date, to_date, portion)} — "
                "Loss of Pay has no balance, so this is simply "
                "deducted from salary."
            )

        elif after < 0:

            st.error(
                f"{span_description(from_date, to_date, portion)} — "
                f"you have {available:g} {leave_type} day(s) left, "
                f"so this is {abs(after):g} more than you can take. "
                "Shorten the range or use Loss of Pay for the rest."
            )

        else:

            skipped = [
                d for d in holiday_date_set({from_date.year, to_date.year})
                if str(from_date) <= d <= str(to_date)
                and datetime.date.fromisoformat(d).weekday() < 5
            ]

            line = (
                f"{span_description(from_date, to_date, portion)} — "
                f"{leave_type} would go from {available:g} to "
                f"{after:g}."
            )

            if skipped:

                line += (
                    f" Skips {len(skipped)} public holiday(s) "
                    "in that range."
                )

            st.success(line)

    reason_options = LEAVE_REASONS[leave_type]
    reason_choice = st.selectbox(
        "Reason *",
        reason_options,
        index=None,
        placeholder="Select reason",
        key=f"book_reason_option_{leave_type.replace(' ', '_')}"
    )

    if reason_choice == CUSTOM_REASON:

        reason = st.text_input(
            "Custom reason *",
            key="book_custom_reason",
            placeholder="Enter your reason"
        ).strip()

    else:

        reason = reason_choice or ""

    with st.form("book_leave_form"):
        manager_email = st.text_input(
            "Manager/team email (optional)",
            key="book_manager_email",
            placeholder="name@company.com",
            help=(
                "The manager/team contact will receive an email with "
                "your leave dates, leave type, and reason."
            )
        ).strip()

        submitted = st.form_submit_button(
            "Apply",
            icon=":material/send:",
            type="primary",
            width="stretch"
        )

    if submitted:

        if not reason_choice:

            st.error("Select a reason for your leave request.")

        elif reason_choice == CUSTOM_REASON and not reason:

            st.error("Enter your custom reason.")

        elif manager_email and not re.fullmatch(
            r"[^@\s]+@[^@\s]+\.[^@\s]+",
            manager_email
        ):

            st.error("Enter a valid manager/team email address.")

        else:

            try:

                request_id = apply_leave(
                    employee_id,
                    leave_type,
                    from_date,
                    to_date,
                    reason,
                    portion=portion,
                    manager_email=manager_email
                )

            except ValueError as error:

                st.error(str(error))

            else:

                request_info = next(
                    request
                    for request in get_requests(employee_id=employee_id)
                    if request["id"] == request_id
                )
                st.session_state["leave_flash"] = (
                    f"Request #{request_id} submitted for "
                    f"{request_info['days']:g} working day(s). "
                    "HR will see it in the approval queue."
                )

                if manager_email:
                    try:
                        send_leave_request_email(request_info)
                    except (
                        OSError,
                        RuntimeError,
                        ValueError,
                        smtplib.SMTPException
                    ) as error:
                        st.session_state["leave_email_error"] = (
                            "Your leave request was saved, but the email "
                            f"to your TL could not be sent: {error}"
                        )
                    else:
                        st.session_state["leave_flash"] += (
                            f" Notification email sent to {manager_email}."
                        )

                st.rerun()
