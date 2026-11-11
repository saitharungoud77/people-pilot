import sys
from pathlib import Path

import streamlit as st


# ============================================================
# IMPORT PATHS
# ============================================================

# Allow imports from the project root (e.g. `database`) and the app
# folder (e.g. `modules`) no matter which directory Streamlit is
# started from.
APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent

for _path in (str(PROJECT_ROOT), str(APP_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


# ============================================================
# LIVING DOCUMENTATION
# ============================================================
# "AI HR Payroll Details.md" is regenerated automatically whenever
# the code changes (on each app rerun). The helper only writes the
# file when it actually differs, so it is cheap.

try:

    from scripts.update_ai_hr_payroll_details import refresh_if_changed

    refresh_if_changed(PROJECT_ROOT)

except Exception:

    pass


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="PeoplePilot",
    page_icon=":material/business:",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# APPLICATION MODULES
# ============================================================

from database.connection import initialize_database
from modules.auth import ensure_auth_setup, show_login_page
from modules.nav import render_sidebar
from modules.notifications import render_notifications
from modules.home import show_home
from modules.application import show_application
from modules.employee import show_employee
from modules.salary import (
    show_salary_page,
    show_my_salary
)
from modules.payslip import (
    auto_generate_current_month_payslips,
    latest_released_payroll_period,
    show_payslip_page,
    show_my_payslips
)
from modules.epfo import show_epfo_page, show_my_epfo
from modules.tax import show_tax_page, show_my_tax
from modules.database_viewer import show_database_page
from modules.accounts import show_accounts_page
from modules.approvals import show_approval_center
from modules.employee_services import show_employee_services
from modules.open_positions import show_open_positions_page
from modules.leave import (
    show_leave_page,
    show_my_leave,
    show_my_leave_history
)
from modules.attendance import (
    show_attendance_page,
    show_my_attendance
)
from modules.my_overview import show_portal_home
from modules.quick_links import show_quick_links
from modules.profile import show_my_profile
from modules.holidays import show_holidays_page, show_my_holidays
from modules.employee_documents import show_employee_documents
from modules.shifts import show_shifts_page
from modules.assets import show_assets_page, show_my_assets
from modules.reimbursements import (
    show_reimbursements_page,
    show_my_reimbursements
)
from modules.policies import show_policies_page, show_my_policies
from modules.revisions import show_revisions_page
from modules.settlement import show_settlement_page
from modules.offer_letter import show_offer_letter_page
from modules.resume_analyzer import show_resume_analyzer_page
from modules.payroll_audit import show_payroll_audit_page
from modules.payroll_migration import migrate_payroll_rules
from modules.letter_generator import show_letter_page
from modules.hiring_pack import show_hiring_pack_page
from modules.theme import (
    inject as inject_theme,
    inject_user_theme,
)
from modules.assistant import render_assistant
from modules.settings import get_user_preferences


# ============================================================
# DATABASE + AUTH SETUP
# ============================================================

@st.cache_resource(show_spinner=False)
def initialize_app_database():
    initialize_database()
    ensure_auth_setup()
    migrate_payroll_rules()


initialize_app_database()


# ============================================================
# GLOBAL THEME
# ============================================================
# Motion, gradients and hover polish for every page. Colours and
# fonts themselves live in .streamlit/config.toml.

inject_theme()


# ============================================================
# SESSION STATE
# ============================================================

if "auth_user" not in st.session_state:
    st.session_state.auth_user = None

if "current_page" not in st.session_state:
    st.session_state.current_page = "landing"


# ============================================================
# SIGN-IN GATE
# ============================================================

if st.session_state.auth_user is None:

    show_login_page()

    try:
        st.stop()
    except Exception:
        pass
    # In bare Python execution, exit gracefully
    raise SystemExit(0)

try:
    user = st.session_state.auth_user
except Exception:
    raise SystemExit(0)
if user is None:
    raise SystemExit(0)

user_preferences = get_user_preferences(user["username"])
inject_user_theme(user_preferences)


# ============================================================
# AUTO-GENERATED PAYSLIPS
# ============================================================
# Catch up all missing periods through the latest due pay period.
# The daily task also runs this while the portal is closed; this
# session-level check is a safe fallback.

_payroll_year, _payroll_month = latest_released_payroll_period()
_current_period = f"{_payroll_year}-{_payroll_month:02d}"

if st.session_state.get("auto_generated_period") != _current_period:

    auto_generate_current_month_payslips()

    st.session_state.auto_generated_period = _current_period


# ============================================================
# NAVIGATION
# ============================================================

def go_home():
    """Return to the role's home screen."""

    st.session_state.current_page = "application"


if user["role"] == "hr":

    # -----------------------------------------------------
    # HR - FULL ACCESS
    # -----------------------------------------------------

    PAGES = {
        "landing": show_home,
        "application": show_application,
        "approvals": lambda: show_approval_center(go_home=go_home),
        "employee_services": lambda: show_employee_services(
            go_home=go_home
        ),
        "employee": lambda: show_employee(go_home=go_home),
        "open_positions": show_open_positions_page,
        "offer_letter": lambda: show_offer_letter_page(go_home=go_home),
        "resume": lambda: show_resume_analyzer_page(go_home=go_home),
        "hiring_pack": lambda: show_hiring_pack_page(go_home=go_home),
        "letters": lambda: show_letter_page(go_home=go_home),
        "payroll_audit": lambda: show_payroll_audit_page(go_home=go_home),
        "settlement": lambda: show_settlement_page(go_home=go_home),
        "salary": lambda: show_salary_page(go_home=go_home),
        "revisions": lambda: show_revisions_page(go_home=go_home),
        "payslip": lambda: show_payslip_page(go_home=go_home),
        "epfo": lambda: show_epfo_page(go_home=go_home),
        "tax": lambda: show_tax_page(go_home=go_home),
        "reimbursements": lambda: show_reimbursements_page(
            go_home=go_home
        ),
        "leave": lambda: show_leave_page(go_home=go_home),
        "attendance": lambda: show_attendance_page(go_home=go_home),
        "shifts": lambda: show_shifts_page(go_home=go_home),
        "holidays": lambda: show_holidays_page(go_home=go_home),
        "assets": lambda: show_assets_page(go_home=go_home),
        "documents": lambda: show_employee_documents(go_home=go_home),
        "policies": lambda: show_policies_page(go_home=go_home),
        "accounts": lambda: show_accounts_page(go_home=go_home),
        "database": lambda: show_database_page(go_home=go_home),
    }

else:

    # -----------------------------------------------------
    # EMPLOYEE - READ-ONLY, OWN DATA ONLY
    # -----------------------------------------------------

    PAGES = {
        "landing": show_home,
        "application": show_portal_home,
        "quick_links": show_quick_links,
        "profile": show_my_profile,
        "employee_services": show_employee_services,
        "open_positions": show_open_positions_page,
        "salary": show_my_salary,
        "payslips": show_my_payslips,
        "epfo": show_my_epfo,
        "tax": show_my_tax,
        "reimbursements": show_my_reimbursements,
        "leave": show_my_leave,
        "leave_history": show_my_leave_history,
        "attendance": show_my_attendance,
        "holidays": show_my_holidays,
        "assets": show_my_assets,
        "documents": show_employee_documents,
        "policies": show_my_policies,
    }


# ============================================================
# RUN THE SELECTED PAGE
# ============================================================

render_sidebar(user)

_page = st.session_state.get("current_page", "landing")

# Never let a stale or out-of-role page id through the guard.
if _page not in PAGES:

    _page = "landing"

    st.session_state.current_page = _page

# ============================================================
# NOTIFICATION BAR (TOP RIGHT)
# ============================================================
# The bell sits at the top right, above the page body, on every
# signed-in screen (the brief splash screen is skipped).

with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
    if _page != "landing":
        render_notifications(user)


PAGES[_page]()


# ============================================================
# AI HR ASSISTANT
# ============================================================
# Rendered after the page body so the floating launcher (and the chat
# panel, when open) is present on every signed-in screen. The bot
# scopes itself to the signed-in user and answers only from the
# database, via the tools in modules/assistant.py.

render_assistant(user)
