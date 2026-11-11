import sqlite3
import os
import tempfile
import threading


# ============================================================
# DATABASE LOCATION
# ============================================================

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)

DATABASE_FOLDER = os.path.join(
    PROJECT_ROOT,
    "database"
)
DATABASE_NAME = os.path.abspath(
    os.environ.get(
        "HR_PAYROLL_DB_PATH",
        os.path.join(DATABASE_FOLDER, "hr_payroll.db")
    )
)

_INITIALIZATION_STATE = threading.local()
_DATABASE_INITIALIZATION_LOCK = threading.Lock()
_DATABASE_LOCATION_LOCK = threading.Lock()
_DATABASE_LOCATION_READY = False


# ============================================================
# DATABASE CONNECTION
# ============================================================

def _ensure_database_location():
    """Ensure the project database folder exists."""

    global _DATABASE_LOCATION_READY

    if _DATABASE_LOCATION_READY:
        return

    with _DATABASE_LOCATION_LOCK:
        if _DATABASE_LOCATION_READY:
            return

        os.makedirs(os.path.dirname(DATABASE_NAME), exist_ok=True)
        _DATABASE_LOCATION_READY = True


def get_connection():
    _ensure_database_location()

    connection = sqlite3.connect(
        DATABASE_NAME,
        timeout=60
    )
    connection.execute("PRAGMA busy_timeout = 60000")

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    initialization_connections = getattr(
        _INITIALIZATION_STATE, "connections", None
    )
    if initialization_connections is not None:
        initialization_connections.append(connection)

    return connection


# ============================================================
# EMPLOYEE TABLE
# ============================================================

def create_employee_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS employees (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT UNIQUE NOT NULL,

            employee_name TEXT NOT NULL,

            department TEXT NOT NULL,

            designation TEXT NOT NULL,

            joining_date TEXT NOT NULL,

            location TEXT NOT NULL,

            employment_type TEXT NOT NULL,

            annual_ctc REAL NOT NULL,

            health_insurance_opted INTEGER NOT NULL DEFAULT 0,

            dob TEXT NOT NULL DEFAULT '',

            gender TEXT NOT NULL DEFAULT '',

            marital_status TEXT NOT NULL DEFAULT '',

            blood_group TEXT NOT NULL DEFAULT '',

            mobile_number TEXT NOT NULL DEFAULT '',

            personal_email TEXT NOT NULL DEFAULT '',

            work_email TEXT NOT NULL DEFAULT '',

            address TEXT NOT NULL DEFAULT '',

            emergency_contact_name TEXT NOT NULL DEFAULT '',

            emergency_contact_number TEXT NOT NULL DEFAULT '',

            family_details TEXT NOT NULL DEFAULT '[]',

            bank_name TEXT NOT NULL DEFAULT '',

            bank_account_number TEXT NOT NULL DEFAULT '',

            bank_ifsc TEXT NOT NULL DEFAULT '',

            uan_number TEXT NOT NULL DEFAULT '',

            photo BLOB

        )
        """
    )

    # Light migration for databases created before employee
    # personal detail fields were added.
    cursor.execute("PRAGMA table_info(employees)")

    existing = {row[1] for row in cursor.fetchall()}

    for column, declaration in [
        ("dob", "TEXT NOT NULL DEFAULT ''"),
        ("gender", "TEXT NOT NULL DEFAULT ''"),
        ("marital_status", "TEXT NOT NULL DEFAULT ''"),
        ("blood_group", "TEXT NOT NULL DEFAULT ''"),
        ("mobile_number", "TEXT NOT NULL DEFAULT ''"),
        ("personal_email", "TEXT NOT NULL DEFAULT ''"),
        ("work_email", "TEXT NOT NULL DEFAULT ''"),
        ("address", "TEXT NOT NULL DEFAULT ''"),
        ("emergency_contact_name", "TEXT NOT NULL DEFAULT ''"),
        ("emergency_contact_number", "TEXT NOT NULL DEFAULT ''"),
        ("family_details", "TEXT NOT NULL DEFAULT '[]'"),
        ("bank_name", "TEXT NOT NULL DEFAULT ''"),
        ("bank_account_number", "TEXT NOT NULL DEFAULT ''"),
        ("bank_ifsc", "TEXT NOT NULL DEFAULT ''"),
        ("uan_number", "TEXT NOT NULL DEFAULT ''"),
        ("health_insurance_opted", "INTEGER NOT NULL DEFAULT 0"),
        ("exit_date", "TEXT NOT NULL DEFAULT ''"),
        ("photo", "BLOB"),
        ("shift_id", "INTEGER"),
    ]:

        if column not in existing:

            cursor.execute(
                f"ALTER TABLE employees "
                f"ADD COLUMN {column} {declaration}"
            )

    connection.commit()

    connection.close()


# ============================================================
# SALARY STRUCTURE TABLE
# ============================================================

def create_salary_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS salary_structures (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT UNIQUE NOT NULL,

            basic_annual REAL NOT NULL DEFAULT 0,

            hra_annual REAL NOT NULL DEFAULT 0,

            special_allowance_annual REAL NOT NULL DEFAULT 0,

            other_allowance_annual REAL NOT NULL DEFAULT 0,

            employee_pf_annual REAL NOT NULL DEFAULT 0,

            employer_pf_annual REAL NOT NULL DEFAULT 0,

            other_deduction_annual REAL NOT NULL DEFAULT 0,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    connection.commit()

    connection.close()


# ============================================================
# PAYSLIP TABLE
# ============================================================

def create_payslip_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS payslips (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT NOT NULL,

            pay_month INTEGER NOT NULL,

            pay_year INTEGER NOT NULL,

            basic_monthly REAL NOT NULL DEFAULT 0,

            hra_monthly REAL NOT NULL DEFAULT 0,

            special_allowance_monthly REAL NOT NULL DEFAULT 0,

            other_allowance_monthly REAL NOT NULL DEFAULT 0,

            gross_monthly REAL NOT NULL DEFAULT 0,

            employee_pf_monthly REAL NOT NULL DEFAULT 0,

            employer_pf_monthly REAL NOT NULL DEFAULT 0,

            professional_tax_monthly REAL NOT NULL DEFAULT 0,

            other_deduction_monthly REAL NOT NULL DEFAULT 0,

            total_deductions REAL NOT NULL DEFAULT 0,

            net_pay REAL NOT NULL DEFAULT 0,

            lop_days REAL NOT NULL DEFAULT 0,

            lop_amount REAL NOT NULL DEFAULT 0,

            generated_at TEXT DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (employee_id, pay_month, pay_year),

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    # Light migration for databases created before LOP support.
    cursor.execute("PRAGMA table_info(payslips)")

    existing = {row[1] for row in cursor.fetchall()}

    for column, declaration in [
        ("lop_days", "REAL NOT NULL DEFAULT 0"),
        ("lop_amount", "REAL NOT NULL DEFAULT 0"),
        ("professional_tax_monthly", "REAL NOT NULL DEFAULT 0"),
    ]:

        if column not in existing:

            cursor.execute(
                f"ALTER TABLE payslips "
                f"ADD COLUMN {column} {declaration}"
            )

    connection.commit()

    connection.close()


# ============================================================
# USERS TABLE (LOGIN / ROLES)
# ============================================================

def create_users_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS users (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            username TEXT UNIQUE NOT NULL,

            password_hash TEXT NOT NULL,

            password_salt TEXT NOT NULL,

            role TEXT NOT NULL,

            employee_id TEXT,

            login_email TEXT NOT NULL DEFAULT '',

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    cursor.execute("PRAGMA table_info(users)")
    existing = {row[1] for row in cursor.fetchall()}
    if "login_email" not in existing:
        cursor.execute(
            "ALTER TABLE users "
            "ADD COLUMN login_email TEXT NOT NULL DEFAULT ''"
        )

    connection.commit()

    connection.close()


def create_user_preferences_table():

    connection = get_connection()

    try:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                username TEXT PRIMARY KEY,
                preferences_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (username)
                    REFERENCES users(username)
                    ON DELETE CASCADE
            )
            """
        )

        connection.commit()

    finally:

        connection.close()


# ============================================================
# LEAVE TABLES
# ============================================================

def create_leave_request_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_requests (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT NOT NULL,

            leave_type TEXT NOT NULL,

            from_date TEXT NOT NULL,

            to_date TEXT NOT NULL,

            days REAL NOT NULL DEFAULT 0,

            portion TEXT DEFAULT 'Full day',

            reason TEXT,

            manager_email TEXT NOT NULL DEFAULT '',

            status TEXT NOT NULL DEFAULT 'Pending',

            applied_at TEXT DEFAULT CURRENT_TIMESTAMP,

            decided_at TEXT,

            decided_by TEXT,

            decision_note TEXT,

            employee_reply TEXT NOT NULL DEFAULT '',

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    # Older databases predate half-day leave and HR decision notes.
    # SQLite has no "ADD COLUMN IF NOT EXISTS", so ask first.
    existing = {
        row[1]
        for row in cursor.execute(
            "PRAGMA table_info(leave_requests)"
        ).fetchall()
    }

    for column, kind in (
        ("portion", "TEXT DEFAULT 'Full day'"),
        ("decision_note", "TEXT"),
        ("manager_email", "TEXT NOT NULL DEFAULT ''"),
        ("employee_reply", "TEXT NOT NULL DEFAULT ''")
    ):

        if column not in existing:

            cursor.execute(
                f"ALTER TABLE leave_requests ADD COLUMN {column} {kind}"
            )

    connection.commit()

    connection.close()


def create_leave_entitlement_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS leave_entitlements (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT NOT NULL,

            leave_type TEXT NOT NULL,

            year INTEGER NOT NULL,

            entitled REAL NOT NULL DEFAULT 0,

            UNIQUE (employee_id, leave_type, year),

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    connection.commit()

    connection.close()


# ============================================================
# ATTENDANCE TABLE
# ============================================================

def create_attendance_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS attendance (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT NOT NULL,

            att_date TEXT NOT NULL,

            status TEXT NOT NULL,

            note TEXT,

            in_time TEXT,

            out_time TEXT,

            recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (employee_id, att_date),

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    # Older databases were created before the app recorded clock in /
    # clock out times, so add the columns if they are missing. SQLite
    # has no "ADD COLUMN IF NOT EXISTS", hence the PRAGMA.
    existing = {
        row[1]
        for row in cursor.execute(
            "PRAGMA table_info(attendance)"
        ).fetchall()
    }

    for column in ("in_time", "out_time"):

        if column not in existing:

            cursor.execute(
                f"ALTER TABLE attendance ADD COLUMN {column} TEXT"
            )

    connection.commit()

    connection.close()


# ============================================================
# SHIFT TABLE
# ============================================================
# HR can run more than one timing in the same office: a client
# project may start at 08:00, support may run 14:00-23:00, and
# everyone else stays on the company general shift. Each employee
# points at one shift through employees.shift_id.

def create_shift_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS shifts (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            shift_name TEXT UNIQUE NOT NULL,

            client_project TEXT NOT NULL DEFAULT '',

            start_time TEXT NOT NULL,

            end_time TEXT NOT NULL,

            grace_minutes INTEGER NOT NULL DEFAULT 15,

            break_minutes INTEGER NOT NULL DEFAULT 60,

            min_hours_full_day REAL NOT NULL DEFAULT 8,

            min_hours_half_day REAL NOT NULL DEFAULT 4,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP

        )
        """
    )

    # Seed the company default once. Existing employees are put on
    # it so nobody is left without a shift after the upgrade.
    cursor.execute(
        "SELECT id FROM shifts WHERE shift_name = ?",
        ("General",)
    )

    row = cursor.fetchone()

    if row:

        default_id = row[0]

    else:

        cursor.execute(
            """
            INSERT INTO shifts
                (shift_name, client_project, start_time, end_time,
                 grace_minutes, break_minutes,
                 min_hours_full_day, min_hours_half_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("General", "All", "09:30", "18:30", 15, 60, 8.0, 4.0)
        )

        default_id = cursor.lastrowid

    cursor.execute(
        "UPDATE employees SET shift_id = ? "
        "WHERE shift_id IS NULL OR shift_id = 0",
        (default_id,)
    )

    connection.commit()

    connection.close()


# ============================================================
# HOLIDAY TABLE
# ============================================================

def create_holiday_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS holidays (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            holiday_date TEXT UNIQUE NOT NULL,

            name TEXT NOT NULL,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP

        )
        """
    )

    connection.commit()

    connection.close()


def create_holiday_seed_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS holiday_seed (

            year INTEGER PRIMARY KEY,

            seeded_at TEXT NOT NULL DEFAULT ''

        )
        """
    )

    connection.commit()

    connection.close()


# ============================================================
# SALARY REVISION TABLE
# ============================================================

def create_revision_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS salary_revisions (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT NOT NULL,

            effective_date TEXT NOT NULL,

            old_ctc REAL NOT NULL DEFAULT 0,

            new_ctc REAL NOT NULL DEFAULT 0,

            change_pct REAL NOT NULL DEFAULT 0,

            reason TEXT,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    connection.commit()

    connection.close()


# ============================================================
# FULL & FINAL SETTLEMENT TABLE
# ============================================================

def create_settlement_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS settlements (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT NOT NULL,

            last_working_date TEXT NOT NULL,

            notice_period_days INTEGER NOT NULL DEFAULT 0,

            final_month_gross REAL NOT NULL DEFAULT 0,

            final_month_pf REAL NOT NULL DEFAULT 0,

            final_month_other_deduction REAL NOT NULL DEFAULT 0,

            leave_encashment_days REAL NOT NULL DEFAULT 0,

            leave_encashment_amount REAL NOT NULL DEFAULT 0,

            gratuity_amount REAL NOT NULL DEFAULT 0,

            other_earnings REAL NOT NULL DEFAULT 0,

            notice_recovery REAL NOT NULL DEFAULT 0,

            other_recovery REAL NOT NULL DEFAULT 0,

            net_settlement REAL NOT NULL DEFAULT 0,

            remarks TEXT,

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            UNIQUE (employee_id, last_working_date),

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    # Light migration for databases created before the final-month
    # component split was added.
    cursor.execute("PRAGMA table_info(settlements)")

    existing = {row[1] for row in cursor.fetchall()}

    for column, declaration in [
        ("final_month_gross", "REAL NOT NULL DEFAULT 0"),
        ("final_month_pf", "REAL NOT NULL DEFAULT 0"),
        (
            "final_month_other_deduction",
            "REAL NOT NULL DEFAULT 0"
        ),
    ]:

        if column not in existing:

            cursor.execute(
                f"ALTER TABLE settlements "
                f"ADD COLUMN {column} {declaration}"
            )

    connection.commit()

    connection.close()


# ============================================================
# CANDIDATE TABLE (AI resume analyzer)
# ============================================================
# One row per resume that HR has screened with AI. Skill lists
# are stored as comma-separated text so the table stays easy to
# read in any SQLite browser.

def create_candidate_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS candidates (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            job_title TEXT NOT NULL,

            required_skills TEXT,

            candidate_name TEXT,

            email TEXT,

            phone TEXT,

            experience_years REAL NOT NULL DEFAULT 0,

            education TEXT,

            current_role TEXT,

            skills TEXT,

            matched_skills TEXT,

            missing_skills TEXT,

            score INTEGER NOT NULL DEFAULT 0,

            verdict TEXT,

            strengths TEXT,

            gaps TEXT,

            summary TEXT,

            file_name TEXT,

            decision TEXT NOT NULL DEFAULT 'New',

            created_at TEXT DEFAULT CURRENT_TIMESTAMP,

            created_by TEXT

        )
        """
    )

    connection.commit()

    connection.close()


# ============================================================
# FORM 16 TABLE (income-tax documents)
# ============================================================
# One row per issued Form 16. The PDF itself is kept in the
# ``data`` column as a BLOB, exactly like the employee photo, so
# a form can never go missing from its employee record.
# ``tax_year`` stores the year the Indian financial year starts
# in (2025 means FY 2025-26). A re-issued form replaces the old
# one for that employee and year.

def create_form16_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS form16_documents (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT NOT NULL,

            tax_year INTEGER NOT NULL,

            file_name TEXT NOT NULL DEFAULT '',

            mime TEXT NOT NULL DEFAULT 'application/pdf',

            size_bytes INTEGER NOT NULL DEFAULT 0,

            data BLOB,

            matched_name TEXT NOT NULL DEFAULT '',

            match_method TEXT NOT NULL DEFAULT '',

            match_score REAL NOT NULL DEFAULT 0,

            employee_pan TEXT NOT NULL DEFAULT '',

            employer_name TEXT NOT NULL DEFAULT '',

            gross_salary REAL NOT NULL DEFAULT 0,

            total_tds REAL NOT NULL DEFAULT 0,

            issued_on TEXT NOT NULL DEFAULT '',

            issued_by TEXT NOT NULL DEFAULT '',

            notes TEXT NOT NULL DEFAULT '',

            UNIQUE (employee_id, tax_year),

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    connection.commit()

    connection.close()


# ============================================================
# NOTIFICATION TABLE
# ============================================================

def create_notification_table():
    """In-app notifications ("bell" alerts) for HR and employees.

    One row per message. ``recipient`` is either the literal "hr"
    (the HR inbox) or an employee id. ``page`` is the portal page the
    notification points at, and ``is_read`` tracks whether it has
    been opened. Rows are written by ``modules/notifications.py``.
    """

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            recipient TEXT NOT NULL,

            title TEXT NOT NULL,

            message TEXT NOT NULL DEFAULT '',

            category TEXT NOT NULL DEFAULT 'System',

            page TEXT NOT NULL DEFAULT '',

            is_read INTEGER NOT NULL DEFAULT 0,

            created_at TEXT NOT NULL DEFAULT ''

        )
        """
    )

    connection.commit()

    connection.close()


# ============================================================
# ASSET TABLE
# ============================================================

def create_asset_table():
    """Company assets issued to employees (laptop, phone, ID card...).

    One row per asset. ``employee_id`` is set while the asset is with
    an employee; ``status`` tracks its lifecycle. Rows are managed by
    ``modules/assets.py``.
    """

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS assets (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            asset_tag TEXT NOT NULL DEFAULT '',

            category TEXT NOT NULL,

            name TEXT NOT NULL,

            serial_number TEXT NOT NULL DEFAULT '',

            condition TEXT NOT NULL DEFAULT 'Good',

            status TEXT NOT NULL DEFAULT 'Available',

            employee_id TEXT NOT NULL DEFAULT '',

            assigned_date TEXT NOT NULL DEFAULT '',

            returned_date TEXT NOT NULL DEFAULT '',

            notes TEXT NOT NULL DEFAULT '',

            created_at TEXT NOT NULL DEFAULT ''

        )
        """
    )

    connection.commit()

    connection.close()


# ============================================================
# REIMBURSEMENT TABLE (expense bills)
# ============================================================
# One row per bill an employee uploads. The file itself is kept in
# the ``data`` column as a BLOB, exactly like the employee photo and
# the Form 16 PDF, so a claim can never lose its proof. HR approves
# or rejects a claim, then marks an approved one as paid.

def create_reimbursement_table():
    """Expense claims: employees upload bills, HR settles them.

    ``status`` walks Pending -> Approved -> Paid (or Rejected).
    ``amount`` is what the employee is asking for; it is NOT part of
    the salary structure and never touches a payslip on its own.
    """

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS reimbursements (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT NOT NULL,

            category TEXT NOT NULL,

            amount REAL NOT NULL DEFAULT 0,

            expense_date TEXT NOT NULL,

            description TEXT NOT NULL DEFAULT '',

            status TEXT NOT NULL DEFAULT 'Pending',

            file_name TEXT NOT NULL DEFAULT '',

            mime TEXT NOT NULL DEFAULT '',

            size_bytes INTEGER NOT NULL DEFAULT 0,

            data BLOB,

            submitted_at TEXT NOT NULL DEFAULT '',

            decided_at TEXT NOT NULL DEFAULT '',

            decided_by TEXT NOT NULL DEFAULT '',

            decision_note TEXT NOT NULL DEFAULT '',

            paid_on TEXT NOT NULL DEFAULT '',

            created_at TEXT NOT NULL DEFAULT '',

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    existing = {
        row[1]
        for row in cursor.execute(
            "PRAGMA table_info(reimbursements)"
        ).fetchall()
    }
    if "employee_reply" not in existing:
        cursor.execute(
            "ALTER TABLE reimbursements "
            "ADD COLUMN employee_reply TEXT NOT NULL DEFAULT ''"
        )

    connection.commit()

    connection.close()


def create_employee_service_tables():
    """Employee letter requests and onboarding checklist tasks."""

    connection = get_connection()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS employee_letter_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                letter_type TEXT NOT NULL,
                purpose TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'Pending',
                hr_note TEXT NOT NULL DEFAULT '',
                employee_reply TEXT NOT NULL DEFAULT '',
                requested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT NOT NULL DEFAULT '',
                FOREIGN KEY (employee_id)
                    REFERENCES employees(employee_id)
                    ON DELETE CASCADE
            )
            """
        )
        letter_columns = {
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(employee_letter_requests)"
            ).fetchall()
        }
        if "employee_reply" not in letter_columns:
            connection.execute(
                "ALTER TABLE employee_letter_requests "
                "ADD COLUMN employee_reply TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS onboarding_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                task_title TEXT NOT NULL,
                task_type TEXT NOT NULL DEFAULT 'Employee',
                status TEXT NOT NULL DEFAULT 'Pending',
                employee_note TEXT NOT NULL DEFAULT '',
                hr_note TEXT NOT NULL DEFAULT '',
                completed_by TEXT NOT NULL DEFAULT '',
                completed_at TEXT NOT NULL DEFAULT '',
                UNIQUE(employee_id, task_title),
                FOREIGN KEY (employee_id)
                    REFERENCES employees(employee_id)
                    ON DELETE CASCADE
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def create_request_history_table():
    connection = get_connection()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS request_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_type TEXT NOT NULL,
                request_id INTEGER NOT NULL,
                employee_id TEXT NOT NULL,
                status TEXT NOT NULL,
                actor TEXT NOT NULL DEFAULT '',
                comment TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


# ============================================================
# EMPLOYEE DOCUMENTS TABLE
# ============================================================

def create_employee_document_table():
    """Employee-submitted documents, stored in the database."""

    connection = get_connection()

    try:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS employee_documents (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                employee_id TEXT NOT NULL,

                document_type TEXT NOT NULL,

                file_name TEXT NOT NULL,

                mime TEXT NOT NULL,

                size_bytes INTEGER NOT NULL,

                data BLOB NOT NULL,

                status TEXT NOT NULL DEFAULT 'Pending review',

                submitted_at TEXT NOT NULL DEFAULT '',

                reviewed_at TEXT NOT NULL DEFAULT '',

                reviewed_by TEXT NOT NULL DEFAULT '',

                FOREIGN KEY (employee_id)
                    REFERENCES employees(employee_id)
                    ON DELETE CASCADE

            )
            """
        )

        connection.commit()

    finally:

        connection.close()


# ============================================================
# EMPLOYEE PROJECTS TABLE
# ============================================================
# One row per project an employee is working on. HR assigns the
# projects; employees see their own assignments on My overview.
# The same employee can be on several projects, and the same
# project can be shared by several employees.

def create_project_table():

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS employee_projects (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            employee_id TEXT NOT NULL,

            project_name TEXT NOT NULL,

            role TEXT NOT NULL DEFAULT '',

            status TEXT NOT NULL DEFAULT 'Active',

            start_date TEXT NOT NULL DEFAULT '',

            notes TEXT NOT NULL DEFAULT '',

            created_at TEXT NOT NULL DEFAULT '',

            FOREIGN KEY (employee_id)
                REFERENCES employees(employee_id)
                ON DELETE CASCADE

        )
        """
    )

    connection.commit()

    connection.close()


# ============================================================
# OPEN POSITIONS
# ============================================================

def create_open_positions_table():
    """Create the HR-managed job postings visible to employees."""

    connection = get_connection()
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS open_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role_title TEXT NOT NULL,
            department TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            employment_type TEXT NOT NULL DEFAULT '',
            experience_required TEXT NOT NULL DEFAULT '',
            role_summary TEXT NOT NULL DEFAULT '',
            responsibilities TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'Open'
                CHECK (status IN ('Open', 'Closed')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    existing_columns = {
        row[1] for row in cursor.execute("PRAGMA table_info(open_positions)")
    }
    if "experience_required" not in existing_columns:
        cursor.execute(
            """
            ALTER TABLE open_positions
            ADD COLUMN experience_required TEXT NOT NULL DEFAULT ''
            """
        )
    connection.commit()
    connection.close()


# ============================================================
# INITIALIZE DATABASE
# ============================================================

def initialize_database():
    with _DATABASE_INITIALIZATION_LOCK:
        _initialize_database_tables()


def _initialize_database_tables():
    previous_connections = getattr(
        _INITIALIZATION_STATE, "connections", None
    )
    initialization_connections = []
    _INITIALIZATION_STATE.connections = initialization_connections

    try:
        create_employee_table()
        create_salary_table()
        create_payslip_table()
        create_users_table()
        create_user_preferences_table()
        create_leave_request_table()
        create_leave_entitlement_table()
        create_attendance_table()
        create_shift_table()
        create_holiday_table()
        create_holiday_seed_table()
        create_revision_table()
        create_settlement_table()
        create_candidate_table()
        create_open_positions_table()
        create_notification_table()
        create_form16_table()
        create_asset_table()
        create_reimbursement_table()
        create_employee_document_table()
        create_employee_service_tables()
        create_request_history_table()
        create_project_table()
    finally:
        for connection in initialization_connections:
            connection.close()
        if previous_connections is None:
            del _INITIALIZATION_STATE.connections
        else:
            _INITIALIZATION_STATE.connections = previous_connections