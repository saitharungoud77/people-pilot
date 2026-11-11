"""Employee project assignments.

HR records which projects each employee is working on; employees see
their own assignments on **My overview**. One row is one assignment,
so an employee can sit on several projects and a project can be shared
by several employees.

The table lives in ``database/connection.py`` (``create_project_table``)
so it is created with the rest of the schema at startup.
"""

import datetime

import streamlit as st

from database.connection import (
    get_connection,
    create_project_table
)

from modules.notifications import notify_employee


# ============================================================
# SETTINGS
# ============================================================

PROJECT_STATUSES = [
    "Active",
    "On hold",
    "Completed"
]

# Badge colours match the palette used across the portal.
STATUS_COLORS = {
    "Active": "green",
    "On hold": "orange",
    "Completed": "gray"
}


# ============================================================
# READING PROJECTS
# ============================================================

def get_projects(employee_id=None, status=None):
    """Project assignments, active ones first.

    Pass an ``employee_id`` to scope the list to one person; leave it
    out for the whole register. An optional ``status`` filters the
    list to a single state.
    """

    create_project_table()

    query = """
        SELECT
            id,
            employee_id,
            project_name,
            role,
            status,
            start_date,
            notes,
            created_at
        FROM employee_projects
        WHERE 1 = 1
    """

    params = []

    if employee_id:

        query += " AND employee_id = ?"

        params.append(employee_id)

    if status:

        query += " AND status = ?"

        params.append(status)

    # Active first, then On hold, then Completed; newest start date
    # among equals so the current project reads first.
    query += """
        ORDER BY
            CASE status
                WHEN 'Active' THEN 0
                WHEN 'On hold' THEN 1
                ELSE 2
            END,
            start_date DESC,
            project_name COLLATE NOCASE
    """

    connection = get_connection()

    try:

        rows = connection.execute(query, params).fetchall()

    finally:

        connection.close()

    keys = [
        "id",
        "employee_id",
        "project_name",
        "role",
        "status",
        "start_date",
        "notes",
        "created_at"
    ]

    return [dict(zip(keys, row)) for row in rows]


# ============================================================
# WRITING PROJECTS
# ============================================================
def add_project(
    employee_id,
    project_name,
    role="",
    status="Active",
    start_date="",
    notes=""
):
    """Assign one project to an employee and notify them."""

    create_project_table()

    project_name = project_name.strip()

    if not project_name:

        raise ValueError("A project name is required.")

    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    connection = get_connection()

    try:

        cursor = connection.execute(
            """
            INSERT INTO employee_projects
                (
                    employee_id,
                    project_name,
                    role,
                    status,
                    start_date,
                    notes,
                    created_at
                )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                project_name,
                role.strip(),
                status,
                start_date or "",
                notes.strip(),
                stamp
            )
        )

        connection.commit()

        project_id = cursor.lastrowid

    finally:

        connection.close()

    detail = f"You have been assigned to “{project_name}”"

    if role.strip():

        detail += f" as {role.strip()}"

    notify_employee(
        employee_id,
        "New project assigned",
        detail + ". You can see it on My overview.",
        category="Project",
        page="application"
    )

    return project_id


def delete_project(project_id):
    """Remove one project assignment."""

    connection = get_connection()

    try:

        connection.execute(
            """
            DELETE FROM employee_projects
            WHERE id = ?
            """,
            (project_id,)
        )

        connection.commit()

    finally:

        connection.close()


# ============================================================
# SMALL FORMATTING HELPERS
# ============================================================

def _pretty_date(value):
    """Turn a stored ISO date into a readable one (returns it if not ISO)."""

    if not value:

        return ""

    try:

        return datetime.date.fromisoformat(value).strftime("%d %b %Y")

    except (ValueError, TypeError):

        return value


def _detail_line(project):
    """The muted second line under a project name."""

    parts = []

    if project["role"]:

        parts.append(project["role"])

    if project["start_date"]:

        parts.append(f"Since {_pretty_date(project['start_date'])}")

    return " · ".join(parts)


def _status_badge(project):
    """A status badge using the portal's colour palette."""

    st.badge(
        project["status"],
        color=STATUS_COLORS.get(project["status"], "gray")
    )


# ============================================================
# EMPLOYEE VIEW (MY OVERVIEW)
# ============================================================

def render_my_projects(employee_id):
    """The employee's own projects, read-only.

    Only what HR has assigned is shown - employees cannot edit this
    list. Active projects appear first and carry a green badge.
    """

    projects = get_projects(employee_id)

    with st.container(border=True, key="my_projects"):

        header, count = st.columns([4, 1], vertical_alignment="center")

        with header:

            st.markdown("**Projects**")

        with count:

            if projects:

                active = sum(
                    1 for project in projects
                    if project["status"] == "Active"
                )

                st.caption(f"{active} active · {len(projects)} total")

        if not projects:

            st.caption(
                "No project has been assigned to you yet. "
                "HR manages project assignments."
            )

            return

        for index, project in enumerate(projects):

            if index:

                st.divider()

            name_col, badge_col = st.columns(
                [4, 1],
                vertical_alignment="center"
            )

            with name_col:

                st.markdown(f"**{project['project_name']}**")

                detail = _detail_line(project)

                if detail:

                    st.caption(detail)

            with badge_col:

                _status_badge(project)

            if project["notes"]:

                st.caption(f"Notes: {project['notes']}")


# ============================================================
# HR VIEW (EMPLOYEE RECORD)
# ============================================================

def render_hr_projects(employee_id):
    """HR: assign a project and remove existing assignments."""

    projects = get_projects(employee_id)

    st.markdown("#### Projects")

    st.caption(
        "Assign the projects this employee is working on. "
        "They see the list on My overview."
    )

    with st.container(border=True):

        with st.form(
            f"assign_project_{employee_id}",
            clear_on_submit=True,
            border=False
        ):

            left, right = st.columns(2)

            with left:

                project_name = st.text_input(
                    "Project name *",
                    placeholder="e.g. Payroll migration"
                )

                role = st.text_input(
                    "Role on project",
                    placeholder="Optional - e.g. Developer"
                )

            with right:

                status = st.selectbox(
                    "Status",
                    PROJECT_STATUSES
                )

                start_date = st.date_input(
                    "Start date",
                    value=datetime.date.today()
                )

            notes = st.text_area(
                "Notes",
                placeholder="Optional - scope, client, anything useful"
            )

            submitted = st.form_submit_button(
                "Assign project",
                icon=":material/add_task:",
                width="stretch"
            )

        if submitted:

            if not project_name.strip():

                st.error("Enter a project name.")

            else:

                add_project(
                    employee_id,
                    project_name,
                    role,
                    status,
                    start_date.isoformat() if start_date else "",
                    notes
                )

                st.rerun()

    if not projects:

        st.caption("No projects assigned to this employee yet.")

        return

    for project in projects:

        with st.container(border=True):

            info_col, badge_col, action_col = st.columns(
                [4, 1, 1],
                vertical_alignment="center"
            )

            with info_col:

                st.markdown(f"**{project['project_name']}**")

                detail = _detail_line(project)

                if detail:

                    st.caption(detail)

                if project["notes"]:

                    st.caption(f"Notes: {project['notes']}")

            with badge_col:

                _status_badge(project)

            with action_col:

                if st.button(
                    "Remove",
                    key=f"remove_project_{project['id']}",
                    icon=":material/delete:",
                    width="stretch"
                ):

                    delete_project(project["id"])

                    st.rerun()
