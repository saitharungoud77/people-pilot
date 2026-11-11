import os

import pandas as pd
import streamlit as st

from database.connection import DATABASE_NAME, get_connection


# ============================================================
# DATABASE VIEWER
# ============================================================
# Read-only browser for the SQLite data (employees, salary
# structures, payslips). Nothing here writes to the database.

TABLE_LABELS = {
    "employees": "Employees",
    "salary_structures": "Salary Structures",
    "payslips": "Payslips",
}


def _list_tables():
    """Names of the user tables in the database."""

    conn = get_connection()

    try:

        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()

        return [row[0] for row in rows]

    finally:

        conn.close()


def _read_table(table):
    """Every row of a table as a DataFrame."""

    conn = get_connection()

    try:

        return pd.read_sql_query(
            f"SELECT * FROM {table}",
            conn
        )

    finally:

        conn.close()


def _schema(table):
    """Column definitions for a table."""

    conn = get_connection()

    try:

        cursor = conn.execute(
            f"PRAGMA table_info({table})"
        )

        rows = cursor.fetchall()

        columns = [d[0] for d in cursor.description]

        return pd.DataFrame(rows, columns=columns)

    finally:

        conn.close()


def show_database_page(go_home=None):
    """Full database page, wired up by main.py."""

    st.title("Database viewer", icon=":material/database:")

    st.caption(
        "Read-only view of the SQLite data behind the application."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="database_back",
        width="content"
    ):

        go_home()

        st.rerun()

    # -----------------------------------------------------
    # DATABASE FILE
    # -----------------------------------------------------

    exists = os.path.exists(DATABASE_NAME)

    size_kb = (
        os.path.getsize(DATABASE_NAME) / 1024
        if exists
        else 0
    )

    st.caption(f"{DATABASE_NAME}")

    tables = _list_tables()

    row_counts = {}

    for table in tables:

        row_counts[table] = len(_read_table(table))

    total_rows = sum(row_counts.values())

    m1, m2, m3 = st.columns(3)

    with m1:

        st.metric("Tables", len(tables))

    with m2:

        st.metric("Total Rows", total_rows)

    with m3:

        st.metric("File Size", f"{size_kb:,.1f} KB")

    st.divider()

    # -----------------------------------------------------
    # TABLE BROWSER
    # -----------------------------------------------------

    labels = {
        TABLE_LABELS.get(table, table): table
        for table in tables
    }

    selected_label = st.selectbox(
        "Select Table",
        list(labels.keys())
    )

    table = labels[selected_label]

    frame = _read_table(table)

    st.caption(
        f"{len(frame)} row(s) in `{table}`"
    )

    if frame.empty:

        st.info("This table has no rows yet.")

    else:

        st.dataframe(
            frame,
            width="stretch",
            hide_index=True
        )

    # -----------------------------------------------------
    # SCHEMA
    # -----------------------------------------------------

    with st.expander("Table schema"):

        st.dataframe(
            _schema(table),
            width="stretch",
            hide_index=True
        )

    # -----------------------------------------------------
    # READ-ONLY SQL
    # -----------------------------------------------------

    with st.expander("Run a read-only SQL query"):

        query = st.text_area(
            "SQL (SELECT only)",
            value=f"SELECT * FROM {table} LIMIT 50;",
            height=110
        )

        if st.button("▶ Run query", key="db_run_query"):

            if not query.strip().lower().startswith(
                ("select", "with")
            ):

                st.error(
                    "Only read-only SELECT queries are allowed."
                )

            else:

                conn = get_connection()

                try:

                    result = pd.read_sql_query(
                        query,
                        conn
                    )

                    st.success(
                        f"{len(result)} row(s) returned."
                    )

                    st.dataframe(
                        result,
                        width="stretch",
                        hide_index=True
                    )

                except Exception as error:

                    st.error(f"Query failed: {error}")

                finally:

                    conn.close()
