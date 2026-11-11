import datetime
from pathlib import PurePath

import streamlit as st

from database.connection import (
    create_employee_document_table,
    get_connection
)
from modules.leave import list_employees
from modules.session import require_employee


DOCUMENT_TYPES = [
    "Education certificate",
    "Experience letter",
    "Government ID",
    "Other"
]

MAX_FILE_SIZE = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}


def _validate_upload(uploaded):
    """Return a concise validation error, or None when the file is valid."""

    extension = PurePath(uploaded.name).suffix.lower()
    data = uploaded.getvalue()

    if extension not in ALLOWED_EXTENSIONS:

        return "Upload a PDF, JPG, JPEG, or PNG file."

    if not data:

        return "The selected file is empty."

    if len(data) > MAX_FILE_SIZE:

        return "Files must be 10 MB or smaller."

    signatures = {
        ".pdf": data.startswith(b"%PDF-"),
        ".jpg": data.startswith(b"\xff\xd8\xff"),
        ".jpeg": data.startswith(b"\xff\xd8\xff"),
        ".png": data.startswith(b"\x89PNG\r\n\x1a\n")
    }

    if not signatures[extension]:

        return "The file content does not match its file type."

    return None


def _add_document(employee_id, document_type, uploaded):
    data = uploaded.getvalue()
    extension = PurePath(uploaded.name).suffix.lower()
    mime = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png"
    }[extension]

    connection = get_connection()

    try:

        connection.execute(
            """
            INSERT INTO employee_documents
                (employee_id, document_type, file_name, mime, size_bytes,
                 data, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                document_type,
                PurePath(uploaded.name).name,
                mime,
                len(data),
                data,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
        )

        connection.commit()

    finally:

        connection.close()


def _employee_documents(employee_id):
    connection = get_connection()

    try:

        return connection.execute(
            """
            SELECT id, document_type, file_name, mime, size_bytes,
                   data, status, submitted_at
            FROM employee_documents
            WHERE employee_id = ?
            ORDER BY submitted_at DESC, id DESC
            """,
            (employee_id,)
        ).fetchall()

    finally:

        connection.close()


def _all_documents(employee_id=None):
    connection = get_connection()

    try:

        query = """
            SELECT d.id, d.employee_id, e.employee_name,
                   d.document_type, d.file_name, d.mime, d.size_bytes,
                   d.data, d.status, d.submitted_at
            FROM employee_documents AS d
            JOIN employees AS e ON e.employee_id = d.employee_id
        """

        params = ()

        if employee_id:

            query += " WHERE d.employee_id = ?"
            params = (employee_id,)

        query += " ORDER BY d.submitted_at DESC, d.id DESC"

        return connection.execute(query, params).fetchall()

    finally:

        connection.close()


def _set_reviewed(document_id, reviewer):
    connection = get_connection()

    try:

        connection.execute(
            """
            UPDATE employee_documents
            SET status = 'Reviewed',
                reviewed_at = ?,
                reviewed_by = ?
            WHERE id = ?
            """,
            (
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                reviewer,
                document_id
            )
        )

        connection.commit()

    finally:

        connection.close()


def _delete_document(document_id, employee_id=None):
    """Delete one document, restricting employee access to their own row."""

    connection = get_connection()

    try:

        if employee_id is None:

            cursor = connection.execute(
                "DELETE FROM employee_documents WHERE id = ?",
                (document_id,)
            )

        else:

            cursor = connection.execute(
                """
                DELETE FROM employee_documents
                WHERE id = ? AND employee_id = ?
                """,
                (document_id, employee_id)
            )

        connection.commit()

        if cursor.rowcount != 1:

            raise ValueError(
                "The document was not found or you do not have permission "
                "to delete it."
            )

    finally:

        connection.close()


def _format_size(size_bytes):
    if size_bytes >= 1024 * 1024:

        return f"{size_bytes / (1024 * 1024):.1f} MB"

    return f"{size_bytes / 1024:.0f} KB"


def _render_download(document_id, file_name, mime, data, key_prefix):
    st.download_button(
        "Download",
        data=data,
        file_name=file_name,
        mime=mime,
        key=f"{key_prefix}_download_{document_id}",
        width="stretch"
    )


def _render_delete_button(document_id, key_prefix):
    if st.button(
        "Delete",
        key=f"{key_prefix}_delete_{document_id}",
        width="stretch"
    ):

        st.session_state.document_delete_pending = document_id
        st.rerun()


def _render_delete_confirmation(document_id, employee_id, key_prefix):
    if st.session_state.get("document_delete_pending") != document_id:

        return

    st.warning(
        "Delete this document? This cannot be undone."
    )

    confirm_col, cancel_col = st.columns(2)

    with confirm_col:

        if st.button(
            "Confirm delete",
            key=f"{key_prefix}_confirm_delete_{document_id}",
            type="primary",
            width="stretch"
        ):

            try:

                _delete_document(
                    document_id,
                    employee_id=employee_id
                )

            except Exception as exc:

                st.error(f"Could not delete the document: {exc}")

            else:

                st.session_state.pop("document_delete_pending", None)
                st.rerun()

    with cancel_col:

        if st.button(
            "Cancel",
            key=f"{key_prefix}_cancel_delete_{document_id}",
            width="stretch"
        ):

            st.session_state.pop("document_delete_pending", None)
            st.rerun()


def _show_employee_documents():
    employee = require_employee()

    if employee is None:

        return

    employee_id = employee["employee_id"]

    st.title("My documents", icon=":material/folder:")
    st.caption(
        "Upload education certificates and other employment documents. "
        "HR can access files submitted here."
    )

    with st.container(border=True):

        st.subheader("Upload a document")

        with st.form("employee_document_upload_form"):

            document_type = st.selectbox(
                "Document type",
                DOCUMENT_TYPES
            )

            uploaded = st.file_uploader(
                "Choose a PDF, JPG, JPEG, or PNG file (maximum 10 MB)",
                type=["pdf", "jpg", "jpeg", "png"]
            )

            submitted = st.form_submit_button(
                "Upload document",
                type="primary",
                width="stretch"
            )

        if submitted:

            if uploaded is None:

                st.error("Choose a file to upload.")

            else:

                error = _validate_upload(uploaded)

                if error:

                    st.error(error)

                else:

                    try:

                        _add_document(
                            employee_id,
                            document_type,
                            uploaded
                        )

                    except Exception as exc:

                        st.error(f"Could not upload the document: {exc}")

                    else:

                        st.success("Document uploaded for HR review.")
                        st.rerun()

    st.subheader("Your uploaded documents")

    documents = _employee_documents(employee_id)

    if not documents:

        st.info("You have not uploaded any documents yet.")

        return

    for (
        document_id,
        document_type,
        file_name,
        mime,
        size_bytes,
        data,
        status,
        submitted_at
    ) in documents:

        with st.container(border=True):

            info, download, delete = st.columns([4, 1, 1])

            with info:

                st.markdown(f"**{document_type}** · {file_name}")
                st.caption(
                    f"{status} · Uploaded {submitted_at} · "
                    f"{_format_size(size_bytes)}"
                )

            with download:

                _render_download(
                    document_id,
                    file_name,
                    mime,
                    data,
                    "employee"
                )

            with delete:

                _render_delete_button(document_id, "employee")

            _render_delete_confirmation(
                document_id,
                employee_id,
                "employee"
            )


def show_employee_documents(go_home=None):
    create_employee_document_table()

    user = st.session_state.get("auth_user") or {}

    if user.get("role") != "hr":

        _show_employee_documents()

        return

    st.title("Employee documents", icon=":material/folder:")
    st.caption("Review and download employee-submitted documents.")

    if go_home and st.button(
        "← Back to dashboard",
        key="employee_documents_back",
        width="content"
    ):

        go_home()
        st.rerun()

    employees = list_employees()
    employee_options = {"All employees": ""}

    employee_options.update({
        f"{name} ({employee_id})": employee_id
        for employee_id, name in employees
    })

    selected = st.selectbox(
        "Filter by employee",
        list(employee_options.keys())
    )

    documents = _all_documents(employee_options[selected])

    if not documents:

        st.info("No employee documents have been uploaded.")

        return

    for (
        document_id,
        employee_id,
        employee_name,
        document_type,
        file_name,
        mime,
        size_bytes,
        data,
        status,
        submitted_at
    ) in documents:

        with st.container(border=True):

            info, download, review, delete = st.columns([4, 1, 1, 1])

            with info:

                st.markdown(
                    f"**{document_type}** · {file_name}"
                )
                st.caption(
                    f"{employee_name} ({employee_id}) · {status} · "
                    f"Submitted {submitted_at} · {_format_size(size_bytes)}"
                )

            with download:

                _render_download(
                    document_id,
                    file_name,
                    mime,
                    data,
                    "hr"
                )

            with review:

                if status != "Reviewed" and st.button(
                    "Mark reviewed",
                    key=f"review_document_{document_id}",
                    width="stretch"
                ):

                    try:

                        _set_reviewed(
                            document_id,
                            user.get("username", "HR")
                        )

                    except Exception as exc:

                        st.error(f"Could not update review status: {exc}")

                    else:

                        st.rerun()

            with delete:

                _render_delete_button(document_id, "hr")

            _render_delete_confirmation(
                document_id,
                None,
                "hr"
            )
