import datetime
import streamlit as st

from database.connection import get_connection
from modules.theme import hero


# ============================================================
# CORPORATE HR COMMAND CENTER (HR DASHBOARD)
# ============================================================
# High-trust enterprise HR management dashboard:
# 1. Corporate Context Topbar (Live Date, Quarter, Facility, System Health)
# 2. Executive Welcome Hero with operational badges
# 3. 4 Elevated KPI stat cards with trend/status subtext
# 4. Quick Operations toolbar for 1-click execution
# 5. Categorized Workspace Hub organized into professional tabs
# 6. Operational Intelligence: Upcoming Holidays & Statutory Security Posture

MODULE_GROUPS = [
    (
        "Workforce & People",
        [
            (
                "Employee Master",
                "Complete employee records, personal data, departments and job roles.",
                ":material/groups:",
                "employee",
                "People Master",
                "btn_emp",
            ),
            (
                "Shift Timings",
                "Configure client/project shift hours, grace periods and break deductions.",
                ":material/schedule:",
                "shifts",
                "Rostering",
                "btn_shifts",
            ),
            (
                "Company Assets",
                "Track assigned hardware, laptops, serial numbers and conditions.",
                ":material/devices:",
                "assets",
                "Inventory",
                "btn_assets",
            ),
            (
                "POSH Policy",
                "Company guidelines on prevention of sexual harassment and compliance.",
                ":material/policy:",
                "policies",
                "Governance",
                "btn_posh",
            ),
        ],
    ),
    (
        "Payroll, PF & Taxes",
        [
            (
                "Salary Structures",
                "Statutory CTC split: basic, HRA, special allowances, PF and deductions.",
                ":material/payments:",
                "salary",
                "Compensation",
                "btn_salary",
            ),
            (
                "Monthly Payslips",
                "Generate, preview, edit components and export official PDF payslips.",
                ":material/receipt_long:",
                "payslip",
                "1-Click Run",
                "btn_payslip",
            ),
            (
                "Salary Revisions",
                "Log CTC raises and automatically scale monthly compensation components.",
                ":material/trending_up:",
                "revisions",
                "Appraisals",
                "btn_revisions",
            ),
            (
                "Provident Fund (EPFO)",
                "Employee & employer monthly EPF statements and contribution balances.",
                ":material/account_balance:",
                "epfo",
                "Statutory",
                "btn_epfo",
            ),
            (
                "Income Tax & Form 16",
                "Old vs New regime calculator & bulk Form 16 PDF document archive.",
                ":material/request_quote:",
                "tax",
                "Taxation",
                "btn_tax",
            ),
            (
                "Final Settlement",
                "Full and final exit calculations, leave encashment, notice pay and gratuity.",
                ":material/gavel:",
                "settlement",
                "Offboarding",
                "btn_settle",
            ),
        ],
    ),
    (
        "AI Intelligence Hub",
        [
            (
                "AI Offer Letter",
                "Upload offer letter PDFs; AI automatically extracts terms into employee master.",
                ":material/document_scanner:",
                "offer_letter",
                "Vision / JSON",
                "btn_offer",
            ),
            (
                "AI Resume Analyzer",
                "Screen candidate resumes against required skills with scores and verdicts.",
                ":material/person_search:",
                "resume",
                "Talent AI",
                "btn_resume",
            ),
            (
                "AI Hiring Pack",
                "Generate complete job descriptions, screening questions & interview scorecards.",
                ":material/psychology:",
                "hiring_pack",
                "Recruiting AI",
                "btn_hiring",
            ),
            (
                "AI Payroll Audit",
                "Pre-disbursement anomaly scanner: missing payslips, LOP and PF mismatches.",
                ":material/troubleshoot:",
                "payroll_audit",
                "Audit AI",
                "btn_audit",
            ),
            (
                "AI Letter Generator",
                "Draft verified experience, relieving, salary certificates and warning letters.",
                ":material/description:",
                "letters",
                "Document AI",
                "btn_letters",
            ),
        ],
    ),
    (
        "Time, Leave & Claims",
        [
            (
                "Attendance Register",
                "Daily check-in/out logs, Office vs WFH mode, and monthly timesheet summaries.",
                ":material/fact_check:",
                "attendance",
                "Daily Ops",
                "btn_att",
            ),
            (
                "Leave Management",
                "Review employee applications, team coverage and approve or reject with notes.",
                ":material/event_available:",
                "leave",
                "Approvals",
                "btn_leave",
            ),
            (
                "Reimbursements",
                "Review uploaded expense bills with AI prefill, approve claims & track payment.",
                ":material/upload_file:",
                "reimbursements",
                "Expenses",
                "btn_claims",
            ),
            (
                "Holiday Calendar",
                "Curated annual schedule of national festivals and public holidays.",
                ":material/celebration:",
                "holidays",
                "Corporate Calendar",
                "btn_holidays",
            ),
        ],
    ),
]


def _dashboard_stats():
    """Retrieve workforce, payroll and holiday figures for the dashboard."""

    connection = get_connection()

    try:

        cursor = connection.cursor()

        employees = cursor.execute(
            "SELECT COUNT(id) FROM employees"
        ).fetchone()[0]

        payslips = cursor.execute(
            "SELECT COUNT(id) FROM payslips"
        ).fetchone()[0]

        total_ctc = cursor.execute(
            "SELECT COALESCE(SUM(annual_ctc), 0) FROM employees"
        ).fetchone()[0]

        average_ctc = cursor.execute(
            "SELECT COALESCE(AVG(annual_ctc), 0) FROM employees"
        ).fetchone()[0]

        upcoming_holidays = cursor.execute(
            """
            SELECT name, holiday_date
            FROM holidays
            WHERE holiday_date >= date('now')
            ORDER BY holiday_date ASC
            LIMIT 3
            """
        ).fetchall()

    finally:

        connection.close()

    return (
        employees,
        payslips,
        total_ctc,
        average_ctc,
        upcoming_holidays
    )


def show_application():
    """Render the modern corporate HR command center."""

    user = st.session_state.get("auth_user") or {}

    who = (user.get("username") or "").strip() or "HR Admin"

    if who.lower() == "hr":

        who = "HR Administrator"

    today = datetime.date.today()

    date_str = today.strftime("%A, %d %B %Y")

    quarter_str = f"Q{(today.month - 1) // 3 + 1} FY {today.year}-{str(today.year + 1)[-2:]}"

    (
        employees,
        payslips,
        total_ctc,
        average_ctc,
        upcoming_holidays
    ) = _dashboard_stats()

    # -----------------------------------------------------
    # 1. CONTEXT TOPBAR
    # -----------------------------------------------------

    st.html(f"""
    <div class="corp-topbar">
        <div class="corp-topbar-left">
            <span style="font-family: 'Material Symbols Rounded', sans-serif; font-size: 18px; color: #16856B;">calendar_today</span>
            <span>{date_str}</span>
            <span style="color: #64748B;">&bull;</span>
            <span style="color: #68716F;">{quarter_str}</span>
            <span style="color: #64748B;">&bull;</span>
            <span style="color: #68716F;">Hi-Tech City Campus, Hyderabad</span>
        </div>
        <div class="corp-topbar-right">
            <span class="corp-status-pill">
                <span style="display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: #10B981;"></span>
                Systems Operational
            </span>
            <span class="corp-badge-pill">
                PBKDF2-SHA256 Encrypted
            </span>
        </div>
    </div>
    """)

    # -----------------------------------------------------
    # 2. EXECUTIVE HERO
    # -----------------------------------------------------

    hero(
        f"AIT Solutions · HR Command Center",
        f"Signed in as {who} · Manage personnel, statutory compliance, and AI workflows.",
        icon="space_dashboard",
        badges=[
            (f"{employees} Active Personnel", "groups"),
            (f"₹ {total_ctc / 100000:,.1f} L Annual CTC", "payments"),
            (f"{payslips} Payslips Disbursed", "receipt_long"),
            ("AI Automation Active", "smart_toy"),
        ]
    )

    # -----------------------------------------------------
    # 3. EXECUTIVE KPI CARDS
    # -----------------------------------------------------

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "Active Workforce",
            f"{employees:,}",
            icon=":material/groups:",
            border=True,
            help="Total registered employee records in the company."
        )

    with col2:

        st.metric(
            "Annual Payroll Run",
            f"Rs. {total_ctc / 100000:,.2f} L",
            icon=":material/payments:",
            border=True,
            help=f"Combined annual CTC (Avg: Rs. {average_ctc / 100000:,.2f} L / yr)."
        )

    with col3:

        st.metric(
            "Payslips Generated",
            f"{payslips:,}",
            icon=":material/receipt_long:",
            border=True,
            help="Historical monthly payslips generated and stored."
        )

    # -----------------------------------------------------
    # 4. QUICK OPERATIONS TOOLBAR
    # -----------------------------------------------------

    st.space("small")

    with st.container(border=True, key="lift_quick_actions"):

        st.markdown(
            "**Quick Operations** &nbsp;&middot;&nbsp; "
            "<span style='font-size: 0.82rem; color: #68716F; font-weight: 400;'>"
            "Instant access to high-frequency HR administration tasks"
            "</span>",
            unsafe_allow_html=True
        )

        st.space("small")

        q1, q2, q3, q4, q5 = st.columns(5)

        with q1:

            if st.button(
                "Add Employee",
                key="qa_emp",
                width="stretch"
            ):

                st.session_state.current_page = "employee"

                st.rerun()

        with q2:

            if st.button(
                "1-Click Payroll",
                key="qa_pay",
                width="stretch"
            ):

                st.session_state.current_page = "payslip"

                st.rerun()

        with q3:

            if st.button(
                "Leave Desk",
                key="qa_leave",
                width="stretch"
            ):

                st.session_state.current_page = "leave"

                st.rerun()

        with q4:

            if st.button(
                "Review Claims",
                key="qa_reimb",
                width="stretch"
            ):

                st.session_state.current_page = "reimbursements"

                st.rerun()

        with q5:

            if st.button(
                "Launch Assist",
                key="qa_assist",
                width="stretch",
                type="primary"
            ):

                st.session_state.ait_bot_open = True

                st.rerun()

    # -----------------------------------------------------
    # 5. CATEGORIZED WORKSPACE HUB (TABS)
    # -----------------------------------------------------

    st.space("small")

    st.markdown(
        "### Enterprise Workspaces",
        help="Access all people, payroll, AI automation, and governance modules"
    )

    tab_labels = [group_name for group_name, _ in MODULE_GROUPS]

    tabs = st.tabs(tab_labels)

    for tab_idx, (group_name, modules) in enumerate(MODULE_GROUPS):

        with tabs[tab_idx]:

            cols = st.columns(3)

            for mod_idx, (title, desc, icon, page, tag, key) in enumerate(modules):

                col = cols[mod_idx % 3]

                with col:

                    with st.container(border=True, key=f"lift_module_{key}"):

                        h_left, h_right = st.columns([3, 1.4])

                        with h_left:

                            st.markdown(f"**{icon} {title}**")

                        with h_right:

                            st.html(f"""
                            <div style="text-align: right;">
                                <span style="font-size: 0.68rem; font-weight: 700; color: #116B57; background: #E8F2ED; padding: 2px 7px; border-radius: 999px; text-transform: uppercase; letter-spacing: 0.04em;">
                                    {tag}
                                </span>
                            </div>
                            """)

                        st.caption(desc)

                        st.space("small")

                        if st.button(
                            "Launch Module →",
                            key=f"launch_{key}",
                            width="stretch"
                        ):

                            st.session_state.current_page = page

                            st.rerun()

    # -----------------------------------------------------
    # 6. OPERATIONAL INTELLIGENCE & COMPLIANCE POSTURE
    # -----------------------------------------------------

    st.space("small")

    col_hol, col_sec = st.columns(2)

    with col_hol:

        with st.container(border=True, key="lift_holidays_box"):

            st.markdown(
                "##### Upcoming Corporate Holidays",
                help="Next public holidays recognized by AIT Solutions"
            )

            st.caption("Auto-synchronized with the corporate holiday register.")

            if upcoming_holidays:

                for hol_name, hol_date in upcoming_holidays:

                    st.html(f"""
                    <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px dashed #E1E5DF;">
                        <div style="font-weight: 650; color: #252A2A; font-size: 0.92rem;">
                            {hol_name}
                        </div>
                        <div style="font-size: 0.8rem; color: #116B57; font-weight: 650; background: #E8F2ED; padding: 2px 9px; border-radius: 6px;">
                            {hol_date}
                        </div>
                    </div>
                    """)

            else:

                st.caption("No upcoming public holidays scheduled for this cycle.")

    with col_sec:

        with st.container(border=True, key="lift_compliance_box"):

            st.markdown(
                "##### Governance & Statutory Compliance",
                help="System health, security and compliance benchmarks"
            )

            st.caption("All security standards and regulatory rules active.")

            st.html("""
            <div style="display: flex; flex-direction: column; gap: 9px; margin-top: 6px;">
                <div style="display: flex; align-items: center; gap: 9px; font-size: 0.87rem; color: #34413B;">
                    <span style="color: #10B981; font-family: 'Material Symbols Rounded', sans-serif; font-size: 19px;">verified</span>
                    <span><strong>Statutory Payroll:</strong> EPF (12%), ESI &amp; TDS compliance engine</span>
                </div>
                <div style="display: flex; align-items: center; gap: 9px; font-size: 0.87rem; color: #34413B;">
                    <span style="color: #10B981; font-family: 'Material Symbols Rounded', sans-serif; font-size: 19px;">lock</span>
                    <span><strong>Authentication:</strong> PBKDF2-HMAC-SHA256 (200,000 iterations)</span>
                </div>
                <div style="display: flex; align-items: center; gap: 9px; font-size: 0.87rem; color: #34413B;">
                    <span style="color: #10B981; font-family: 'Material Symbols Rounded', sans-serif; font-size: 19px;">shield</span>
                    <span><strong>Workplace Policy:</strong> POSH Act prevention &amp; governance standards</span>
                </div>
            </div>
            """)
