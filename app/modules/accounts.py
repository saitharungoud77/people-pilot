import re

import streamlit as st

from modules.auth import (
    list_users,
    reset_employee_password,
    update_hr_login_email,
    DEFAULT_EMPLOYEE_PASSWORD
)


# ============================================================
# LOGIN ACCOUNTS (HR ONLY)
# ============================================================
# Lets HR see every sign-in account and reset an employee's
# password (either to a custom value or back to the default).


def show_accounts_page(go_home=None):
    """Full login-accounts page, wired up by main.py."""

    st.title("Login accounts", icon=":material/key:")

    st.caption(
        "Manage sign-in accounts. HR has full access; "
        "employees can only see their own details."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="accounts_back",
        width="content"
    ):

        go_home()

        st.rerun()

    users = list_users()

    hr_accounts = [u for u in users if u["role"] == "hr"]

    employee_accounts = [
        u for u in users if u["role"] == "employee"
    ]

    # -----------------------------------------------------
    # SUMMARY
    # -----------------------------------------------------

    col1, col2 = st.columns(2)

    with col1:

        st.metric("HR accounts", len(hr_accounts), border=True)

    with col2:

        st.metric(
            "Employee accounts",
            len(employee_accounts),
            border=True
        )

    if hr_accounts:
        st.subheader("HR email sign-in", icon=":material/mail:")
        st.caption(
            "Set a company email for an HR account. Employees sign in "
            "with the work email listed on their employee profile."
        )
        hr_options = [u["username"] for u in hr_accounts]
        selected_hr = st.selectbox(
            "HR account",
            hr_options,
            key="hr_email_account"
        )
        selected_account = next(
            user for user in hr_accounts
            if user["username"] == selected_hr
        )
        with st.form("hr_login_email_form"):
            hr_email = st.text_input(
                "Company email",
                value=selected_account["login_email"] or "",
                placeholder="hr@company.com"
            )
            save_hr_email = st.form_submit_button(
                "Save HR email",
                width="stretch"
            )
        if save_hr_email:
            if hr_email and not re.fullmatch(
                r"[^@\s]+@[^@\s]+\.[^@\s]+",
                hr_email.strip()
            ):
                st.error("Enter a valid company email address.")
            else:
                try:
                    update_hr_login_email(selected_hr, hr_email)
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.success("HR company email saved.")
                    st.rerun()

    # -----------------------------------------------------
    # RESET PASSWORD
    # -----------------------------------------------------

    st.subheader(
        "Reset an employee password",
        icon=":material/lock_reset:"
    )

    if not employee_accounts:

        st.info(
            "No employee accounts yet. Add an employee first."
        )

        return

    options = [u["username"] for u in employee_accounts]

    with st.form("accounts_reset_form"):

        username = st.selectbox("Employee account", options)

        new_password = st.text_input(
            "New password",
            type="password",
            help=(
                "Leave blank to reset to the default "
                f"({DEFAULT_EMPLOYEE_PASSWORD})."
            )
        )

        confirm = st.text_input(
            "Confirm new password",
            type="password"
        )

        submitted = st.form_submit_button(
            "Reset password",
            width="stretch"
        )

    if submitted:

        if new_password and new_password != confirm:

            st.error("The two passwords do not match.")

        elif new_password and len(new_password) < 6:

            st.error("Use at least 6 characters.")

        else:

            used = reset_employee_password(
                username,
                new_password or None
            )

            if new_password:

                st.success(f"Password updated for {username}.")

            else:

                st.success(
                    f"Password for {username} reset to the "
                    f"default: **{used}**"
                )

    # -----------------------------------------------------
    # ALL ACCOUNTS
    # -----------------------------------------------------

    st.divider()

    st.subheader("All accounts", icon=":material/list:")

    st.dataframe(
        [
            {
                "Username": u["username"],
                "Role": "HR" if u["role"] == "hr" else "Employee",
                "Employee ID": u["employee_id"] or "—",
                "Login email": u["login_email"] or "—",
                "Created": u["created_at"],
            }
            for u in users
        ],
        width="stretch",
        hide_index=True
    )
