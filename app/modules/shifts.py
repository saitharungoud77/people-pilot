import datetime

import streamlit as st

from database.connection import get_connection
from modules.attendance import (
    assign_shift,
    get_shift,
    list_shifts,
    save_shift,
    shift_counts
)
from modules.notifications import notify_employee
from modules.theme import hero


# ============================================================
# SHIFT TIMINGS
# ============================================================
# Client projects and support teams rarely work the same hours.
# HR creates a shift per project/client here and assigns people
# to it. Attendance, punctuality, half-day and break rules all
# read the shift of the employee, so a 08:00 project is not
# marked late against the 09:30 general shift.


def _employee_rows():
    """(employee_id, name, department, designation, shift_id)."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT employee_id, employee_name, department,
                   designation, shift_id
            FROM employees
            WHERE COALESCE(exit_date, '') = ''
            ORDER BY employee_name
            """
        ).fetchall()

    finally:

        connection.close()

    return rows


def _assignments(employees, shifts):

    by_id = {shift["id"]: shift for shift in shifts}

    rows = []

    for employee_id, name, department, designation, shift_id in employees:

        shift = by_id.get(shift_id) or by_id.get(
            next(
                (
                    item["id"]
                    for item in shifts
                    if item["shift_name"] == "General"
                ),
                0
            )
        )

        if not shift:

            continue

        rows.append(
            {
                "Employee": name,
                "Employee ID": employee_id,
                "Department": department,
                "Client / project": shift["client_project"] or "—",
                "Shift": shift["shift_name"],
                "Timing": f"{shift['start_time']} – {shift['end_time']}",
                "Grace": f"{int(shift['grace_minutes'])} min",
                "Break": f"{int(shift['break_minutes'])} min"
            }
        )

    return rows


def _flash(message):

    st.session_state["shift_flash"] = message


def _create_form():

    with st.form("create_shift_form", clear_on_submit=False):

        col1, col2 = st.columns(2)

        with col1:

            name = st.text_input(
                "Shift name",
                placeholder="e.g. Client – Acme support"
            )

            client_project = st.text_input(
                "Client / project",
                placeholder="e.g. Acme Retail, Internal, Night support"
            )

            grace = st.number_input(
                "Grace period (minutes)",
                min_value=0,
                max_value=120,
                value=15,
                step=5
            )

        with col2:

            start = st.time_input(
                "Shift start",
                value=datetime.time(9, 30)
            )

            end = st.time_input(
                "Shift end",
                value=datetime.time(18, 30)
            )

            break_minutes = st.number_input(
                "Break (minutes)",
                min_value=0,
                max_value=180,
                value=60,
                step=15
            )

        col3, col4 = st.columns(2)

        with col3:

            full_day = st.number_input(
                "Full-day hours",
                min_value=1.0,
                max_value=16.0,
                value=8.0,
                step=0.5
            )

        with col4:

            half_day = st.number_input(
                "Half-day below (hours)",
                min_value=0.5,
                max_value=15.0,
                value=4.0,
                step=0.5
            )

        submitted = st.form_submit_button(
            "Create shift",
            icon=":material/add:",
            type="primary",
            width="stretch"
        )

    if not submitted:

        return

    ok, message = save_shift(
        None,
        name,
        client_project,
        start,
        end,
        grace,
        break_minutes,
        full_day,
        half_day
    )

    if ok:

        _flash(message)

        st.rerun()

    st.error(message, icon=":material/error:")


def _edit_form(shift):

    with st.form(f"edit_shift_{shift['id']}"):

        col1, col2 = st.columns(2)

        with col1:

            name = st.text_input(
                "Shift name",
                value=shift["shift_name"],
                key=f"shift_name_{shift['id']}"
            )

            client_project = st.text_input(
                "Client / project",
                value=shift["client_project"],
                key=f"shift_project_{shift['id']}"
            )

            grace = st.number_input(
                "Grace period (minutes)",
                min_value=0,
                max_value=120,
                value=int(shift["grace_minutes"]),
                step=5,
                key=f"shift_grace_{shift['id']}"
            )

        with col2:

            start = st.time_input(
                "Shift start",
                value=datetime.time.fromisoformat(shift["start_time"]),
                key=f"shift_start_{shift['id']}"
            )

            end = st.time_input(
                "Shift end",
                value=datetime.time.fromisoformat(shift["end_time"]),
                key=f"shift_end_{shift['id']}"
            )

            break_minutes = st.number_input(
                "Break (minutes)",
                min_value=0,
                max_value=180,
                value=int(shift["break_minutes"]),
                step=15,
                key=f"shift_break_{shift['id']}"
            )

        col3, col4 = st.columns(2)

        with col3:

            full_day = st.number_input(
                "Full-day hours",
                min_value=1.0,
                max_value=16.0,
                value=float(shift["min_hours_full_day"]),
                step=0.5,
                key=f"shift_full_{shift['id']}"
            )

        with col4:

            half_day = st.number_input(
                "Half-day below (hours)",
                min_value=0.5,
                max_value=15.0,
                value=float(shift["min_hours_half_day"]),
                step=0.5,
                key=f"shift_half_{shift['id']}"
            )

        saved = st.form_submit_button(
            "Save changes",
            icon=":material/save:",
            type="primary",
            width="stretch"
        )

    if not saved:

        return

    ok, message = save_shift(
        shift["id"],
        name,
        client_project,
        start,
        end,
        grace,
        break_minutes,
        full_day,
        half_day
    )

    if ok:

        _flash(message)

        st.rerun()

    st.error(message, icon=":material/error:")


def show_shifts_page(go_home=None):
    """HR: create client/project shifts and assign employees."""

    hero(
        "Shift timings",
        "Run more than one timing in the same office. Create a shift "
        "per client or project, then put people on it - attendance "
        "and punctuality follow each person's own shift.",
        icon="schedule",
        badges=[
            ("HR only", "admin_panel_settings"),
            ("Client / project shifts", "business_center"),
            ("Feeds attendance", "fact_check")
        ]
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="shifts_back",
        width="content"
    ):

        go_home()

        st.rerun()

    flash = st.session_state.pop("shift_flash", None)

    if flash:

        st.success(flash, icon=":material/check_circle:")

    shifts = list_shifts()

    employees = _employee_rows()

    counts = shift_counts()

    if not shifts:

        st.info(
            "No shifts yet. Create the first one below.",
            icon=":material/schedule:"
        )

    # -----------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------

    metrics = st.columns(3)

    with metrics[0]:

        st.metric(
            "Shifts configured",
            len(shifts),
            icon=":material/schedule:",
            border=True
        )

    with metrics[1]:

        st.metric(
            "Employees on a shift",
            len(employees),
            icon=":material/groups:",
            border=True
        )

    with metrics[2]:

        st.metric(
            "Client / project shifts",
            len(
                [
                    item for item in shifts
                    if (item["client_project"] or "").lower()
                    not in ("", "all")
                ]
            ),
            icon=":material/business_center:",
            border=True
        )

    st.caption(
        "Each employee is measured against the shift they are on. "
        "Changing a shift affects late marks, half-days and the break "
        "deduction from that person's next clock-out."
    )

    st.space("medium")

    # -----------------------------------------------------
    # EXISTING SHIFTS
    # -----------------------------------------------------

    st.markdown("#### Shifts")

    if shifts:

        for shift in shifts:

            people = counts.get(shift["id"], 0)

            project = shift["client_project"] or "All"

            label = (
                f"{shift['shift_name']} · {project} · "
                f"{shift['start_time']} – {shift['end_time']} · "
                f"{people} employee(s)"
            )

            with st.expander(label, icon=":material/schedule:"):

                info = st.columns(4)

                with info[0]:

                    st.metric(
                        "Timing",
                        f"{shift['start_time']} – {shift['end_time']}",
                        border=True
                    )

                with info[1]:

                    st.metric(
                        "Grace",
                        f"{int(shift['grace_minutes'])} min",
                        border=True
                    )

                with info[2]:

                    st.metric(
                        "Break",
                        f"{int(shift['break_minutes'])} min",
                        border=True
                    )

                with info[3]:

                    st.metric(
                        "Half day below",
                        f"{float(shift['min_hours_half_day']):.1f} h",
                        border=True
                    )

                st.caption(
                    f"Full day is "
                    f"{float(shift['min_hours_full_day']):.1f} hours. "
                    f"{people} employee(s) currently on this shift."
                )

                _edit_form(shift)

    # -----------------------------------------------------
    # NEW SHIFT
    # -----------------------------------------------------

    st.space("medium")

    with st.expander(
        "Add a shift",
        icon=":material/add_circle:",
        type="compact"
    ):

        m1, m2 = st.columns(2)

        with m1:

            st.caption(
                "Create one shift per client or project. The name "
                "is what HR and employees see."
            )

        with m2:

            st.caption(
                "Grace is the free minutes after the start time. "
                "Break is deducted only when the day runs past six hours."
            )

        _create_form()

    # -----------------------------------------------------
    # ASSIGN EMPLOYEES
    # -----------------------------------------------------

    st.space("medium")

    st.markdown("#### Who is on which shift")

    if not employees:

        st.info("No active employees to assign.", icon=":material/groups:")

    elif not shifts:

        st.info("Create a shift first.", icon=":material/schedule:")

    else:

        with st.form("assign_shift_form"):

            options = {
                f"{name}  ({employee_id}) · {department}": employee_id
                for employee_id, name, department, _, _ in employees
            }

            selected = st.multiselect(
                "Employees",
                list(options.keys()),
                placeholder="Choose one or more people",
                help="Only active employees are listed."
            )

            shift_options = {
                f"{shift['shift_name']} · "
                f"{shift['client_project'] or 'All'} · "
                f"{shift['start_time']} – {shift['end_time']}": shift["id"]
                for shift in shifts
            }

            chosen_shift = st.selectbox(
                "Move them to",
                list(shift_options.keys())
            )

            assigned = st.form_submit_button(
                "Assign shift",
                icon=":material/group_add:",
                type="primary",
                width="stretch"
            )

        if assigned:

            if not selected:

                st.error(
                    "Choose at least one employee.",
                    icon=":material/error:"
                )

            else:

                shift_id = shift_options[chosen_shift]

                ok, changed = assign_shift(
                    [options[label] for label in selected],
                    shift_id
                )

                if not ok:

                    st.error(
                        "Those employees could not be assigned.",
                        icon=":material/error:"
                    )

                else:

                    shift = get_shift(shift_id)

                    for employee_id in changed:

                        notify_employee(
                            employee_id,
                            "Shift timing updated",
                            f"Your shift is now {shift['shift_name']} "
                            f"({shift['start_time']} – {shift['end_time']}), "
                            f"with a {int(shift['grace_minutes'])} minute "
                            "grace period.",
                            category="Attendance",
                            page="attendance"
                        )

                    _flash(
                        f"{len(changed)} employee(s) moved to "
                        f"“{shift['shift_name']}”."
                        if changed
                        else "Everyone selected was already on that shift."
                    )

                    st.rerun()

        st.space("small")

        st.dataframe(
            _assignments(employees, shifts),
            width="stretch",
            hide_index=True
        )

        st.caption(
            "Attendance uses the shift above for late marks, half-days "
            "and the break deduction. Employees see their own timing on "
            "the My attendance page."
        )
