import datetime

import streamlit as st

from database.connection import (
    get_connection,
    create_reimbursement_table
)

from modules.bill_reader import ai_available, read_bill

from modules.leave import list_employees

from modules.notifications import notify_employee, notify_hr
from modules.request_tracking import record_request_event

from modules.session import require_employee

from modules.theme import hero


# ============================================================
# REIMBURSEMENTS (EMPLOYEE BILLS)
# ============================================================
# Employees upload a bill they paid out of pocket (travel, food,
# internet, medical...); HR reviews the claim against the receipt,
# approves or rejects it, then marks the approved one as paid.
#
# The uploaded file is kept as a BLOB in the row itself, the same
# way the employee photo and the Form 16 PDF are stored, so a claim
# can never lose its proof.
#
# A reimbursement is deliberately NOT part of the salary structure.
# It is a separate settlement, so approving one never silently
# changes a payslip.

# Plain Material Symbols ligature names - Streamlit does not expand
# ":material/..." shortcodes inside st.html, so the chip is given the
# bare icon name and the Material font draws it.
CATEGORY_ICONS = {
    "Travel": "flight",
    "Food": "restaurant",
    "Accommodation": "hotel",
    "Internet": "wifi",
    "Phone": "phone_iphone",
    "Medical": "health_and_safety",
    "Training": "school",
    "Office supplies": "edit_note",
    "Client entertainment": "celebration",
    "Other": "receipt_long"
}

REIMBURSEMENT_CATEGORIES = list(CATEGORY_ICONS.keys())

STATUS_COLORS = {
    "Pending": "orange",
    "Needs information": "yellow",
    "Approved": "green",
    "Rejected": "red",
    "Paid": "violet",
    "Cancelled": "gray"
}

REIMBURSEMENT_STATUSES = list(STATUS_COLORS.keys())

# Statuses that remain open for HR or employee action.
OPEN_STATUSES = ("Pending", "Needs information", "Approved")

# Bills come in as a photo or a PDF, and only up to a sensible size.
ALLOWED_TYPES = ("pdf", "png", "jpg", "jpeg")

MAX_SIZE_MB = 8

MAX_SIZE_BYTES = MAX_SIZE_MB * 1024 * 1024

# Every chip uses the one accent colour, so a busy list stays calm.
_ACCENTS = [
    "#47765E"
]

_FIELDS = [
    "id",
    "employee_id",
    "category",
    "amount",
    "expense_date",
    "description",
    "status",
    "file_name",
    "mime",
    "size_bytes",
    "data",
    "submitted_at",
    "decided_at",
    "decided_by",
    "decision_note",
    "employee_reply",
    "paid_on",
    "created_at"
]

# Columns the UI is allowed to change (never ``data`` by accident).
_EDITABLE = [
    "category",
    "amount",
    "expense_date",
    "description",
    "status",
    "file_name",
    "mime",
    "size_bytes",
    "data",
    "decided_at",
    "decided_by",
    "decision_note",
    "employee_reply",
    "paid_on"
]


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def _now():
    """Local timestamp, matching the notifications table."""

    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse(value):
    """ISO date string -> date, or None when unparseable."""

    try:

        return datetime.date.fromisoformat(str(value))

    except (TypeError, ValueError):

        return None


def _stamp_date(value):
    """'2026-10-16 15:32:11' -> '16 Oct 2026' (timestamps, not dates)."""

    return _nice_date(str(value)[:10])


def _nice_date(value):
    """'2026-10-01' -> '01 Oct 2026'; anything else passes through."""

    day = _parse(value)

    return day.strftime("%d %b %Y") if day else (str(value) if value else "")


def _rupees(value):
    """'₹ 10,500.00' — the app's money format everywhere."""

    try:

        return f"₹ {float(value):,.2f}"

    except (TypeError, ValueError):

        return "₹ 0.00"


def _human_size(size):
    """81234 -> '79 KB'."""

    try:

        size = float(size or 0)

    except (TypeError, ValueError):

        size = 0

    if size >= 1024 * 1024:

        return f"{size / (1024 * 1024):.1f} MB"

    if size >= 1024:

        return f"{size / 1024:.0f} KB"

    return f"{int(size)} B"


def _accent(index):
    return _ACCENTS[index % len(_ACCENTS)]


def _icon(category):
    return CATEGORY_ICONS.get(category, "receipt_long")


def _employee_names():
    """{employee_id: name} for labelling claimants."""

    return {employee_id: name for employee_id, name in list_employees()}


def _employee_name(claim, names):
    """Human name for a claim's owner."""

    employee_id = claim["employee_id"]

    return names.get(employee_id, employee_id)


def html_escape(value):
    """Minimal HTML escaping for values dropped into a card."""

    text = str(value)

    for char, replacement in (
        ("&", "&amp;"),
        ("<", "&lt;"),
        (">", "&gt;"),
    ):

        text = text.replace(char, replacement)

    return text


# ---------------------------------------------------------
# DATA
# ---------------------------------------------------------

def create_reimbursement_tables():

    create_reimbursement_table()


def _row_to_dict(row):

    return dict(zip(_FIELDS, row))


def list_reimbursements(employee_id=None, status=None):
    """Claims as dicts, newest first, optionally filtered."""

    query = (
        "SELECT " + ", ".join(_FIELDS)
        + " FROM reimbursements WHERE 1 = 1"
    )

    params = []

    if employee_id is not None:

        query += " AND employee_id = ?"

        params.append(employee_id)

    if status is not None:

        query += " AND status = ?"

        params.append(status)

    query += " ORDER BY id DESC"

    connection = get_connection()

    try:

        rows = connection.execute(query, params).fetchall()

    finally:

        connection.close()

    return [_row_to_dict(row) for row in rows]


def get_reimbursement(claim_id):
    """One claim as a dict (including its file bytes), or None."""

    connection = get_connection()

    try:

        row = connection.execute(
            "SELECT " + ", ".join(_FIELDS)
            + " FROM reimbursements WHERE id = ?",
            (claim_id,)
        ).fetchone()

    finally:

        connection.close()

    return _row_to_dict(row) if row else None


def get_reimbursement_file(claim_id):
    """Just the stored bill file, or None when there is nothing."""

    claim = get_reimbursement(claim_id)

    if not claim or not claim["data"]:

        return None

    return claim["data"]


def employee_reimbursements(employee_id):
    """Every claim an employee has filed, newest first."""

    return list_reimbursements(employee_id=employee_id)


def reimbursement_summary(employee_id=None):
    """Counts and amounts per status, ready for the headline metrics."""

    claims = list_reimbursements(employee_id=employee_id)

    counts = {status: 0 for status in REIMBURSEMENT_STATUSES}

    amounts = {status: 0.0 for status in REIMBURSEMENT_STATUSES}

    for claim in claims:

        counts[claim["status"]] = counts.get(claim["status"], 0) + 1

        amounts[claim["status"]] = (
            amounts.get(claim["status"], 0.0) + (claim["amount"] or 0)
        )

    counts["Total"] = len(claims)

    amounts["Total"] = sum(amounts[status] for status in REIMBURSEMENT_STATUSES)

    return {"counts": counts, "amounts": amounts}


def submit_reimbursement(
    employee_id,
    category,
    amount,
    expense_date,
    description,
    uploaded
):
    """File a new claim with its bill. Returns the new id.

    Raises ValueError with a message meant for the person filling in
    the form.
    """

    amount = float(amount or 0)

    if amount <= 0:

        raise ValueError("Please enter the amount you are claiming.")

    if uploaded is None:

        raise ValueError(
            f"Please attach the bill (a PDF or photo, "
            f"up to {MAX_SIZE_MB} MB)."
        )

    name = (getattr(uploaded, "name", "") or "bill").strip()

    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""

    if extension not in ALLOWED_TYPES:

        raise ValueError(
            "That file type is not accepted. "
            "Please upload a PDF, PNG or JPG."
        )

    data = uploaded.getvalue()

    if not data:

        raise ValueError("That file is empty — please attach the bill again.")

    if len(data) > MAX_SIZE_BYTES:

        raise ValueError(
            f"That file is {_human_size(len(data))}. "
            f"The limit is {MAX_SIZE_MB} MB."
        )

    mime = getattr(uploaded, "type", "") or ""

    if not mime:

        mime = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg"
        }.get(extension, "application/octet-stream")

    stamp = _now()

    connection = get_connection()

    try:

        connection.execute(
            """
            INSERT INTO reimbursements
                (
                    employee_id,
                    category,
                    amount,
                    expense_date,
                    description,
                    status,
                    file_name,
                    mime,
                    size_bytes,
                    data,
                    submitted_at,
                    created_at
                )
            VALUES (?, ?, ?, ?, ?, 'Pending', ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                category,
                amount,
                str(expense_date),
                (description or "").strip(),
                name,
                mime,
                len(data),
                data,
                stamp,
                stamp
            )
        )

        claim_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]

        connection.commit()

    finally:

        connection.close()

    notify_hr(
        "New reimbursement claim",
        f"{employee_id} — {category}, {_rupees(amount)} "
        f"spent on {_nice_date(expense_date)}.",
        category="Reimbursement",
        page="reimbursements"
    )
    record_request_event(
        "Reimbursement",
        claim_id,
        employee_id,
        "Pending",
        actor=employee_id,
        comment=description
    )

    return claim_id


def _update_claim(claim_id, **values):
    """Update the given columns of one claim."""

    columns = [key for key in values if key in _EDITABLE]

    if not columns:

        return

    assignments = ", ".join(f"{column} = ?" for column in columns)

    params = [values[column] for column in columns] + [claim_id]

    connection = get_connection()

    try:

        connection.execute(
            f"UPDATE reimbursements SET {assignments} WHERE id = ?",
            params
        )

        connection.commit()

    finally:

        connection.close()


def approve_reimbursement(claim_id, decided_by="", note=""):
    """HR approves a claim. Employees are told."""

    claim = get_reimbursement(claim_id)

    if not claim:

        return

    _update_claim(
        claim_id,
        status="Approved",
        decided_at=_now(),
        decided_by=decided_by,
        decision_note=(note or "").strip()
    )
    record_request_event(
        "Reimbursement",
        claim_id,
        claim["employee_id"],
        "Approved",
        actor=decided_by,
        comment=note
    )

    notify_employee(
        claim["employee_id"],
        "Reimbursement approved",
        f"Your {claim['category']} claim of "
        f"{_rupees(claim['amount'])} was approved"
        + (f" — {note.strip()}." if note and note.strip() else "."),
        category="Reimbursement",
        page="reimbursements"
    )


def reject_reimbursement(claim_id, decided_by="", note=""):
    """HR rejects a claim. Employees are told, with the reason."""

    claim = get_reimbursement(claim_id)

    if not claim:

        return

    _update_claim(
        claim_id,
        status="Rejected",
        decided_at=_now(),
        decided_by=decided_by,
        decision_note=(note or "").strip()
    )
    record_request_event(
        "Reimbursement",
        claim_id,
        claim["employee_id"],
        "Rejected",
        actor=decided_by,
        comment=note
    )

    notify_employee(
        claim["employee_id"],
        "Reimbursement rejected",
        f"Your {claim['category']} claim of "
        f"{_rupees(claim['amount'])} was rejected"
        + (f" — {note.strip()}." if note and note.strip() else "."),
        category="Reimbursement",
        page="reimbursements"
    )


def request_reimbursement_information(claim_id, decided_by="", note=""):
    """Ask the employee for more information about a claim."""

    note = (note or "").strip()
    if not note:
        raise ValueError("Add a note describing the information needed.")

    claim = get_reimbursement(claim_id)
    if not claim or claim["status"] not in ("Pending", "Needs information"):
        return False

    _update_claim(
        claim_id,
        status="Needs information",
        decided_at=_now(),
        decided_by=decided_by,
        decision_note=note,
        employee_reply=""
    )
    record_request_event(
        "Reimbursement",
        claim_id,
        claim["employee_id"],
        "Needs information",
        actor=decided_by,
        comment=note
    )
    notify_employee(
        claim["employee_id"],
        "Reimbursement needs information",
        f"HR needs more information for your {claim['category']} claim "
        f"of {_rupees(claim['amount'])}. Note: {note}",
        category="Reimbursement",
        page="reimbursements"
    )
    return True


def reply_to_reimbursement(claim_id, employee_id, reply):
    """Employee responds to an information request on their own claim."""

    reply = (reply or "").strip()
    if not reply:
        raise ValueError("Enter a response before submitting.")

    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE reimbursements
            SET employee_reply = ?,
                status = 'Pending',
                decided_at = '',
                decided_by = ''
            WHERE id = ?
              AND employee_id = ?
              AND status = 'Needs information'
            """,
            (reply, claim_id, employee_id)
        )
        connection.commit()
        updated = cursor.rowcount > 0
    finally:
        connection.close()

    if updated:
        record_request_event(
            "Reimbursement",
            claim_id,
            employee_id,
            "Pending",
            actor=employee_id,
            comment=reply
        )
        notify_hr(
            "Employee responded to reimbursement request",
            f"{employee_id} replied to reimbursement claim "
            f"#{claim_id}: {reply}",
            category="Reimbursement",
            page="reimbursements"
        )

    return updated


def reopen_reimbursement(claim_id):
    """Put a decided claim back in the queue."""

    claim = get_reimbursement(claim_id)
    if not claim:
        return

    _update_claim(
        claim_id,
        status="Pending",
        decided_at="",
        decided_by="",
        decision_note="",
        paid_on=""
    )
    record_request_event(
        "Reimbursement",
        claim_id,
        claim["employee_id"],
        "Pending",
        actor="HR",
        comment="Reopened for review."
    )


def undo_approval(claim_id):
    """Take back an approval before it is paid."""

    reopen_reimbursement(claim_id)


def mark_paid(claim_id, paid_on=None):
    """HR records that the money has gone out."""

    paid_on = str(paid_on or datetime.date.today())

    claim = get_reimbursement(claim_id)

    if not claim:

        return

    _update_claim(claim_id, status="Paid", paid_on=paid_on)
    record_request_event(
        "Reimbursement",
        claim_id,
        claim["employee_id"],
        "Paid",
        actor="HR",
        comment=f"Paid on {paid_on}."
    )

    notify_employee(
        claim["employee_id"],
        "Reimbursement paid",
        f"{_rupees(claim['amount'])} for your {claim['category']} claim "
        f"was paid on {_nice_date(paid_on)}.",
        category="Reimbursement",
        page="reimbursements"
    )


def withdraw_reimbursement(claim_id):
    """An employee cancels one of their own claims, while pending."""

    claim = get_reimbursement(claim_id)

    if not claim or claim["status"] != "Pending":

        return False

    _update_claim(claim_id, status="Cancelled")
    record_request_event(
        "Reimbursement",
        claim_id,
        claim["employee_id"],
        "Cancelled",
        actor=claim["employee_id"],
        comment="Employee withdrew the claim."
    )

    return True


def delete_reimbursement(claim_id):
    """Remove a claim and its stored bill."""

    connection = get_connection()

    try:

        connection.execute(
            "DELETE FROM reimbursements WHERE id = ?",
            (claim_id,)
        )

        connection.commit()

    finally:

        connection.close()


# ---------------------------------------------------------
# RENDERING HELPERS
# ---------------------------------------------------------

def _summary_metrics(employee_id=None):
    """Headline figures for the page."""

    summary = reimbursement_summary(employee_id)

    counts = summary["counts"]

    amounts = summary["amounts"]

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "Total claims",
            counts["Total"],
            icon=":material/upload_file:",
            border=True,
            help="Every bill submitted so far."
        )

    with col2:

        st.metric(
            "Pending",
            counts["Pending"],
            icon=":material/hourglass_top:",
            border=True,
            help="Waiting for HR to review."
        )

    with col3:

        st.metric(
            "Awaiting payment",
            _rupees(amounts["Approved"]),
            icon=":material/pending_actions:",
            border=True,
            help="Approved claims that have not been paid yet."
        )

    with col4:

        st.metric(
            "Reimbursed",
            _rupees(amounts["Paid"]),
            icon=":material/paid:",
            border=True,
            help="Money already paid back to employees."
        )


def _bill_chip(claim, index, headline, meta):
    """The shared coloured-icon header of a claim card."""

    st.html(
        '<div class="ait-bill">'
        f'<div class="ait-bill__chip" '
        f'style="--bill-accent:{_accent(index)}">'
        f'{_icon(claim["category"])}</div>'
        '<div class="ait-bill__body">'
        f'<div class="ait-bill__name">{html_escape(headline)}</div>'
        f'<div class="ait-bill__meta">{html_escape(meta)}</div>'
        '</div>'
        '</div>'
    )


def _download(claim, key):
    """A download button for the stored bill, when there is one."""

    if not claim["data"]:

        st.caption("No bill file attached.")

        return

    st.download_button(
        "Download bill",
        data=claim["data"],
        file_name=claim["file_name"] or f"bill-{claim['id']}.pdf",
        mime=claim["mime"] or "application/pdf",
        key=key,
        icon=":material/download:",
        width="stretch",
        help=f"{claim['file_name']} · {_human_size(claim['size_bytes'])}"
    )


def _claim_card(claim, index, names, can_manage):
    """One claim as a card. HR gets the decision controls."""

    meta_bits = [claim["category"], _nice_date(claim["expense_date"])]

    meta = " · ".join(meta_bits)

    headline = (
        f"{_employee_name(claim, names)} · {_rupees(claim['amount'])}"
        if can_manage
        else _rupees(claim["amount"])
    )

    with st.container(border=True, key=f"lift_bill_{claim['id']}"):

        _bill_chip(claim, index, headline, meta)

        st.badge(
            claim["status"],
            color=STATUS_COLORS.get(claim["status"], "gray")
        )

        caption_bits = []

        if can_manage:

            caption_bits.append(claim["employee_id"])

        caption_bits.append(f"submitted {_stamp_date(claim['submitted_at'])}")

        if not can_manage and claim["status"] == "Pending":

            caption_bits.append("awaiting HR review")

        elif not can_manage and claim["status"] == "Needs information":

            caption_bits.append("response needed from you")

        if claim["status"] == "Paid" and claim["paid_on"]:

            caption_bits.append(f"paid {_nice_date(claim['paid_on'])}")

        if claim["decided_at"]:

            caption_bits.append(f"decided by {claim['decided_by'] or 'HR'}")

        st.caption(" · ".join(caption_bits))

        if claim["description"]:

            st.caption(claim["description"])

        if claim["decision_note"]:

            st.caption(f"Note: {claim['decision_note']}")

        if claim.get("employee_reply"):

            st.caption(f"Employee response: {claim['employee_reply']}")

        _download(claim, key=f"bill_dl_{claim['id']}")

        if can_manage:

            _hr_controls(claim)

        elif claim["status"] == "Needs information":

            with st.form(f"bill_reply_{claim['id']}"):
                reply = st.text_area(
                    "Reply to HR",
                    key=f"bill_reply_text_{claim['id']}"
                )
                submitted = st.form_submit_button("Send response")
            if submitted:
                try:
                    updated = reply_to_reimbursement(
                        claim["id"],
                        claim["employee_id"],
                        reply
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    if updated:
                        st.success("Your response was sent to HR.")
                        st.rerun()
                    st.warning(
                        "This claim is no longer awaiting information."
                    )

        elif claim["status"] == "Pending":

            if st.button(
                "Withdraw",
                key=f"bill_withdraw_{claim['id']}",
                icon=":material/cancel:",
                type="tertiary",
                width="stretch",
                help="Cancel this claim while it is still pending."
            ):

                withdraw_reimbursement(claim["id"])

                st.session_state.bill_flash = "Claim withdrawn."

                st.rerun()


def _hr_controls(claim):
    """Approve / pay / reject / delete, sized to the claim's state."""

    status = claim["status"]

    with st.form(f"bill_decide_{claim['id']}", clear_on_submit=True):

        note = st.text_input(
            "Note",
            key=f"bill_note_{claim['id']}",
            placeholder="Optional — the employee sees this"
        )

        col1, col2, col3 = st.columns(3)

        with col1:

            if status in ("Pending", "Needs information"):

                approve = st.form_submit_button(
                    "Approve",
                    icon=":material/check_circle:",
                    type="primary",
                    width="stretch"
                )

                reject = False

            elif status == "Approved":

                approve = st.form_submit_button(
                    "Mark paid",
                    icon=":material/paid:",
                    type="primary",
                    width="stretch"
                )

                reject = False

            elif status == "Rejected":

                approve = st.form_submit_button(
                    "Reopen",
                    icon=":material/replay:",
                    width="stretch"
                )

                reject = False

            else:

                approve = reject = False

        with col2:

            if status in ("Pending", "Needs information"):

                reject = st.form_submit_button(
                    "Reject",
                    icon=":material/cancel:",
                    width="stretch"
                )

            elif status == "Approved":

                reject = st.form_submit_button(
                    "Undo",
                    icon=":material/replay:",
                    width="stretch"
                )

            else:

                reject = False

        with col3:

            request_info = (
                st.form_submit_button(
                    "Need info",
                    icon=":material/help:",
                    width="stretch"
                )
                if status in ("Pending", "Needs information")
                else False
            )

    decided = None

    if approve:

        decided = "approve"

    elif reject:

        decided = "reject"

    if decided == "approve":

        if status in ("Pending", "Needs information"):

            approve_reimbursement(claim["id"], decided_by="HR", note=note)

            st.session_state.bill_flash = (
                f"{_employee_name(claim, _employee_names())}'s "
                f"claim of {_rupees(claim['amount'])} approved."
            )

        elif status == "Approved":

            mark_paid(claim["id"])

            st.session_state.bill_flash = (
                f"{_rupees(claim['amount'])} marked as paid."
            )

        else:

            reopen_reimbursement(claim["id"])

            st.session_state.bill_flash = "Claim reopened."

        st.rerun()

    if decided == "reject" and status in ("Pending", "Needs information"):

        reject_reimbursement(claim["id"], decided_by="HR", note=note)

        st.session_state.bill_flash = (
            f"{_employee_name(claim, _employee_names())}'s claim rejected."
        )

        st.rerun()

    if request_info:

        try:
            request_reimbursement_information(
                claim["id"],
                decided_by="HR",
                note=note
            )
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state.bill_flash = (
                f"More information requested from "
                f"{_employee_name(claim, _employee_names())}."
            )
            st.rerun()

    if decided == "reject" and status == "Approved":

        undo_approval(claim["id"])

        st.session_state.bill_flash = "Approval undone."

        st.rerun()

    # HR can delete any claim — including a duplicate or a pending
    # one they do not want to process — so this is not status-gated.
    if st.button(
        "Remove",
        key=f"bill_delete_{claim['id']}",
        icon=":material/delete:",
        type="tertiary",
        width="stretch",
        help="Delete this claim and its bill file."
    ):

        delete_reimbursement(claim["id"])

        st.session_state.bill_flash = "Claim removed."

        st.rerun()


def _claim_grid(claims, names, can_manage):
    """Three-column grid of claim cards."""

    columns = st.columns(3, gap="small")

    for index, claim in enumerate(claims):

        with columns[index % 3]:

            _claim_card(claim, index, names, can_manage)


def _filters(claims, names):
    """Status / employee / search controls. Returns the visible rows."""

    col1, col2, col3 = st.columns([2, 2, 3])

    with col1:

        status = st.selectbox(
            "Status",
            ["All"] + REIMBURSEMENT_STATUSES,
            key="bill_filter_status"
        )

    with col2:

        employee_options = ["All"] + [
            f"{names.get(eid, eid)} ({eid})"
            for eid in sorted({c["employee_id"] for c in claims})
        ]

        employee = st.selectbox(
            "Employee",
            employee_options,
            key="bill_filter_employee"
        )

    with col3:

        search = st.text_input(
            "Search",
            key="bill_filter_search",
            placeholder="Category or description"
        ).strip().lower()

    visible = []

    for claim in claims:

        if status != "All" and claim["status"] != status:

            continue

        if employee != "All":

            eid = claim["employee_id"]

            if employee != f"{names.get(eid, eid)} ({eid})":

                continue

        if search:

            haystack = " ".join(
                str(claim[key]) for key in ("category", "description")
            ).lower()

            if search not in haystack:

                continue

        visible.append(claim)

    return visible


# ---------------------------------------------------------
# HR PAGE
# ---------------------------------------------------------

def show_reimbursements_page(go_home=None):
    """HR: review, approve and settle employee bills."""

    create_reimbursement_tables()

    hero(
        "Reimbursements",
        "Bills employees paid out of their own pocket — review the "
        "claim against the receipt, approve it, then mark it as paid.",
        icon="upload_file",
        badges=[
            ("Uploaded by employees", "upload_file"),
            ("Approved by HR", "check_circle"),
            ("Bills kept on file", "folder")
        ]
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="bills_back",
        width="content"
    ):

        go_home()

        st.rerun()

    flash = st.session_state.pop("bill_flash", None)

    if flash:

        st.success(flash, icon=":material/check_circle:")

    claims = list_reimbursements()

    names = _employee_names()

    _summary_metrics()

    st.space("medium")

    if not claims:

        st.info(
            "No reimbursement claims yet. Employees upload their bills "
            "from \"My reimbursements\".",
            title="Nothing to review",
            icon=":material/upload_file:"
        )

        return

    st.caption(
        f"{len(claims)} claim(s). Use the filters to narrow the list, "
        "then approve, pay or reject."
    )

    visible = _filters(claims, names)

    if not visible:

        st.info(
            "No claims match these filters.",
            icon=":material/search_off:"
        )

        return

    _claim_grid(visible, names, can_manage=True)


# ---------------------------------------------------------
# EMPLOYEE PAGE
# ---------------------------------------------------------

def show_my_reimbursements():
    """Employee: upload a bill and follow their own claims."""

    employee = require_employee()

    if employee is None:

        return

    employee_id = employee["employee_id"]

    create_reimbursement_tables()

    hero(
        "My reimbursements",
        "Upload a bill you paid yourself and HR will settle it.",
        icon="upload_file",
        badges=[
            ("Upload a bill", "upload_file"),
            ("HR reviews it", "support_agent"),
            ("Paid back to you", "paid")
        ]
    )

    flash = st.session_state.pop("bill_flash", None)

    if flash:

        st.success(flash, icon=":material/check_circle:")

    claims = employee_reimbursements(employee_id)

    _summary_metrics(employee_id)

    st.space("medium")

    with st.expander(
        "Upload a bill",
        icon=":material/upload_file:",
        type="compact"
    ):

        _upload_form(employee_id)

    st.space("medium")

    if not claims:

        st.info(
            "You have not claimed anything yet. Upload your first bill "
            "above — travel, food, internet and more.",
            title="No claims yet",
            icon=":material/upload_file:"
        )

        return

    st.caption(
        f"{len(claims)} claim(s) so far. "
        "A pending claim can still be withdrawn."
    )

    _claim_grid(claims, _employee_names(), can_manage=False)


def _scan_summary(scan):
    """One line describing what the AI read from the bill."""

    bits = []

    if scan.get("vendor"):

        bits.append(scan["vendor"])

    if scan.get("amount"):

        bits.append(_rupees(scan["amount"]))

    if scan.get("date"):

        bits.append(_nice_date(scan["date"]))

    if scan.get("category"):

        bits.append(scan["category"])

    return " · ".join(bits)


def _scan_description(scan):
    """Turn the AI fields into a tidy claim description."""

    vendor = (scan.get("vendor") or "").strip()

    summary = (scan.get("description") or "").strip()

    parts = []

    if vendor and vendor.lower() not in summary.lower():

        parts.append(vendor)

    if summary:

        parts.append(summary)

    if scan.get("bill_no"):

        parts.append(f"Bill {scan['bill_no']}")

    return " — ".join(parts)


def _upload_form(employee_id):
    """Upload a bill, let AI fill the claim, then submit."""

    version = st.session_state.get("bill_form_version", 0)

    scanned = st.session_state.get("bill_scan") or {}

    scanned_name = st.session_state.get("bill_scan_name", "")

    available, _reason = ai_available()

    st.caption(
        "Upload the bill and let AI fill the form — then check the "
        "numbers before submitting."
        if available
        else "Upload the bill and fill in the details below."
    )

    uploaded = st.file_uploader(
        "Bill / receipt",
        type=list(ALLOWED_TYPES),
        help=f"A PDF or photo of the bill, up to {MAX_SIZE_MB} MB.",
        key=f"bill_file_{version}"
    )

    # A scan only describes the file it was made from.
    if scanned and uploaded is not None and uploaded.name != scanned_name:

        scanned = {}

        st.info("That is a different file — click Read bill with AI again.")

    if available and st.button(
        "Read bill with AI",
        key=f"bill_read_{version}",
        disabled=uploaded is None
    ):

        with st.spinner("Reading the bill…"):

            try:

                bill = read_bill(uploaded, REIMBURSEMENT_CATEGORIES)

            except ValueError as error:

                st.error(str(error))

            except Exception as error:  # noqa: BLE001

                st.error(f"AI could not read this bill: {error}")

            else:

                st.session_state.bill_scan = bill

                st.session_state.bill_scan_name = uploaded.name

                st.rerun()

    if scanned:

        summary = _scan_summary(scanned)

        if scanned.get("confidence", 0) >= 0.5:

            st.success(
                f"AI read: {summary}",
                icon=":material/check_circle:"
            )

        else:

            st.warning(
                f"AI read: {summary}. The bill was hard to read — "
                "please double-check the amount and date.",
                icon=":material/warning:"
            )

        if scanned.get("gst_amount"):

            st.caption(
                f"GST on the bill: {_rupees(scanned['gst_amount'])} "
                "(already included in the total)."
            )

        if st.button(
            "Clear the AI values",
            key=f"bill_clear_{version}"
        ):

            st.session_state.pop("bill_scan", None)

            st.session_state.pop("bill_scan_name", None)

            st.session_state.bill_form_version = version + 1

            st.rerun()

    default_date = datetime.date.today()

    if scanned.get("date"):

        try:

            default_date = datetime.date.fromisoformat(scanned["date"])

        except ValueError:

            pass

    default_category = (
        scanned.get("category")
        if scanned.get("category") in REIMBURSEMENT_CATEGORIES
        else REIMBURSEMENT_CATEGORIES[0]
    )

    with st.form(
        f"bill_upload_form_{version}",
        clear_on_submit=True
    ):

        col1, col2 = st.columns(2)

        with col1:

            category = st.selectbox(
                "Category",
                REIMBURSEMENT_CATEGORIES,
                index=REIMBURSEMENT_CATEGORIES.index(default_category),
                key=f"bill_category_{version}"
            )

            amount = st.number_input(
                "Amount",
                min_value=0.0,
                step=100.0,
                format="%.2f",
                value=float(scanned.get("amount") or 0.0),
                placeholder="0.00",
                key=f"bill_amount_{version}"
            )

        with col2:

            expense_date = st.date_input(
                "Expense date",
                value=default_date,
                key=f"bill_date_{version}"
            )

            st.caption(
                f"Bill attached above · up to {MAX_SIZE_MB} MB"
            )

        description = st.text_area(
            "What was this for?",
            value=_scan_description(scanned),
            placeholder="e.g. Cab to the client site in Hi-Tech City",
            key=f"bill_description_{version}"
        )

        saved = st.form_submit_button(
            "Submit claim",
            icon=":material/upload_file:",
            type="primary",
            width="stretch"
        )

    if not saved:

        return

    try:

        claim_id = submit_reimbursement(
            employee_id,
            category,
            amount,
            expense_date,
            description,
            uploaded
        )

    except ValueError as error:

        st.error(str(error))

        return

    claim = get_reimbursement(claim_id)

    st.session_state.bill_flash = (
        f"Claim submitted — {_rupees(claim['amount'])} for "
        f"{claim['category']}. HR will review it."
    )

    # Start a fresh form with a new uploader, so the same bill
    # cannot be submitted twice by accident.
    st.session_state.pop("bill_scan", None)

    st.session_state.pop("bill_scan_name", None)

    st.session_state.bill_form_version = version + 1

    st.rerun()
