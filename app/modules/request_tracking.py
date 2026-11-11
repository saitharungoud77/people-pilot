from database.connection import create_request_history_table, get_connection


def record_request_event(
    request_type,
    request_id,
    employee_id,
    status,
    actor="",
    comment=""
):
    create_request_history_table()
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO request_history
                (request_type, request_id, employee_id, status, actor, comment)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                request_type,
                int(request_id),
                employee_id,
                status,
                actor or "",
                (comment or "").strip()
            )
        )
        connection.commit()
    finally:
        connection.close()


def get_request_history(limit=300):
    create_request_history_table()
    connection = get_connection()
    try:
        rows = connection.execute(
            """
            SELECT request_type, request_id, employee_id, status,
                   actor, comment, created_at
            FROM request_history
            ORDER BY id DESC
            LIMIT ?
            """,
            (int(limit),)
        ).fetchall()
    finally:
        connection.close()
    keys = (
        "request_type", "request_id", "employee_id", "status",
        "actor", "comment", "created_at"
    )
    return [dict(zip(keys, row)) for row in rows]
