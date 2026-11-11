import streamlit as st

from database.connection import create_employee_service_tables
from modules.leave import decide_request, get_requests
from modules.reimbursements import (
    approve_reimbursement,
    list_reimbursements,
    reject_reimbursement,
    request_reimbursement_information,
)
from modules.employee_services import (
    list_letter_requests,
    update_letter_request,
)
from modules.request_tracking import get_request_history


def _review_leave(request, reviewer):
    with st.container(border=True):
        st.markdown(
            f"**Leave · {request['employee_name']} "
            f"({request['employee_id']})**"
        )
        st.write(
            f"{request['leave_type']} · {request['from_date']} to "
            f"{request['to_date']} · {request['days']:g} day(s)"
        )
        st.caption(f"Reason: {request.get('reason') or 'Not provided'}")
        if request.get("employee_reply"):
            st.info(f"Employee response: {request['employee_reply']}")
        if request.get("decision_note"):
            st.caption(f"Previous HR note: {request['decision_note']}")

        with st.form(f"approval_leave_{request['id']}"):
            note = st.text_input(
                "Comment / information needed",
                key=f"approval_leave_note_{request['id']}"
            )
            approve_col, reject_col, info_col = st.columns(3)
            approve = approve_col.form_submit_button(
                "Approve", type="primary", width="stretch"
            )
            reject = reject_col.form_submit_button(
                "Reject", width="stretch"
            )
            ask_info = info_col.form_submit_button(
                "Request info", width="stretch"
            )

        status = (
            "Approved" if approve
            else "Rejected" if reject
            else "Needs information" if ask_info
            else None
        )
        if status:
            if status == "Needs information" and not note.strip():
                st.error("Add a note explaining what information is needed.")
            else:
                decide_request(request["id"], status, reviewer, note)
                st.rerun()


def _review_reimbursement(claim, reviewer):
    with st.container(border=True):
        st.markdown(
            f"**Reimbursement · {claim['employee_id']} · "
            f"{claim['category']} · ₹{claim['amount']:,.2f}**"
        )
        st.write(
            f"Expense date: {claim['expense_date']} · "
            f"{claim.get('description') or 'No description'}"
        )
        if claim.get("employee_reply"):
            st.info(f"Employee response: {claim['employee_reply']}")
        if claim.get("decision_note"):
            st.caption(f"Previous HR note: {claim['decision_note']}")
        if claim.get("data"):
            st.download_button(
                "Download receipt",
                data=claim["data"],
                file_name=claim["file_name"] or f"claim-{claim['id']}",
                mime=claim["mime"] or "application/octet-stream",
                key=f"approval_receipt_{claim['id']}"
            )

        with st.form(f"approval_reimbursement_{claim['id']}"):
            note = st.text_input(
                "Comment / information needed",
                key=f"approval_reimbursement_note_{claim['id']}"
            )
            approve_col, reject_col, info_col = st.columns(3)
            approve = approve_col.form_submit_button(
                "Approve", type="primary", width="stretch"
            )
            reject = reject_col.form_submit_button(
                "Reject", width="stretch"
            )
            ask_info = info_col.form_submit_button(
                "Request info", width="stretch"
            )

        if ask_info:
            try:
                request_reimbursement_information(
                    claim["id"],
                    decided_by=reviewer,
                    note=note
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.rerun()
        elif approve:
            approve_reimbursement(
                claim["id"],
                decided_by=reviewer,
                note=note
            )
            st.rerun()
        elif reject:
            reject_reimbursement(
                claim["id"],
                decided_by=reviewer,
                note=note
            )
            st.rerun()


def _review_letter(request, reviewer):
    with st.container(border=True):
        st.markdown(
            f"**Letter · {request['employee_name']} "
            f"({request['employee_id']}) · {request['letter_type']}**"
        )
        st.caption(
            f"Purpose: {request['purpose'] or 'Not specified'} · "
            f"Requested {request['requested_at']}"
        )
        if request.get("employee_reply"):
            st.info(f"Employee response: {request['employee_reply']}")
        if request.get("hr_note"):
            st.caption(f"Previous HR note: {request['hr_note']}")
        with st.form(f"approval_letter_{request['id']}"):
            note = st.text_input(
                "Comment / information needed",
                key=f"approval_letter_note_{request['id']}"
            )
            issue_col, reject_col, info_col = st.columns(3)
            issue = issue_col.form_submit_button(
                "Issue letter", type="primary", width="stretch"
            )
            reject = reject_col.form_submit_button(
                "Reject", width="stretch"
            )
            ask_info = info_col.form_submit_button(
                "Request info", width="stretch"
            )
        status = (
            "Issued" if issue
            else "Rejected" if reject
            else "Needs information" if ask_info
            else None
        )
        if status:
            try:
                update_letter_request(
                    request["id"], status, reviewer, note
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.rerun()


def show_approval_center(go_home=None):
    """HR view of pending leave and reimbursement approvals and history."""

    user = st.session_state.get("auth_user") or {}
    if user.get("role") != "hr":
        st.error("The approval center is only available to HR.")
        return

    create_employee_service_tables()
    reviewer = user.get("username") or "HR"
    leave = get_requests()
    claims = list_reimbursements()
    letters = list_letter_requests()
    pending_leave = [
        row for row in leave
        if row["status"] in ("Pending", "Needs information")
    ]
    pending_claims = [
        row for row in claims
        if row["status"] in ("Pending", "Needs information")
    ]
    pending_letters = [
        row for row in letters
        if row["status"] in ("Pending", "Needs information")
    ]

    st.title("Approval center", icon=":material/task_alt:")
    st.caption(
        "Review leave, reimbursement, and employee letter requests "
        "in one place. "
        "Employees receive in-app notifications for decisions and "
        "requests for more information."
    )
    if go_home and st.button("← Back to dashboard", key="approval_back"):
        go_home()
        st.rerun()

    metric_cols = st.columns(3)
    metric_cols[0].metric("Leave awaiting action", len(pending_leave))
    metric_cols[1].metric(
        "Reimbursements awaiting action", len(pending_claims)
    )
    metric_cols[2].metric("Letters awaiting action", len(pending_letters))

    pending_tab, history_tab = st.tabs(["Needs action", "Request history"])
    with pending_tab:
        leave_tab, reimbursement_tab, letter_tab = st.tabs(
            ["Leave", "Reimbursements", "Letters"]
        )
        with leave_tab:
            if not pending_leave:
                st.info("No leave requests need action.")
            for request in pending_leave:
                _review_leave(request, reviewer)
        with reimbursement_tab:
            if not pending_claims:
                st.info("No reimbursement claims need action.")
            for claim in pending_claims:
                _review_reimbursement(claim, reviewer)
        with letter_tab:
            if not pending_letters:
                st.info("No employee letter requests need action.")
            for request in pending_letters:
                _review_letter(request, reviewer)

    with history_tab:
        st.subheader("Leave history")
        if leave:
            st.dataframe(
                [
                    {
                        "Employee": row["employee_name"],
                        "Employee ID": row["employee_id"],
                        "Leave": row["leave_type"],
                        "Dates": f"{row['from_date']} – {row['to_date']}",
                        "Status": row["status"],
                        "Reviewer": row.get("decided_by") or "Awaiting review",
                        "Comment": row.get("decision_note") or "",
                        "Employee response": row.get("employee_reply") or "",
                    }
                    for row in leave
                ],
                width="stretch",
                hide_index=True
            )
        else:
            st.info("No leave requests yet.")

        st.subheader("Reimbursement history")
        if claims:
            st.dataframe(
                [
                    {
                        "Employee ID": row["employee_id"],
                        "Category": row["category"],
                        "Amount": row["amount"],
                        "Status": row["status"],
                        "Reviewer": row.get("decided_by") or "Awaiting review",
                        "Comment": row.get("decision_note") or "",
                        "Employee response": row.get("employee_reply") or "",
                    }
                    for row in claims
                ],
                width="stretch",
                hide_index=True
            )
        else:
            st.info("No reimbursement claims yet.")

        st.subheader("Letter request history")
        if letters:
            st.dataframe(
                [
                    {
                        "Employee": row["employee_name"],
                        "Employee ID": row["employee_id"],
                        "Letter": row["letter_type"],
                        "Purpose": row["purpose"],
                        "Status": row["status"],
                        "Reviewer": row.get("reviewed_by") or "Awaiting review",
                        "Comment": row.get("hr_note") or "",
                        "Employee response": row.get("employee_reply") or "",
                    }
                    for row in letters
                ],
                width="stretch",
                hide_index=True
            )
        else:
            st.info("No employee letter requests yet.")

        st.subheader("Status change timeline")
        timeline = get_request_history()
        if timeline:
            st.dataframe(
                [
                    {
                        "Type": row["request_type"],
                        "Request ID": row["request_id"],
                        "Employee ID": row["employee_id"],
                        "Status": row["status"],
                        "Updated by": row["actor"] or "—",
                        "Comment": row["comment"],
                        "Time": row["created_at"],
                    }
                    for row in timeline
                ],
                width="stretch",
                hide_index=True
            )
        else:
            st.info("No status changes have been recorded yet.")
