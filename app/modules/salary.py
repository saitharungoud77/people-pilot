import streamlit as st

from database.connection import (
    get_connection,
    create_salary_table
)
from modules.session import require_employee


# ---------------------------------------------------------
# STATUTORY SALARY STRUCTURE RULES
# ---------------------------------------------------------
#
# Auto-generated structure, based on Indian statutory norms:
#
#   Basic             = 50% of CTC
#       (Code on Wages, 2019: "wages" (basic + DA) must be at
#        least 50% of the total remuneration)
#
#   HRA               = 50% of Basic (metro / common practice)
#                       40% of Basic (non-metro)
#
#   Employer PF       = 12% of PF wages
#   Employee PF       = 12% of PF wages
#       standard wage ceiling = Rs 15,000 / month.
#   Employer EPS       = 8.33% of pensionable wages, capped at
#       Rs 15,000 / month; the remaining employer share goes to EPF.
#       This application assumes existing employees are EPF members
#       and EPS-eligible, as confirmed by HR.
#
#   Special Allowance = balance (CTC - Basic - HRA - Employer PF)
#   Other Allowance   = 0
#   Other Deduction   = 0
#
# References (not part of this structure):
#   Gratuity @ 4.81% of Basic  -> Payment of Gratuity Act, 1972
#   ESI @ 0.75% employee / 3.25% employer -> applies only when
#       gross monthly pay is up to Rs 21,000 (ESI Act, 1948)
#
BASIC_PCT_OF_CTC = 0.50

HRA_PCT_METRO = 0.50
HRA_PCT_NON_METRO = 0.40

PF_RATE = 0.12
PF_WAGE_CEILING_MONTHLY = 15000.0
PF_CEILING_ANNUAL = PF_WAGE_CEILING_MONTHLY * 12
EPS_RATE = 0.0833
EPS_WAGE_CEILING_MONTHLY = 15000.0
PROFESSIONAL_TAX_MONTHLY = 200.0

GRATUITY_PCT_OF_BASIC = 0.0481
ESI_GROSS_LIMIT_MONTHLY = 21000.0
ESI_EMPLOYEE_RATE = 0.0075
ESI_EMPLOYER_RATE = 0.0325


COMPONENT_LABELS = [
    ("basic_annual", "Basic Salary"),
    ("hra_annual", "House Rent Allowance (HRA)"),
    ("special_allowance_annual", "Special Allowance"),
    ("other_allowance_annual", "Other Allowance"),
    ("employee_pf_annual", "Employee PF"),
    ("employer_pf_annual", "Employer PF"),
    ("other_deduction_annual", "Other Deduction"),
]

COMPONENT_KEYS = [key for key, _label in COMPONENT_LABELS]


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def auto_salary_components(
    annual_ctc,
    pf_on_ceiling=True,
    hra_pct=HRA_PCT_METRO
):
    """
    Build a statutory salary structure from the annual CTC.

    pf_on_ceiling=True  -> PF on the standard wage ceiling
                           (Rs 15,000 / month).
    pf_on_ceiling=False -> PF on the full basic wages.
    """

    annual_ctc = float(annual_ctc or 0)

    basic = annual_ctc * BASIC_PCT_OF_CTC

    hra = basic * hra_pct

    pf_wage_base = (
        min(basic, PF_CEILING_ANNUAL)
        if pf_on_ceiling
        else basic
    )

    st.caption(
    f"Professional Tax: ₹ {PROFESSIONAL_TAX_MONTHLY:,.2f} / month "
    "(deducted from take-home; not included in CTC)."
    )

    employer_pf = pf_wage_base * PF_RATE

    employee_pf = pf_wage_base * PF_RATE

    special = annual_ctc - basic - hra - employer_pf

    if special < 0:

        special = 0.0

    return {
        "basic_annual": round(basic, 2),
        "hra_annual": round(hra, 2),
        "special_allowance_annual": round(special, 2),
        "other_allowance_annual": 0.0,
        "employee_pf_annual": round(employee_pf, 2),
        "employer_pf_annual": round(employer_pf, 2),
        "other_deduction_annual": 0.0,
    }


def pf_contributions_for_basic(basic_monthly):
    """Return capped PF wages and 12% employee/employer contributions."""

    pf_wages = min(
        max(0.0, float(basic_monthly or 0)),
        PF_WAGE_CEILING_MONTHLY
    )
    contribution = round(pf_wages * PF_RATE, 2)
    return {
        "pf_wages": round(pf_wages, 2),
        "employee_pf": contribution,
        "employer_pf": contribution,
    }


def get_structure(employee_id):
    """Return an employee's saved salary structure as a dict, or None."""

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        f"""
        SELECT {", ".join(COMPONENT_KEYS)}
        FROM salary_structures
        WHERE employee_id = ?
        """,
        (employee_id,)
    )

    row = cursor.fetchone()

    connection.close()

    if not row:

        return None

    return dict(zip(COMPONENT_KEYS, row))


def save_structure(employee_id, values):
    """Insert or update an employee's salary structure."""

    connection = get_connection()

    try:
        employee = connection.execute(
            "SELECT annual_ctc FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()

        if employee is None:
            raise ValueError(f"Employee not found: {employee_id}")

        values = dict(values)
        contributions = pf_contributions_for_basic(
            float(values["basic_annual"]) / 12
        )
        employee_pf = round(contributions["employee_pf"] * 12, 2)
        employer_pf = round(contributions["employer_pf"] * 12, 2)
        values["employee_pf_annual"] = employee_pf
        values["employer_pf_annual"] = employer_pf
        values["special_allowance_annual"] = round(
            float(employee[0])
            - float(values["basic_annual"])
            - float(values["hra_annual"])
            - float(values["other_allowance_annual"])
            - employer_pf,
            2
        )

        if values["special_allowance_annual"] < 0:
            raise ValueError(
                "Basic, HRA, other allowance, and employer PF exceed "
                "the employee's annual CTC."
            )

        _save_structure(connection, employee_id, values)
    finally:
        connection.close()


def _save_structure(connection, employee_id, values):
    """Persist a validated structure on an existing connection."""

    connection.execute(
        """
        INSERT INTO salary_structures
        (
            employee_id,
            basic_annual,
            hra_annual,
            special_allowance_annual,
            other_allowance_annual,
            employee_pf_annual,
            employer_pf_annual,
            other_deduction_annual
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)

        ON CONFLICT(employee_id)
        DO UPDATE SET

            basic_annual = excluded.basic_annual,

            hra_annual = excluded.hra_annual,

            special_allowance_annual =
                excluded.special_allowance_annual,

            other_allowance_annual =
                excluded.other_allowance_annual,

            employee_pf_annual =
                excluded.employee_pf_annual,

            employer_pf_annual =
                excluded.employer_pf_annual,

            other_deduction_annual =
                excluded.other_deduction_annual
        """,
        (
            employee_id,
            values["basic_annual"],
            values["hra_annual"],
            values["special_allowance_annual"],
            values["other_allowance_annual"],
            values["employee_pf_annual"],
            values["employer_pf_annual"],
            values["other_deduction_annual"],
        )
    )
    connection.commit()


def structure_summary(values):
    """Return (gross_annual, total_deductions, net_annual)."""

    gross_annual = (
        values["basic_annual"]
        + values["hra_annual"]
        + values["special_allowance_annual"]
        + values["other_allowance_annual"]
    )

    total_deductions = (
        values["employee_pf_annual"]
        + values["other_deduction_annual"]
        + PROFESSIONAL_TAX_MONTHLY * 12
    )

    return gross_annual, total_deductions, gross_annual - total_deductions


def scale_salary_structure(employee_id, old_ctc, new_ctc):
    """
    Proportionally rescale an employee's salary structure when
    their annual CTC changes.

    Every component (basic, HRA, allowances, PF, deductions)
    keeps its existing share of the CTC, so the structure stays
    consistent with the new annual salary.

    Returns True when an existing structure was updated.
    """

    if not old_ctc or old_ctc <= 0:

        return False

    if new_ctc is None or float(new_ctc) == float(old_ctc):

        return False

    ratio = float(new_ctc) / float(old_ctc)

    connection = get_connection()

    try:

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT
                basic_annual,
                hra_annual,
                special_allowance_annual,
                other_allowance_annual,
                employee_pf_annual,
                employer_pf_annual,
                other_deduction_annual
            FROM salary_structures
            WHERE employee_id = ?
            """,
            (employee_id,)
        )

        row = cursor.fetchone()

        if not row:

            return False

        scaled = [round(value * ratio, 2) for value in row]
        basic, hra, _special, other_allowance, _employee_pf, _employer_pf, other_deduction = scaled
        contributions = pf_contributions_for_basic(basic / 12)
        employee_pf = round(contributions["employee_pf"] * 12, 2)
        employer_pf = round(contributions["employer_pf"] * 12, 2)
        special = round(
            float(new_ctc) - basic - hra - other_allowance - employer_pf,
            2
        )
        if special < 0:
            raise ValueError(
                "The revised CTC cannot cover the employee's salary "
                "components and capped employer PF."
            )
        scaled = [
            basic, hra, special, other_allowance, employee_pf,
            employer_pf, other_deduction
        ]

        cursor.execute(
            """
            UPDATE salary_structures
            SET
                basic_annual = ?,
                hra_annual = ?,
                special_allowance_annual = ?,
                other_allowance_annual = ?,
                employee_pf_annual = ?,
                employer_pf_annual = ?,
                other_deduction_annual = ?
            WHERE employee_id = ?
            """,
            (*scaled, employee_id)
        )

        connection.commit()

        return True

    finally:

        connection.close()


# ---------------------------------------------------------
# SHARED RENDERING
# ---------------------------------------------------------

def render_structure_details(values):
    """Show the salary components and summary for given annual values."""

    st.markdown("#### Salary Components")

    col1, col2 = st.columns(2)

    for index, (key, label) in enumerate(COMPONENT_LABELS):

        target = col1 if index < 4 else col2

        target.write(
            f"**{label}:** "
            f"₹ {values[key] / 100000:.5f} LPA "
            f"(₹ {values[key] / 12:,.2f} / month)"
        )

    gross_annual, total_deductions, net_annual = structure_summary(
        values
    )

    st.markdown("#### Salary Summary")

    m1, m2, m3, m4 = st.columns(4)

    with m1:

        st.metric(
            "Gross Annual",
            f"₹ {gross_annual / 100000:.5f} L"
        )

    with m2:

        st.metric(
            "Gross Monthly",
            f"₹ {gross_annual / 12:,.2f}"
        )

    with m3:

        st.metric(
            "Employee PF (Monthly)",
            f"₹ {values['employee_pf_annual'] / 12:,.2f}"
        )

    with m4:

        st.metric(
            "Net Monthly",
            f"₹ {net_annual / 12:,.2f}"
        )

    # -----------------------------------------------------
    # STATUTORY REFERENCE NOTES
    # -----------------------------------------------------

    basic_annual = values["basic_annual"]

    gross_monthly = gross_annual / 12

    note = (
        f"PF is calculated at 12% of basic wages up to "
        f"₹ {PF_WAGE_CEILING_MONTHLY:,.0f} / month; the employer "
        f"contribution includes EPS at {EPS_RATE * 100:.2f}% of "
        f"pensionable wages up to ₹{EPS_WAGE_CEILING_MONTHLY:,.0f}/month. "
        f"Gratuity @ 4.81% of Basic ≈ "
        f"₹ {basic_annual * GRATUITY_PCT_OF_BASIC:,.0f} / year "
        f"is an employer liability (Payment of Gratuity "
        f"Act, 1972). "
    )

    if gross_monthly <= ESI_GROSS_LIMIT_MONTHLY:

        note += (
            f"ESI applies: gross ≤ "
            f"₹ {ESI_GROSS_LIMIT_MONTHLY:,.0f} / month "
            f"(0.75% employee / 3.25% employer)."
        )

    else:

        note += (
            f"ESI not applicable: gross > "
            f"₹ {ESI_GROSS_LIMIT_MONTHLY:,.0f} / month."
        )

    st.caption(note)


# ---------------------------------------------------------
# CREATE / UPDATE SALARY
# ---------------------------------------------------------

def render_create_salary():

    st.subheader("Create / Update Salary Structure")

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            employee_id,
            employee_name,
            annual_ctc
        FROM employees
        ORDER BY employee_name
        """
    )

    employees = cursor.fetchall()

    connection.close()

    if not employees:

        st.warning("Please create an employee first.")

        return

    employee_options = {
        f"{employee_id} - {employee_name}": (
            employee_id,
            employee_name,
            annual_ctc
        )
        for employee_id, employee_name, annual_ctc in employees
    }

    selected = st.selectbox(
        "Select Employee",
        list(employee_options.keys())
    )

    (
        employee_id,
        employee_name,
        annual_ctc
    ) = employee_options[selected]

    with st.container(border=True):

        st.markdown(f"### {employee_name}")

        col1, col2, col3 = st.columns(3)

        with col1:

            st.write(f"**Employee ID:** {employee_id}")

        with col2:

            st.write(
                f"**Annual CTC:** ₹ {annual_ctc / 100000:.2f} LPA"
            )

        with col3:

            st.write(
                f"**Monthly CTC:** ₹ {annual_ctc / 12:,.2f}"
            )

    # -----------------------------------------------------
    # STATUTORY AUTO-GENERATION SETTINGS
    # -----------------------------------------------------

    with st.expander(
        "Statutory auto-generation settings",
        expanded=False
    ):

        st.caption(
            "Used when a structure is auto-generated from the "
            "CTC (no saved structure yet) and by "
            "Auto-fill from CTC while editing."
        )

        hra_basis = st.radio(
            "HRA rate",
            [
                "50% of Basic (metro / common practice)",
                "40% of Basic (non-metro)"
            ],
            index=0,
            key="salary_hra_basis",
            horizontal=True
        )

    hra_pct = (
        HRA_PCT_METRO
        if hra_basis.startswith("50%")
        else HRA_PCT_NON_METRO
    )

    editing_flag = f"salary_editing_{employee_id}"
    token_key = f"salary_token_{employee_id}"

    editing = st.session_state.get(editing_flag, False)
    token = st.session_state.get(token_key, 0)

    saved = get_structure(employee_id)

    # -----------------------------------------------------
    # READ-ONLY VIEW
    # -----------------------------------------------------

    if not editing:

        if saved:

            values = saved

            st.caption(
                "Saved salary structure. Click Edit to "
                "modify the components."
            )

        else:

            values = auto_salary_components(
                annual_ctc,
                hra_pct=hra_pct
            )

            st.info(
                "No salary structure is saved yet. The details "
                "below are auto-generated from the annual CTC "
                "using statutory norms (Basic = 50% of CTC, "
                f"HRA = {int(hra_pct * 100)}% of Basic, PF = 12% "
                f"of Basic up to ₹{PF_WAGE_CEILING_MONTHLY:,.0f}/month). "
                "Click Edit to adjust them, "
                "then Update to save."
            )

        render_structure_details(values)

        if st.button(
            "Edit Salary Details",
            width="content"
        ):

            st.session_state[token_key] = token + 1
            st.session_state[editing_flag] = True

            st.rerun()

        return

    # -----------------------------------------------------
    # EDIT VIEW
    # -----------------------------------------------------

    st.markdown("### Edit Salary Components")

    st.caption("Enter all salary values in LPA.")

    base_values = (
        saved if saved
        else auto_salary_components(
            annual_ctc,
            hra_pct=hra_pct
        )
    )

    def autofill():

        components = auto_salary_components(
            annual_ctc,
            hra_pct=hra_pct
        )

        for key in COMPONENT_KEYS:

            st.session_state[
                f"{editing_flag}_{token}_{key}"
            ] = components[key] / 100000

    st.button(
        "Auto-fill from CTC",
        on_click=autofill,
        width="content"
    )

    values = {}

    col1, col2 = st.columns(2)

    for index, (key, label) in enumerate(COMPONENT_LABELS):

        target = col1 if index < 4 else col2

        widget_key = f"{editing_flag}_{token}_{key}"

        input_args = {
            "label": f"{label} (LPA)",
            "min_value": 0.0,
            "step": 0.00001,
            "format": "%.5f",
            "key": widget_key,
        }

        # Only supply a default the first time the widget is
        # created. Afterwards the widget keeps its own state
        # (including values written by "Auto-fill from CTC").
        if widget_key not in st.session_state:

            input_args["value"] = float(
                base_values[key] / 100000
            )

        if key in ("employee_pf_annual", "employer_pf_annual"):
            basic_widget_key = f"{editing_flag}_{token}_basic_annual"
            basic_lpa = st.session_state.get(
                basic_widget_key,
                base_values["basic_annual"] / 100000
            )
            calculated = pf_contributions_for_basic(
                float(basic_lpa) * 100000 / 12
            )
            input_args["value"] = (
                calculated["employee_pf" if key == "employee_pf_annual"
                           else "employer_pf"] * 12 / 100000
            )
            input_args["disabled"] = True

        values[key] = target.number_input(**input_args)

    annual_values = {
        key: values[key] * 100000
        for key in COMPONENT_KEYS
    }

    render_structure_details(annual_values)

    save_col, cancel_col = st.columns(2)

    with save_col:

        save_clicked = st.button(
            "Update Salary Structure",
            width="stretch"
        )

    with cancel_col:

        cancel_clicked = st.button(
            "Cancel",
            width="stretch"
        )

    if save_clicked:

        save_structure(employee_id, annual_values)

        st.session_state[editing_flag] = False

        st.session_state["salary_flash"] = (
            f"Salary structure updated for {employee_name}."
        )

        st.rerun()

    if cancel_clicked:

        st.session_state[editing_flag] = False

        st.rerun()


# ---------------------------------------------------------
# VIEW SALARY STRUCTURES
# ---------------------------------------------------------

def render_view_salaries():

    st.subheader("Salary Structures")

    search_name = st.text_input(
        "Search by Employee Name",
        placeholder="Enter employee name..."
    ).strip()

    connection = get_connection()

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            s.employee_id,
            e.employee_name,
            e.annual_ctc,
            s.basic_annual,
            s.hra_annual,
            s.special_allowance_annual,
            s.other_allowance_annual,
            s.employee_pf_annual,
            s.employer_pf_annual,
            s.other_deduction_annual
        FROM salary_structures s
        JOIN employees e
            ON s.employee_id = e.employee_id
        ORDER BY e.employee_name
        """
    )

    salaries = cursor.fetchall()

    connection.close()

    if search_name:

        salaries = [
            salary
            for salary in salaries
            if search_name.lower() in str(salary[1]).lower()
        ]

    if not salaries:

        if search_name:

            st.warning(
                f"No salary structure found for "
                f"'{search_name}'."
            )

        else:

            st.info("No salary structures found.")

        return

    if search_name:

        st.info(
            f"Showing {len(salaries)} result(s) "
            f"for '{search_name}'."
        )

    for salary in salaries:

        (
            employee_id,
            employee_name,
            annual_ctc,
            basic,
            hra,
            special,
            other_allowance,
            employee_pf,
            employer_pf,
            other_deduction
        ) = salary

        gross_annual = (
            basic
            + hra
            + special
            + other_allowance
        )

        gross_monthly = gross_annual / 12

        employee_pf_monthly = employee_pf / 12

        other_deduction_monthly = other_deduction / 12

        net_monthly = (
            gross_monthly
            - employee_pf_monthly
            - other_deduction_monthly
            - PROFESSIONAL_TAX_MONTHLY
        )

        with st.container(border=True):

            st.markdown(f"### {employee_name}")

            st.write(f"**Employee ID:** {employee_id}")

            col1, col2, col3, col4 = st.columns(4)

            with col1:

                st.metric(
                    "CTC",
                    f"₹ {annual_ctc / 100000:.2f} L"
                )

            with col2:

                st.metric(
                    "Gross Monthly",
                    f"₹ {gross_monthly:,.2f}"
                )

            with col3:

                st.metric(
                    "Employee PF",
                    f"₹ {employee_pf_monthly:,.2f}"
                )

            with col4:

                st.metric(
                    "Net Monthly",
                    f"₹ {net_monthly:,.2f}"
                )

            with st.expander("View Salary Components"):

                st.write(
                    f"Basic Salary: ₹ {basic / 100000:.5f} LPA"
                )

                st.write(
                    f"HRA: ₹ {hra / 100000:.5f} LPA"
                )

                st.write(
                    f"Special Allowance: "
                    f"₹ {special / 100000:.5f} LPA"
                )

                st.write(
                    f"Other Allowance: "
                    f"₹ {other_allowance / 100000:.5f} LPA"
                )

                st.write(
                    f"Employee PF: "
                    f"₹ {employee_pf / 100000:.5f} LPA"
                )

                st.write(
                    f"Employer PF: "
                    f"₹ {employer_pf / 100000:.5f} LPA"
                )

                st.write(
                    f"Other Deduction: "
                    f"₹ {other_deduction / 100000:.5f} LPA"
                )
                st.write(
                    "Professional Tax: "
                    f"₹ {PROFESSIONAL_TAX_MONTHLY:,.2f} / month"
                )


# ---------------------------------------------------------
# SALARY PAGE
# ---------------------------------------------------------

def show_salary():

    create_salary_table()

    flash_message = st.session_state.pop("salary_flash", None)

    if flash_message:

        st.success(flash_message)

    st.divider()

    option = st.selectbox(
        "Select Salary Action",
        [
            "Create Salary Structure",
            "View Salary Structures"
        ]
    )

    if option == "Create Salary Structure":

        render_create_salary()

    elif option == "View Salary Structures":

        render_view_salaries()


# ============================================================
# SALARY PAGE (header + back button + module)
# ============================================================

def show_salary_page(go_home=None):
    """Full salary page, wired up by main.py."""

    st.title("Salary & payroll", icon=":material/payments:")

    st.caption(
        "Manage employee salary structures, allowances, "
        "PF and deductions per EPFO / statutory norms."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="salary_back",
        width="content"
    ):

        go_home()

        st.rerun()

    show_salary()


# ============================================================
# MY SALARY (EMPLOYEE VIEW)
# ============================================================
# Read-only breakdown of the signed-in employee's own structure.

def show_my_salary():

    employee = require_employee()

    if employee is None:

        return

    st.title("My salary", icon=":material/payments:")

    st.caption("Your annual salary structure and monthly breakdown.")

    structure = get_structure(employee["employee_id"])

    if not structure:

        st.info(
            "Your salary structure has not been set up yet. "
            "Please contact HR."
        )

        return

    gross_annual, total_deductions, net_annual = structure_summary(
        structure
    )

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "Annual CTC",
            f"₹ {employee['annual_ctc'] / 100000:,.2f} L",
            border=True
        )

    with col2:

        st.metric(
            "Net annual",
            f"₹ {net_annual / 100000:,.2f} L",
            border=True
        )

    with col3:

        st.metric(
            "Net monthly",
            f"₹ {net_annual / 12:,.2f}",
            border=True
        )

    st.divider()

    render_structure_details(structure)

    st.divider()

    # Imported locally so this module and revisions.py never form a
    # circular dependency (revisions.py builds on this module).
    from modules.revisions import render_revision_history

    render_revision_history(employee["employee_id"])
