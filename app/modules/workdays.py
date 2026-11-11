import datetime

from database.connection import get_connection


# ============================================================
# WORKING DAYS
# ============================================================
# One place that answers "how many working days is that?".
#
# A school register counts every calendar day between two dates, so
# Friday to Monday is "4 days". A company only loses Monday and
# Friday, so that is 2 days — and if Monday is a public holiday it
# is 1 day.
#
# This module deliberately imports nothing from the rest of
# ``modules``. ``holidays`` imports ``payslip`` (for MONTHS), so
# ``payslip`` cannot import ``holidays`` back without a cycle. It
# reads the holiday table straight from the database instead, which
# keeps every caller able to use it freely.

DAY_PORTIONS = ["Full day", "First half", "Second half"]

HALF_DAY = 0.5


def holiday_date_set(years=None):
    """ISO date strings that are holidays, optionally for given years."""

    connection = get_connection()

    try:

        if years is not None:

            marks = set()

            for year in years:

                marks.update(
                    row[0]
                    for row in connection.execute(
                        "SELECT holiday_date FROM holidays "
                        "WHERE substr(holiday_date, 1, 4) = ?",
                        (str(year),)
                    ).fetchall()
                )

            return marks

        return {
            row[0]
            for row in connection.execute(
                "SELECT holiday_date FROM holidays"
            ).fetchall()
        }

    except Exception:  # noqa: BLE001 - a missing table means no holidays

        return set()

    finally:

        connection.close()


def is_working_day(day, holidays=None):
    """True when the date is a Mon-Fri that is not a holiday."""

    if isinstance(day, str):

        try:

            day = datetime.date.fromisoformat(str(day).strip())

        except (TypeError, ValueError):

            return False

    if not isinstance(day, datetime.date) or day.weekday() >= 5:

        return False

    skip = (
        holidays
        if holidays is not None
        else holiday_date_set({day.year})
    )

    return day.isoformat() not in skip


def working_days_between(from_date, to_date, portion="Full day"):
    """Working days in a range: Mon-Fri, excluding public holidays.

    ``portion`` halves a single-day request (a first-half or
    second-half day is half a day's pay/entitlement). Multi-day
    ranges always count whole working days.
    """

    if isinstance(from_date, str):

        try:

            from_date = datetime.date.fromisoformat(
                str(from_date).strip()
            )

        except (TypeError, ValueError):

            return 0

    if isinstance(to_date, str):

        try:

            to_date = datetime.date.fromisoformat(str(to_date).strip())

        except (TypeError, ValueError):

            return 0

    if to_date < from_date:

        return 0

    skip = holiday_date_set({from_date.year, to_date.year})

    total = 0

    current = from_date

    one_day = datetime.timedelta(days=1)

    while current <= to_date:

        if is_working_day(current, skip):

            total += 1

        current += one_day

    if total == 1 and portion in ("First half", "Second half"):

        return HALF_DAY

    return float(total)


def span_description(from_date, to_date, portion="Full day"):
    """A short human line: 'Mon 19 Oct – Tue 20 Oct · 2 working days'."""

    start = from_date if isinstance(from_date, datetime.date) else None
    end = to_date if isinstance(to_date, datetime.date) else None

    try:

        start = start or datetime.date.fromisoformat(str(from_date))

        end = end or datetime.date.fromisoformat(str(to_date))

    except (TypeError, ValueError):

        return ""

    if start == end:

        head = start.strftime("%a %d %b %Y")

    else:

        head = (
            f"{start.strftime('%a %d %b')} – "
            f"{end.strftime('%a %d %b %Y')}"
        )

    days = working_days_between(start, end, portion)

    if days == 0:

        return f"{head} · no working days (weekend or holiday)"

    label = "working day" if days == 1 else "working days"

    if days == HALF_DAY:

        label = "working day (half)"

    return f"{head} · {days:g} {label}"


def skipped_days(from_date, to_date):
    """Weekend/holiday dates inside a range, as ISO strings.

    Shown to the employee so they can see exactly which days in the
    range are not being deducted from their balance.
    """

    if isinstance(from_date, str):

        try:

            from_date = datetime.date.fromisoformat(
                str(from_date).strip()
            )

        except (TypeError, ValueError):

            return []

    if isinstance(to_date, str):

        try:

            to_date = datetime.date.fromisoformat(str(to_date).strip())

        except (TypeError, ValueError):

            return []

    if to_date < from_date:

        return []

    skip = holiday_date_set({from_date.year, to_date.year})

    out = []

    current = from_date

    one_day = datetime.timedelta(days=1)

    while current <= to_date:

        if not is_working_day(current, skip):

            out.append(current.isoformat())

        current += one_day

    return out
