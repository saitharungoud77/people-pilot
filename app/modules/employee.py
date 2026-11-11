import datetime
import re

import streamlit as st

from database.connection import (
    get_connection,
    create_employee_table
)

from modules.salary import scale_salary_structure

from modules.auth import reset_employee_password

from modules.projects import render_hr_projects


# ============================================================
# EMPLOYEE MANAGEMENT
# ============================================================

EMPLOYMENT_TYPES = [
    "Full Time",
    "Part Time",
    "Contract",
    "Intern"
]


def _validated_bank_details(bank_name, account_number, ifsc, uan):
    """Normalize HR-entered banking details and reject malformed IDs."""

    bank_name = str(bank_name or "").strip()
    account_number = str(account_number or "").strip()
    ifsc = str(ifsc or "").strip().upper()
    uan = str(uan or "").strip()

    if ifsc and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", ifsc):
        return None, "Enter a valid 11-character IFSC code."

    if uan and not re.fullmatch(r"\d{12}", uan):
        return None, "UAN must contain exactly 12 digits."

    return (bank_name, account_number, ifsc, uan), None


# Styles for the employee module. Injected once with st.html so the
# browser applies them to the cards below. (st.markdown would treat
# indented HTML as a code block and show the raw tags.)
EMPLOYEE_CSS = """
<style>

.employee-card {
    background: #F8FAFC;

    border: 1px solid #E2E8F0;

    border-radius: 12px;

    padding: 18px 20px;

    margin-bottom: 10px;
}

.employee-name {
    font-size: 20px;
    font-weight: 700;
    color: #0F172A;
    margin-bottom: 8px;
}

.employee-info {
    color: #334155;
    line-height: 1.8;
}

</style>
"""


def render_employee_card(
    employee_id,
    employee_name,
    department,
    designation,
    joining_date,
    location,
    employment_type,
    annual_ctc,
    health_insurance_opted=False,
    show_employment_type=True
):
    """Render a single employee record card as HTML."""

    employment_row = ""
    if show_employment_type:
        employment_row = (
            f"<b>Employment Type:</b> {employment_type}<br>"
        )

    insurance_status = "Yes" if health_insurance_opted else "No"

    st.html(
        f"""
        <div class="employee-card">

            <div class="employee-name">
                {employee_name}
            </div>

            <div class="employee-info">

                <b>Employee ID:</b> {employee_id}
                <br>

                <b>Department:</b> {department}
                &nbsp;&nbsp;&nbsp;
                <b>Designation:</b> {designation}
                <br>

                <b>Joining Date:</b> {joining_date}
                &nbsp;&nbsp;&nbsp;
                <b>Location:</b> {location}
                <br>

                {employment_row}

                <b>Health Insurance Opted:</b> {insurance_status}
                <br>

                <b>Annual CTC:</b> ₹ {annual_ctc / 100000:.2f} Lakhs

            </div>

        </div>
        """
    )


def delete_employee(db_id, employee_id, employee_name):
    """Delete an employee and any linked salary structure."""

    connection = get_connection()

    cursor = connection.cursor()

    # Remove the linked salary structure first, so the delete works
    # even if the salary table was created without ON DELETE CASCADE.
    try:

        cursor.execute(
            """
            DELETE FROM salary_structures
            WHERE employee_id = ?
            """,
            (employee_id,)
        )

    except Exception:

        pass

    cursor.execute(
        """
        DELETE FROM employees
        WHERE id = ?
        """,
        (db_id,)
    )

    connection.commit()

    connection.close()

    st.session_state.employee_action = "view"
    st.session_state.delete_employee_id = None

    st.success(
        f"{employee_name} deleted successfully."
    )

    st.rerun()


def update_employee(
    db_id,
    old_employee_id,
    new_employee_id,
    employee_name,
    department,
    designation,
    joining_date,
    location,
    employment_type,
    annual_ctc,
    health_insurance_opted=False,
    bank_name="",
    bank_account_number="",
    bank_ifsc="",
    uan_number=""
):
    """Update an employee, repointing its salary row if the ID changed."""

    connection = get_connection()

    try:

        cursor = connection.cursor()

        if new_employee_id != old_employee_id:

            cursor.execute(
                """
                SELECT 1
                FROM employees
                WHERE employee_id = ?
                """,
                (new_employee_id,)
            )

            if cursor.fetchone():

                raise ValueError(
                    f"Employee ID '{new_employee_id}' "
                    "is already in use."
                )

            # Repoint the linked salary structure. Foreign keys are
            # disabled so the child row can be updated before the
            # parent key changes.
            connection.execute(
                "PRAGMA foreign_keys = OFF"
            )

            try:

                cursor.execute(
                    """
                    UPDATE salary_structures
                    SET employee_id = ?
                    WHERE employee_id = ?
                    """,
                    (new_employee_id, old_employee_id)
                )

            except Exception:

                pass

            try:

                cursor.execute(
                    """
                    UPDATE payslips
                    SET employee_id = ?
                    WHERE employee_id = ?
                    """,
                    (new_employee_id, old_employee_id)
                )

            except Exception:

                pass

            # Keep the employee's login account in sync (username =
            # Employee ID). The password is unchanged.
            try:

                cursor.execute(
                    """
                    UPDATE users
                    SET employee_id = ?,
                        username = ?
                    WHERE employee_id = ?
                    """,
                    (
                        new_employee_id,
                        new_employee_id,
                        old_employee_id
                    )
                )

            except Exception:

                pass

            # Project assignments follow the employee to their new ID.
            try:

                cursor.execute(
                    """
                    UPDATE employee_projects
                    SET employee_id = ?
                    WHERE employee_id = ?
                    """,
                    (new_employee_id, old_employee_id)
                )

            except Exception:

                pass

        cursor.execute(
            """
            UPDATE employees
            SET
                employee_id = ?,
                employee_name = ?,
                department = ?,
                designation = ?,
                joining_date = ?,
                location = ?,
                employment_type = ?,
                annual_ctc = ?,
                health_insurance_opted = ?,
                bank_name = ?,
                bank_account_number = ?,
                bank_ifsc = ?,
                uan_number = ?
            WHERE id = ?
            """,
            (
                new_employee_id,
                employee_name,
                department,
                designation,
                joining_date,
                location,
                employment_type,
                annual_ctc,
                int(health_insurance_opted),
                bank_name,
                bank_account_number,
                bank_ifsc,
                uan_number,
                db_id
            )
        )

        connection.commit()

    finally:

        connection.close()


def render_employee_record(
    db_id,
    employee_id,
    employee_name,
    department,
    designation,
    joining_date,
    location,
    employment_type,
    annual_ctc,
    health_insurance_opted=False,
    show_employment_type=True
):
    """Render an employee card with its Edit / Delete actions beside it."""

    details_col, actions_col = st.columns(
        [4, 1],
        vertical_alignment="center"
    )

    with details_col:

        render_employee_card(
            employee_id,
            employee_name,
            department,
            designation,
            joining_date,
            location,
            employment_type,
            annual_ctc,
            health_insurance_opted,
            show_employment_type
        )

    with actions_col:

        if st.button(
            "Edit",
            key=f"edit_{db_id}",
            width="stretch"
        ):

            st.session_state.edit_employee_id = db_id
            st.session_state.employee_action = "edit"

            st.rerun()

        if st.button(
            "Delete",
            key=f"delete_{db_id}",
            width="stretch"
        ):

            st.session_state.delete_employee_id = db_id

            st.rerun()

    # Confirmation step before actually deleting
    if st.session_state.get("delete_employee_id") == db_id:

        st.warning(
            f"Delete {employee_name} ({employee_id})? "
            "This cannot be undone."
        )

        confirm_col, cancel_col = st.columns(2)

        with confirm_col:

            if st.button(
                "Yes, delete",
                key=f"confirm_delete_{db_id}",
                width="stretch"
            ):

                delete_employee(
                    db_id,
                    employee_id,
                    employee_name
                )

        with cancel_col:

            if st.button(
                "Cancel",
                key=f"cancel_delete_{db_id}",
                width="stretch"
            ):

                st.session_state.delete_employee_id = None

                st.rerun()

    # Project assignments live below the card. HR manages them here;
    # the employee sees the same list read-only on My overview.
    st.space("medium")

    render_hr_projects(employee_id)


def show_employee(go_home=None):

    # Create table if it does not exist
    create_employee_table()

    # ========================================================
    # CSS
    # ========================================================

    st.html(EMPLOYEE_CSS)

    # Flash message from a previous action, shown once after rerun
    flash_message = st.session_state.pop("employee_flash", None)

    if flash_message:

        st.success(flash_message)

    # ========================================================
    # BACK BUTTON
    # ========================================================

    # The edit screen provides its own back buttons, so avoid a
    # duplicate "Back to Application" button there.
    if (
        go_home
        and st.session_state.get("employee_action") != "edit"
    ):

        if st.button(
            "← Back to Application",
            width="content"
        ):

            go_home()

            st.rerun()

    # ========================================================
    # HEADER
    # ========================================================

    st.title("Employee management", icon=":material/groups:")

    st.caption(
        "Manage employee profiles, employment information "
        "and records."
    )

    # ========================================================
    # ACTION BUTTONS
    # ========================================================

    col1, col2, col3 = st.columns(3)

    with col1:

        if st.button(
            "Add Employee",
            width="stretch"
        ):

            st.session_state.employee_action = "add"

            st.rerun()

    with col2:

        if st.button(
            "View Employees",
            width="stretch"
        ):

            st.session_state.employee_action = "view"

            st.rerun()

    with col3:

        if st.button(
            "Search Employee",
            width="stretch"
        ):

            st.session_state.employee_action = "search"

            st.rerun()

    # ========================================================
    # DEFAULT
    # ========================================================

    if "employee_action" not in st.session_state:

        st.session_state.employee_action = "view"

    action = st.session_state.employee_action

    # ========================================================
    # ADD EMPLOYEE
    # ========================================================

    if action == "add":

        st.markdown("### Add New Employee")

        with st.form("employee_form"):

            col1, col2 = st.columns(2)

            with col1:

                employee_id = st.text_input(
                    "Employee ID"
                )

                employee_name = st.text_input(
                    "Employee Name"
                )

                department = st.text_input(
                    "Department"
                )

                designation = st.text_input(
                    "Designation"
                )

            with col2:

                joining_date = st.date_input(
                    "Joining Date"
                )

                location = st.text_input(
                    "Location"
                )

                employment_type = st.selectbox(
                    "Employment Type",
                    EMPLOYMENT_TYPES
                )

                health_insurance_opted = st.selectbox(
                    "Health Insurance Opted",
                    ["No", "Yes"]
                )

                annual_ctc_lpa = st.number_input(
                    "Annual CTC (LPA)",
                    min_value=0.0,
                    step=0.1,
                    format="%.2f"
                )

            st.markdown("#### Bank and UAN details")
            bank_col1, bank_col2 = st.columns(2)

            with bank_col1:

                bank_name = st.text_input("Bank name")
                bank_account_number = st.text_input("Bank account number")

            with bank_col2:

                bank_ifsc = st.text_input("IFSC code")
                uan_number = st.text_input("UAN")

            submitted = st.form_submit_button(
                "Save Employee",
                width="stretch"
            )

        if submitted:

            bank_details, bank_error = _validated_bank_details(
                bank_name,
                bank_account_number,
                bank_ifsc,
                uan_number
            )

            if bank_error:

                st.error(bank_error)

            elif (
                not employee_id
                or not employee_name
                or not department
                or not designation
                or not location
            ):

                st.error(
                    "Please fill all required fields."
                )

            else:

                annual_ctc = (
                    annual_ctc_lpa * 100000
                )

                try:

                    connection = get_connection()

                    cursor = connection.cursor()

                    cursor.execute(
                        """
                        INSERT INTO employees
                        (
                            employee_id,
                            employee_name,
                            department,
                            designation,
                            joining_date,
                            location,
                            employment_type,
                            annual_ctc,
                            health_insurance_opted,
                            bank_name,
                            bank_account_number,
                            bank_ifsc,
                            uan_number
                        )

                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            employee_id,
                            employee_name,
                            department,
                            designation,
                            str(joining_date),
                            location,
                            employment_type,
                            annual_ctc,
                            int(health_insurance_opted == "Yes"),
                            *bank_details
                        )
                    )

                    connection.commit()

                    connection.close()

                    st.success(
                        "Employee added successfully!"
                    )

                    st.session_state.employee_action = "view"

                    st.rerun()

                except Exception as e:

                    st.error(
                        f"Error: {e}"
                    )

    # ========================================================
    # VIEW EMPLOYEES
    # ========================================================

    elif action == "view":

        st.markdown(
            "### Employee Records"
        )

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                id,
                employee_id,
                employee_name,
                department,
                designation,
                joining_date,
                location,
                employment_type,
                annual_ctc,
                health_insurance_opted

            FROM employees

            ORDER BY id DESC
            """
        )

        employees = cursor.fetchall()

        connection.close()

        if not employees:

            st.info(
                "No employees found. "
                "Click Add Employee to create one."
            )

        else:

            options = {
                f"{row[2]}  ({row[1]})": row
                for row in employees
            }

            selected = st.selectbox(
                "Select an employee to view details",
                list(options.keys()),
                index=None,
                placeholder="Choose an employee..."
            )

            if selected:

                (
                    db_id,
                    employee_id,
                    employee_name,
                    department,
                    designation,
                    joining_date,
                    location,
                    employment_type,
                    annual_ctc,
                    health_insurance_opted
                ) = options[selected]

                render_employee_record(
                    db_id,
                    employee_id,
                    employee_name,
                    department,
                    designation,
                    joining_date,
                    location,
                    employment_type,
                    annual_ctc,
                    health_insurance_opted,
                    show_employment_type=True
                )

    # ========================================================
    # SEARCH EMPLOYEE
    # ========================================================

    elif action == "search":

        st.markdown(
            "### Search Employee"
        )

        search_value = st.text_input(
            "Employee ID or Employee Name"
        )

        if search_value:

            connection = get_connection()

            cursor = connection.cursor()

            cursor.execute(
                """
                SELECT
                    id,
                    employee_id,
                    employee_name,
                    department,
                    designation,
                    joining_date,
                    location,
                    employment_type,
                    annual_ctc,
                    health_insurance_opted

                FROM employees

                WHERE employee_id LIKE ?
                OR employee_name LIKE ?
                """,
                (
                    f"%{search_value}%",
                    f"%{search_value}%"
                )
            )

            employees = cursor.fetchall()

            connection.close()

            if not employees:

                st.warning(
                    "No employee found."
                )

            else:

                selected_row = None

                # Exactly one match -> show its details directly.
                # Several matches -> let the user pick one.
                if len(employees) == 1:

                    selected_row = employees[0]

                else:

                    options = {
                        f"{row[2]}  ({row[1]})": row
                        for row in employees
                    }

                    selected = st.selectbox(
                        "Multiple matches found - "
                        "select an employee",
                        list(options.keys()),
                        index=None,
                        placeholder="Choose an employee..."
                    )

                    if selected:

                        selected_row = options[selected]

                if selected_row:

                    (
                        db_id,
                        employee_id,
                        employee_name,
                        department,
                        designation,
                        joining_date,
                        location,
                        employment_type,
                        annual_ctc,
                        health_insurance_opted
                    ) = selected_row

                    render_employee_record(
                        db_id,
                        employee_id,
                        employee_name,
                        department,
                        designation,
                        joining_date,
                        location,
                        employment_type,
                        annual_ctc,
                        health_insurance_opted,
                        show_employment_type=True
                    )

    # ========================================================
    # EDIT EMPLOYEE
    # ========================================================

    elif action == "edit":

        db_id = st.session_state.get(
            "edit_employee_id"
        )

        connection = get_connection()

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                employee_id,
                employee_name,
                department,
                designation,
                joining_date,
                location,
                employment_type,
                annual_ctc,
                health_insurance_opted,
                bank_name,
                bank_account_number,
                bank_ifsc,
                uan_number

            FROM employees

            WHERE id = ?
            """,
            (db_id,)
        )

        employee = cursor.fetchone()

        connection.close()

        if not employee:

            st.error(
                "Employee record not found."
            )

            if st.button(
                "← Back to records",
                key="edit_missing_back",
                width="content"
            ):

                st.session_state.employee_action = "view"

                st.rerun()

        else:

            (
                employee_id,
                employee_name,
                department,
                designation,
                joining_date,
                location,
                employment_type,
                annual_ctc,
                health_insurance_opted,
                bank_name,
                bank_account_number,
                bank_ifsc,
                uan_number
            ) = employee

            st.markdown("### Edit Employee")

            try:

                joining_date_value = (
                    datetime.date.fromisoformat(
                        joining_date
                    )
                )

            except (TypeError, ValueError):

                joining_date_value = datetime.date.today()

            try:

                employment_index = EMPLOYMENT_TYPES.index(
                    employment_type
                )

            except ValueError:

                employment_index = 0

            with st.form("edit_employee_form"):

                new_employee_id = st.text_input(
                    "Employee ID",
                    value=employee_id
                )

                col1, col2 = st.columns(2)

                with col1:

                    new_employee_name = st.text_input(
                        "Employee Name",
                        value=employee_name
                    )

                    new_department = st.text_input(
                        "Department",
                        value=department
                    )

                    new_designation = st.text_input(
                        "Designation",
                        value=designation
                    )

                with col2:

                    new_joining_date = st.date_input(
                        "Joining Date",
                        value=joining_date_value
                    )

                    new_location = st.text_input(
                        "Location",
                        value=location
                    )

                    new_employment_type = st.selectbox(
                        "Employment Type",
                        EMPLOYMENT_TYPES,
                        index=employment_index
                    )

                    new_health_insurance_opted = st.selectbox(
                        "Health Insurance Opted",
                        ["No", "Yes"],
                        index=1 if health_insurance_opted else 0
                    )

                    new_annual_ctc_lpa = st.number_input(
                        "Annual CTC (LPA)",
                        min_value=0.0,
                        value=float(annual_ctc) / 100000,
                        step=0.1,
                        format="%.2f"
                    )

                st.markdown("#### Bank and UAN details")
                bank_col1, bank_col2 = st.columns(2)

                with bank_col1:

                    new_bank_name = st.text_input(
                        "Bank name",
                        value=bank_name or ""
                    )
                    new_bank_account_number = st.text_input(
                        "Bank account number",
                        value=bank_account_number or ""
                    )

                with bank_col2:

                    new_bank_ifsc = st.text_input(
                        "IFSC code",
                        value=bank_ifsc or ""
                    )
                    new_uan_number = st.text_input(
                        "UAN",
                        value=uan_number or ""
                    )

                save_col, records_col, app_col = st.columns(3)

                with save_col:

                    updated = st.form_submit_button(
                        "Update Employee",
                        width="stretch"
                    )

                with records_col:

                    back_records = st.form_submit_button(
                        "← Back to Records",
                        width="stretch"
                    )

                with app_col:

                    back_app = st.form_submit_button(
                        "← Back to Application",
                        width="stretch"
                    )

            if back_app and go_home:

                go_home()

                st.rerun()

            if back_records:

                st.session_state.employee_action = "view"

                st.rerun()

            if updated:

                bank_details, bank_error = _validated_bank_details(
                    new_bank_name,
                    new_bank_account_number,
                    new_bank_ifsc,
                    new_uan_number
                )

                if bank_error:

                    st.error(bank_error)

                elif (
                    not new_employee_id
                    or not new_employee_name
                    or not new_department
                    or not new_designation
                    or not new_location
                ):

                    st.error(
                        "Please fill all required fields."
                    )

                else:

                    new_annual_ctc = (
                        new_annual_ctc_lpa * 100000
                    )

                    try:

                        update_employee(
                            db_id,
                            employee_id,
                            new_employee_id,
                            new_employee_name,
                            new_department,
                            new_designation,
                            str(new_joining_date),
                            new_location,
                            new_employment_type,
                            new_annual_ctc,
                            new_health_insurance_opted == "Yes",
                            *bank_details
                        )

                        # Keep the salary structure in sync with the
                        # employee's new annual CTC.
                        adjusted = scale_salary_structure(
                            new_employee_id,
                            annual_ctc,
                            new_annual_ctc
                        )

                        # Log a CTC change in the revision history.
                        if (
                            abs(
                                float(new_annual_ctc or 0)
                                - float(annual_ctc or 0)
                            ) >= 0.01
                        ):

                            from modules.revisions import (
                                record_revision
                            )

                            record_revision(
                                new_employee_id,
                                str(datetime.date.today()),
                                annual_ctc,
                                new_annual_ctc,
                                "CTC updated via employee record"
                            )

                        message = "Employee updated successfully!"

                        if adjusted:

                            message += (
                                " Salary structure components "
                                "were adjusted to the new CTC."
                            )

                        st.session_state.employee_flash = message
                        st.session_state.employee_action = "view"

                        st.rerun()

                    except Exception as e:

                        st.error(
                            f"Unable to update employee: {e}"
                        )

            # -------------------------------------------------
            # LOGIN ACCOUNT
            # -------------------------------------------------

            st.divider()

            st.subheader("Login account", icon=":material/key:")

            st.caption(
                f"Sign-in username: **{employee_id}** "
                "(the Employee ID)."
            )

            with st.expander("Reset password"):

                with st.form("edit_reset_password_form"):

                    reset_pw = st.text_input(
                        "New password",
                        type="password",
                        help=(
                            "Leave blank to reset to the default "
                            "'employee123'."
                        )
                    )

                    reset_confirm = st.text_input(
                        "Confirm new password",
                        type="password"
                    )

                    reset_submitted = st.form_submit_button(
                        "Reset password",
                        width="stretch"
                    )

                if reset_submitted:

                    if reset_pw and reset_pw != reset_confirm:

                        st.error(
                            "The two passwords do not match."
                        )

                    elif reset_pw and len(reset_pw) < 6:

                        st.error("Use at least 6 characters.")

                    else:

                        try:

                            used = reset_employee_password(
                                employee_id,
                                reset_pw or None
                            )

                            st.success(
                                "Login password has been reset "
                                f"(new password: {used})."
                            )

                        except Exception as e:

                            st.error(
                                f"Unable to reset password: {e}"
                            )
