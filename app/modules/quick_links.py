"""Employee shortcuts displayed in the main content area."""

import streamlit as st


EMPLOYEE_QUICK_LINKS = [
    ("My Payslips", "payslips", ":material/receipt_long:"),
    ("My Leave", "leave", ":material/event_available:"),
    ("My Tax", "tax", ":material/request_quote:"),
    ("My PF", "epfo", ":material/account_balance:"),
    ("Attendance", "attendance", ":material/fact_check:"),
    ("Reimbursements", "reimbursements", ":material/receipt:"),
    ("Holidays", "holidays", ":material/celebration:"),
    ("My Assets", "assets", ":material/inventory_2:"),
    ("My Documents", "documents", ":material/folder:"),
    ("Policies", "policies", ":material/policy:"),
    ("My Details", "profile", ":material/person:"),
]


def show_quick_links():
    """Render employee shortcuts as cards in the main app area."""

    st.title("Quick Links")
    st.caption("Choose a shortcut to open that section of your employee portal.")

    ordered_links = sorted(EMPLOYEE_QUICK_LINKS, key=lambda link: link[0].casefold())

    for row_start in range(0, len(ordered_links), 3):
        columns = st.columns(3)

        for column, (label, page, icon) in zip(
            columns,
            ordered_links[row_start:row_start + 3],
        ):
            with column:
                with st.container(border=True):
                    if st.button(
                        label,
                        key=f"dashboard_quick_{page}",
                        icon=icon,
                        width="stretch",
                    ):
                        st.session_state.current_page = page
                        st.rerun()
