import streamlit as st

from database.connection import get_connection


# ============================================================
# SIGNED-IN SESSION HELPERS
# ============================================================
# Shared by every employee-facing feature module. Resolving the
# signed-in user lives here so each feature file stays focused on
# its own screen and data.

_EMPLOYEE_FIELDS = """
    employee_id,
    employee_name,
    department,
    designation,
    joining_date,
    location,
    employment_type,
    annual_ctc,
    health_insurance_opted
"""


def signed_in_employee_id():
    """Employee id of the signed-in user, or None for HR."""

    user = st.session_state.get("auth_user") or {}

    return user.get("employee_id")


def employee_details(employee_id):
    """Return one employee's core record as a dict, or None when the
    record does not exist."""

    if not employee_id:

        return None

    connection = get_connection()

    try:

        row = connection.execute(
            f"""
            SELECT {_EMPLOYEE_FIELDS}
            FROM employees
            WHERE employee_id = ?
            """,
            (employee_id,)
        ).fetchone()

    finally:

        connection.close()

    if row is None:

        return None

    keys = [
        "employee_id",
        "employee_name",
        "department",
        "designation",
        "joining_date",
        "location",
        "employment_type",
        "annual_ctc",
        "health_insurance_opted"
    ]

    return dict(zip(keys, row))


def require_employee():
    """Fetch the signed-in employee, or show a friendly error and
    return None."""

    employee = employee_details(signed_in_employee_id())

    if employee is None:

        st.error(
            "Your employee record could not be found. "
            "Please contact HR."
        )

    return employee
