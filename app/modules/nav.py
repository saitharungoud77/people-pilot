import streamlit as st

from modules.auth import sign_out, verify_current_password, set_password
from modules.session import employee_details
from modules.avatar import render_avatar
from modules.settings import render_settings


# ============================================================
# CORPORATE NAVIGATION SIDEBAR
# ============================================================
# Branding plus role-aware module navigation and a sign-out
# button. The active module is highlighted (primary button).
# Clicking an item sets session_state.current_page, which main.py
# routes on.

# Navigation is grouped into collapsible blocks so the sidebar reads as
# a few short menus instead of one long list. Each entry is
# (group heading, [(label, page id, icon), ...]). The heading is an
# expander: click it to open the block and choose a module inside.
#
# HR-only AI modules are grouped together, separate from ordinary
# record-keeping screens. The floating assistant is available from its
# launcher and does not need a duplicate sidebar entry.
AI_BLOCK = "AI Assist"

HR_NAV = [
    ("Workspace", [
        ("Dashboard", "application", ":material/space_dashboard:"),
        ("Approval Center", "approvals", ":material/task_alt:"),
        ("Employees", "employee", ":material/groups:"),
        ("Employee Documents", "documents", ":material/folder:"),
        ("Onboarding & Letters", "employee_services", ":material/assignment_ind:"),
        ("Open Positions", "open_positions", ":material/work:"),
    ]),
    (AI_BLOCK, [
        ("Offer Letter", "offer_letter", ":material/document_scanner:"),
        ("Resume Analyzer", "resume", ":material/person_search:"),
        ("Hiring Pack", "hiring_pack", ":material/psychology:"),
        ("Letter Generator", "letters", ":material/description:"),
        ("Payroll Audit", "payroll_audit", ":material/troubleshoot:"),
    ]),
    ("Payroll", [
        ("Salary & payroll", "salary", ":material/payments:"),
        ("Revisions", "revisions", ":material/trending_up:"),
        ("Payslips", "payslip", ":material/receipt_long:"),
        ("Provident Fund", "epfo", ":material/account_balance:"),
        ("Income Tax", "tax", ":material/request_quote:"),
        ("Reimbursements", "reimbursements", ":material/upload_file:"),
        ("Settlement", "settlement", ":material/gavel:"),
    ]),
    ("Time Off & Workplace", [
        ("Leave", "leave", ":material/event_available:"),
        ("Attendance", "attendance", ":material/fact_check:"),
        ("Shift Timings", "shifts", ":material/schedule:"),
        ("Holidays", "holidays", ":material/celebration:"),
        ("Assets", "assets", ":material/devices:"),
        ("POSH Policy", "policies", ":material/policy:"),
    ]),
    ("Admin", [
        ("Login Accounts", "accounts", ":material/key:"),
        ("Database", "database", ":material/database:"),
    ]),
]

EMPLOYEE_NAV = [
    ("Profile", [
        ("My Overview", "application", ":material/space_dashboard:"),
        ("My Details", "profile", ":material/badge:"),
        ("My Documents", "documents", ":material/folder:"),
        ("My Onboarding & Letters", "employee_services", ":material/assignment_ind:"),
    ]),
    ("Careers", [
        ("Open Positions", "open_positions", ":material/work:"),
    ]),
    ("Payroll", [
        ("My Salary", "salary", ":material/payments:"),
        ("My Payslips", "payslips", ":material/receipt_long:"),
        ("My PF", "epfo", ":material/account_balance:"),
        ("My Tax", "tax", ":material/request_quote:"),
        ("My Reimbursements", "reimbursements", ":material/upload_file:"),
    ]),
    ("Time Off & Workplace", [
        ("My Leave", "leave", ":material/event_available:"),
        ("My Attendance", "attendance", ":material/fact_check:"),
        ("Holidays", "holidays", ":material/celebration:"),
        ("My Assets", "assets", ":material/devices:"),
        ("POSH Policy", "policies", ":material/policy:"),
    ]),
]

def render_sidebar(user):
    """Render the sidebar for the signed-in user."""

    current = st.session_state.get("current_page", "application")

    items = HR_NAV if user["role"] == "hr" else EMPLOYEE_NAV

    with st.sidebar:
        st.html("""
        <div class="ait-sidebar-brand" style="display: flex; align-items: center; gap: 11px; padding: 2px 0 12px 0;">
            <div class="ait-sidebar-brand-icon" style="
                width: 38px; height: 38px; border-radius: 10px;
                background: linear-gradient(135deg, #16856B, #116B57);
                display: grid; place-items: center; color: white;
                font-family: 'Material Symbols Rounded', sans-serif;
                font-size: 22px; box-shadow: 0 4px 10px rgba(22, 133, 107, 0.25);">
                corporate_fare
            </div>
            <div>
                <div class="ait-sidebar-brand-title" style="font-weight: 750; font-size: 1.05rem; color: #F4F4EF; letter-spacing: -0.015em; line-height: 1.2;">
                    AIT Solutions
                </div>
                <div style="display: flex; align-items: center; gap: 5px; margin-top: 2px;">
                    <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #10B981;"></span>
                    <span class="ait-sidebar-brand-label" style="font-size: 0.72rem; color: #B9C4BE; font-weight: 550; text-transform: uppercase; letter-spacing: 0.04em;">HR Platform</span>
                </div>
            </div>
        </div>
        """)

        st.divider()

        if user["role"] != "hr":
            if st.button(
                "Quick Links",
                key="nav_quick_links",
                icon=":material/bolt:",
                width="stretch",
                type="primary" if current == "quick_links" else "secondary",
            ):
                st.session_state.current_page = "quick_links"
                st.rerun()

            st.markdown("#### Health Benefits")
            st.link_button(
                "Pazcare Sign In",
                "https://app.pazcare.com/login",
                icon=":material/health_and_safety:",
                width="stretch",
            )

            st.divider()

        for group, entries in items:

            # Each block is a collapsible section: click the heading to
            # open it, then pick a module inside. The block that holds
            # the page you are on opens itself, so the menu never hides
            # where you are.
            pages = [page for _, page, _ in entries]

            with st.expander(group, expanded=current in pages):

                for label, page, icon in entries:

                    if st.button(
                        label,
                        key=f"nav_{page}",
                        icon=icon,
                        width="stretch",
                        type="primary" if page == current else "secondary"
                    ):

                        st.session_state.current_page = page

                        st.rerun()

                if group == "Payroll":
                    st.caption("Portals")
                    st.link_button(
                        "Pazcare Login",
                        "https://app.pazcare.com/login",
                        icon=":material/open_in_new:",
                        width="stretch",
                    )

        st.space("medium")
        st.divider()

        with st.container(border=True, key="lift_sidebar_user"):

            role_label = (
                "HR Administrator"
                if user["role"] == "hr"
                else "Employee"
            )

            if user["role"] != "hr" and user.get("employee_id"):

                employee = employee_details(user["employee_id"])

                display_name = (
                    employee["employee_name"]
                    if employee
                    else user["username"]
                )

                col_av, col_info = st.columns([1, 2.2], vertical_alignment="center")

                with col_av:
                    render_avatar(
                        display_name,
                        user["employee_id"],
                        size=44
                    )

                with col_info:
                    st.markdown(f"**{display_name}**")
                    st.caption(f"{role_label} · `{user['employee_id']}`")

            else:

                col_ic, col_info = st.columns([1, 2.5], vertical_alignment="center")

                with col_ic:
                    st.html("""
                    <div style="width: 38px; height: 38px; border-radius: 50%; background: #E8F2ED; color: #116B57; display: grid; place-items: center; font-family: 'Material Symbols Rounded', sans-serif; font-size: 20px;">
                        admin_panel_settings
                    </div>
                    """)

                with col_info:
                    st.markdown(f"**{user['username']}**")
                    st.caption(role_label)

            st.space("small")

            signout_col, pass_col = st.columns([1, 1.5])

            with signout_col:
                if st.button(
                    "Sign Out",
                    key="nav_sign_out",
                    icon=":material/logout:",
                    width="stretch"
                ):
                    sign_out()

            with pass_col:
                with st.popover(
                    "Password",
                    width="stretch",
                    type="secondary",
                ):
                    with st.form("sidebar_change_password"):
                        current = st.text_input(
                            "Current Password",
                            type="password"
                        )
                        new_password = st.text_input(
                            "New Password",
                            type="password"
                        )
                        confirm = st.text_input(
                            "Confirm New Password",
                            type="password"
                        )
                        saved = st.form_submit_button(
                            "Update Password",
                            width="stretch"
                        )

                    if saved:
                        if not verify_current_password(
                            user["username"],
                            current
                        ):
                            st.error("Current password is incorrect.")
                        elif len(new_password) < 6:
                            st.error("Use at least 6 characters.")
                        elif new_password != confirm:
                            st.error("Passwords do not match.")
                        else:
                            set_password(
                                user["username"],
                                new_password
                            )
                            st.success("Password updated.")

        st.space("small")
        render_settings(user, key="sidebar_settings")
