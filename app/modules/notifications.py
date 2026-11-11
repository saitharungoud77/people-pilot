"""In-app notifications — the bell in the sidebar.

Every "something happened" moment (a leave request is filed, a
payslip is generated, a salary is revised) drops a short message into
the ``notifications`` table for the person who should hear about it:

* HR has one shared inbox (``recipient = "hr"``).
* Each employee has their own inbox (``recipient = employee_id``).

The sidebar draws a **Notifications** button with a count of unread
messages; opening it lists the recent messages and lets the reader
mark them all as read. Other modules only ever call ``notify_hr`` /
``notify_employee`` — they never touch the table directly.
"""

import datetime

import streamlit as st

from database.connection import get_connection


# ============================================================
# SETTINGS
# ============================================================

# The HR inbox is shared by every HR user.
HR_INBOX = "hr"

# How many messages the popover shows.
LIST_LIMIT = 20

# A small icon per category.
_CATEGORY_ICONS = {
    "Leave": ":material/event_available:",
    "Payslip": ":material/receipt_long:",
    "Salary": ":material/trending_up:",
    "Tax": ":material/request_quote:",
    "Asset": ":material/devices:",
    "Project": ":material/work:",
    "Reimbursement": ":material/upload_file:",
    "Message": ":material/chat:",
    "System": ":material/notifications:",
}


# ============================================================
# WHO OWNS AN INBOX
# ============================================================

def recipient_for(user):
    """The inbox key for a signed-in user."""

    if not user:

        return HR_INBOX

    if user.get("role") == "hr":

        return HR_INBOX

    return user.get("employee_id") or HR_INBOX


# ============================================================
# WRITING NOTIFICATIONS
# ============================================================

def notify(recipient, title, message="", category="System", page=""):
    """Add one notification to an inbox."""

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    connection = get_connection()

    try:

        connection.execute(
            """
            INSERT INTO notifications
                (
                    recipient,
                    title,
                    message,
                    category,
                    page,
                    is_read,
                    created_at
                )
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (recipient, title, message, category, page, stamp)
        )

        connection.commit()

    finally:

        connection.close()


def notify_hr(title, message="", category="System", page=""):
    """Send a notification to the HR inbox."""

    notify(HR_INBOX, title, message, category, page)


def notify_employee(employee_id, title, message="", category="System", page=""):
    """Send a notification to one employee's inbox."""

    if not employee_id:

        return

    notify(employee_id, title, message, category, page)


# ============================================================
# READING NOTIFICATIONS
# ============================================================

def get_notifications(recipient, limit=LIST_LIMIT):
    """Recent notifications for an inbox, newest first."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT id, title, message, category, page, is_read, created_at
            FROM notifications
            WHERE recipient = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (recipient, limit)
        ).fetchall()

    finally:

        connection.close()

    keys = [
        "id",
        "title",
        "message",
        "category",
        "page",
        "is_read",
        "created_at"
    ]

    return [dict(zip(keys, row)) for row in rows]


def unread_count(recipient):
    """How many unread notifications an inbox holds."""

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM notifications
            WHERE recipient = ? AND is_read = 0
            """,
            (recipient,)
        ).fetchone()

    finally:

        connection.close()

    return row[0] if row else 0


def mark_read(notification_id):
    """Flag one notification as read."""

    connection = get_connection()

    try:

        connection.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ?",
            (notification_id,)
        )

        connection.commit()

    finally:

        connection.close()


def mark_all_read(recipient):
    """Flag every notification in an inbox as read."""

    connection = get_connection()

    try:

        connection.execute(
            """
            UPDATE notifications
            SET is_read = 1
            WHERE recipient = ? AND is_read = 0
            """,
            (recipient,)
        )

        connection.commit()

    finally:

        connection.close()


def clear_all(recipient):
    """Delete every notification in an inbox."""

    connection = get_connection()

    try:

        connection.execute(
            "DELETE FROM notifications WHERE recipient = ?",
            (recipient,)
        )

        connection.commit()

    finally:

        connection.close()


# ============================================================
# TIME LABELS
# ============================================================

def _time_ago(stamp):
    """Turn a stored timestamp into "5 min ago" style text."""

    try:

        when = datetime.datetime.strptime(
            str(stamp)[:19],
            "%Y-%m-%d %H:%M:%S"
        )

    except (TypeError, ValueError):

        return ""

    seconds = int((datetime.datetime.now() - when).total_seconds())

    if seconds < 60:

        return "just now"

    minutes = seconds // 60

    if minutes < 60:

        return f"{minutes} min ago"

    hours = minutes // 60

    if hours < 24:

        return "1 hour ago" if hours == 1 else f"{hours} hours ago"

    days = hours // 24

    if days == 1:

        return "yesterday"

    if days < 7:

        return f"{days} days ago"

    return when.strftime("%d %b %Y")


# ============================================================
# THE SIDEBAR BELL
# ============================================================

def _render_note(note):
    """One line of the list: icon, title, message and age."""

    unread = not note["is_read"]

    icon = _CATEGORY_ICONS.get(
        note["category"],
        ":material/notifications:"
    )

    if unread:

        st.markdown(f"{icon} **{note['title']}**")

    else:

        st.markdown(f"{icon} {note['title']}")

    age = _time_ago(note["created_at"])

    caption = note["message"]

    if age:

        caption = f"{caption}  ·  {age}" if caption else age

    if caption:

        st.caption(caption)


def render_notifications(user):
    """Draw the bell button and its popover of messages."""

    recipient = recipient_for(user)

    count = unread_count(recipient)

    label = (
        f"Notifications · {count} new"
        if count
        else "Notifications"
    )

    with st.popover(
        label,
        icon=":material/notifications:"
    ):

        notes = get_notifications(recipient)

        if not notes:

            st.caption("You're all caught up — nothing new.")

            return

        for note in notes:

            _render_note(note)

        st.divider()

        col1, col2 = st.columns(2)

        with col1:

            if st.button(
                "Mark all read",
                key=f"notif_read_{recipient}",
                disabled=count == 0,
                width="stretch"
            ):

                mark_all_read(recipient)

                st.rerun()

        with col2:

            if st.button(
                "Clear",
                key=f"notif_clear_{recipient}",
                width="stretch"
            ):

                clear_all(recipient)

                st.rerun()
