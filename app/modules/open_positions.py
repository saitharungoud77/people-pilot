"""HR-managed open roles and employee-facing career opportunities."""

import streamlit as st

from database.connection import create_open_positions_table, get_connection


_EMPLOYMENT_TYPES = (
    "Full Time",
    "Part Time",
    "Contract",
    "Intern",
)


def _get_positions(open_only=False):
    """Fetch published positions, or all positions for HR."""

    connection = get_connection()
    try:
        if open_only:
            rows = connection.execute(
                """
                SELECT id, role_title, department, location, employment_type,
                       experience_required, role_summary, responsibilities,
                       status, updated_at
                FROM open_positions
                WHERE status = 'Open'
                ORDER BY updated_at DESC, role_title COLLATE NOCASE
                """
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, role_title, department, location, employment_type,
                       experience_required, role_summary, responsibilities,
                       status, updated_at
                FROM open_positions
                ORDER BY
                    CASE status WHEN 'Open' THEN 0 ELSE 1 END,
                    updated_at DESC,
                    role_title COLLATE NOCASE
                """
            ).fetchall()
    finally:
        connection.close()

    keys = (
        "id",
        "role_title",
        "department",
        "location",
        "employment_type",
        "experience_required",
        "role_summary",
        "responsibilities",
        "status",
        "updated_at",
    )
    return [dict(zip(keys, row)) for row in rows]


def _save_position(position_id, role_title, department, location,
                   employment_type, experience_required, role_summary,
                   responsibilities, status):
    """Insert a new role or update an existing posting."""

    values = (
        role_title.strip(),
        department.strip(),
        location.strip(),
        employment_type,
        experience_required.strip(),
        role_summary.strip(),
        responsibilities.strip(),
        status,
    )
    connection = get_connection()
    try:
        if position_id is None:
            connection.execute(
                """
                INSERT INTO open_positions (
                    role_title, department, location, employment_type,
                    experience_required, role_summary, responsibilities,
                    status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        else:
            connection.execute(
                """
                UPDATE open_positions
                SET role_title = ?,
                    department = ?,
                    location = ?,
                    employment_type = ?,
                    experience_required = ?,
                    role_summary = ?,
                    responsibilities = ?,
                    status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*values, position_id),
            )
            if connection.total_changes == 0:
                raise ValueError("The selected opening no longer exists.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _render_position(position):
    """Show an opening card to employees."""

    with st.container(border=True):
        title_col, status_col = st.columns([4, 1])
        with title_col:
            st.subheader(position["role_title"])
        with status_col:
            st.badge("Open", icon=":material/check_circle:", color="green")

        details = [
            value for value in (
                position["department"],
                position["location"],
                position["employment_type"],
                (
                    f"{position['experience_required']} experience"
                    if position["experience_required"]
                    else ""
                ),
            ) if value
        ]
        if details:
            st.caption(" · ".join(details))
        if position["role_summary"]:
            st.write(position["role_summary"])
        if position["responsibilities"]:
            with st.expander("Responsibilities"):
                st.markdown(position["responsibilities"])


def _render_employee_openings():
    """List only active openings to employees."""

    st.title("Open Positions", icon=":material/work:")
    st.caption(
        "Explore current opportunities and review the responsibilities "
        "for each role."
    )
    positions = _get_positions(open_only=True)
    if not positions:
        st.info("There are no open positions at the moment.")
        return

    st.caption(
        f"{len(positions)} open position"
        f"{'' if len(positions) == 1 else 's'}"
    )
    for position in positions:
        _render_position(position)


def _render_hr_editor():
    """Allow HR to create or edit and publish/close openings."""

    positions = _get_positions()
    st.title("Open Positions", icon=":material/work:")
    st.caption(
        "Create and maintain role postings. Only openings marked Open "
        "are visible to employees."
    )

    mode = st.radio(
        "Action",
        ("Add position", "Edit position"),
        horizontal=True,
        key="open_positions_action",
    )

    selected = None
    if mode == "Edit position":
        if not positions:
            st.info("No positions to edit yet. Add a position first.")
            return
        options = {
            f"{position['role_title']} · {position['status']} "
            f"(#{position['id']})": position
            for position in positions
        }
        selected_label = st.selectbox(
            "Select position",
            list(options),
            key="open_positions_selected",
        )
        selected = options[selected_label]

    position_id = selected["id"] if selected else None
    form_key = (
        f"open_position_form_{position_id}"
        if position_id is not None
        else "open_position_form_new"
    )
    employment_type = (
        selected["employment_type"]
        if selected and selected["employment_type"] in _EMPLOYMENT_TYPES
        else _EMPLOYMENT_TYPES[0]
    )
    experience_required = (
        selected["experience_required"] if selected else ""
    )
    status = selected["status"] if selected else "Open"

    with st.form(form_key):
        role_title = st.text_input(
            "Role title *",
            value=selected["role_title"] if selected else "",
        )
        col1, col2 = st.columns(2)
        with col1:
            department = st.text_input(
                "Department",
                value=selected["department"] if selected else "",
            )
            location = st.text_input(
                "Location",
                value=selected["location"] if selected else "",
            )
        with col2:
            employment_type = st.selectbox(
                "Employment type",
                _EMPLOYMENT_TYPES,
                index=_EMPLOYMENT_TYPES.index(employment_type),
            )
            experience_required = st.text_input(
                "Experience required",
                value=experience_required,
                placeholder="e.g. 2+ years or Freshers",
            )
            status = st.selectbox(
                "Status",
                ("Open", "Closed"),
                index=0 if status == "Open" else 1,
                help="Closed positions are hidden from employees.",
            )
        role_summary = st.text_area(
            "Role summary",
            value=selected["role_summary"] if selected else "",
            height=90,
        )
        responsibilities = st.text_area(
            "Roles and responsibilities *",
            value=selected["responsibilities"] if selected else "",
            height=180,
            help="Use one responsibility per line for easy reading.",
        )
        submitted = st.form_submit_button(
            "Save position",
            type="primary",
            width="stretch",
        )

    if submitted:
        if not role_title.strip():
            st.error("Enter a role title.")
        elif not responsibilities.strip():
            st.error("Add the responsibilities for this role.")
        else:
            try:
                _save_position(
                    position_id,
                    role_title,
                    department,
                    location,
                    employment_type,
                    experience_required,
                    role_summary,
                    responsibilities,
                    status,
                )
            except Exception as exc:
                st.error(f"Could not save this position: {exc}")
            else:
                st.session_state["open_positions_flash"] = (
                    f"{role_title.strip()} saved successfully."
                )
                st.rerun()

    flash = st.session_state.pop("open_positions_flash", None)
    if flash:
        st.success(flash)

    st.divider()
    st.subheader("All positions")
    if not positions:
        st.info("No positions have been added.")
        return
    st.dataframe(
        [
            {
                "Role": position["role_title"],
                "Department": position["department"],
                "Location": position["location"],
                "Employment type": position["employment_type"],
                "Experience required": position["experience_required"],
                "Status": position["status"],
                "Updated": position["updated_at"],
            }
            for position in positions
        ],
        hide_index=True,
        width="stretch",
    )


def show_open_positions_page():
    """Show HR management or employee view based on the authenticated role."""

    create_open_positions_table()
    user = st.session_state.get("auth_user") or {}
    if user.get("role") == "hr":
        _render_hr_editor()
    elif user.get("role") == "employee":
        _render_employee_openings()
    else:
        st.error("Sign in with an HR or employee account to view positions.")
