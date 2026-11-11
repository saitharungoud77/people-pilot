"""Release due monthly payroll from a scheduled task."""

import logging
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "app"

for path in (PROJECT_ROOT, APP_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from database.connection import initialize_database
from modules.payslip import auto_generate_current_month_payslips


def main():
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    logging.basicConfig(
        filename=log_dir / "monthly_payroll_release.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    initialize_database()

    try:
        generated = auto_generate_current_month_payslips()
    except Exception:
        logging.exception("Scheduled payroll release failed")
        raise

    logging.info("Scheduled payroll release completed: %s payslip(s)", generated)
    print(f"Payroll release completed: {generated} payslip(s) created.")


if __name__ == "__main__":
    main()
