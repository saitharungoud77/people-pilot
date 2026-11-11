import datetime
import json
import os
import re

import streamlit as st

from database.connection import get_connection

from modules.config import get_secret

from modules.offer_letter import ai_available
from modules.salary import PROFESSIONAL_TAX_MONTHLY


# ============================================================
# AI LETTER GENERATOR
# ============================================================
# HR needs the same handful of letters over and over: experience,
# relieving, salary certificate, employment verification and the
# occasional warning.
#
# The facts (name, dates, designation, salary) are written by this
# module from the database, never by the model. AI only improves
# the wording, and every number it writes is checked against the
# facts before the letter is shown. If the check fails, the
# standard wording is used instead - so a letter can never go out
# with the wrong salary.

LETTER_TYPES = [
    ("Experience letter", "experience"),
    ("Relieving letter", "relieving"),
    ("Salary certificate", "salary"),
    ("Employment verification", "employment"),
    ("Warning letter", "warning")
]

LETTER_LABELS = dict(LETTER_TYPES)

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

COMPANY = "AIT Solutions"

LOCATION = "Hi-Tech City, Hyderabad"

POLISH_PROMPT = """You rewrite HR letters for AIT Solutions, an Indian company.

Rules:
- Keep every name, date, amount, job title and fact exactly as given.
- Never add achievements, awards, duties or numbers that are not in the facts.
- Formal, warm, plain English. Short paragraphs.
- Keep the same structure and the same legal meaning.

Return ONLY a JSON object:
{"subject": "the subject line", "body": ["paragraph", "paragraph"]}"""


# ---------------------------------------------------------
# DATA
# ---------------------------------------------------------

def _employee_rows():
    """Every employee with their salary structure (or None)."""

    connection = get_connection()

    try:

        return connection.execute(
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
                COALESCE(e.exit_date, '') AS exit_date,
                e.gender,
                s.basic_annual,
                s.hra_annual,
                s.special_allowance_annual,
                s.other_allowance_annual,
                s.employee_pf_annual,
                s.employer_pf_annual,
                s.other_deduction_annual
            FROM employees e
            LEFT JOIN salary_structures s
                ON e.employee_id = s.employee_id
            ORDER BY e.employee_name
            """
        ).fetchall()

    finally:

        connection.close()


def employee_options():
    """(label, employee_id) for the picker."""

    return [
        (f"{row[1]} · {row[0]}", row[0])
        for row in _employee_rows()
    ]


def get_employee(employee_id):
    """One employee as a dict, or None."""

    for row in _employee_rows():

        if row[0] != employee_id:

            continue

        keys = [
            "employee_id",
            "employee_name",
            "department",
            "designation",
            "joining_date",
            "location",
            "employment_type",
            "annual_ctc",
            "exit_date",
            "gender",
            "basic_annual",
            "hra_annual",
            "special_allowance_annual",
            "other_allowance_annual",
            "employee_pf_annual",
            "employer_pf_annual",
            "other_deduction_annual"
        ]

        return dict(zip(keys, row))

    return None


# ---------------------------------------------------------
# FORMATTING
# ---------------------------------------------------------

def _date(value):
    """A stored date as '23 October 2026' (or a fallback)."""

    try:

        return datetime.date.fromisoformat(str(value)).strftime(
            "%d %B %Y"
        )

    except (TypeError, ValueError):

        return str(value or "")


def _money(value):

    return f"{float(value or 0):,.2f}"


_ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven",
    "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
    "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen",
    "Nineteen"
]

_TENS = [
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty",
    "Seventy", "Eighty", "Ninety"
]


def _two_words(number):

    if number < 20:

        return _ONES[number]

    tens, ones = divmod(number, 10)

    return _TENS[tens] + ("" if ones == 0 else " " + _ONES[ones])


def _three_words(number):

    hundred, rest = divmod(number, 100)

    parts = []

    if hundred:

        parts.append(f"{_ONES[hundred]} Hundred")

    if rest:

        parts.append(_two_words(rest))

    return " ".join(parts)


def amount_in_words(amount):
    """Indian cheque-style words: 'Twelve Lakh Rupees Only'."""

    amount = round(float(amount or 0), 2)

    rupees = int(amount)

    paise = int(round((amount - rupees) * 100))

    parts = []

    crore, rest = divmod(rupees, 10_000_000)

    lakh, rest = divmod(rest, 100_000)

    thousand, rest = divmod(rest, 1000)

    if crore:

        parts.append(f"{_three_words(crore)} Crore")

    if lakh:

        parts.append(f"{_two_words(lakh)} Lakh")

    if thousand:

        parts.append(f"{_two_words(thousand)} Thousand")

    if rest:

        parts.append(_three_words(rest))

    words = (" ".join(parts) + " Rupees") if parts else "Zero Rupees"

    if paise:

        words += f" and {_two_words(paise)} Paise"

    return words + " Only"


def _monthly(employee):
    """Monthly salary figures from the annual structure."""

    annual = {
        "basic": float(employee.get("basic_annual") or 0),
        "hra": float(employee.get("hra_annual") or 0),
        "special": float(employee.get("special_allowance_annual") or 0),
        "other": float(employee.get("other_allowance_annual") or 0),
        "employee_pf": float(employee.get("employee_pf_annual") or 0),
        "employer_pf": float(employee.get("employer_pf_annual") or 0),
        "other_deduction": float(employee.get("other_deduction_annual") or 0)
    }

    monthly = {key: value / 12 for key, value in annual.items()}

    monthly["gross"] = (
        monthly["basic"]
        + monthly["hra"]
        + monthly["special"]
        + monthly["other"]
    )

    monthly["net"] = (
        monthly["gross"]
        - monthly["employee_pf"]
        - monthly["other_deduction"]
        - PROFESSIONAL_TAX_MONTHLY
    )
    monthly["professional_tax"] = PROFESSIONAL_TAX_MONTHLY

    return monthly


# ---------------------------------------------------------
# DRAFTING
# ---------------------------------------------------------

def _facts_text(employee, options, kind):
    """The fixed facts handed to the model."""

    monthly = _monthly(employee)

    lines = [
        f"Company: {COMPANY}, {LOCATION}",
        f"Letter type: {LETTER_LABELS.get(kind, kind)}",
        f"Letter date: {_date(options.get('issue_date'))}",
        f"Employee: {employee['employee_name']} ({employee['employee_id']})",
        f"Designation: {employee['designation']}",
        f"Department: {employee['department']}",
        f"Employment type: {employee['employment_type']}",
        f"Joining date: {_date(employee['joining_date'])}",
        f"Work location: {employee['location']}",
        f"Annual CTC: INR {_money(employee['annual_ctc'])}",
        f"Monthly gross: INR {_money(monthly['gross'])}",
        f"Monthly net: INR {_money(monthly['net'])}"
    ]

    for key in ("last_day", "addressed_to", "purpose", "incident_date"):

        if options.get(key):

            label = key.replace("_", " ").title()

            value = options[key]

            if isinstance(value, datetime.date):

                value = _date(value)

            lines.append(f"{label}: {value}")

    if options.get("incident_summary"):

        lines.append(f"Incident: {options['incident_summary']}")

    return "\n".join(lines)


def _draft_experience(employee, options):
    """A factual experience certificate."""

    name = employee["employee_name"]

    joined = _date(employee["joining_date"])

    exit_date = employee.get("exit_date")

    if exit_date:

        tenure = (
            f"from {joined} to {_date(exit_date)}"
        )

        status = "was employed with"

    else:

        tenure = f"from {joined}"

        status = "is employed with"

    body = [
        (
            f"This is to certify that {name} ({employee['employee_id']}) "
            f"{status} {COMPANY} as {employee['designation']} in the "
            f"{employee['department']} department, based at "
            f"{employee['location']}, {tenure}."
        ),
        (
            f"During this tenure, {name} carried out the responsibilities "
            f"of the {employee['designation']} role. Their conduct and "
            f"performance were found to be satisfactory."
        ),
        (
            f"We wish {name} continued success in their professional "
            f"journey."
        )
    ]

    return {
        "subject": f"Experience Certificate — {name}",
        "title": "TO WHOMSOEVER IT MAY CONCERN",
        "body": body
    }


def _draft_relieving(employee, options):
    """A relieving letter dated on the last working day."""

    name = employee["employee_name"]

    last_day = options.get("last_day") or employee.get("exit_date")

    if not last_day:

        raise ValueError(
            "Choose the last working day for the relieving letter."
        )

    body = [
        (
            f"This is to certify that {name} ({employee['employee_id']}), "
            f"working as {employee['designation']} in the "
            f"{employee['department']} department at {COMPANY}, has been "
            f"relieved of their duties at the close of business on "
            f"{_date(last_day)}."
        ),
        (
            f"All company property issued to {name} has been accounted "
            f"for, and their full and final settlement will be processed "
            f"as per company policy and applicable law."
        ),
        (
            f"{name} is free to take up employment elsewhere, and we "
            f"wish them success in their future endeavours."
        )
    ]

    return {
        "subject": f"Relieving Letter — {name}",
        "title": "",
        "body": body
    }


def _draft_salary(employee, options):
    """A salary certificate for a bank, visa or landlord."""

    name = employee["employee_name"]

    monthly = _monthly(employee)

    addressed = (options.get("addressed_to") or "").strip()

    purpose = (options.get("purpose") or "").strip()

    body = []

    if addressed:

        body.append(f"To: {addressed}")

    body.append(
        f"This is to certify that {name} ({employee['employee_id']}) is "
        f"employed with {COMPANY} as {employee['designation']} in the "
        f"{employee['department']} department since "
        f"{_date(employee['joining_date'])}."
    )

    body.append(
        f"Their current annual cost to company is INR "
        f"{_money(employee['annual_ctc'])} "
        f"({amount_in_words(employee['annual_ctc'])})."
    )

    if options.get("include_breakdown", True):

        body.append(
            "The monthly salary structure is as follows:"
        )

        body.append(
            f"Basic: INR {_money(monthly['basic'])} · "
            f"HRA: INR {_money(monthly['hra'])} · "
            f"Special allowance: INR {_money(monthly['special'])} · "
            f"Other allowance: INR {_money(monthly['other'])}"
        )

        body.append(
            f"Gross monthly salary: INR {_money(monthly['gross'])} · "
            f"Employee PF: INR {_money(monthly['employee_pf'])} · "
            f"Professional Tax: INR {_money(monthly['professional_tax'])} · "
            f"Net monthly salary: INR {_money(monthly['net'])}"
        )

    body.append(
        f"This certificate is issued at the request of the employee"
        + (f" for {purpose}" if purpose else "")
        + "."
    )

    return {
        "subject": f"Salary Certificate — {name}",
        "title": "TO WHOMSOEVER IT MAY CONCERN",
        "body": body
    }


def _draft_employment(employee, options):
    """A short employment verification letter."""

    name = employee["employee_name"]

    addressed = (options.get("addressed_to") or "").strip()

    purpose = (options.get("purpose") or "").strip()

    active = not employee.get("exit_date")

    body = []

    if addressed:

        body.append(f"To: {addressed}")

    body.append(
        f"This is to confirm that {name} ({employee['employee_id']}) "
        f"{'is currently employed' if active else 'was employed'} with "
        f"{COMPANY} as {employee['designation']} in the "
        f"{employee['department']} department, at {employee['location']}."
    )

    body.append(
        f"Employment type: {employee['employment_type']} · "
        f"Date of joining: {_date(employee['joining_date'])}"
        + (
            f" · Date of exit: {_date(employee['exit_date'])}"
            if employee.get("exit_date") else ""
        )
    )

    body.append(
        "This letter is issued for verification purposes"
        + (f" in connection with {purpose}" if purpose else "")
        + "."
    )

    return {
        "subject": f"Employment Verification — {name}",
        "title": "",
        "body": body
    }


def _draft_warning(employee, options):
    """A formal warning letter."""

    name = employee["employee_name"]

    issue = (options.get("incident_summary") or "").strip()

    if not issue:

        raise ValueError(
            "Describe the issue for the warning letter."
        )

    incident_date = options.get("incident_date")

    body = [
        (
            f"This letter is a formal warning to you, {name} "
            f"({employee['employee_id']}), {employee['designation']}, "
            f"regarding {issue}"
            + (f", which came to our attention on {_date(incident_date)}" if incident_date else "")
            + "."
        ),
        (
            "This falls short of the standards of conduct and performance "
            "expected at AIT Solutions. You are advised to correct this "
            "with immediate effect and to ensure it is not repeated."
        ),
        (
            "Failure to improve may lead to further disciplinary action "
            "as per company policy. Please sign and return a copy of "
            "this letter to acknowledge receipt."
        )
    ]

    return {
        "subject": "Warning Letter",
        "title": "",
        "body": body
    }


_DRAFTERS = {
    "experience": _draft_experience,
    "relieving": _draft_relieving,
    "salary": _draft_salary,
    "employment": _draft_employment,
    "warning": _draft_warning
}


def draft_letter(kind, employee, options):
    """Build the factual letter without any AI."""

    drafter = _DRAFTERS.get(kind)

    if drafter is None:

        raise ValueError(f"Unknown letter type: {kind}")

    letter = drafter(employee, options)

    letter["kind"] = kind

    letter["closing"] = (
        "Yours sincerely,"
        if kind == "warning"
        else "Yours sincerely,"
    )

    return letter


# ---------------------------------------------------------
# AI POLISH
# ---------------------------------------------------------

def _number_set(text):
    """Every number in the text, normalised for comparison."""

    return {
        re.sub(r"[^0-9]", "", match)
        for match in re.findall(r"\d[\d,.]*", text or "")
        if re.sub(r"[^0-9]", "", match)
    }


def polish_letter(kind, employee, options, letter, model=DEFAULT_MODEL):
    """Rewrite the wording while keeping every fact fixed.

    Raises ValueError when the model changes a number - the caller
    then keeps the factual draft.
    """

    facts = _facts_text(employee, options, kind)

    draft_text = (
        f"Subject: {letter['subject']}\n\n"
        + "\n\n".join(letter["body"])
    )

    from openai import OpenAI

    client = OpenAI(api_key=get_secret("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": POLISH_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Facts (do not change):\n{facts}\n\n"
                    f"Current draft:\n{draft_text}"
                )
            }
        ]
    )

    raw = response.choices[0].message.content or "{}"

    try:

        parsed = json.loads(raw)

    except json.JSONDecodeError as error:

        raise ValueError("AI answer was not valid JSON.") from error

    subject = str(parsed.get("subject") or "").strip()

    body = [
        str(paragraph).strip()
        for paragraph in (parsed.get("body") or [])
        if str(paragraph).strip()
    ]

    if not subject or not body:

        raise ValueError("AI answer was missing the letter text.")

    joined = subject + "\n" + "\n".join(body)

    allowed = _number_set(facts) | _number_set(draft_text)

    if not _number_set(joined) <= allowed:

        raise ValueError(
            "AI changed a number, so the standard wording was kept."
        )

    if employee["employee_name"].split()[0] not in joined:

        raise ValueError(
            "AI dropped the employee's name, so the standard wording "
            "was kept."
        )

    return {
        **letter,
        "subject": subject,
        "body": body
    }


# ---------------------------------------------------------
# PDF
# ---------------------------------------------------------

def build_letter_pdf(letter, employee, options):
    """Return the letter as a printable A4 PDF (bytes)."""

    from fpdf import FPDF

    issue_date = options.get("issue_date") or datetime.date.today()

    if not isinstance(issue_date, datetime.date):

        issue_date = datetime.date.fromisoformat(str(issue_date))

    reference = (
        f"AIT/HR/{letter['kind'][:4].upper()}/"
        f"{employee['employee_id']}/"
        f"{issue_date.strftime('%Y%m%d')}"
    )

    ACCENT = (124, 58, 237)
    DARK = (17, 24, 39)
    GRAY = (107, 114, 128)

    arial = r"C:\Windows\Fonts\arial.ttf"
    arial_bold = r"C:\Windows\Fonts\arialbd.ttf"

    use_arial = os.path.exists(arial) and os.path.exists(arial_bold)

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    if use_arial:

        pdf.add_font("Arial", "", arial)
        pdf.add_font("Arial", "B", arial_bold)

        font = "Arial"

    else:

        font = "Helvetica"

    def write(text, size=10.5, style="", color=DARK, align="L", h=6.4, gap=3.6):

        text = str(text).encode("latin-1", "replace").decode("latin-1")
        pdf.set_font(font, style, size)
        pdf.set_text_color(*color)
        pdf.multi_cell(0, h, text, align=align)
        pdf.ln(gap)

    # --- letterhead -------------------------------------------

    pdf.set_font(font, "B", 22)
    pdf.set_text_color(*ACCENT)
    pdf.cell(100, 10, COMPANY, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font(font, "", 9)
    pdf.set_text_color(*GRAY)
    pdf.cell(100, 5, LOCATION, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font(font, "", 9)
    pdf.set_text_color(*GRAY)
    pdf.set_xy(120, 18)
    pdf.cell(0, 5, f"Date: {_date(issue_date)}", align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(120)
    pdf.cell(0, 5, f"Ref: {reference}", align="R",
             new_x="LMARGIN", new_y="NEXT")

    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(15, 32, 195, 32)

    pdf.set_y(40)

    # --- title / subject --------------------------------------

    if letter.get("title"):

        write(letter["title"], size=11, style="B", align="C", gap=4)

    write(letter["subject"], size=11, style="B", gap=5)

    # --- body -------------------------------------------------

    for paragraph in letter["body"]:

        write(paragraph, size=10.5, gap=3.6)

    # --- signature --------------------------------------------

    pdf.ln(6)

    write(letter.get("closing", "Yours sincerely,"), size=10.5, gap=10)

    signed_by = (options.get("signed_by") or "").strip() or (
        "Authorised Signatory"
    )

    write(f"For {COMPANY}", size=10.5, style="B", gap=10)

    write(signed_by, size=10.5, style="B", gap=1)

    write("Human Resources", size=9, color=GRAY, gap=0)

    return bytes(pdf.output())


# ---------------------------------------------------------
# PAGE
# ---------------------------------------------------------

def show_letter_page(go_home=None):
    """HR: draft and download a letter with AI-polished wording."""

    user = st.session_state.get("auth_user") or {}

    if user.get("role") != "hr":

        st.error("This screen is only available to HR.")

        st.stop()

    st.title("AI letter generator", icon=":material/description:")

    st.caption(
        "Pick a person and a letter. Every date, title and amount comes "
        "from the database — AI only improves the wording."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="letters_back",
        width="content"
    ):

        go_home()

        st.rerun()

    options_list = employee_options()

    if not options_list:

        st.info("Add an employee first, then come back to write a letter.")

        return

    available, reason = ai_available()

    if not available:

        st.info(reason + " Letters will use the standard wording.")

    labels = [label for label, _ in options_list]

    col1, col2 = st.columns(2)

    with col1:

        employee_label = st.selectbox(
            "Employee",
            labels,
            key="letter_employee"
        )

    with col2:

        kind_label = st.selectbox(
            "Letter type",
            [label for label, _ in LETTER_TYPES],
            key="letter_type"
        )

    employee_id = dict(zip(labels, [value for _, value in options_list]))[
        employee_label
    ]

    kind = dict(LETTER_TYPES)[kind_label]

    employee = get_employee(employee_id)

    if employee is None:

        st.error("That employee record could not be loaded.")

        return

    st.space("small")

    # -----------------------------------------------------
    # OPTIONS
    # -----------------------------------------------------

    col1, col2 = st.columns(2)

    with col1:

        issue_date = st.date_input(
            "Letter date",
            value=datetime.date.today(),
            key="letter_date"
        )

        signed_by = st.text_input(
            "Signed by",
            placeholder="e.g. A. Sharma, HR Manager",
            key="letter_signed_by"
        )

    with col2:

        if kind == "relieving":

            default_last = datetime.date.today()

            if employee.get("exit_date"):

                try:

                    default_last = datetime.date.fromisoformat(
                        employee["exit_date"]
                    )

                except ValueError:

                    pass

            last_day = st.date_input(
                "Last working day",
                value=default_last,
                key="letter_last_day"
            )

        elif kind in ("salary", "employment"):

            addressed_to = st.text_input(
                "Addressed to (optional)",
                placeholder="e.g. The Branch Manager, HDFC Bank",
                key="letter_addressed"
            )

            purpose = st.text_input(
                "Purpose (optional)",
                placeholder="e.g. a home loan application",
                key="letter_purpose"
            )

        elif kind == "warning":

            incident_date = st.date_input(
                "Date of the incident",
                value=datetime.date.today(),
                key="letter_incident_date"
            )

    if kind in ("salary", "employment"):

        include_breakdown = st.checkbox(
            "Include the monthly salary breakdown",
            value=True,
            key="letter_breakdown"
        )

    if kind == "warning":

        incident_summary = st.text_area(
            "What happened?",
            placeholder=(
                "e.g. repeated late arrival on 12 and 13 October 2026 "
                "despite an earlier verbal discussion"
            ),
            height=90,
            key="letter_incident"
        )

    polish = st.checkbox(
        "Polish the wording with AI",
        value=available,
        disabled=not available,
        key="letter_polish",
        help="Facts and amounts stay exactly as they are in the database."
    )

    # -----------------------------------------------------
    # BUILD
    # -----------------------------------------------------

    if st.button(
        "Draft the letter",
        type="primary",
        key="letter_generate"
    ):

        options = {
            "issue_date": issue_date,
            "signed_by": signed_by.strip()
        }

        if kind == "relieving":

            options["last_day"] = last_day

        if kind in ("salary", "employment"):

            options["addressed_to"] = addressed_to.strip()

            options["purpose"] = purpose.strip()

            options["include_breakdown"] = include_breakdown

        if kind == "warning":

            options["incident_summary"] = incident_summary.strip()

            options["incident_date"] = incident_date

        try:

            letter = draft_letter(kind, employee, options)

        except ValueError as error:

            st.error(str(error))

            return

        polished = False

        warning = ""

        if polish and available:

            with st.spinner("Polishing the wording…"):

                try:

                    letter = polish_letter(
                        kind, employee, options, letter
                    )

                    polished = True

                except Exception as error:  # noqa: BLE001

                    warning = str(error)

        pdf_bytes = build_letter_pdf(letter, employee, options)

        st.session_state.letter_result = {
            "letter": letter,
            "employee": employee,
            "options": options,
            "pdf": pdf_bytes,
            "polished": polished,
            "warning": warning
        }

    # -----------------------------------------------------
    # PREVIEW
    # -----------------------------------------------------

    result = st.session_state.get("letter_result")

    if not result:

        return

    letter = result["letter"]

    st.divider()

    st.subheader(
        "Preview",
        icon=":material/visibility:"
    )

    st.caption(
        "AI-polished wording — please read before sending."
        if result["polished"]
        else "Standard wording."
    )

    if result["warning"]:

        st.warning(result["warning"])

    with st.container(border=True):

        st.markdown(
            f"**{COMPANY}** · {LOCATION}"
        )

        st.caption(
            f"{_date(result['options'].get('issue_date'))}"
        )

        if letter.get("title"):

            st.markdown(
                f"<div style='text-align:center;font-weight:700;'>"
                f"{letter['title']}</div>",
                unsafe_allow_html=True
            )

        st.markdown(f"**{letter['subject']}**")

        for paragraph in letter["body"]:

            st.markdown(paragraph)

        st.markdown(letter.get("closing", "Yours sincerely,"))

        st.markdown(
            f"**For {COMPANY}**  \n"
            f"{result['options'].get('signed_by') or 'Authorised Signatory'}  \n"
            "Human Resources"
        )

    file_name = (
        f"{letter['kind']}-{result['employee']['employee_id']}-"
        f"{result['options']['issue_date'].strftime('%Y%m%d')}.pdf"
    )

    st.download_button(
        "Download PDF",
        data=result["pdf"],
        file_name=file_name,
        mime="application/pdf",
        icon=":material/download:",
        type="primary"
    )