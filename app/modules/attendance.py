import datetime
import sqlite3

import streamlit as st

from database.connection import (
    get_connection,
    create_attendance_table
)
from modules.payslip import MONTHS
from modules.leave import list_employees, get_requests
from modules.holidays import working_days, holiday_dates
from modules.theme import hero


# ============================================================
# ATTENDANCE — time & attendance, the corporate way
# ============================================================
# This is not a roll-call register. Nobody ticks a box that says
# "I am present". A person **clocks in** when they start and
# **clocks out** when they finish, and the system works out the
# rest: hours served, whether they were late, and what the day
# should be called.
#
# The company shift is 09:30 - 18:30 with a one hour break, so a
# full day is 8 hours. Anyone arriving more than GRACE_MINUTES
# after the shift starts is late.
#
# Status is largely derived:
#
#   clock in  ->  Present (or Work From Home, if that is the mode)
#   clock out ->  Half Day when less than half the shift was served
#   no clock in on a working day  ->  Absent
#   approved leave  ->  Leave (comes from the leave module)
#
# HR can still override any day — that is the "correct a day"
# panel, which is also how a missed punch gets regularised.

ATTENDANCE_STATUSES = [
    "Present",
    "Work From Home",
    "Half Day",
    "Leave",
    "Absent"
]

STATUS_COLORS = {
    "Present": "green",
    "Work From Home": "blue",
    "Half Day": "orange",
    "Leave": "violet",
    "Absent": "red"
}

# How someone is working today. This is a mode, not a grade.
WORK_MODES = ["Office", "Work From Home"]

# -----------------------------------------------------------
# THE SHIFT
# -----------------------------------------------------------

SHIFT_START = "09:30"

SHIFT_END = "18:30"

# Arriving within this many minutes of SHIFT_START still counts
# as on time — traffic happens.
GRACE_MINUTES = 15

# Unpaid lunch break, deducted once a day runs longer than this.
BREAK_MINUTES = 60

BREAK_THRESHOLD_HOURS = 6.0

# What a day is worth.
MIN_HOURS_HALF_DAY = 4.0

MIN_HOURS_FULL_DAY = 8.0


# -----------------------------------------------------------
# TIME HELPERS
# -----------------------------------------------------------

def _as_time(value):
    """A datetime.time from 'HH:MM', 'HH:MM:SS' or a time, else None."""

    if isinstance(value, datetime.time):

        return value

    if isinstance(value, datetime.datetime):

        return value.time()

    text = str(value or "").strip()

    if not text:

        return None

    for pattern in ("%H:%M:%S", "%H:%M"):

        try:

            return datetime.datetime.strptime(text, pattern).time()

        except ValueError:

            continue

    return None


def _clock(value):
    """A stored time as 'HH:MM', or '' when there is none."""

    parsed = _as_time(value)

    return parsed.strftime("%H:%M") if parsed else ""


def _as_date(value):
    """A date from a date or ISO string, else None."""

    if isinstance(value, datetime.datetime):

        return value.date()

    if isinstance(value, datetime.date):

        return value

    try:

        return datetime.date.fromisoformat(str(value).strip())

    except (TypeError, ValueError):

        return None


def _minutes(value):
    """A time as minutes past midnight, or None."""

    parsed = _as_time(value)

    if parsed is None:

        return None

    return parsed.hour * 60 + parsed.minute


# -----------------------------------------------------------
# SHIFTS
# -----------------------------------------------------------
# The constants above are the company default. HR can create
# other shifts (a client project at 08:00, a support window at
# 14:00) and assign employees to them. Every timing function
# accepts an optional shift dict; with no shift it uses the
# default, so existing callers keep working unchanged.

DEFAULT_SHIFT = {
    "id": 0,
    "shift_name": "General",
    "client_project": "All",
    "start_time": SHIFT_START,
    "end_time": SHIFT_END,
    "grace_minutes": GRACE_MINUTES,
    "break_minutes": BREAK_MINUTES,
    "min_hours_full_day": MIN_HOURS_FULL_DAY,
    "min_hours_half_day": MIN_HOURS_HALF_DAY
}


def _shift_int(shift, key, default):
    """Read an integer setting from a shift dict without losing explicit 0."""

    if not shift:
        return int(default)
    val = shift.get(key)
    return int(default if val is None else val)


def _shift_row(row):

    if not row or row[0] is None:

        return dict(DEFAULT_SHIFT)

    keys = (
        "id",
        "shift_name",
        "client_project",
        "start_time",
        "end_time",
        "grace_minutes",
        "break_minutes",
        "min_hours_full_day",
        "min_hours_half_day"
    )

    shift = dict(zip(keys, row))

    shift["shift_name"] = shift["shift_name"] or DEFAULT_SHIFT["shift_name"]
    shift["client_project"] = (
        shift["client_project"] or DEFAULT_SHIFT["client_project"]
    )
    shift["start_time"] = _clock(shift["start_time"]) or SHIFT_START
    shift["end_time"] = _clock(shift["end_time"]) or SHIFT_END
    if shift["grace_minutes"] is None:
        shift["grace_minutes"] = GRACE_MINUTES
    if shift["break_minutes"] is None:
        shift["break_minutes"] = BREAK_MINUTES
    if shift["min_hours_full_day"] is None:
        shift["min_hours_full_day"] = MIN_HOURS_FULL_DAY
    if shift["min_hours_half_day"] is None:
        shift["min_hours_half_day"] = MIN_HOURS_HALF_DAY

    return shift


def list_shifts():

    try:

        connection = get_connection()

        try:

            rows = connection.execute(
                """
                SELECT id, shift_name, client_project, start_time, end_time,
                       grace_minutes, break_minutes,
                       min_hours_full_day, min_hours_half_day
                FROM shifts
                ORDER BY shift_name
                """
            ).fetchall()

        finally:

            connection.close()

    except sqlite3.OperationalError:

        return []

    return [_shift_row(row) for row in rows]


def get_shift(shift_id):

    if not shift_id:

        return dict(DEFAULT_SHIFT)

    try:

        connection = get_connection()

        try:

            row = connection.execute(
                """
                SELECT id, shift_name, client_project, start_time, end_time,
                       grace_minutes, break_minutes,
                       min_hours_full_day, min_hours_half_day
                FROM shifts WHERE id = ?
                """,
                (shift_id,)
            ).fetchone()

        finally:

            connection.close()

    except sqlite3.OperationalError:

        return dict(DEFAULT_SHIFT)

    return _shift_row(row)


def shift_for_employee(employee_id):
    """The shift an employee works, falling back to the default."""

    try:

        connection = get_connection()

        try:

            row = connection.execute(
                """
                SELECT s.id, s.shift_name, s.client_project, s.start_time,
                       s.end_time, s.grace_minutes, s.break_minutes,
                       s.min_hours_full_day, s.min_hours_half_day
                FROM employees e
                LEFT JOIN shifts s ON s.id = e.shift_id
                WHERE e.employee_id = ?
                """,
                (employee_id,)
            ).fetchone()

        finally:

            connection.close()

    except sqlite3.OperationalError:

        return dict(DEFAULT_SHIFT)

    return _shift_row(row)


def shift_lookup():
    """{employee_id: shift} for every employee, default filled in."""

    try:

        connection = get_connection()

        try:

            rows = connection.execute(
                """
                SELECT e.employee_id, s.id, s.shift_name, s.client_project,
                       s.start_time, s.end_time, s.grace_minutes,
                       s.break_minutes, s.min_hours_full_day,
                       s.min_hours_half_day
                FROM employees e
                LEFT JOIN shifts s ON s.id = e.shift_id
                """
            ).fetchall()

        finally:

            connection.close()

    except sqlite3.OperationalError:

        return {}

    return {
        row[0]: _shift_row(row[1:])
        for row in rows
    }


def save_shift(
    shift_id,
    shift_name,
    client_project,
    start_time,
    end_time,
    grace_minutes=15,
    break_minutes=60,
    min_hours_full_day=8.0,
    min_hours_half_day=4.0
):
    """Create (shift_id falsy) or update a shift. Returns (ok, message)."""

    shift_name = (shift_name or "").strip()

    if not shift_name:

        return False, "Give the shift a name."

    start = _as_time(start_time)
    end = _as_time(end_time)

    if start is None or end is None:

        return False, "Pick a valid start and end time."

    if start == end:

        return False, "Start and end time cannot be the same."

    try:

        grace_minutes = max(int(grace_minutes), 0)
        break_minutes = max(int(break_minutes), 0)
        min_hours_full_day = max(float(min_hours_full_day), 1.0)
        min_hours_half_day = max(float(min_hours_half_day), 0.5)

    except (TypeError, ValueError):

        return False, "The hour and minute values must be numbers."

    if min_hours_half_day >= min_hours_full_day:

        return False, "Half-day hours must be less than full-day hours."

    connection = get_connection()

    try:

        clash = connection.execute(
            "SELECT id FROM shifts WHERE shift_name = ? AND id != ?",
            (shift_name, shift_id or 0)
        ).fetchone()

        if clash:

            return False, f"A shift named “{shift_name}” already exists."

        values = (
            shift_name,
            (client_project or "").strip(),
            _clock(start),
            _clock(end),
            grace_minutes,
            break_minutes,
            min_hours_full_day,
            min_hours_half_day
        )

        if shift_id:

            connection.execute(
                """
                UPDATE shifts SET
                    shift_name = ?, client_project = ?,
                    start_time = ?, end_time = ?,
                    grace_minutes = ?, break_minutes = ?,
                    min_hours_full_day = ?, min_hours_half_day = ?
                WHERE id = ?
                """,
                values + (shift_id,)
            )

            message = f"Shift “{shift_name}” updated."

        else:

            connection.execute(
                """
                INSERT INTO shifts
                    (shift_name, client_project, start_time, end_time,
                     grace_minutes, break_minutes,
                     min_hours_full_day, min_hours_half_day)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values
            )

            message = f"Shift “{shift_name}” created."

        connection.commit()

    finally:

        connection.close()

    return True, message


def assign_shift(employee_ids, shift_id):
    """Put employees on a shift. Returns (ok, changed_ids)."""

    ids = [e for e in (employee_ids or []) if e]

    if not ids:

        return False, []

    shift = get_shift(shift_id)

    connection = get_connection()

    try:

        before = {}

        for employee_id in ids:

            row = connection.execute(
                "SELECT shift_id FROM employees WHERE employee_id = ?",
                (employee_id,)
            ).fetchone()

            if row:

                before[employee_id] = row[0]

        connection.executemany(
            "UPDATE employees SET shift_id = ? WHERE employee_id = ?",
            [(shift["id"], employee_id) for employee_id in ids]
        )

        connection.commit()

    finally:

        connection.close()

    changed = [
        employee_id
        for employee_id in ids
        if before.get(employee_id) != shift["id"]
    ]

    return True, changed


def shift_counts():
    """{shift_id: number of employees} for the shift list."""

    try:

        connection = get_connection()

        try:

            rows = connection.execute(
                "SELECT shift_id, COUNT(*) FROM employees GROUP BY shift_id"
            ).fetchall()

        finally:

            connection.close()

    except sqlite3.OperationalError:

        return {}

    return {row[0]: row[1] for row in rows}


def hours_worked(in_time, out_time, shift=None):
    """Hours actually served, net of the shift's lunch break.

    Returns None when either punch is missing, because guessing a
    number out of one punch would be a lie HR has to defend later.
    """

    shift = shift or DEFAULT_SHIFT

    start = _minutes(in_time)

    end = _minutes(out_time)

    if start is None or end is None:

        return None

    span = end - start

    if span < 0:

        # A shift that runs past midnight.
        span += 24 * 60

    break_mins = _shift_int(shift, "break_minutes", BREAK_MINUTES)
    if break_mins and (
        span > BREAK_THRESHOLD_HOURS * 60
    ):

        span -= break_mins

    return round(max(span, 0) / 60.0, 2)


def late_by(in_time, shift=None):
    """Minutes late, or 0 when the person was on time (or early)."""

    shift = shift or DEFAULT_SHIFT

    start = _minutes(in_time)

    if start is None:

        return 0

    allowed = (
        _minutes(shift.get("start_time") or SHIFT_START)
        + _shift_int(shift, "grace_minutes", GRACE_MINUTES)
    )

    return max(start - allowed, 0)


def early_by(out_time, shift=None):
    """Minutes left before the shift officially ends."""

    shift = shift or DEFAULT_SHIFT

    end = _minutes(out_time)

    if end is None:

        return 0

    return max(_minutes(shift.get("end_time", SHIFT_END)) - end, 0)


def punctuality(in_time, shift=None):
    """'On time', 'Late by 22 min' or '' when nobody punched in."""

    if not in_time:

        return ""

    minutes = late_by(in_time, shift)

    if minutes:

        return f"Late by {minutes} min"

    return "On time"


def _hours_label(hours):
    """8.25 -> '8h 15m'."""

    if hours is None:

        return ""

    total = int(round(hours * 60))

    return f"{total // 60}h {total % 60:02d}m"


def derive_status(hours, shift=None):
    """What a served day is called, given the hours in it."""

    shift = shift or DEFAULT_SHIFT

    if hours is None:

        return "Present"

    half_hours = shift.get("min_hours_half_day")
    if hours < float(MIN_HOURS_HALF_DAY if half_hours is None else half_hours):

        return "Half Day"

    return "Present"


def is_working_day(att_date):
    """True when the date is a Mon–Fri that is not a holiday."""

    day = _as_date(att_date)

    if day is None:

        return False

    if day.weekday() >= 5:

        return False

    return day.isoformat() not in holiday_dates(day.year)


def create_attendance_tables():

    create_attendance_table()


def _working_days(year, month):
    """Number of weekdays (Mon–Fri) in the month, excluding holidays."""

    return working_days(year, month)


# -----------------------------------------------------------
# DATA
# -----------------------------------------------------------

_FIELDS = ("status", "note", "in_time", "out_time")


def get_attendance(employee_id, year, month):
    """Return {date_str: {status, note, in_time, out_time}} for a month.

    ``in_time`` / ``out_time`` are 'HH:MM' (or '' when nobody
    punched). Older callers only look at ``status``, and still do.
    """

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT att_date, status, note, in_time, out_time
            FROM attendance
            WHERE employee_id = ?
              AND substr(att_date, 1, 4) = ?
              AND substr(att_date, 6, 2) = ?
            ORDER BY att_date
            """,
            (employee_id, f"{year:04d}", f"{month:02d}")
        ).fetchall()

    finally:

        connection.close()

    return {
        row[0]: {
            "status": row[1],
            "note": row[2],
            "in_time": _clock(row[3]),
            "out_time": _clock(row[4])
        }
        for row in rows
    }


def get_attendance_for_date(att_date):
    """Return {employee_id: {status, note, in_time, out_time}} for a day."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT employee_id, status, note, in_time, out_time
            FROM attendance
            WHERE att_date = ?
            """,
            (str(att_date),)
        ).fetchall()

    finally:

        connection.close()

    return {
        row[0]: {
            "status": row[1],
            "note": row[2],
            "in_time": _clock(row[3]),
            "out_time": _clock(row[4])
        }
        for row in rows
    }


def mark_attendance(
    employee_id,
    att_date,
    status,
    note=None,
    in_time=None,
    out_time=None
):
    """Insert or update one attendance record.

    ``in_time`` / ``out_time`` accept 'HH:MM', 'HH:MM:SS' or a
    datetime.time. Passing None leaves the stored punch alone, so a
    status-only correction never wipes someone's clock-in.
    """

    connection = get_connection()

    try:

        record = connection.execute(
            "SELECT in_time, out_time FROM attendance "
            "WHERE employee_id = ? AND att_date = ?",
            (employee_id, str(att_date))
        ).fetchone()

        stored_in = _clock(record[0]) if record else ""

        stored_out = _clock(record[1]) if record else ""

        new_in = _clock(in_time) if in_time is not None else stored_in

        new_out = _clock(out_time) if out_time is not None else stored_out

        connection.execute(
            """
            INSERT INTO attendance
                (employee_id, att_date, status, note, in_time, out_time)
            VALUES (?, ?, ?, ?, ?, ?)

            ON CONFLICT(employee_id, att_date)
            DO UPDATE SET
                status = excluded.status,
                note = excluded.note,
                in_time = excluded.in_time,
                out_time = excluded.out_time,
                recorded_at = CURRENT_TIMESTAMP
            """,
            (
                employee_id,
                str(att_date),
                status,
                note,
                new_in or None,
                new_out or None
            )
        )

        connection.commit()

    finally:

        connection.close()


def mark_self(employee_id, att_date, status, note=None):
    """An employee setting their own day — today only.

    Kept for callers that already know the status they want (the
    assistant, and the mode picker below). Returns ``(ok, message)``.
    Once a day has passed the employee can no longer change it; HR
    can still correct any day from the attendance register.
    """

    day = _as_date(att_date)

    if day is None:

        return False, "That date could not be read."

    if day != datetime.date.today():

        return False, "You can only change today's attendance."

    if status not in ATTENDANCE_STATUSES:

        return False, "Please choose an attendance type."

    mark_attendance(employee_id, day, status, note or None)

    return True, f"{day} marked as {status}."


# -----------------------------------------------------------
# CLOCKING
# -----------------------------------------------------------

def today_record(employee_id, day=None):
    """One person's row for a date, or None."""

    day = day or datetime.date.today()

    return get_attendance_for_date(day).get(employee_id)


def clock_in(employee_id, mode="Office", at=None, day=None):
    """Record the start of a shift.

    ``mode`` is Office or Work From Home, which decides the status
    the day is kept under. Returns ``(ok, message)``.
    """

    day = day or datetime.date.today()
    at = at or datetime.datetime.now().time()

    if not is_working_day(day):

        return False, (
            f"{day:%A, %d %B %Y} is a weekend or a holiday — "
            "there is no shift to clock in for."
        )

    if mode not in WORK_MODES:

        return False, "Please choose how you are working today."

    record = today_record(employee_id, day)

    if record and record["in_time"]:

        return False, (
            f"You clocked in at {record['in_time']}. "
            "Clock out to finish the day first."
        )

    if (record and record["status"] == "Leave") or (
        employee_id in _leave_map(day)
    ):

        return False, (
            "You are on approved leave today, so there is nothing "
            "to clock in for."
        )

    status = "Work From Home" if mode == "Work From Home" else "Present"

    mark_attendance(
        employee_id,
        day,
        status,
        in_time=at,
        out_time=None if not record else record["out_time"]
    )

    return True, f"Clocked in at {_clock(at)}."


def clock_out(employee_id, at=None, day=None):
    """Record the end of a shift, and settle what the day was worth.

    Returns ``(ok, message)``.
    """

    day = day or datetime.date.today()
    at = at or datetime.datetime.now().time()

    record = today_record(employee_id, day)

    if not record or not record["in_time"]:

        return False, "Clock in first — there is no shift to finish."

    if record["out_time"]:

        return False, (
            f"You already clocked out at {record['out_time']}."
        )

    hours = hours_worked(
        record["in_time"],
        at,
        shift_for_employee(employee_id)
    )

    # Keep the day's mode: a WFH day stays WFH when it is closed.
    if record["status"] == "Work From Home":

        status = "Work From Home"

    else:

        status = derive_status(hours, shift_for_employee(employee_id))

    mark_attendance(
        employee_id,
        day,
        status,
        out_time=at
    )

    return True, (
        f"Clocked out at {_clock(at)} — {_hours_label(hours)} served."
    )


def set_mode(employee_id, mode, day=None):
    """Switch today between Office and Work From Home."""

    day = day or datetime.date.today()

    if mode not in WORK_MODES:

        return False, "Please choose how you are working today."

    record = today_record(employee_id, day)

    if not record or not record["in_time"]:

        return False, "Clock in first, then choose how you are working."

    mark_attendance(
        employee_id,
        day,
        "Work From Home" if mode == "Work From Home" else "Present",
        in_time=record["in_time"],
        out_time=record["out_time"]
    )

    return True, f"Today set to {mode}."


# -----------------------------------------------------------
# REGISTER / SUMMARIES
# -----------------------------------------------------------

def daily_register(att_date):
    """Everyone, with their punches for one date.

    Returns a list of dicts in employee order. ``status`` is None
    when the person has not been recorded; ``marked`` says whether a
    row exists at all.
    """

    day = _as_date(att_date)

    if day is None:

        return []

    existing = get_attendance_for_date(day)

    register = []

    for employee_id, employee_name in list_employees():

        record = existing.get(employee_id)

        register.append(
            {
                "employee_id": employee_id,
                "employee_name": employee_name,
                "status": record["status"] if record else None,
                "note": (record["note"] if record else "") or "",
                "in_time": record["in_time"] if record else "",
                "out_time": record["out_time"] if record else "",
                "marked": record is not None
            }
        )

    return register


def register_summary(register, att_date):
    """Head-count per status for a date, including "Not marked"."""

    counts = {"Not marked": 0}

    for status in ATTENDANCE_STATUSES:

        counts[status] = 0

    working = is_working_day(att_date)

    for person in register:

        if person["marked"] and person["status"] in counts:

            counts[person["status"]] += 1

        elif working:

            # Only call someone "not marked" on a working day; on a
            # weekend or holiday the register is empty by design.
            counts["Not marked"] += 1

    return counts


def _leave_map(day):
    """{employee_id: leave_type} for approved leave covering a date."""

    day = _as_date(day)

    if day is None:

        return {}

    wanted = day.isoformat()

    covered = {}

    try:

        requests = get_requests(status="Approved")

    except Exception:  # noqa: BLE001

        return covered

    for request in requests:

        try:

            start = datetime.date.fromisoformat(
                str(request["from_date"])
            )

            end = datetime.date.fromisoformat(str(request["to_date"]))

        except (TypeError, ValueError):

            continue

        if start <= day <= end:

            covered[request["employee_id"]] = request["leave_type"]

    return covered


def month_summary(employee_id, year, month):
    """One person's month, in the numbers HR actually reports on."""

    records = get_attendance(employee_id, year, month)

    expected = working_days(year, month)

    shift = shift_for_employee(employee_id)

    present = wfh = half = leave = absent = 0

    late_days = 0

    total_hours = 0.0

    logged_hours = 0

    for date_key, record in records.items():

        status = record["status"]

        hours = hours_worked(
            record["in_time"],
            record["out_time"],
            shift
        )

        if hours is not None:

            total_hours += hours

            logged_hours += 1

        if record["in_time"] and late_by(record["in_time"], shift):

            late_days += 1

        if status == "Present":

            present += 1

        elif status == "Work From Home":

            wfh += 1

        elif status == "Half Day":

            half += 1

        elif status == "Leave":

            leave += 1

        elif status == "Absent":

            absent += 1

    recorded = present + wfh + half + leave + absent

    attended = present + wfh + half * 0.5

    percentage = (
        round(attended / expected * 100, 1) if expected else 0.0
    )

    return {
        "expected": expected,
        "present": present,
        "work_from_home": wfh,
        "half_day": half,
        "leave": leave,
        "absent": absent,
        "unmarked": max(expected - recorded, 0),
        "late_days": late_days,
        "total_hours": round(total_hours, 2),
        "average_hours": (
            round(total_hours / logged_hours, 2) if logged_hours else 0.0
        ),
        "attendance_pct": percentage
    }


def monthly_report(year, month):
    """Every employee's month, for the HR summary table."""

    rows = []

    for employee_id, employee_name in list_employees():

        summary = month_summary(employee_id, year, month)

        rows.append(
            {
                "Employee": employee_name,
                "Employee ID": employee_id,
                "Present": summary["present"],
                "WFH": summary["work_from_home"],
                "Half day": summary["half_day"],
                "Leave": summary["leave"],
                "Absent": summary["absent"],
                "Not marked": summary["unmarked"],
                "Late": summary["late_days"],
                "Hours": summary["total_hours"],
                "Avg hrs/day": summary["average_hours"],
                "Attendance %": summary["attendance_pct"]
            }
        )

    return rows


def attendance_insights(year, month):
    """Exceptions and repeated patterns for a selected month."""

    start = datetime.date(year, month, 1)
    if month == 12:
        end = datetime.date(year, 12, 31)
    else:
        end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    today = datetime.date.today()
    connection = get_connection()
    try:
        employment_dates = {
            row[0]: (row[1], row[2])
            for row in connection.execute(
                "SELECT employee_id, joining_date, exit_date FROM employees"
            ).fetchall()
        }
    finally:
        connection.close()

    approved_leave = {}
    for request in get_requests(status="Approved"):
        try:
            leave_start = datetime.date.fromisoformat(request["from_date"])
            leave_end = datetime.date.fromisoformat(request["to_date"])
        except (TypeError, ValueError):
            continue
        day = leave_start
        while day <= leave_end:
            approved_leave[(request["employee_id"], day.isoformat())] = True
            day += datetime.timedelta(days=1)

    insights = []
    for employee_id, employee_name in list_employees():
        records = get_attendance(employee_id, year, month)
        joining_date, exit_date_value = employment_dates.get(
            employee_id, ("", "")
        )
        joining_date = _as_date(joining_date)
        exit_date = _as_date(exit_date_value) if exit_date_value else None
        shift = shift_for_employee(employee_id)
        shift_start = _minutes(shift.get("start_time", SHIFT_START))
        shift_end = _minutes(shift.get("end_time", SHIFT_END))
        scheduled_minutes = shift_end - shift_start
        if scheduled_minutes < 0:
            scheduled_minutes += 24 * 60
        if scheduled_minutes > BREAK_THRESHOLD_HOURS * 60:
            scheduled_minutes -= _shift_int(
                shift, "break_minutes", BREAK_MINUTES
            )
        scheduled_hours = max(scheduled_minutes, 0) / 60

        late_days = []
        missing_in = []
        missing_out = []
        overtime = []
        absent_days = []
        not_recorded = []

        for date_key, record in records.items():
            day = _as_date(date_key)
            if not day or day < start or day > end:
                continue
            if (
                (joining_date and day < joining_date)
                or (exit_date and day > exit_date)
            ):
                continue
            if record["status"] == "Absent":
                absent_days.append(date_key)
            if record["status"] not in ("Absent", "Leave"):
                if record["in_time"] and late_by(record["in_time"], shift):
                    late_days.append(date_key)
                if not record["in_time"]:
                    missing_in.append(date_key)
                if record["in_time"] and not record["out_time"]:
                    missing_out.append(date_key)
                hours = hours_worked(
                    record["in_time"], record["out_time"], shift
                )
                if hours is not None and hours > scheduled_hours + 0.25:
                    overtime.append(
                        {
                            "date": date_key,
                            "hours": round(hours - scheduled_hours, 2)
                        }
                    )

        checked_day = start
        last_day = min(end, today)
        while checked_day <= last_day:
            date_key = checked_day.isoformat()
            if (
                is_working_day(checked_day)
                and (not joining_date or checked_day >= joining_date)
                and (not exit_date or checked_day <= exit_date)
                and date_key not in records
                and (employee_id, date_key) not in approved_leave
            ):
                not_recorded.append(date_key)
            checked_day += datetime.timedelta(days=1)

        if any((
            late_days, missing_in, missing_out, overtime, absent_days,
            not_recorded
        )):
            insights.append(
                {
                    "Employee": employee_name,
                    "Employee ID": employee_id,
                    "Late arrivals": len(late_days),
                    "Late pattern": (
                        f"Recurring ({len(late_days)} days)"
                        if len(late_days) >= 3 else ""
                    ),
                    "Missed clock-ins": len(missing_in),
                    "Missed clock-outs": len(missing_out),
                    "Unrecorded workdays": len(not_recorded),
                    "Overtime days": len(overtime),
                    "Overtime hours": round(
                        sum(item["hours"] for item in overtime), 2
                    ),
                    "Absent days": len(absent_days),
                    "Dates": ", ".join(
                        late_days + missing_in + missing_out
                        + absent_days + not_recorded
                    )
                }
            )
    return insights


# -----------------------------------------------------------
# SHARED RENDERING
# -----------------------------------------------------------

def _shift_caption(shift=None):
    """The one line explaining the timings that apply."""

    shift = shift or DEFAULT_SHIFT

    where = shift.get("client_project") or ""

    label = shift.get("shift_name") or "General"

    if where and where.lower() != "all":

        label = f"{label} · {where}"

    return (
        f"**{label}** shift "
        f"**{shift['start_time']} – {shift['end_time']}** "
        f"({float(MIN_HOURS_FULL_DAY if shift.get('min_hours_full_day') is None else shift.get('min_hours_full_day')):.0f} "
        f"hours, {_shift_int(shift, 'break_minutes', BREAK_MINUTES)} min break). "
        f"More than {_shift_int(shift, 'grace_minutes', GRACE_MINUTES)} min "
        f"late counts as late."
    )


def _punch_badge(in_time, out_time):
    """A short status chip for one punch pair."""

    if not in_time:

        return "Not checked in"

    if not out_time:

        return "Working"

    return "Checked out"


def _punch_metrics(record, shift=None):
    """In / out / hours / punctuality as a metric row."""

    shift = shift or DEFAULT_SHIFT

    in_time = record["in_time"] if record else ""
    out_time = record["out_time"] if record else ""

    hours = hours_worked(in_time, out_time, shift)

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "Clock in",
            in_time or "—",
            icon=":material/login:",
            border=True
        )

    with col2:

        st.metric(
            "Clock out",
            out_time or "—",
            icon=":material/logout:",
            border=True
        )

    with col3:

        st.metric(
            "Hours served",
            _hours_label(hours) or "—",
            icon=":material/schedule:",
            border=True,
            help="Net of the lunch break."
        )

    with col4:

        st.metric(
            "Punctuality",
            punctuality(in_time, shift) or "—",
            icon=":material/alarm:",
            border=True,
            help=f"On time means before {shift['start_time']}, "
                 f"plus a {_shift_int(shift, 'grace_minutes', GRACE_MINUTES)} "
                 f"minute grace."
        )


# -----------------------------------------------------------
# HR PAGE
# -----------------------------------------------------------

def show_attendance_page(go_home=None):
    """HR time & attendance: today's timesheet, then the month."""

    hero(
        "Attendance",
        "The company timesheet — who clocked in, who is late, and "
        "how many hours the team has served.",
        icon="fact_check",
        badges=[
            (f"Shift {SHIFT_START} – {SHIFT_END}", "schedule"),
            (f"{GRACE_MINUTES} min grace", "alarm"),
            ("Hours served tracked", "timer")
        ]
    )

    flash = st.session_state.pop("att_flash", None)

    if flash:

        st.success(flash)

    if go_home and st.button(
        "← Back to dashboard",
        key="attendance_back",
        width="content"
    ):

        go_home()

        st.rerun()

    employees = list_employees()

    if not employees:

        st.info("No employees yet.")

        return

    sheet_tab, month_tab, insight_tab = st.tabs(
        ["Daily timesheet", "Monthly summary", "Insights"]
    )

    # -----------------------------------------------------
    # DAILY TIMESHEET
    # -----------------------------------------------------
    # Employees clock in and out themselves. HR watches the sheet
    # here and fixes anything that is wrong from the panel below.

    with sheet_tab:

        att_date = st.date_input(
            "Date",
            value=datetime.date.today(),
            max_value=datetime.date.today(),
            key="attendance_register_date"
        )

        working = is_working_day(att_date)

        register = daily_register(att_date)

        on_leave = _leave_map(att_date)

        shifts = shift_lookup()

        st.caption(
            "Each person is measured against their own shift. "
            "HR can add client or project shifts under "
            "*Shift timings*."
        )

        if not working:

            st.info(
                f"{att_date:%A, %d %B %Y} is a weekend or a holiday, "
                "so there is no attendance to record."
            )

        # Anyone on approved leave is on the sheet even without an
        # attendance row, so HR is never left guessing — merge before counting.
        for person in register:

            if (
                not person["marked"]
                and person["employee_id"] in on_leave
            ):

                person["status"] = "Leave"

                person["marked"] = True

        counts = register_summary(register, att_date)

        metrics = st.columns(6)

        late_today = sum(
            1
            for person in register
            if person["in_time"]
            and late_by(
                person["in_time"],
                shifts.get(person["employee_id"])
            )
        )

        served_today = sum(
            1
            for person in register
            if person["in_time"]
        )

        for column, (label, value, icon) in zip(
            metrics,
            [
                ("Present", counts["Present"], ":material/groups:"),
                ("WFH", counts["Work From Home"], ":material/home:"),
                ("Half day", counts["Half Day"], ":material/time_to_leave:"),
                ("On leave", counts["Leave"], ":material/beach_access:"),
                ("Absent", counts["Absent"], ":material/person_off:"),
                ("Late today", late_today, ":material/alarm:")
            ]
        ):

            with column:

                st.metric(
                    label,
                    value,
                    icon=icon,
                    border=True,
                    help=(
                        "Anyone with an approved leave request is "
                        "counted as on leave."
                        if label == "On leave" else None
                    )
                )

        rows = []

        for person in register:

            person_shift = shifts.get(person["employee_id"])

            hours = hours_worked(
                person["in_time"],
                person["out_time"],
                person_shift
            )

            rows.append(
                {
                    "Employee": person["employee_name"],
                    "Employee ID": person["employee_id"],
                    "Status": person["status"] or "Not checked in",
                    "Clock in": person["in_time"] or "—",
                    "Clock out": person["out_time"] or "—",
                    "Hours": _hours_label(hours) or "—",
                    "Punctuality": punctuality(
                        person["in_time"],
                        person_shift
                    ) or "—",
                    "Note": person["note"]
                }
            )

        st.markdown("#### Who is in")

        st.caption(
            f"{served_today} of {len(employees)} have clocked in "
            f"for {att_date:%A, %d %B %Y}."
        )

        st.dataframe(
            rows,
            width="stretch",
            hide_index=True
        )

        with st.expander(
            "Correct a day (status, clock in, clock out)",
            icon=":material/edit_note:",
            type="compact"
        ):

            st.caption(
                "Use this to fix a missed punch or to record on "
                "someone's behalf. The times are pre-filled from "
                "what is already stored — adjust and save."
            )

            with st.form(f"mark_attendance_{att_date}"):

                statuses = {}

                notes = {}

                ins = {}

                outs = {}

                existing = get_attendance_for_date(att_date)

                for employee_id, employee_name in employees:

                    st.markdown(f"**{employee_name} ({employee_id})**")

                    current = existing.get(employee_id, {})

                    status_col, in_col, out_col = st.columns([2, 1, 1])

                    with status_col:

                        status_choices = ["Not marked"] + ATTENDANCE_STATUSES

                        default_status = (
                            current.get("status")
                            if current.get("status") in ATTENDANCE_STATUSES
                            else ("Leave" if employee_id in on_leave else "Not marked")
                        )

                        index = (
                            status_choices.index(default_status)
                            if default_status in status_choices
                            else 0
                        )

                        statuses[employee_id] = st.selectbox(
                            "Status",
                            status_choices,
                            index=index,
                            key=f"att_status_{employee_id}_{att_date}",
                            label_visibility="collapsed"
                        )

                    with in_col:

                        stored_in = _as_time(current.get("in_time"))

                        ins[employee_id] = st.time_input(
                            "Clock in",
                            value=stored_in or datetime.time(9, 30),
                            key=f"att_in_{employee_id}_{att_date}",
                            label_visibility="collapsed"
                        )

                    with out_col:

                        stored_out = _as_time(current.get("out_time"))

                        outs[employee_id] = st.time_input(
                            "Clock out",
                            value=stored_out or datetime.time(18, 30),
                            key=f"att_out_{employee_id}_{att_date}",
                            label_visibility="collapsed"
                        )

                    notes[employee_id] = st.text_input(
                        "Note",
                        value=current.get("note", "") or "",
                        key=f"att_note_{employee_id}_{att_date}",
                        label_visibility="collapsed",
                        placeholder="Note (optional)"
                    )

                saved = st.form_submit_button(
                    "Save attendance",
                    icon=":material/save:",
                    width="stretch"
                )

            if saved:

                for employee_id in statuses:

                    chosen_status = statuses[employee_id]
                    if chosen_status == "Not marked":
                        continue

                    # Absent and Leave days should never retain work punch times.
                    if chosen_status in ("Absent", "Leave"):
                        in_val = ""
                        out_val = ""
                    else:
                        in_val = ins[employee_id]
                        out_val = outs[employee_id]

                    mark_attendance(
                        employee_id,
                        att_date,
                        chosen_status,
                        notes[employee_id],
                        in_time=in_val,
                        out_time=out_val
                    )

                st.session_state["att_flash"] = (
                    f"Attendance saved for {att_date}."
                )

                st.rerun()

    # -----------------------------------------------------
    # MONTHLY SUMMARY
    # -----------------------------------------------------

    with month_tab:

        col1, col2 = st.columns(2)

        today = datetime.date.today()

        with col1:

            month = st.selectbox(
                "Month",
                list(range(1, 13)),
                index=today.month - 1,
                format_func=lambda m: MONTHS[m - 1]
            )

        with col2:

            year = st.number_input(
                "Year",
                min_value=2000,
                max_value=2100,
                value=today.year,
                step=1
            )

        working = _working_days(year, month)

        rows = monthly_report(year, month)

        served = sum(row["Hours"] for row in rows)

        late_total = sum(row["Late"] for row in rows)

        percentages = [
            row["Attendance %"]
            for row in rows
            if row["Attendance %"]
        ]

        average_pct = (
            round(sum(percentages) / len(percentages), 1)
            if percentages else 0.0
        )

        col1, col2, col3, col4 = st.columns(4)

        with col1:

            st.metric(
                "Working days",
                working,
                icon=":material/calendar_month:",
                border=True,
                help="Weekdays, excluding holidays."
            )

        with col2:

            st.metric(
                "Hours served",
                _hours_label(served),
                icon=":material/schedule:",
                border=True,
                help="All employees combined."
            )

        with col3:

            st.metric(
                "Late arrivals",
                late_total,
                icon=":material/alarm:",
                border=True,
                help="Days someone clocked in after their own "
                     "shift start, plus its grace window."
            )

        with col4:

            st.metric(
                "Attendance",
                f"{average_pct}%",
                icon=":material/percent:",
                border=True,
                help="Team average against the working days."
            )

        st.caption(
            f"{MONTHS[month - 1]} {year} · "
            f"{working} working day(s) (Mon–Fri, excl. holidays)."
        )

        st.dataframe(rows, width="stretch", hide_index=True)

        st.divider()

        st.markdown("#### Day-by-day")

        options = {
            f"{name}  ({employee_id})": employee_id
            for employee_id, name in employees
        }

        selected = st.selectbox(
            "Employee",
            list(options.keys()),
            key="attendance_day_by_day"
        )

        records = get_attendance(
            options[selected],
            year,
            month
        )

        if not records:

            st.info("No attendance recorded for this period.")

        else:

            detail = []

            detail_shift = shift_for_employee(options[selected])

            for date, record in records.items():

                hours = hours_worked(
                    record["in_time"],
                    record["out_time"],
                    detail_shift
                )

                detail.append(
                    {
                        "Date": date,
                        "Status": record["status"],
                        "Clock in": record["in_time"] or "—",
                        "Clock out": record["out_time"] or "—",
                        "Hours": _hours_label(hours) or "—",
                        "Punctuality": (
                            punctuality(
                                record["in_time"],
                                detail_shift
                            ) or "—"
                        ),
                        "Note": record["note"] or ""
                    }
                )

            st.dataframe(
                detail,
                width="stretch",
                hide_index=True
            )

    with insight_tab:

        col1, col2 = st.columns(2)
        today = datetime.date.today()
        with col1:
            insight_month = st.selectbox(
                "Month",
                list(range(1, 13)),
                index=today.month - 1,
                format_func=lambda value: MONTHS[value - 1],
                key="attendance_insights_month"
            )
        with col2:
            insight_year = st.number_input(
                "Year",
                min_value=2000,
                max_value=2100,
                value=today.year,
                step=1,
                key="attendance_insights_year"
            )

        insights = attendance_insights(insight_year, insight_month)
        if not insights:
            st.success("No attendance exceptions found for this period.")
        else:
            st.caption(
                "Exceptions are based on recorded punches and assigned "
                "shift timings. Review missed punches before treating "
                "them as attendance violations."
            )
            st.dataframe(
                insights,
                width="stretch",
                hide_index=True
            )


# -----------------------------------------------------------
# EMPLOYEE PAGE
# -----------------------------------------------------------

def show_my_attendance():
    """Employee time & attendance: clock in, clock out, then the month."""

    employee_id = st.session_state.auth_user["employee_id"]

    today = datetime.date.today()

    my_shift = shift_for_employee(employee_id)

    hero(
        "My attendance",
        "Clock in when you start and clock out when you finish — "
        "the hours and your punctuality follow from that.",
        icon="fact_check",
        badges=[
            (
                f"{my_shift['shift_name']} "
                f"{my_shift['start_time']} – {my_shift['end_time']}",
                "schedule"
            ),
            (
                f"{_shift_int(my_shift, 'grace_minutes', GRACE_MINUTES)} min grace",
                "alarm"
            ),
            ("Hours tracked", "timer")
        ]
    )

    flash = st.session_state.pop("att_flash", None)

    if flash:

        st.success(flash)

    record = today_record(employee_id, today)

    # -----------------------------------------------------
    # TODAY
    # -----------------------------------------------------

    st.markdown("#### Today")

    st.caption(
        f"{today:%A, %d %B %Y} · {_shift_caption(my_shift)}"
    )

    if not is_working_day(today):

        reason = (
            "a holiday"
            if today.isoformat() in holiday_dates(today.year)
            else "the weekend"
        )

        st.info(
            f"{today:%A, %d %B %Y} is {reason}, so there is no "
            "shift to clock in for."
        )

    elif employee_id in _leave_map(today) or (
        record and record["status"] == "Leave"
    ):

        st.info(
            "You are on approved leave today, so there is nothing "
            "to clock in for."
        )

        _punch_metrics(record, my_shift)

    else:

        _punch_metrics(record, my_shift)

        state = _punch_badge(
            record["in_time"] if record else "",
            record["out_time"] if record else ""
        )

        st.caption(f"Status: **{state}**")

        col1, col2, col3 = st.columns([2, 2, 3])

        with col1:

            if st.button(
                "Clock in",
                key="my_att_clock_in",
                icon=":material/login:",
                type="primary",
                width="stretch",
                disabled=bool(record and record["in_time"]),
                help="Records your clock-in time for today."
            ):

                ok, message = clock_in(
                    employee_id,
                    mode=st.session_state.get(
                        "my_att_mode",
                        "Office"
                    )
                )

                if ok:

                    st.session_state["att_flash"] = message

                    st.rerun()

                else:

                    st.error(message)

        with col2:

            if st.button(
                "Clock out",
                key="my_att_clock_out",
                icon=":material/logout:",
                type="primary",
                width="stretch",
                disabled=not (record and record["in_time"])
                or bool(record and record["out_time"]),
                help="Records that you finished for the day."
            ):

                ok, message = clock_out(employee_id)

                if ok:

                    st.session_state["att_flash"] = message

                    st.rerun()

                else:

                    st.error(message)

        with col3:

            mode = st.radio(
                "How are you working today?",
                WORK_MODES,
                index=(
                    1
                    if record and record["status"] == "Work From Home"
                    else 0
                ),
                key="my_att_mode",
                horizontal=True,
                disabled=not (record and record["in_time"])
            )

            if st.button(
                "Save work mode",
                key="my_att_mode_save",
                icon=":material/edit_note:",
                width="stretch",
                disabled=not (record and record["in_time"]),
                help="Switch today between the office and home."
            ):

                ok, message = set_mode(employee_id, mode)

                if ok:

                    st.session_state["att_flash"] = message

                    st.rerun()

                else:

                    st.error(message)

    # -----------------------------------------------------
    # MONTH BY MONTH
    # -----------------------------------------------------

    st.markdown("#### This month and earlier")

    col1, col2 = st.columns(2)

    with col1:

        month = st.selectbox(
            "Month",
            list(range(1, 13)),
            index=today.month - 1,
            format_func=lambda m: MONTHS[m - 1],
            key="my_att_month"
        )

    with col2:

        year = st.number_input(
            "Year",
            min_value=2000,
            max_value=2100,
            value=today.year,
            step=1,
            key="my_att_year"
        )

    records = get_attendance(employee_id, year, month)

    summary = month_summary(employee_id, year, month)

    metrics = st.columns(4)

    with metrics[0]:

        st.metric(
            "Attendance",
            f"{summary['attendance_pct']}%",
            icon=":material/percent:",
            border=True,
            help=f"{summary['expected']} working day(s) this month."
        )

    with metrics[1]:

        st.metric(
            "Hours served",
            _hours_label(summary["total_hours"]) or "0h 00m",
            icon=":material/schedule:",
            border=True,
            help="Net of the lunch break."
        )

    with metrics[2]:

        st.metric(
            "Late arrivals",
            summary["late_days"],
            icon=":material/alarm:",
            border=True,
            help=f"Days you clocked in after "
                 f"{my_shift['start_time']} plus "
                 f"{_shift_int(my_shift, 'grace_minutes', GRACE_MINUTES)} min."
        )

    with metrics[3]:

        st.metric(
            "Avg hrs/day",
            summary["average_hours"],
            icon=":material/timer:",
            border=True,
            help="Across the days you actually logged."
        )

    st.caption(
        f"{MONTHS[month - 1]} {year} · "
        f"{summary['present']} present · "
        f"{summary['work_from_home']} WFH · "
        f"{summary['half_day']} half day · "
        f"{summary['leave']} on leave · "
        f"{summary['absent']} absent."
    )

    if not records:

        st.info("No attendance recorded for this period.")

        return

    rows = []

    for date, record in records.items():

        hours = hours_worked(
            record["in_time"],
            record["out_time"],
            my_shift
        )

        rows.append(
            {
                "Date": date,
                "Status": record["status"],
                "Clock in": record["in_time"] or "—",
                "Clock out": record["out_time"] or "—",
                "Hours": _hours_label(hours) or "—",
                "Punctuality": (
                    punctuality(record["in_time"], my_shift) or "—"
                ),
                "Note": record["note"] or ""
            }
        )

    st.dataframe(
        rows,
        width="stretch",
        hide_index=True
    )
