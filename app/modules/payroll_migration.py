"""One-time normalization of salary structures and released payslips."""

import datetime
import os
import sqlite3

from database.connection import (
    DATABASE_FOLDER,
    DATABASE_NAME,
    get_connection,
)
from modules.payslip import build_monthly_breakdown
from modules.salary import (
    PF_RATE,
    PF_WAGE_CEILING_MONTHLY,
    PROFESSIONAL_TAX_MONTHLY,
)


MIGRATION_KEY = "pf_cap_15000_eps_15000_pt_200_v2"


def _create_backup():
    """Create a consistent SQLite backup before the payroll rewrite."""

    backup_folder = os.path.join(DATABASE_FOLDER, "backups")
    os.makedirs(backup_folder, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = os.path.join(
        backup_folder,
        f"hr_payroll_before_{MIGRATION_KEY}_{timestamp}.db"
    )
    source = sqlite3.connect(DATABASE_NAME, timeout=60)
    destination = sqlite3.connect(backup_path, timeout=60)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()
    return backup_path


def migrate_payroll_rules():
    """Recalculate all salary structures and saved payslips exactly once."""

    connection = get_connection()
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS payroll_migrations (
                migration_key TEXT PRIMARY KEY,
                completed_at TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                salary_structures_updated INTEGER NOT NULL,
                payslips_updated INTEGER NOT NULL
            )
            """
        )
        connection.commit()
        if connection.execute(
            "SELECT 1 FROM payroll_migrations WHERE migration_key = ?",
            (MIGRATION_KEY,)
        ).fetchone():
            return None
    finally:
        connection.close()

    backup_path = _create_backup()
    connection = get_connection()
    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM payroll_migrations WHERE migration_key = ?",
            (MIGRATION_KEY,)
        ).fetchone():
            connection.rollback()
            return None

        structures = connection.execute(
            """
            SELECT
                e.employee_id,
                e.employee_name,
                e.department,
                e.designation,
                e.joining_date,
                e.location,
                e.employment_type,
                e.annual_ctc,
                s.basic_annual,
                s.hra_annual,
                s.special_allowance_annual,
                s.other_allowance_annual,
                s.employee_pf_annual,
                s.employer_pf_annual,
                s.other_deduction_annual
            FROM employees e
            JOIN salary_structures s
              ON s.employee_id = e.employee_id
            """
        ).fetchall()

        employees_by_id = {}
        for employee in structures:
            (
                employee_id, employee_name, department, designation,
                joining_date, location, employment_type, annual_ctc,
                basic_annual, hra_annual, _special_annual,
                other_allowance_annual, _old_employee_pf,
                _old_employer_pf, other_deduction_annual
            ) = employee

            basic_monthly = max(0.0, float(basic_annual or 0) / 12)
            pf_wages = min(basic_monthly, PF_WAGE_CEILING_MONTHLY)
            employee_pf_annual = round(
                round(pf_wages * PF_RATE, 2) * 12, 2
            )
            employer_pf_annual = employee_pf_annual
            special_annual = round(
                float(annual_ctc or 0)
                - float(basic_annual or 0)
                - float(hra_annual or 0)
                - float(other_allowance_annual or 0)
                - employer_pf_annual,
                2
            )
            if special_annual < 0:
                raise ValueError(
                    "Cannot normalize salary structure for "
                    f"{employee_id}: CTC is below its fixed salary "
                    "components and capped employer PF."
                )

            connection.execute(
                """
                UPDATE salary_structures
                SET special_allowance_annual = ?,
                    employee_pf_annual = ?,
                    employer_pf_annual = ?
                WHERE employee_id = ?
                """,
                (
                    special_annual, employee_pf_annual,
                    employer_pf_annual, employee_id
                )
            )
            employees_by_id[employee_id] = (
                employee_id, employee_name, department, designation,
                joining_date, location, employment_type, annual_ctc,
                basic_annual, hra_annual, special_annual,
                other_allowance_annual, employee_pf_annual,
                employer_pf_annual, other_deduction_annual
            )

        payslips = connection.execute(
            """
            SELECT employee_id, pay_month, pay_year, lop_days
            FROM payslips
            ORDER BY pay_year, pay_month, employee_id
            """
        ).fetchall()
        missing_structures = sorted({
            employee_id
            for employee_id, _month, _year, _lop_days in payslips
            if employee_id not in employees_by_id
        })
        if missing_structures:
            raise ValueError(
                "Payroll migration cancelled: "
                f"{len(missing_structures)} employee(s) with saved "
                "payslips have no salary structure."
            )

        payslips_updated = 0
        for employee_id, month, year, lop_days in payslips:
            employee = employees_by_id.get(employee_id)
            breakdown = build_monthly_breakdown(
                employee,
                year,
                month,
                lop_days_override=lop_days
            )
            connection.execute(
                """
                UPDATE payslips
                SET basic_monthly = ?,
                    hra_monthly = ?,
                    special_allowance_monthly = ?,
                    other_allowance_monthly = ?,
                    gross_monthly = ?,
                    employee_pf_monthly = ?,
                    employer_pf_monthly = ?,
                    professional_tax_monthly = ?,
                    other_deduction_monthly = ?,
                    total_deductions = ?,
                    net_pay = ?,
                    lop_amount = ?
                WHERE employee_id = ? AND pay_month = ? AND pay_year = ?
                """,
                (
                    breakdown["basic"],
                    breakdown["hra"],
                    breakdown["special"],
                    breakdown["other_allowance"],
                    breakdown["gross_monthly"],
                    breakdown["employee_pf"],
                    breakdown["employer_pf"],
                    PROFESSIONAL_TAX_MONTHLY,
                    breakdown["other_deduction"],
                    breakdown["total_deductions"],
                    breakdown["net_pay"],
                    breakdown["lop_amount"],
                    employee_id,
                    month,
                    year
                )
            )
            payslips_updated += 1

        connection.execute(
            """
            INSERT INTO payroll_migrations (
                migration_key, completed_at, backup_path,
                salary_structures_updated, payslips_updated
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                MIGRATION_KEY,
                datetime.datetime.now().isoformat(timespec="seconds"),
                backup_path,
                len(employees_by_id),
                payslips_updated
            )
        )
        connection.commit()
        return {
            "backup_path": backup_path,
            "salary_structures_updated": len(employees_by_id),
            "payslips_updated": payslips_updated
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
