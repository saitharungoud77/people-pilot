import datetime
import json
import os
import re

import streamlit as st

from database.connection import (
    get_connection,
    create_employee_table
)
from modules.salary import (
    auto_salary_components,
    save_structure,
    render_structure_details
)
from modules.employee import EMPLOYMENT_TYPES
from modules.auth import (
    create_user,
    DEFAULT_EMPLOYEE_PASSWORD
)
from modules.config import get_secret, has_secret, secrets_location


# ============================================================
# AI OFFER LETTER IMPORTER
# ============================================================
# HR uploads a candidate's offer / appointment letter (PDF) or
# pastes its text. The letter is read with PyMuPDF, sent to an
# OpenAI model which returns the employment terms as JSON, and
# then shown in an editable preview. Saving creates the employee
# record together with the statutory salary structure derived
# from the annual CTC (and, optionally, a login account).

# Safety limit so a very large document does not blow the prompt.
MAX_CHARS = 24000

MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
]

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

if DEFAULT_MODEL not in MODELS:

    MODELS.insert(0, DEFAULT_MODEL)

# Keys we ask the model for. Text fields default to "", numbers
# to 0 so the preview is always safe to render.
OFFER_FIELDS = [
    "employee_name",
    "designation",
    "department",
    "joining_date",
    "location",
    "employment_type",
    "annual_ctc",
    "work_email",
    "personal_email",
    "mobile_number",
    "dob",
    "gender",
    "marital_status",
    "blood_group",
    "address",
    "offer_date",
    "probation_period",
    "notice_period",
    "reporting_manager",
    "ctc_components",
    "confidence",
    "notes",
]

SYSTEM_PROMPT = (
    "You are an expert HR assistant that extracts structured "
    "data from employment offer letters and appointment letters. "
    "Return ONLY a single JSON object. Never invent values: use "
    "an empty string for missing text and 0 for missing numbers."
)

USER_PROMPT = """Extract the employment terms from the offer letter below.

Return a JSON object with exactly these keys:
- employee_name: candidate's full name (string)
- designation: job title (string)
- department: department or function (string)
- joining_date: date of joining, YYYY-MM-DD (string, "" if absent)
- location: work location / base city (string)
- employment_type: one of "Full Time", "Part Time", "Contract", "Intern" (string)
- annual_ctc: total annual cost to company in INR as a number (number)
- work_email: official work email if stated (string)
- personal_email: personal email (string)
- mobile_number: phone number (string)
- dob: date of birth, YYYY-MM-DD (string)
- gender: (string)
- marital_status: (string)
- blood_group: (string)
- address: full postal address (string)
- offer_date: date the offer was issued, YYYY-MM-DD (string)
- probation_period: e.g. "6 months" (string)
- notice_period: e.g. "60 days" (string)
- reporting_manager: name/role of reporting manager (string)
- ctc_components: object mapping any stated annual salary component names to INR amounts (object, {} if none)
- confidence: 0 to 1 estimate of extraction quality (number)
- notes: any other important terms (string)

Rules:
- Use only information present in the document. Do not guess.
- Output dates as ISO YYYY-MM-DD. Convert "1st August 2026" to "2026-08-01".
- annual_ctc must be one annual INR number. Monthly salary x 12. "12 LPA" -> 1200000.
- employment_type must be exactly one of the four allowed values.

Document:
<<<DOCUMENT>>>
"""


# ---------------------------------------------------------
# AVAILABILITY
# ---------------------------------------------------------

def ai_available():
    """(ok, message) — whether AI extraction can run."""

    import importlib.util

    if importlib.util.find_spec("openai") is None:

        return False, (
            "The 'openai' package is not installed. Run "
            "`pip install openai` and restart the app."
        )

    if not has_secret("OPENAI_API_KEY"):

        return False, (
            "No OpenAI API key found. Add it to "
            f"{secrets_location()} as  OPENAI_API_KEY = \"sk-...\"  "
            "or set the OPENAI_API_KEY environment variable, then "
            "restart the app."
        )

    return True, ""


# ---------------------------------------------------------
# TEXT EXTRACTION
# ---------------------------------------------------------

def extract_text_from_pdf(data):
    """Return the text of a PDF given as bytes (PyMuPDF)."""

    try:

        import pymupdf

    except ImportError:

        import fitz as pymupdf

    document = pymupdf.open(stream=data, filetype="pdf")

    try:

        return "\n".join(
            page.get_text() for page in document
        )

    finally:

        document.close()


def extract_text(uploaded_file):
    """Return text from an uploaded PDF or text file (bytes)."""

    name = (getattr(uploaded_file, "name", "") or "").lower()

    data = uploaded_file.getvalue()

    if name.endswith((".txt", ".md", ".csv")):

        return data.decode("utf-8", errors="ignore")

    return extract_text_from_pdf(data)


# ---------------------------------------------------------
# VALUE NORMALISATION
# ---------------------------------------------------------

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B, %Y",
    "%Y/%m/%d",
    "%m/%d/%Y",
]


def _to_iso_date(value):
    """Best-effort conversion of a date string to YYYY-MM-DD."""

    text = str(value or "").strip()

    if not text:

        return ""

    # Strip a leading ordinal suffix like "1st", "2nd", "3rd".
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text, flags=re.I)

    for fmt in _DATE_FORMATS:

        try:

            return datetime.datetime.strptime(
                cleaned, fmt
            ).date().isoformat()

        except ValueError:

            continue

    return ""


def _normalise_employment_type(value):
    """Map a free-text employment type onto the allowed values."""

    text = str(value or "").strip().lower()

    if not text:

        return EMPLOYMENT_TYPES[0]

    if "intern" in text or "trainee" in text:

        return "Intern"

    if "contract" in text or "consultant" in text or "freelance" in text:

        return "Contract"

    if "part" in text:

        return "Part Time"

    return "Full Time"


def _to_number(value):
    """Convert a possibly-formatted money string to a float."""

    if isinstance(value, (int, float)):

        return float(value)

    text = re.sub(r"[^0-9.]", "", str(value or ""))

    if not text:

        return 0.0

    try:

        return float(text)

    except ValueError:

        return 0.0


def normalise_fields(raw):
    """Clean a raw AI response into the OFFER_FIELDS shape."""

    raw = raw if isinstance(raw, dict) else {}

    data = {
        key: raw.get(key, "" if key != "annual_ctc" else 0)
        for key in OFFER_FIELDS
    }

    for key in (
        "joining_date",
        "dob",
        "offer_date",
    ):

        data[key] = _to_iso_date(data.get(key))

    data["annual_ctc"] = round(
        _to_number(data.get("annual_ctc")), 2
    )

    data["employment_type"] = _normalise_employment_type(
        data.get("employment_type")
    )

    components = data.get("ctc_components")

    if not isinstance(components, dict):

        components = {}

    data["ctc_components"] = {
        str(name): _to_number(amount)
        for name, amount in components.items()
    }

    try:

        data["confidence"] = max(
            0.0, min(1.0, float(data.get("confidence") or 0))
        )

    except (TypeError, ValueError):

        data["confidence"] = 0.0

    for key in OFFER_FIELDS:

        if key in ("annual_ctc", "confidence", "ctc_components"):

            continue

        if data.get(key) is None:

            data[key] = ""

        elif isinstance(data[key], (int, float)):

            data[key] = str(data[key])

        else:

            data[key] = str(data[key]).strip()

    return data


# ---------------------------------------------------------
# AI EXTRACTION
# ---------------------------------------------------------

def ai_extract_fields(text, model=DEFAULT_MODEL):
    """Send the offer text to OpenAI and return normalised fields."""

    from openai import OpenAI

    client = OpenAI(api_key=get_secret("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        seed=7,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": USER_PROMPT.replace(
                    "<<<DOCUMENT>>>",
                    str(text or "")[:MAX_CHARS]
                )
            },
        ],
    )

    content = response.choices[0].message.content or "{}"

    return normalise_fields(json.loads(content))


# ---------------------------------------------------------
# EMPLOYEE ID SUGGESTION
# ---------------------------------------------------------

def suggest_employee_id(today=None):
    """Next Employee ID for the current year, e.g. EM04-26."""

    today = today or datetime.date.today()

    year_suffix = str(today.year)[2:]

    connection = get_connection()

    try:

        rows = connection.execute(
            "SELECT employee_id FROM employees"
        ).fetchall()

    finally:

        connection.close()

    highest = 0

    for (employee_id,) in rows:

        match = re.search(
            r"EM\s*0*(\d+)\s*-\s*(\d{2})",
            str(employee_id),
            re.IGNORECASE
        )

        if match and match.group(2) == year_suffix:

            highest = max(highest, int(match.group(1)))

    return f"EM{highest + 1:02d}-{year_suffix}"


# ---------------------------------------------------------
# SAVE
# ---------------------------------------------------------

def create_employee_from_offer(
    data,
    create_login=False,
    password=None
):
    """Create the employee record plus salary structure.

    Returns the new employee_id; raises ValueError on bad input.
    """

    employee_id = str(data.get("employee_id") or "").strip()

    employee_name = str(data.get("employee_name") or "").strip()

    department = str(data.get("department") or "").strip()

    designation = str(data.get("designation") or "").strip()

    location = str(data.get("location") or "").strip()

    employment_type = _normalise_employment_type(
        data.get("employment_type")
    )

    joining_date = _to_iso_date(data.get("joining_date"))

    annual_ctc = round(_to_number(data.get("annual_ctc")), 2)

    if not employee_id or not employee_name:

        raise ValueError("Employee ID and name are required.")

    if not department or not designation or not location:

        raise ValueError(
            "Department, designation and location are required."
        )

    if annual_ctc <= 0:

        raise ValueError("Annual CTC must be greater than zero.")

    if not joining_date:

        raise ValueError("A valid joining date is required.")

    connection = get_connection()

    try:

        exists = connection.execute(
            """
            SELECT 1 FROM employees
            WHERE employee_id = ? COLLATE NOCASE
            """,
            (employee_id,)
        ).fetchone()

        if exists:

            raise ValueError(
                f"Employee ID '{employee_id}' is already in use."
            )

        connection.execute(
            """
            INSERT INTO employees
            (
                employee_id,
                employee_name,
                department,
                designation,
                joining_date,
                location,
                employment_type,
                annual_ctc,
                dob,
                gender,
                marital_status,
                blood_group,
                mobile_number,
                personal_email,
                work_email,
                address
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                employee_name,
                department,
                designation,
                joining_date,
                location,
                employment_type,
                annual_ctc,
                _to_iso_date(data.get("dob")),
                str(data.get("gender") or "").strip(),
                str(data.get("marital_status") or "").strip(),
                str(data.get("blood_group") or "").strip(),
                str(data.get("mobile_number") or "").strip(),
                str(data.get("personal_email") or "").strip(),
                str(data.get("work_email") or "").strip(),
                str(data.get("address") or "").strip(),
            )
        )

        connection.commit()

    finally:

        connection.close()

    # Statutory salary structure derived from the annual CTC.
    save_structure(
        employee_id,
        auto_salary_components(annual_ctc)
    )

    if create_login:

        create_user(
            employee_id,
            password or DEFAULT_EMPLOYEE_PASSWORD,
            "employee",
            employee_id,
            overwrite=True
        )

    return employee_id


# ---------------------------------------------------------
# PREVIEW VALUES
# ---------------------------------------------------------

def _as_date(value):
    """Convert an ISO string to a date, defaulting to today."""

    try:

        return datetime.date.fromisoformat(str(value))

    except (TypeError, ValueError):

        return datetime.date.today()


def _select_index(options, value):
    """Index of value in options, defaulting to 0."""

    try:

        return options.index(value)

    except ValueError:

        return 0


# ---------------------------------------------------------
# HR PAGE
# ---------------------------------------------------------

def show_offer_letter_page(go_home=None):
    """HR: import an offer letter with AI and create the employee."""

    create_employee_table()

    st.title(
        "AI offer letter importer",
        icon=":material/document_scanner:"
    )

    st.caption(
        "Upload a candidate's offer letter. AI reads it and "
        "drafts the employee record — review, correct, then save."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="offer_back",
        width="content"
    ):

        go_home()

        st.rerun()

    available, reason = ai_available()

    if not available:

        st.error(reason)

    flash = st.session_state.pop("offer_flash", None)

    if flash:

        st.success(flash)

    # -----------------------------------------------------
    # STEP 1 — PROVIDE THE LETTER
    # -----------------------------------------------------

    st.subheader("1 · Provide the offer letter", icon=":material/upload_file:")

    source = st.radio(
        "Source",
        ["Upload PDF", "Paste text"],
        horizontal=True,
        key="offer_source"
    )

    uploaded = None

    pasted = ""

    if source == "Upload PDF":

        uploaded = st.file_uploader(
            "Offer letter (PDF or text)",
            type=["pdf", "txt", "md"],
            key="offer_file"
        )

    else:

        pasted = st.text_area(
            "Paste the offer letter text",
            height=220,
            key="offer_text"
        )

    model = DEFAULT_MODEL

    if st.button(
        "Extract with AI",
        type="primary",
        key="offer_extract",
        disabled=not available
    ):

        text = ""

        if source == "Upload PDF":

            if uploaded is None:

                st.error("Please upload a PDF first.")

            else:

                try:

                    text = extract_text(uploaded)

                except Exception as exc:

                    st.error(f"Could not read the PDF: {exc}")

        else:

            text = pasted

        if text and text.strip():

            with st.spinner("Reading the offer letter with AI…"):

                try:

                    data = ai_extract_fields(text, model=model)

                    st.session_state.offer_extracted = data

                    st.session_state.offer_raw_text = text

                    st.session_state.offer_used_model = model

                    st.session_state.offer_rev = (
                        st.session_state.get("offer_rev", 0) + 1
                    )

                    st.rerun()

                except Exception as exc:

                    st.error(f"AI extraction failed: {exc}")

        elif text == "" and (
            uploaded is not None or pasted.strip()
        ):

            st.error(
                "No readable text was found. Try a different "
                "file or paste the text instead."
            )

        elif not text.strip():

            st.error("Please provide the offer letter first.")

    # -----------------------------------------------------
    # STEP 2 — REVIEW & SAVE
    # -----------------------------------------------------

    extracted = st.session_state.get("offer_extracted")

    if not extracted:

        st.info(
            "The extracted details will appear here for review "
            "before anything is saved."
        )

        return

    rev = st.session_state.get("offer_rev", 0)

    pre = f"ol{rev}_"

    st.divider()

    st.subheader("2 · Review & correct", icon=":material/fact_check:")

    confidence = extracted.get("confidence", 0)

    st.caption(
        f"Extracted with **AI** · "
        f"confidence {confidence * 100:.0f}%. "
        "Review every field before saving."
    )

    if extracted.get("notes"):

        st.info(f"AI note: {extracted['notes']}")

    col1, col2 = st.columns(2)

    with col1:

        employee_id = st.text_input(
            "Employee ID",
            value=suggest_employee_id(),
            key=pre + "empid"
        )

        employee_name = st.text_input(
            "Employee name",
            value=extracted.get("employee_name", ""),
            key=pre + "name"
        )

        department = st.text_input(
            "Department",
            value=extracted.get("department", ""),
            key=pre + "dept"
        )

        designation = st.text_input(
            "Designation",
            value=extracted.get("designation", ""),
            key=pre + "desig"
        )

    with col2:

        joining_date = st.date_input(
            "Joining date",
            value=_as_date(extracted.get("joining_date")),
            key=pre + "join"
        )

        location = st.text_input(
            "Location",
            value=extracted.get("location", ""),
            key=pre + "loc"
        )

        employment_type = st.selectbox(
            "Employment type",
            EMPLOYMENT_TYPES,
            index=_select_index(
                EMPLOYMENT_TYPES,
                extracted.get("employment_type", EMPLOYMENT_TYPES[0])
            ),
            key=pre + "etype"
        )

        annual_ctc_lpa = st.number_input(
            "Annual CTC (LPA)",
            min_value=0.0,
            value=float(extracted.get("annual_ctc", 0)) / 100000,
            step=0.1,
            format="%.2f",
            key=pre + "ctc"
        )

    # -----------------------------------------------------
    # OPTIONAL PERSONAL / CONTACT DETAILS
    # -----------------------------------------------------

    with st.expander("Personal & contact details (optional)"):

        pc1, pc2 = st.columns(2)

        with pc1:

            work_email = st.text_input(
                "Work email",
                value=extracted.get("work_email", ""),
                key=pre + "wemail"
            )

            personal_email = st.text_input(
                "Personal email",
                value=extracted.get("personal_email", ""),
                key=pre + "pemail"
            )

            mobile_number = st.text_input(
                "Mobile number",
                value=extracted.get("mobile_number", ""),
                key=pre + "mobile"
            )

            dob = st.text_input(
                "Date of birth (YYYY-MM-DD)",
                value=extracted.get("dob", ""),
                key=pre + "dob"
            )

        with pc2:

            gender = st.text_input(
                "Gender",
                value=extracted.get("gender", ""),
                key=pre + "gender"
            )

            marital_status = st.text_input(
                "Marital status",
                value=extracted.get("marital_status", ""),
                key=pre + "marital"
            )

            blood_group = st.text_input(
                "Blood group",
                value=extracted.get("blood_group", ""),
                key=pre + "blood"
            )

            address = st.text_area(
                "Address",
                value=extracted.get("address", ""),
                height=80,
                key=pre + "address"
            )

    # -----------------------------------------------------
    # SALARY STRUCTURE PREVIEW (live)
    # -----------------------------------------------------

    annual_ctc = annual_ctc_lpa * 100000

    st.divider()

    st.subheader(
        "Salary structure preview",
        icon=":material/payments:"
    )

    if annual_ctc > 0:

        render_structure_details(
            auto_salary_components(annual_ctc)
        )

    else:

        st.caption(
            "Enter the annual CTC to preview the salary structure."
        )

    # -----------------------------------------------------
    # EXTRAS FROM THE LETTER
    # -----------------------------------------------------

    extras = [
        ("Offer date", extracted.get("offer_date")),
        ("Probation period", extracted.get("probation_period")),
        ("Notice period", extracted.get("notice_period")),
        ("Reporting manager", extracted.get("reporting_manager")),
    ]

    shown = [(label, value) for label, value in extras if value]

    if shown:

        st.caption(
            "Also found in the letter — "
            + " · ".join(f"**{label}:** {value}" for label, value in shown)
        )

    if extracted.get("ctc_components"):

        with st.expander("CTC components found in the letter"):

            for name, amount in extracted["ctc_components"].items():

                st.write(f"- **{name}:** ₹ {amount:,.2f}")

    with st.expander("Extracted text (for reference)"):

        st.text(st.session_state.get("offer_raw_text", ""))

    # -----------------------------------------------------
    # SAVE
    # -----------------------------------------------------

    st.divider()

    save_col1, save_col2 = st.columns([2, 2])

    with save_col1:

        create_login = st.checkbox(
            f"Create a login account (password "
            f"'{DEFAULT_EMPLOYEE_PASSWORD}')",
            value=True,
            key=pre + "login"
        )

    with save_col2:

        st.space("small")

        if st.button(
            "Create employee",
            type="primary",
            key=pre + "save",
            width="stretch"
        ):

            data = {
                "employee_id": employee_id,
                "employee_name": employee_name,
                "department": department,
                "designation": designation,
                "joining_date": str(joining_date),
                "location": location,
                "employment_type": employment_type,
                "annual_ctc": annual_ctc,
                "work_email": work_email,
                "personal_email": personal_email,
                "mobile_number": mobile_number,
                "dob": dob,
                "gender": gender,
                "marital_status": marital_status,
                "blood_group": blood_group,
                "address": address,
            }

            try:

                new_id = create_employee_from_offer(
                    data,
                    create_login=create_login
                )

                st.session_state.offer_flash = (
                    f"{employee_name} ({new_id}) created with an "
                    f"auto-generated salary structure."
                    + (
                        f" Login account ready (password "
                        f"'{DEFAULT_EMPLOYEE_PASSWORD}')."
                        if create_login else ""
                    )
                )

                st.session_state.pop("offer_extracted", None)

                st.session_state.pop("offer_raw_text", None)

                st.session_state.current_page = "employee"

                st.rerun()

            except Exception as exc:

                st.error(f"Could not create the employee: {exc}")
