import datetime

import streamlit as st

from database.connection import (
    get_connection,
    create_revision_table
)
from modules.salary import (
    auto_salary_components,
    get_structure,
    scale_salary_structure
)
from modules.notifications import notify_employee


# ============================================================
# SALARY REVISIONS (INCREMENTS)
# ============================================================
# Track every CTC change with an effective date. Applying a
# revision updates the employee's annual CTC and rescales the
# saved salary structure, so future payslips use the new figures
# while already-saved payslips stay intact.

def create_revision_tables():

    create_revision_table()


# ---------------------------------------------------------
# DATA HELPERS
# ---------------------------------------------------------

def record_revision(
    employee_id,
    effective_date,
    old_ctc,
    new_ctc,
    reason=None
):
    """Store one CTC change and return the change percentage."""

    old_ctc = float(old_ctc or 0)

    new_ctc = float(new_ctc or 0)

    change_pct = (
        round((new_ctc - old_ctc) / old_ctc * 100, 2)
        if old_ctc
        else 0.0
    )

    connection = get_connection()

    try:

        connection.execute(
            """
            INSERT INTO salary_revisions
                (
                    employee_id,
                    effective_date,
                    old_ctc,
                    new_ctc,
                    change_pct,
                    reason
                )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                str(effective_date),
                old_ctc,
                new_ctc,
                change_pct,
                reason
            )
        )

        connection.commit()

    finally:

        connection.close()

    return change_pct


def get_revisions(employee_id):
    """Revision rows for an employee, newest effective first."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                id,
                effective_date,
                old_ctc,
                new_ctc,
                change_pct,
                reason,
                created_at
            FROM salary_revisions
            WHERE employee_id = ?
            ORDER BY effective_date DESC, id DESC
            """,
            (employee_id,)
        ).fetchall()

    finally:

        connection.close()

    keys = [
        "id",
        "effective_date",
        "old_ctc",
        "new_ctc",
        "change_pct",
        "reason",
        "created_at"
    ]

    return [dict(zip(keys, row)) for row in rows]


def apply_revision(employee_id, new_ctc, effective_date, reason=None):
    """Set a new CTC, rescale the structure and log the revision.

    Returns a summary dict, or raises ValueError when the employee
    does not exist.
    """

    new_ctc = float(new_ctc or 0)

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT employee_name, annual_ctc
            FROM employees
            WHERE employee_id = ?
            """,
            (employee_id,)
        ).fetchone()

    finally:

        connection.close()

    if row is None:

        raise ValueError("Employee not found.")

    employee_name, old_ctc = row

    old_ctc = float(old_ctc or 0)

    connection = get_connection()

    try:

        connection.execute(
            """
            UPDATE employees
            SET annual_ctc = ?
            WHERE employee_id = ?
            """,
            (new_ctc, employee_id)
        )

        connection.commit()

    finally:

        connection.close()

    # Keep the saved structure in step with the new CTC. When no
    # structure exists yet it is auto-generated from the CTC on
    # first view, so there is nothing to rescale.
    adjusted = scale_salary_structure(
        employee_id,
        old_ctc,
        new_ctc
    )

    change_pct = record_revision(
        employee_id,
        effective_date,
        old_ctc,
        new_ctc,
        reason
    )

    notify_employee(
        employee_id,
        "Salary revised",
        f"Your annual CTC changed from ₹ {old_ctc:,.2f} to "
        f"₹ {new_ctc:,.2f}, effective {effective_date}.",
        category="Salary",
        page="salary"
    )

    return {
        "employee_name": employee_name,
        "old_ctc": old_ctc,
        "new_ctc": new_ctc,
        "change_pct": change_pct,
        "adjusted": adjusted
    }


# ---------------------------------------------------------
# SHARED RENDERING
# ---------------------------------------------------------

def render_revision_history(employee_id):
    """Timeline of an employee's CTC changes."""

    st.subheader(
        "Salary revision history",
        icon=":material/history:"
    )

    revisions = get_revisions(employee_id)

    if not revisions:

        st.caption(
            "No salary revisions recorded yet. Changes made here "
            "or while editing the employee's CTC appear here."
        )

        return

    rows = []

    for revision in revisions:

        change = revision["change_pct"]

        rows.append({
            "Effective": revision["effective_date"],
            "Previous CTC": f"₹ {revision['old_ctc'] / 100000:,.2f} L",
            "New CTC": f"₹ {revision['new_ctc'] / 100000:,.2f} L",
            "Change": f"{'+' if change >= 0 else ''}{change:,.2f}%",
            "Reason": revision["reason"] or "—"
        })

    st.dataframe(rows, width="stretch", hide_index=True)


# ---------------------------------------------------------
# HR PAGE
# ---------------------------------------------------------

def show_revisions_page(go_home=None):
    """HR: apply CTC revisions and review the history."""

    create_revision_tables()

    st.title("Salary revisions", icon=":material/trending_up:")

    st.caption(
        "Apply a CTC increment or revision with an effective date. "
        "The salary structure is rescaled to match; saved payslips "
        "remain unchanged."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="revisions_back",
        width="content"
    ):

        go_home()

        st.rerun()

    connection = get_connection()

    try:

        employees = connection.execute(
            """
            SELECT employee_id, employee_name, annual_ctc
            FROM employees
            ORDER BY employee_name
            """
        ).fetchall()

    finally:

        connection.close()

    if not employees:

        st.warning("Please create an employee first.")

        return

    options = {
        f"{name}  ({employee_id})": (employee_id, name, ctc)
        for employee_id, name, ctc in employees
    }

    selected = st.selectbox(
        "Select Employee",
        list(options.keys()),
        key="revision_employee"
    )

    employee_id, employee_name, current_ctc = options[selected]

    flash = st.session_state.pop("revision_flash", None)

    if flash:

        st.success(flash)

    with st.container(border=True):

        st.markdown(f"### {employee_name}")

        col1, col2 = st.columns(2)

        with col1:

            st.metric(
                "Current CTC",
                f"₹ {current_ctc / 100000:,.2f} L",
                border=True
            )

        with col2:

            revisions = get_revisions(employee_id)

            st.metric(
                "Revisions on record",
                len(revisions),
                icon=":material/history:",
                border=True
            )

    st.divider()

    # -----------------------------------------------------
    # APPLY A REVISION
    # -----------------------------------------------------

    st.subheader("Apply a revision", icon=":material/trending_up:")

    with st.form(f"apply_revision_{employee_id}"):

        form_col1, form_col2 = st.columns(2)

        with form_col1:

            new_ctc_lpa = st.number_input(
                "New annual CTC (LPA)",
                min_value=0.0,
                value=float(current_ctc) / 100000,
                step=0.1,
                format="%.2f"
            )

        with form_col2:

            effective_date = st.date_input(
                "Effective date",
                value=datetime.date.today()
            )

        reason = st.text_input(
            "Reason / note",
            placeholder="e.g. Annual appraisal FY 2026-27"
        )

        submitted = st.form_submit_button(
            "Apply revision",
            width="stretch"
        )

    if submitted:

        new_ctc = new_ctc_lpa * 100000

        if new_ctc <= 0:

            st.error("Please enter a valid CTC.")

        elif abs(new_ctc - current_ctc) < 0.01:

            st.error(
                "The new CTC is the same as the current CTC. "
                "No revision was applied."
            )

        else:

            try:

                result = apply_revision(
                    employee_id,
                    new_ctc,
                    str(effective_date),
                    reason.strip() or None
                )

                message = (
                    f"Revision applied for "
                    f"{result['employee_name']}: "
                    f"₹ {result['old_ctc'] / 100000:,.2f} L → "
                    f"₹ {result['new_ctc'] / 100000:,.2f} L "
                    f"({result['change_pct']:+,.2f}%)."
                )

                if result["adjusted"]:

                    message += " Salary structure rescaled."

                else:

                    message += (
                        " No saved structure to rescale yet; it "
                        "will reflect the new CTC when created."
                    )

                st.session_state.revision_flash = message

                st.rerun()

            except Exception as exc:

                st.error(f"Unable to apply the revision: {exc}")

    # -----------------------------------------------------
    # HISTORY
    # -----------------------------------------------------

    st.divider()

    render_revision_history(employee_id)
