import calendar
import datetime
import html

import streamlit as st

from database.connection import (
    get_connection,
    create_holiday_table,
    create_holiday_seed_table
)
from modules.payslip import MONTHS
from modules.theme import hero


# ============================================================
# HOLIDAY CALENDAR
# ============================================================
# HR maintains the list of public/company holidays. The calendar
# feeds the attendance module so holidays are never counted as
# working days, and employees get a read-only holiday list.

DEFAULT_FIXED_HOLIDAYS = [
    (1, 1, "New Year's Day"),
    (1, 26, "Republic Day"),
    (5, 1, "May Day"),
    (8, 15, "Independence Day"),
    (10, 2, "Gandhi Jayanti"),
    (12, 25, "Christmas"),
]

# Festival dates move every year, so they are listed only for years
# whose dates have been checked. Fixed national holidays repeat for
# every year without needing an entry here.
DEFAULT_FESTIVALS = {
    2026: [
        (1, 14, "Makar Sankranti / Pongal"),
        (3, 4, "Holi"),
        (3, 21, "Id-ul-Fitr"),
        (3, 26, "Ram Navami"),
        (3, 31, "Mahavir Jayanti"),
        (4, 3, "Good Friday"),
        (5, 27, "Bakrid"),
        (6, 26, "Muharram"),
        (8, 26, "Milad-un-Nabi"),
        (9, 4, "Janmashtami"),
        (10, 20, "Dussehra"),
        (11, 8, "Diwali"),
        (11, 24, "Guru Nanak Jayanti"),
    ],
}


def create_holiday_tables():

    create_holiday_table()

    create_holiday_seed_table()

    seed_default_holidays()


def seed_default_holidays(year=None):
    """Add the standard holiday list once per year.

    A marker row in ``holiday_seed`` keeps this idempotent and stops
    removed defaults from reappearing on the next rerun.
    """

    year = int(year or datetime.date.today().year)

    entries = list(DEFAULT_FIXED_HOLIDAYS)
    entries.extend(DEFAULT_FESTIVALS.get(year, []))

    if not entries:

        return 0

    connection = get_connection()

    try:

        seeded = connection.execute(
            "SELECT 1 FROM holiday_seed WHERE year = ?",
            (year,)
        ).fetchone()

        if seeded:

            return 0

        before = connection.execute(
            """
            SELECT COUNT(*) FROM holidays
            WHERE substr(holiday_date, 1, 4) = ?
            """,
            (str(year),)
        ).fetchone()[0]

        for month, day_number, name in entries:

            connection.execute(
                """
                INSERT INTO holidays (holiday_date, name)
                VALUES (?, ?)
                ON CONFLICT(holiday_date) DO NOTHING
                """,
                (f"{year:04d}-{month:02d}-{day_number:02d}", name)
            )

        connection.execute(
            """
            INSERT OR REPLACE INTO holiday_seed (year, seeded_at)
            VALUES (?, ?)
            """,
            (year, datetime.datetime.now().isoformat(timespec="seconds"))
        )

        connection.commit()

        after = connection.execute(
            """
            SELECT COUNT(*) FROM holidays
            WHERE substr(holiday_date, 1, 4) = ?
            """,
            (str(year),)
        ).fetchone()[0]

        return after - before

    finally:

        connection.close()



# ---------------------------------------------------------
# DATA HELPERS
# ---------------------------------------------------------

def list_holidays(year=None):
    """Holidays as (id, holiday_date, name), oldest first."""

    connection = get_connection()

    try:

        if year is None:

            rows = connection.execute(
                """
                SELECT id, holiday_date, name
                FROM holidays
                ORDER BY holiday_date
                """
            ).fetchall()

        else:

            rows = connection.execute(
                """
                SELECT id, holiday_date, name
                FROM holidays
                WHERE substr(holiday_date, 1, 4) = ?
                ORDER BY holiday_date
                """,
                (str(year),)
            ).fetchall()

    finally:

        connection.close()

    return rows


def holiday_dates(year=None):
    """Set of ISO date strings that are holidays (optionally one year)."""

    return {row[1] for row in list_holidays(year)}


def add_holiday(holiday_date, name):
    """Insert or rename a holiday for a date."""

    connection = get_connection()

    try:

        connection.execute(
            """
            INSERT INTO holidays (holiday_date, name)
            VALUES (?, ?)

            ON CONFLICT(holiday_date)
            DO UPDATE SET name = excluded.name
            """,
            (str(holiday_date), name)
        )

        connection.commit()

    finally:

        connection.close()


def delete_holiday(holiday_id):
    """Remove one holiday by id."""

    connection = get_connection()

    try:

        connection.execute(
            "DELETE FROM holidays WHERE id = ?",
            (holiday_id,)
        )

        connection.commit()

    finally:

        connection.close()


def update_holiday(holiday_id, holiday_date, name):
    """Change a holiday's date and name. Returns (ok, message)."""

    connection = get_connection()

    try:

        existing = connection.execute(
            "SELECT holiday_date, name FROM holidays WHERE id = ?",
            (holiday_id,)
        ).fetchone()

        if existing is None:

            return False, "That holiday no longer exists."

        target = str(holiday_date)

        clash = connection.execute(
            """
            SELECT id FROM holidays
            WHERE holiday_date = ? AND id <> ?
            """,
            (target, holiday_id)
        ).fetchone()

        if clash:

            return (
                False,
                f"Another holiday already exists on {_nice_date(target)}. "
                "Edit or remove it first."
            )

        connection.execute(
            """
            UPDATE holidays
            SET holiday_date = ?, name = ?
            WHERE id = ?
            """,
            (target, name, holiday_id)
        )

        connection.commit()

    finally:

        connection.close()

    return True, f"'{name}' saved on {_nice_date(holiday_date)}."


def _upcoming_rows(today=None):
    """Current-year holidays from today onwards, oldest first."""

    today = today or datetime.date.today()

    rows = []

    for row in list_holidays(today.year):

        day = _parse(row[1])

        if day and day >= today:

            rows.append(row)

    return rows


def working_days(year, month):
    """Weekdays (Mon-Fri) in a month, excluding holidays."""

    days_in_month = calendar.monthrange(year, month)[1]

    skip = holiday_dates(year)

    count = 0

    for day in range(1, days_in_month + 1):

        current = datetime.date(year, month, day)

        if (
            current.weekday() < 5
            and current.isoformat() not in skip
        ):

            count += 1

    return count


def upcoming_holidays(today=None, limit=6):
    """Next holidays on or after today as (date, name) pairs."""

    today = today or datetime.date.today()

    upcoming = []

    for _id, holiday_date, name in list_holidays():

        try:

            parsed = datetime.date.fromisoformat(str(holiday_date))

        except ValueError:

            continue

        if parsed >= today:

            upcoming.append((parsed, name))

    return upcoming[:limit]


# ---------------------------------------------------------
# SHARED RENDERING
# ---------------------------------------------------------

# Every holiday chip uses the one accent colour, so the calendar
# reads as one calm grid instead of a multi-hue rainbow. The list is
# kept so the calling code stays the same.
_ACCENTS = [
    "#16856B"
]


def _parse(value):
    """ISO date string -> date, or None when unparseable."""

    try:

        return datetime.date.fromisoformat(str(value))

    except (TypeError, ValueError):

        return None


def _nice_date(value):
    """Format an ISO date as DD Mon YYYY."""

    parsed = _parse(value)

    if parsed is None:

        return str(value)

    return parsed.strftime("%d %b %Y")


def _accent(index):
    """Accent colour for a card, cycling through the palette."""

    return _ACCENTS[index % len(_ACCENTS)]


def _status(day, today):
    """(label, colour, icon) for the badge under a holiday."""

    if day == today:

        return "Today", "green", ":material/today:"

    return "Upcoming", "violet", ":material/event_upcoming:"


def _countdown(days):
    """"Today" / "Tomorrow" / "in 5 days"."""

    if days <= 0:

        return "Today"

    if days == 1:

        return "Tomorrow"

    return f"in {days} days"


def _next_badge(rows, today):
    """Hero badge naming the next upcoming holiday."""

    if not rows:

        return "No holidays left", "event_busy"

    next_date = _parse(rows[0][1])

    if next_date is None:

        return "No holidays left", "event_busy"

    return (
        f"Next: {rows[0][2]} · {next_date.strftime('%d %b')}",
        "event_upcoming"
    )


def _summary(rows, today):
    """Three headline metrics, shared by the HR and employee pages."""

    month_rows = [
        row for row in rows
        if (_parse(row[1]) or today).month == today.month
    ]

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "Upcoming holidays",
            len(rows),
            icon=":material/event_upcoming:",
            border=True,
            help=f"From today to 31 Dec {today.year}."
        )

    with col2:

        st.metric(
            "This month",
            len(month_rows),
            icon=":material/calendar_month:",
            border=True,
            help=(
                f"Remaining holidays in "
                f"{MONTHS[today.month - 1]} {today.year}."
            )
        )

    with col3:

        if rows:

            next_date = _parse(rows[0][1])

            st.metric(
                "Next holiday",
                rows[0][2],
                delta=_countdown((next_date - today).days),
                icon=":material/event:",
                border=True,
                help=f"Falls on {_nice_date(next_date)}."
            )

        else:

            st.metric(
                "Next holiday",
                "None left",
                icon=":material/event_busy:",
                border=True,
                help="No holidays left in this year."
            )


def _edit_holiday_panel(row, today):
    """Inline editor for one upcoming holiday."""

    holiday_id, holiday_date, name = row

    day = _parse(holiday_date)

    last_day = datetime.date(today.year, 12, 31)

    first_day = min(today, last_day)

    with st.container(border=True):

        st.subheader(
            "Edit holiday",
            icon=":material/edit_calendar:",
            divider=True
        )

        with st.form(f"edit_holiday_form_{holiday_id}"):

            form_col1, form_col2 = st.columns([1, 2])

            with form_col1:

                new_date = st.date_input(
                    "Holiday date",
                    value=day if day and day >= first_day else first_day,
                    min_value=first_day,
                    max_value=last_day,
                    key=f"edit_holiday_date_{holiday_id}"
                )

            with form_col2:

                new_name = st.text_input(
                    "Holiday name",
                    value=str(name),
                    key=f"edit_holiday_name_{holiday_id}"
                )

            saved = st.form_submit_button(
                "Save changes",
                icon=":material/save:",
                type="primary",
                width="stretch"
            )

        if saved:

            clean_name = new_name.strip()

            if not clean_name:

                st.error("Please enter the holiday name.")

            else:

                ok, message = update_holiday(
                    holiday_id, new_date, clean_name
                )

                if ok:

                    st.session_state.pop("holiday_edit_id", None)

                    st.session_state.holiday_flash = message

                    st.rerun()

                else:

                    st.error(message, icon=":material/error:")

        if st.button(
            "Cancel",
            key=f"cancel_edit_holiday_{holiday_id}",
            icon=":material/close:",
            type="tertiary",
            width="content"
        ):

            st.session_state.pop("holiday_edit_id", None)

            st.rerun()


def _holiday_card(row, index, today, can_manage):
    """One holiday as a colourful date-chip card."""

    holiday_id, holiday_date, name = row

    day = _parse(holiday_date)

    chip_day = day.strftime("%d") if day else "--"
    chip_mon = day.strftime("%b") if day else ""

    meta = (
        f"{day.strftime('%A')}, {day.strftime('%d %b %Y')}"
        if day else str(holiday_date)
    )

    with st.container(border=True, key=f"lift_hol_{holiday_id}"):

        st.html(
            '<div class="ait-hol">'
            f'<div class="ait-hol__chip" '
            f'style="--hol-accent:{_accent(index)}">'
            f'<span class="ait-hol__day">{chip_day}</span>'
            f'<span class="ait-hol__mon">{chip_mon}</span>'
            '</div>'
            '<div class="ait-hol__body">'
            f'<div class="ait-hol__name">'
            f'{html.escape(str(name))}</div>'
            f'<div class="ait-hol__meta">{meta}</div>'
            '</div>'
            '</div>'
        )

        if day:

            label, colour, icon = _status(day, today)

            st.badge(label, icon=icon, color=colour)

        if can_manage:

            edit_col, remove_col = st.columns(2, gap="small")

            with edit_col:

                if st.button(
                    "Edit",
                    key=f"edit_holiday_{holiday_id}",
                    icon=":material/edit:",
                    type="secondary",
                    width="stretch",
                    help=f"Edit {name}."
                ):

                    st.session_state.holiday_edit_id = holiday_id

                    st.rerun()

            with remove_col:

                if st.button(
                    "Remove",
                    key=f"del_holiday_{holiday_id}",
                    icon=":material/delete:",
                    type="tertiary",
                    width="stretch",
                    help=f"Remove {name} from the calendar."
                ):

                    st.session_state.pop("holiday_edit_id", None)

                    delete_holiday(holiday_id)

                    st.session_state.holiday_flash = f"'{name}' removed."

                    st.rerun()


def _holiday_grid(rows, today, can_manage):
    """Month-grouped grid of holiday cards."""

    groups = []

    for row in rows:

        day = _parse(row[1])

        bucket = (day.year, day.month) if day else (0, 0)

        if not groups or groups[-1][0] != bucket:

            groups.append((bucket, []))

        groups[-1][1].append(row)

    index = 0

    for (group_year, group_month), group in groups:

        title = (
            f"{MONTHS[group_month - 1]} {group_year}"
            if group_month else "Undated"
        )

        count = len(group)

        st.subheader(
            f"{title} · {count} holiday"
            + ("s" if count != 1 else ""),
            icon=":material/calendar_month:",
            divider=True
        )

        columns = st.columns(3, gap="small")

        for position, row in enumerate(group):

            with columns[position % 3]:

                _holiday_card(row, index, today, can_manage)

            index += 1


# ---------------------------------------------------------
# HR PAGE
# ---------------------------------------------------------

def show_holidays_page(go_home=None):
    """HR: maintain the holiday calendar."""

    create_holiday_tables()

    today = datetime.date.today()

    rows = _upcoming_rows(today)

    hero(
        "Holiday calendar",
        "Upcoming public and company holidays — kept out of "
        "attendance working days.",
        icon="celebration",
        badges=[
            ("Maintained by HR", "edit_calendar"),
            ("Feeds attendance", "event_busy"),
            ("Current year", "today")
        ]
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="holidays_back",
        width="content"
    ):

        st.session_state.pop("holiday_edit_id", None)

        go_home()

        st.rerun()

    flash = st.session_state.pop("holiday_flash", None)

    if flash:

        st.success(flash, icon=":material/check_circle:")

    _summary(rows, today)

    edit_id = st.session_state.get("holiday_edit_id")

    if edit_id:

        target = next(
            (row for row in rows if row[0] == edit_id),
            None
        )

        if target:

            st.space("small")

            _edit_holiday_panel(target, today)

            st.space("small")

        else:

            st.session_state.pop("holiday_edit_id", None)

    with st.expander(
        "Add a holiday",
        icon=":material/add_circle:",
        type="compact"
    ):

        with st.form("add_holiday_form", clear_on_submit=True):

            first_day = today
            last_day = datetime.date(today.year, 12, 31)

            form_col1, form_col2 = st.columns([1, 2])

            with form_col1:

                new_date = st.date_input(
                    "Holiday date",
                    value=first_day,
                    min_value=first_day,
                    max_value=last_day
                )

            with form_col2:

                new_name = st.text_input(
                    "Holiday name",
                    placeholder="e.g. Diwali, Independence Day"
                )

            saved = st.form_submit_button(
                "Add holiday",
                icon=":material/add:",
                type="primary",
                width="stretch"
            )

        if saved:

            if not new_name.strip():

                st.error("Please enter the holiday name.")

            else:

                add_holiday(new_date, new_name.strip())

                st.session_state.holiday_flash = (
                    f"'{new_name.strip()}' added on "
                    f"{_nice_date(new_date)}."
                )

                st.rerun()

    st.space("medium")

    if not rows:

        st.info(
            f"No upcoming holidays in {today.year}. "
            "Add one above to start the calendar.",
            title="No upcoming holidays",
            icon=":material/beach_access:"
        )

        return

    st.caption(
        f"{len(rows)} upcoming holiday(s) in {today.year}. "
        "Past holidays are hidden; edit or remove any upcoming one."
    )

    _holiday_grid(rows, today, can_manage=True)


# ---------------------------------------------------------
# EMPLOYEE PAGE
# ---------------------------------------------------------

def show_my_holidays():
    """Employee: read-only holiday calendar."""

    create_holiday_tables()

    today = datetime.date.today()

    rows = _upcoming_rows(today)

    hero(
        "Holidays",
        "Your company holiday calendar for the year.",
        icon="celebration",
        badges=[
            ("Read-only", "lock"),
            ("Company-wide", "groups"),
            _next_badge(rows, today)
        ]
    )

    _summary(rows, today)

    st.space("medium")

    if not rows:

        st.info(
            f"No upcoming holidays in {today.year}.",
            title="No upcoming holidays",
            icon=":material/beach_access:"
        )

        return

    st.caption(
        f"{len(rows)} upcoming holiday(s) in {today.year}. "
        "Holidays are never counted as working days."
    )

    _holiday_grid(rows, today, can_manage=False)
