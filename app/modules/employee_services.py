import datetime

import streamlit as st

from database.connection import (
    create_employee_service_tables,
    create_employee_document_table,
    get_connection,
)
from modules.leave import list_employees
from modules.notifications import notify_employee, notify_hr
from modules.request_tracking import record_request_event
from modules.session import require_employee


LETTER_TYPES = [
    "Employment verification",
    "Salary certificate",
    "Experience letter",
]

ONBOARDING_TASKS = [
    ("Complete personal details", "Employee"),
    ("Confirm work email and emergency contact", "Employee"),
    ("Upload government ID", "Employee"),
    ("Upload education certificate", "Employee"),
    ("Upload experience or offer document", "Employee"),
    ("Review company policies", "Employee"),
    ("Confirm payroll details with HR", "Employee"),
    ("Verify employee profile", "HR"),
    ("Review submitted documents", "HR"),
]


def _stamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _employee_record(employee_id):
    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT employee_id, employee_name, department, designation,
                   joining_date, employment_type, annual_ctc, exit_date
            FROM employees
            WHERE employee_id = ?
            """,
            (employee_id,)
        ).fetchone()
    finally:
        connection.close()
    if not row:
        return None
    keys = (
        "employee_id", "employee_name", "department", "designation",
        "joining_date", "employment_type", "annual_ctc", "exit_date"
    )
    return dict(zip(keys, row))


def _seed_onboarding(employee_id):
    connection = get_connection()
    try:
        connection.executemany(
            """
            INSERT OR IGNORE INTO onboarding_tasks
                (employee_id, task_title, task_type)
            VALUES (?, ?, ?)
            """,
            [
                (employee_id, title, task_type)
                for title, task_type in ONBOARDING_TASKS
            ]
        )
        connection.commit()
    finally:
        connection.close()


def _tasks(employee_id):
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT id, task_title, task_type, status, employee_note,
                   hr_note, completed_by, completed_at
            FROM onboarding_tasks
            WHERE employee_id = ?
            ORDER BY id
            """,
            (employee_id,)
        ).fetchall()
    finally:
        connection.close()
    keys = (
        "id", "task_title", "task_type", "status", "employee_note",
        "hr_note", "completed_by", "completed_at"
    )
    return [dict(zip(keys, row)) for row in rows]


def _validate_employee_task(employee_id, title):
    profile_requirements = {
        "Complete personal details": (
            "dob", "gender", "mobile_number", "address",
            "emergency_contact_name", "emergency_contact_number"
        ),
        "Confirm work email and emergency contact": (
            "work_email", "emergency_contact_name",
            "emergency_contact_number"
        ),
    }
    if title in profile_requirements:
        columns = profile_requirements[title]
        connection = get_connection()
        try:
            row = connection.execute(
                f"SELECT {', '.join(columns)} FROM employees "
                "WHERE employee_id = ?",
                (employee_id,)
            ).fetchone()
        finally:
            connection.close()
        if not row or any(not str(value or "").strip() for value in row):
            raise ValueError(
                "Complete the required fields in My details before "
                "submitting this task."
            )
        return

    document_types = {
        "Upload government ID": ("Government ID",),
        "Upload education certificate": ("Education certificate",),
        "Upload experience or offer document": (
            "Experience letter", "Other"
        ),
    }
    if title in document_types:
        create_employee_document_table()
        placeholders = ", ".join("?" for _ in document_types[title])
        connection = get_connection()
        try:
            exists = connection.execute(
                f"""
                SELECT 1 FROM employee_documents
                WHERE employee_id = ?
                  AND document_type IN ({placeholders})
                LIMIT 1
                """,
                (employee_id, *document_types[title])
            ).fetchone()
        finally:
            connection.close()
        if not exists:
            raise ValueError(
                "Upload this document from My documents before submitting "
                "the checklist task."
            )


def _update_task(task_id, employee_id, status, note, actor, is_hr):
    if status not in ("Submitted", "Complete", "Needs update", "Pending"):
        raise ValueError("Invalid onboarding task status.")

    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT task_type, status, task_title
            FROM onboarding_tasks
            WHERE id = ? AND employee_id = ?
            """,
            (task_id, employee_id)
        ).fetchone()
        if not row:
            raise ValueError("That onboarding task could not be found.")
        if not is_hr:
            if row[0] != "Employee" or status != "Submitted":
                raise ValueError("Employees can only submit their own tasks.")
            if row[1] not in ("Pending", "Needs update"):
                raise ValueError("This task is not awaiting your update.")
            _validate_employee_task(employee_id, row[2])

        stamp = _stamp() if status in ("Submitted", "Complete") else ""
        connection.execute(
            """
            UPDATE onboarding_tasks
            SET status = ?,
                employee_note = CASE WHEN ? = 0 THEN ? ELSE employee_note END,
                hr_note = CASE WHEN ? = 1 THEN ? ELSE hr_note END,
                completed_by = ?,
                completed_at = ?
            WHERE id = ? AND employee_id = ?
            """,
            (
                status,
                int(is_hr),
                note.strip(),
                int(is_hr),
                note.strip(),
                actor,
                stamp,
                task_id,
                employee_id
            )
        )
        connection.commit()
    finally:
        connection.close()

    if is_hr:
        notify_employee(
            employee_id,
            f"Onboarding task {status.lower()}",
            f"{note.strip() or 'An onboarding task was updated by HR.'}",
            category="System",
            page="employee_services"
        )
    else:
        notify_hr(
            "Onboarding task submitted",
            f"{employee_id} submitted '{row[2]}'"
            + (f": {note.strip()}" if note.strip() else "."),
            category="System",
            page="employee_services"
        )


def _submit_letter_request(employee, letter_type, purpose):
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            INSERT INTO employee_letter_requests
                (employee_id, letter_type, purpose, requested_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                employee["employee_id"],
                letter_type,
                purpose.strip(),
                _stamp()
            )
        )
        connection.commit()
        request_id = cursor.lastrowid
    finally:
        connection.close()

    notify_hr(
        "Employee letter requested",
        f"{employee['employee_name']} ({employee['employee_id']}) "
        f"requested a {letter_type.lower()}.",
        category="Message",
        page="employee_services"
    )
    record_request_event(
        "Letter",
        request_id,
        employee["employee_id"],
        "Pending",
        actor=employee["employee_id"],
        comment=purpose
    )
    return request_id


def list_letter_requests(employee_id=None):
    connection = get_connection()
    try:
        query = """
            SELECT r.id, r.employee_id, e.employee_name, r.letter_type,
                   r.purpose, r.status, r.hr_note, r.requested_at,
                          r.reviewed_at, r.reviewed_by, r.employee_reply
            FROM employee_letter_requests AS r
            JOIN employees AS e ON e.employee_id = r.employee_id
        """
        params = ()
        if employee_id:
            query += " WHERE r.employee_id = ?"
            params = (employee_id,)
        query += " ORDER BY r.id DESC"
        rows = connection.execute(query, params).fetchall()
    finally:
        connection.close()
    keys = (
        "id", "employee_id", "employee_name", "letter_type", "purpose",
        "status", "hr_note", "requested_at", "reviewed_at", "reviewed_by",
        "employee_reply"
    )
    return [dict(zip(keys, row)) for row in rows]


def update_letter_request(request_id, status, reviewer, note):
    if status not in ("Issued", "Rejected", "Needs information"):
        raise ValueError("Invalid letter request status.")

    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT employee_id, letter_type, status
            FROM employee_letter_requests
            WHERE id = ?
            """,
            (request_id,)
        ).fetchone()
        if not row:
            raise ValueError("That letter request could not be found.")
        if row[2] not in ("Pending", "Needs information"):
            raise ValueError("This letter request has already been decided.")
        if status == "Needs information" and not note.strip():
            raise ValueError("Explain what information is needed.")
        connection.execute(
            """
            UPDATE employee_letter_requests
            SET status = ?, hr_note = ?, employee_reply = '',
                reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
            """,
            (status, note.strip(), _stamp(), reviewer, request_id)
        )
        connection.commit()
    finally:
        connection.close()

    notify_employee(
        row[0],
        f"{row[1]} request {status.lower()}",
        note.strip() or f"Your requested {row[1].lower()} is ready to download.",
        category="Message",
        page="employee_services"
    )
    record_request_event(
        "Letter",
        request_id,
        row[0],
        status,
        actor=reviewer,
        comment=note
    )


def _reply_to_letter_request(request_id, employee_id, reply):
    reply = (reply or "").strip()
    if not reply:
        raise ValueError("Enter a response before submitting.")
    connection = get_connection()
    try:
        cursor = connection.execute(
            """
            UPDATE employee_letter_requests
            SET employee_reply = ?, status = 'Pending',
                reviewed_at = '', reviewed_by = ''
            WHERE id = ? AND employee_id = ?
              AND status = 'Needs information'
            """,
            (reply, request_id, employee_id)
        )
        connection.commit()
        updated = cursor.rowcount > 0
    finally:
        connection.close()
    if updated:
        record_request_event(
            "Letter",
            request_id,
            employee_id,
            "Pending",
            actor=employee_id,
            comment=reply
        )
        notify_hr(
            "Employee responded to letter request",
            f"{employee_id} replied to letter request #{request_id}: {reply}",
            category="Message",
            page="employee_services"
        )
    return updated


def _pdf_safe(value):
    return str(value or "").encode("latin-1", "replace").decode("latin-1")


def _letter_pdf(request):
    from fpdf import FPDF

    employee = _employee_record(request["employee_id"])
    if not employee:
        raise ValueError("The employee record for this letter is missing.")

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_text_color(49, 46, 129)
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "AIT Solutions", ln=True)
    pdf.set_text_color(30, 41, 59)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 12, _pdf_safe(request["letter_type"]), ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.ln(8)
    pdf.cell(0, 8, _pdf_safe(f"Date: {datetime.date.today():%d %B %Y}"), ln=True)
    pdf.ln(8)

    name = _pdf_safe(employee["employee_name"])
    employee_id = _pdf_safe(employee["employee_id"])
    joining = _pdf_safe(employee["joining_date"])
    role = _pdf_safe(employee["designation"])
    department = _pdf_safe(employee["department"])

    if request["letter_type"] == "Employment verification":
        body = (
            f"This letter confirms that {name} (Employee ID: {employee_id}) "
            f"is employed by AIT Solutions as {role} in {department}. "
            f"The employment start date on record is {joining}."
        )
    elif request["letter_type"] == "Salary certificate":
        body = (
            f"This is to certify that {name} (Employee ID: {employee_id}) "
            f"is employed by AIT Solutions as {role} in {department}. "
            f"The annual CTC recorded by the company is "
            f"INR {float(employee['annual_ctc'] or 0):,.2f}."
        )
    else:
        end_date = employee.get("exit_date")
        if end_date:
            body = (
                f"This letter confirms that {name} (Employee ID: "
                f"{employee_id}) worked with AIT Solutions as {role} in "
                f"{department} from {joining} to {_pdf_safe(end_date)}."
            )
        else:
            body = (
                f"This letter confirms that {name} (Employee ID: "
                f"{employee_id}) has been employed by AIT Solutions as "
                f"{role} in {department} from {joining} to the present."
            )

    pdf.multi_cell(0, 7, _pdf_safe(body))
    if request.get("purpose"):
        pdf.ln(5)
        pdf.multi_cell(
            0, 7, _pdf_safe(f"Purpose: {request['purpose']}")
        )
    pdf.ln(18)
    pdf.cell(0, 7, "For AIT Solutions", ln=True)
    pdf.ln(15)
    pdf.cell(0, 7, _pdf_safe(f"Authorized by: {request.get('reviewed_by') or 'HR'}"))
    return bytes(pdf.output())


def _employee_letters_panel(employee):
    st.subheader("Request an employment letter")
    with st.form("employee_letter_request"):
        letter_type = st.selectbox("Letter type", LETTER_TYPES)
        purpose = st.text_input(
            "Purpose (optional)",
            placeholder="e.g. bank, rental application"
        )
        submit = st.form_submit_button("Request letter", type="primary")
    if submit:
        request_id = _submit_letter_request(employee, letter_type, purpose)
        st.success(f"Letter request #{request_id} sent to HR.")

    st.subheader("My letter requests")
    requests = list_letter_requests(employee["employee_id"])
    if not requests:
        st.info("You have not requested a letter yet.")
    for request in requests:
        with st.container(border=True):
            st.markdown(
                f"**{request['letter_type']}** · {request['status']}"
            )
            st.caption(
                f"Requested {request['requested_at']} · "
                f"Reviewer: {request['reviewed_by'] or 'Awaiting HR'}"
            )
            if request["hr_note"]:
                st.info(request["hr_note"])
            if request["employee_reply"]:
                st.caption(f"Your response: {request['employee_reply']}")
            if request["status"] == "Needs information":
                with st.form(f"letter_reply_{request['id']}"):
                    reply = st.text_area(
                        "Reply to HR",
                        key=f"letter_reply_text_{request['id']}"
                    )
                    submitted = st.form_submit_button("Send response")
                if submitted:
                    try:
                        updated = _reply_to_letter_request(
                            request["id"],
                            employee["employee_id"],
                            reply
                        )
                    except ValueError as error:
                        st.error(str(error))
                    else:
                        if updated:
                            st.success("Your response was sent to HR.")
                            st.rerun()
                        st.warning(
                            "This letter request is no longer awaiting information."
                        )
            if request["status"] == "Issued":
                st.download_button(
                    "Download letter",
                    data=_letter_pdf(request),
                    file_name=(
                        f"{request['letter_type'].lower().replace(' ', '_')}_"
                        f"{employee['employee_id']}.pdf"
                    ),
                    mime="application/pdf",
                    key=f"letter_download_{request['id']}"
                )


def _employee_onboarding(employee_id):
    _seed_onboarding(employee_id)
    st.subheader("My onboarding checklist")
    st.caption(
        "Upload requested files from My documents. Mark your tasks "
        "complete when finished; HR will confirm the checklist."
    )
    tasks = _tasks(employee_id)
    done = sum(task["status"] == "Complete" for task in tasks)
    st.progress(done / len(tasks) if tasks else 0, text=f"{done}/{len(tasks)} confirmed")
    for task in tasks:
        with st.container(border=True):
            st.markdown(
                f"**{task['task_title']}** · {task['status']}"
            )
            st.caption(
                (
                    "Update your profile details or upload the requested "
                    "file from the matching self-service page."
                    if task["task_type"] == "Employee"
                    else "HR will complete this task."
                )
            )
            if task["employee_note"]:
                st.caption(f"Your note: {task['employee_note']}")
            if task["hr_note"]:
                st.info(f"HR: {task['hr_note']}")
            if (
                task["task_type"] == "Employee"
                and task["status"] in ("Pending", "Needs update")
            ):
                with st.form(f"onboarding_submit_{task['id']}"):
                    note = st.text_input(
                        "Optional note",
                        key=f"onboarding_employee_note_{task['id']}"
                    )
                    submitted = st.form_submit_button("Mark complete")
                if submitted:
                    try:
                        _update_task(
                            task["id"],
                            employee_id,
                            "Submitted",
                            note,
                            employee_id,
                            False
                        )
                    except ValueError as error:
                        st.error(str(error))
                    else:
                        st.rerun()


def _hr_letters():
    requests = list_letter_requests()
    pending = [
        row for row in requests
        if row["status"] in ("Pending", "Needs information")
    ]
    st.subheader(f"Letter requests ({len(pending)} awaiting action)")
    if not pending:
        st.info("No employee letter requests need review.")
    reviewer = (st.session_state.get("auth_user") or {}).get("username", "HR")
    for request in pending:
        with st.container(border=True):
            st.markdown(
                f"**{request['employee_name']} ({request['employee_id']})** · "
                f"{request['letter_type']}"
            )
            st.caption(
                f"Purpose: {request['purpose'] or 'Not specified'} · "
                f"Requested {request['requested_at']}"
            )
            if request["employee_reply"]:
                st.info(f"Employee response: {request['employee_reply']}")
            with st.form(f"hr_letter_{request['id']}"):
                note = st.text_input(
                    "Note to employee",
                    key=f"hr_letter_note_{request['id']}"
                )
                issue_col, info_col, reject_col = st.columns(3)
                issue = issue_col.form_submit_button(
                    "Issue letter", type="primary", width="stretch"
                )
                ask_info = info_col.form_submit_button(
                    "Need info", width="stretch"
                )
                reject = reject_col.form_submit_button(
                    "Reject", width="stretch"
                )
            selected = (
                "Issued" if issue
                else "Needs information" if ask_info
                else "Rejected" if reject
                else None
            )
            if selected:
                try:
                    update_letter_request(
                        request["id"], selected, reviewer, note
                    )
                except ValueError as error:
                    st.error(str(error))
                else:
                    st.rerun()


def _hr_onboarding():
    employees = list_employees()
    if not employees:
        st.info("Add an employee before managing onboarding.")
        return
    options = {
        f"{name} ({employee_id})": employee_id
        for employee_id, name in employees
    }
    selected = st.selectbox(
        "Employee",
        list(options),
        key="onboarding_employee_filter"
    )
    employee_id = options[selected]
    _seed_onboarding(employee_id)
    tasks = _tasks(employee_id)
    completed = sum(task["status"] == "Complete" for task in tasks)
    st.progress(
        completed / len(tasks) if tasks else 0,
        text=f"{completed}/{len(tasks)} tasks confirmed"
    )
    reviewer = (st.session_state.get("auth_user") or {}).get("username", "HR")
    for task in tasks:
        with st.container(border=True):
            st.markdown(
                f"**{task['task_title']}** · {task['status']} "
                f"· {task['task_type']}"
            )
            if task["employee_note"]:
                st.caption(f"Employee: {task['employee_note']}")
            if task["hr_note"]:
                st.caption(f"HR note: {task['hr_note']}")
            can_review = (
                task["status"] == "Submitted"
                or (
                    task["task_type"] == "HR"
                    and task["status"] in ("Pending", "Needs update")
                )
                or (
                    task["task_type"] == "Employee"
                    and task["status"] == "Needs update"
                )
            )
            if can_review:
                with st.form(f"onboarding_review_{task['id']}"):
                    note = st.text_input(
                        "HR note",
                        key=f"onboarding_hr_note_{task['id']}"
                    )
                    complete_col, update_col = st.columns(2)
                    complete = complete_col.form_submit_button(
                        "Confirm complete",
                        type="primary",
                        width="stretch"
                    )
                    needs_update = update_col.form_submit_button(
                        "Needs update",
                        width="stretch"
                    )
                if complete or needs_update:
                    _update_task(
                        task["id"],
                        employee_id,
                        "Complete" if complete else "Needs update",
                        note,
                        reviewer,
                        True
                    )
                    st.rerun()


def show_employee_services(go_home=None):
    """Employee self-service letters and HR-managed onboarding."""

    create_employee_service_tables()
    user = st.session_state.get("auth_user") or {}
    if go_home and st.button(
        "← Back to dashboard",
        key="employee_services_back"
    ):
        go_home()
        st.rerun()

    if user.get("role") == "hr":
        st.title("Employee services", icon=":material/assignment_ind:")
        letters_tab, onboarding_tab = st.tabs(
            ["Letter requests", "Onboarding"]
        )
        with letters_tab:
            _hr_letters()
        with onboarding_tab:
            _hr_onboarding()
        return

    employee = require_employee()
    if not employee:
        return
    st.title("My employee services", icon=":material/assignment_ind:")
    letters_tab, onboarding_tab = st.tabs(
        ["Letters", "Onboarding checklist"]
    )
    with letters_tab:
        _employee_letters_panel(employee)
    with onboarding_tab:
        _employee_onboarding(employee["employee_id"])
