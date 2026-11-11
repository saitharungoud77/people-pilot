"""Income tax — Form 16 issuing and the monthly TDS estimate.

How it works, in plain English:

1. **TDS, month by month.** The app works out each employee's likely
   income-tax for a financial year (April to March) from their salary
   structure, spreads it over the months, and shows a month-by-month
   statement. It is an **estimate** — it uses the new tax regime and
   knows nothing about an employee's investments, rent or other income —
   so it is labelled as an estimate everywhere it appears.

2. **Form 16.** In practice a Form 16 arrives as one PDF per employee.
   HR uploads several at once; the app reads the text out of each PDF and
   asks an OpenAI model for the employee's **name**, PAN, employer and
   the totals printed on the form. It then matches that name against the
   employees on file (a filename containing the employee id is treated as
   a strong hint). The result is shown as a **review list**: the form, the
   name that was read, the employee it matched and how confident the
   match is. HR can correct the employee or the year, then clicks Issue.

   Nothing is issued until HR approves it.

3. **Issue.** Issuing stores the PDF against that employee and year, tells
   the employee with a notification, and the form appears on their
   "My tax" page with a download button.

This screen replaces guesswork with something checkable: the AI only
*reads*, and every decision it feeds is shown to HR before anything is
filed.
"""

import datetime
import json
import re

import pandas as pd
import streamlit as st

from database.connection import (
    get_connection,
    create_form16_table
)
from modules.offer_letter import (
    DEFAULT_MODEL,
    MODELS,
    ai_available,
    extract_text
)
from modules.config import get_secret
from modules.notifications import notify_employee
from modules.session import require_employee


# ============================================================
# INCOME-TAX RULES
# ============================================================
# The new regime, as it stands for FY 2025-26 (and used here for
# later years too). Annual income in rupees.

TAX_SLABS = [
    (400000.0, 0.00),
    (800000.0, 0.05),
    (1200000.0, 0.10),
    (1600000.0, 0.15),
    (2000000.0, 0.20),
    (2400000.0, 0.25),
    (float("inf"), 0.30),
]

# The flat deduction every salaried person gets under the new regime.
STANDARD_DEDUCTION = 75000.0

# Section 87A: no tax at all up to this income, and the rebate is
# capped here. Just above the limit, marginal relief stops the tax
# from jumping by more than the income above it.
REBATE_LIMIT = 1200000.0
REBATE_MAX = 60000.0

# Health and education cess on the tax itself.
CESS_RATE = 0.04

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]


# ============================================================
# FORM 16 READING
# ============================================================

MAX_CHARS = 24000

# The keys we ask the model for. Text defaults to "" and numbers
# to 0 so the review screen is always safe to render.
FORM16_FIELDS = [
    "employee_name",
    "employee_pan",
    "employer_name",
    "employer_tan",
    "tax_year",
    "assessment_year",
    "gross_salary",
    "total_tds",
    "deductions",
    "taxable_income",
    "confidence",
    "notes",
]

SYSTEM_PROMPT = (
    "You are an expert Indian payroll and income-tax assistant. You "
    "read the text of a Form 16 and return the facts printed on it. "
    "Return ONLY a single JSON object. Never invent values: use an "
    "empty string for missing text and 0 for missing numbers."
)

USER_PROMPT = """Read this Form 16 and report the facts it contains.

Return a JSON object with exactly these keys:
- employee_name: the employee's (deductee's) full name (string)
- employee_pan: the employee's PAN (string, e.g. "ABCDE1234F")
- employer_name: the employer's / deductor's name (string)
- employer_tan: the employer's TAN (string)
- tax_year: the financial year the form covers, as "YYYY-YY" (string)
- assessment_year: the assessment year, as "YYYY-YY" (string)
- gross_salary: salary as per section 17(1), total gross salary paid (number)
- total_tds: total tax deducted at source for the year (number)
- deductions: total deductions claimed (number)
- taxable_income: total taxable income (number)
- confidence: 0 to 1 estimate of how sure you are of the name (number)
- notes: anything unusual, e.g. "name unclear" or "scan unreadable" (string)

Rules:
- Read the name exactly as printed, including its spelling.
- Form 16 has Part A (TDS details) and Part B (salary details); the
  employee's name is usually near the top or in Part B.
- Numbers are annual INR amounts. "1,03,422" means 103422.
- Do not guess a PAN or a name that is not printed.
- If the text is a scan with no usable text, use "" and say so in notes.

Form 16 text:
<<<DOCUMENT>>>
"""


def _to_float(value):

    try:

        return float(str(value).replace(",", "").strip())

    except (TypeError, ValueError):

        return 0.0


# ============================================================
# FINANCIAL YEAR HELPERS
# ============================================================
# The Indian financial year runs April to March. We store the year
# it *starts* in, so 2025 means FY 2025-26.

def financial_year_start(when=None):
    """The year the financial year containing ``when`` starts in."""

    when = when or datetime.date.today()

    return when.year if when.month >= 4 else when.year - 1


def fy_label(start):
    """Human label for a financial year, e.g. "FY 2025-26"."""

    return f"FY {start}-{str(start + 1)[2:]}"


def _parse_iso(value):
    """Parse a YYYY-MM-DD date, returning None when it is not one."""

    try:

        return datetime.datetime.strptime(
            str(value or "")[:10], "%Y-%m-%d"
        ).date()

    except (TypeError, ValueError):

        return None


def parse_tax_year(value, assessment=False):
    """Turn "2025-26" / "2025-2026" / "FY 2025-26" into 2025.

    An assessment year is one ahead of its financial year, so
    ``assessment=True`` steps back a year.
    """

    text = str(value or "")

    match = re.search(r"(20\d{2})\s*[-\u2013/]\s*(\d{2,4})", text)

    if not match:

        return None

    start = int(match.group(1))

    if not 2000 <= start <= 2100:

        return None

    return start - 1 if assessment else start


# ============================================================
# THE TDS ESTIMATE
# ============================================================

def gross_annual(structure):
    """A year's gross salary: the earnings, before any deduction."""

    return round(
        float(structure.get("basic_annual") or 0)
        + float(structure.get("hra_annual") or 0)
        + float(structure.get("special_allowance_annual") or 0)
        + float(structure.get("other_allowance_annual") or 0),
        2
    )


def slab_tax(taxable):
    """Tax on a taxable income, applying the slabs one by one."""

    tax = 0.0

    lower = 0.0

    for upper, rate in TAX_SLABS:

        if taxable <= lower:

            break

        tax += (min(taxable, upper) - lower) * rate

        lower = upper

    return tax


def estimate_tax(gross):
    """Estimated income tax on a gross salary, new regime.

    Returns a dict so every figure can be explained on screen.
    """

    gross = float(gross or 0)

    taxable = max(0.0, gross - STANDARD_DEDUCTION)

    tax = slab_tax(taxable)

    rebate = 0.0

    if taxable <= REBATE_LIMIT:

        rebate = min(tax, REBATE_MAX)

    elif taxable > REBATE_LIMIT:

        # Marginal relief: never pay more tax than the amount by
        # which the income went over the rebate limit.
        tax = min(tax, taxable - REBATE_LIMIT)

    tax = max(0.0, tax - rebate)

    cess = tax * CESS_RATE

    total = tax + cess

    return {
        "gross": round(gross, 2),
        "standard_deduction": round(min(STANDARD_DEDUCTION, gross), 2),
        "taxable_income": round(taxable, 2),
        "slab_tax": round(slab_tax(taxable), 2),
        "rebate": round(rebate, 2),
        "tax_after_rebate": round(tax, 2),
        "cess": round(cess, 2),
        "annual_tax": round(total, 2),
        "monthly_tax": round(total / 12.0, 2)
    }


def employees_with_salary():
    """Every employee that has a salary structure, with its parts."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                e.employee_id,
                e.employee_name,
                e.joining_date,
                e.annual_ctc,
                s.basic_annual,
                s.hra_annual,
                s.special_allowance_annual,
                s.other_allowance_annual
            FROM employees e
            JOIN salary_structures s
                ON e.employee_id = s.employee_id
            ORDER BY e.employee_name
            """
        ).fetchall()

    finally:

        connection.close()

    keys = [
        "employee_id",
        "employee_name",
        "joining_date",
        "annual_ctc",
        "basic_annual",
        "hra_annual",
        "special_allowance_annual",
        "other_allowance_annual"
    ]

    return [dict(zip(keys, row)) for row in rows]


def estimate_for(row):
    """The full TDS estimate for one employee row (or None)."""

    if not row:

        return None

    return estimate_tax(gross_annual(row))


def tds_months(fy_start, joining_date=None, as_of=None):
    """The (year, month) pairs of a financial year to show.

    Runs from April (or the joining month, when that is later) up
    to the statement month, never past March.
    """

    as_of = as_of or datetime.date.today()

    first = datetime.date(fy_start, 4, 1)

    last = datetime.date(fy_start + 1, 3, 1)

    start = first

    joined = _parse_iso(joining_date)

    if joined and joined.replace(day=1) > first:

        start = joined.replace(day=1)

    end = min(
        datetime.date(as_of.year, as_of.month, 1),
        last
    )

    months = []

    year, month = start.year, start.month

    while (year, month) <= (end.year, end.month):

        months.append((year, month))

        month += 1

        if month == 13:

            year, month = year + 1, 1

    return months


def monthly_tds_rows(estimate, fy_start, joining_date=None, as_of=None):
    """Month-by-month TDS, with the running total (YTD)."""

    rows = []

    running = 0.0

    for year, month in tds_months(fy_start, joining_date, as_of):

        running += estimate["monthly_tax"]

        rows.append({
            "period": f"{MONTHS[month - 1]} {year}",
            "month": f"{year}-{month:02d}",
            "tds": estimate["monthly_tax"],
            "ytd": round(running, 2)
        })

    return rows


def tds_so_far(estimate, fy_start, joining_date=None, as_of=None):
    """How much TDS the estimate says has been deducted so far."""

    return round(
        estimate["monthly_tax"]
        * len(tds_months(fy_start, joining_date, as_of)),
        2
    )


# ============================================================
# MATCHING A FORM 16 TO AN EMPLOYEE
# ============================================================
# The AI only reads the name off the form; deciding *which* employee
# that is happens here, in plain Python, so the same input always
# gives the same answer and HR can see the reasoning.

_TITLES = {
    "mr", "mrs", "ms", "miss", "dr", "shri", "sri", "smt",
    "kum", "s/o", "d/o", "w/o", "late"
}


def name_parts(value):
    """Split a name into comparable lower-case words."""

    text = re.sub(r"[^A-Za-z0-9\s]", " ", str(value or "").lower())

    return [
        word
        for word in text.split()
        if word and word not in _TITLES
    ]


def name_score(left, right):
    """How alike two names are, from 0 to 1."""

    a = name_parts(left)

    b = name_parts(right)

    if not a or not b:

        return 0.0

    if a == b:

        return 1.0

    if sorted(a) == sorted(b):

        return 0.97

    set_a, set_b = set(a), set(b)

    shared = set_a & set_b

    if not shared:

        return 0.0

    # How much of the shorter name appears in the longer one, plus
    # the overall overlap. Both are 0..1.
    containment = len(shared) / min(len(set_a), len(set_b))

    overlap = len(shared) / len(set_a | set_b)

    score = 0.65 * containment + 0.35 * overlap

    # A surname-only match ("Kumar") should not look confident.
    if len(set_a) == 1 and len(set_b) > 1:

        score = min(score, 0.55)

    return round(min(score, 0.96), 3)


def confidence_label(score):
    """(label, emoji) for a match score."""

    if score >= 0.9:

        return "High", ""

    if score >= 0.7:

        return "Medium", ""

    if score >= 0.5:

        return "Low", ""

    return "No match", ""


def match_employee(name, employees, file_name=""):
    """Find the employee a Form 16 belongs to.

    Two signals are used:

    * the **name printed on the form** (the main evidence), and
    * the **employee id**, when the file name carries it.

    A strong printed name wins. Otherwise the file name decides, so a
    badly scanned form can still be filed correctly. When the two
    disagree the ``conflict`` flag is set and the screen warns HR —
    this is exactly the case where a form could reach the wrong
    person, so it is never resolved silently.

    Returns a dict with employee_id, employee_name, score, method,
    label, emoji, candidates, conflict and file_hint.
    """

    squashed_file = re.sub(r"\s+", "", str(file_name or "").lower())

    by_name = []

    file_hint = None

    for employee in employees:

        by_name.append({
            "employee_id": employee["employee_id"],
            "employee_name": employee["employee_name"],
            "score": round(name_score(name, employee["employee_name"]), 3),
            "method": "name"
        })

        # The stored ids can contain spaces ("EMO4- 25"), so compare
        # on a squashed form of both.
        squashed_id = re.sub(r"\s+", "", employee["employee_id"] or "").lower()

        if squashed_id and squashed_id in squashed_file and file_hint is None:

            file_hint = {
                "employee_id": employee["employee_id"],
                "employee_name": employee["employee_name"],
                "score": 0.99,
                "method": "file name"
            }

    by_name.sort(key=lambda item: item["score"], reverse=True)

    name_best = by_name[0] if by_name else None

    pick = None

    if name_best and name_best["score"] >= 0.9:

        pick = name_best

    elif file_hint:

        pick = dict(file_hint)

        # Keep whichever score is higher for the confidence label.
        for item in by_name:

            if item["employee_id"] == file_hint["employee_id"]:

                pick["score"] = max(pick["score"], item["score"])

                break

    elif name_best and name_best["score"] >= 0.5:

        pick = name_best

    conflict = bool(
        file_hint
        and pick
        and file_hint["employee_id"] != pick["employee_id"]
    )

    base = {
        "candidates": by_name[:3],
        "conflict": conflict,
        "file_hint": file_hint
    }

    if pick is None:

        return {
            "employee_id": "",
            "employee_name": "",
            "score": name_best["score"] if name_best else 0.0,
            "method": "",
            "label": "No match",
            "emoji": "",
            **base
        }

    label, emoji = confidence_label(pick["score"])

    return {
        "employee_id": pick["employee_id"],
        "employee_name": pick["employee_name"],
        "score": pick["score"],
        "method": pick["method"],
        "label": label,
        "emoji": emoji,
        **base
    }


def all_employees():
    """Every employee on file, for the review dropdowns."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT employee_id, employee_name
            FROM employees
            ORDER BY employee_name
            """
        ).fetchall()

    finally:

        connection.close()

    return [
        {"employee_id": row[0], "employee_name": row[1]}
        for row in rows
    ]


# ============================================================
# READING A FORM 16 WITH AI
# ============================================================

def normalise_form16(raw):
    """Make the model's JSON safe and complete before it is used."""

    raw = raw if isinstance(raw, dict) else {}

    return {
        "employee_name": str(raw.get("employee_name") or "").strip(),
        "employee_pan": str(raw.get("employee_pan") or "").strip().upper(),
        "employer_name": str(raw.get("employer_name") or "").strip(),
        "employer_tan": str(raw.get("employer_tan") or "").strip().upper(),
        "tax_year": str(raw.get("tax_year") or "").strip(),
        "assessment_year": str(raw.get("assessment_year") or "").strip(),
        "gross_salary": round(_to_float(raw.get("gross_salary")), 2),
        "total_tds": round(_to_float(raw.get("total_tds")), 2),
        "deductions": round(_to_float(raw.get("deductions")), 2),
        "taxable_income": round(_to_float(raw.get("taxable_income")), 2),
        "confidence": round(_to_float(raw.get("confidence")), 2),
        "notes": str(raw.get("notes") or "").strip()
    }


def ai_read_form16(text, model=DEFAULT_MODEL):
    """Ask the model what one Form 16 says. Returns a dict."""

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
                    "<<<DOCUMENT>>>", str(text or "")[:MAX_CHARS]
                )
            }
        ]
    )

    content = response.choices[0].message.content or "{}"

    return normalise_form16(json.loads(content))


# ============================================================
# STORING ISSUED FORM 16s
# ============================================================

def save_form16(
    employee_id,
    tax_year,
    data,
    file_name,
    ai=None,
    match=None,
    issued_by=None,
    notes=""
):
    """Store (or replace) one employee's Form 16 for a year."""

    ai = ai or {}

    match = match or {}

    create_form16_table()

    connection = get_connection()

    try:

        # A re-issued form replaces the previous one: there is only
        # ever one Form 16 per employee per year.
        connection.execute(
            """
            DELETE FROM form16_documents
            WHERE employee_id = ? AND tax_year = ?
            """,
            (employee_id, int(tax_year))
        )

        connection.execute(
            """
            INSERT INTO form16_documents (
                employee_id, tax_year, file_name, mime, size_bytes,
                data, matched_name, match_method, match_score,
                employee_pan, employer_name, gross_salary, total_tds,
                issued_on, issued_by, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                int(tax_year),
                file_name or "form16.pdf",
                "application/pdf",
                len(data or b""),
                data,
                ai.get("employee_name", ""),
                match.get("method", ""),
                float(match.get("score") or 0),
                ai.get("employee_pan", ""),
                ai.get("employer_name", ""),
                float(ai.get("gross_salary") or 0),
                float(ai.get("total_tds") or 0),
                datetime.date.today().isoformat(),
                issued_by or "",
                notes or ai.get("notes", "")
            )
        )

        connection.commit()

    finally:

        connection.close()


_META_COLUMNS = """
    id, employee_id, tax_year, file_name, size_bytes, matched_name,
    match_method, match_score, employee_pan, employer_name,
    gross_salary, total_tds, issued_on, issued_by, notes
"""


def get_form16_index(tax_year=None, employee_id=None):
    """Issued Form 16 records, newest first (never the PDF itself)."""

    query = (
        f"SELECT {_META_COLUMNS} FROM form16_documents WHERE 1 = 1"
    )

    params = []

    if tax_year is not None:

        query += " AND tax_year = ?"

        params.append(int(tax_year))

    if employee_id:

        query += " AND employee_id = ?"

        params.append(employee_id)

    query += " ORDER BY id DESC"

    connection = get_connection()

    try:

        cursor = connection.execute(query, params)

        keys = [column[0] for column in cursor.description]

        rows = cursor.fetchall()

    finally:

        connection.close()

    return [dict(zip(keys, row)) for row in rows]


def get_form16_data(doc_id):
    """The stored PDF bytes for one record, or None."""

    connection = get_connection()

    try:

        row = connection.execute(
            "SELECT data FROM form16_documents WHERE id = ?",
            (int(doc_id),)
        ).fetchone()

    finally:

        connection.close()

    return row[0] if row and row[0] else None


def count_form16(tax_year=None):
    """How many Form 16s have been issued."""

    query = "SELECT COUNT(*) FROM form16_documents"

    params = []

    if tax_year is not None:

        query += " WHERE tax_year = ?"

        params.append(int(tax_year))

    connection = get_connection()

    try:

        return connection.execute(query, params).fetchone()[0]

    finally:

        connection.close()


def issued_employee_ids(tax_year):
    """Which employees already have a Form 16 for a year."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT employee_id FROM form16_documents
            WHERE tax_year = ?
            """,
            (int(tax_year),)
        ).fetchall()

    finally:

        connection.close()

    return {row[0] for row in rows}


def delete_form16(doc_id):
    """Remove one issued Form 16."""

    connection = get_connection()

    try:

        connection.execute(
            "DELETE FROM form16_documents WHERE id = ?",
            (int(doc_id),)
        )

        connection.commit()

    finally:

        connection.close()


# ============================================================
# SHARED UI PIECES
# ============================================================

def _rupees(value):
    """Money in the portal's usual format."""

    return f"₹ {float(value or 0):,.2f}"


def _fy_options(selected=None):
    """Financial years to choose from, newest first.

    Starts at the current financial year — a year that has not begun
    yet has nothing to show.
    """

    current = financial_year_start()

    starts = list(range(current, current - 6, -1))

    if selected is not None and int(selected) not in starts:

        starts.insert(0, int(selected))

        starts.sort(reverse=True)

    return starts


def _fy_picker(key, default=None, label="Financial year"):
    """A financial-year dropdown returning the year it starts in."""

    chosen = default if default is not None else financial_year_start()

    options = _fy_options(chosen)

    return int(st.selectbox(
        label,
        options,
        index=options.index(int(chosen)),
        format_func=fy_label,
        key=key
    ))


def _employee_labels():
    """Dropdown labels ("ID · Name") in employee order."""

    return [
        f"{row['employee_id']} · {row['employee_name']}"
        for row in all_employees()
    ]


def _employee_id_from_label(label):
    """The employee id inside a dropdown label."""

    return str(label or "").split(" · ")[0].strip()


def _estimate_caption():
    """The honesty note that goes under every estimate."""

    st.caption(
        "**Estimate only.** It uses the new tax regime, the standard "
        "deduction of ₹ 75,000 and a 4% cess, worked out from the "
        "employee's salary structure. It does not know about their "
        "investments, rent, other income, or any tax already paid, and "
        "it does not apply surcharge above ₹ 50 lakh."
    )


# ============================================================
# HR — TDS OVERVIEW
# ============================================================

def _render_tds_overview(fy_start, issued):
    """One row per employee: what the estimate says they owe."""

    rows_with_salary = employees_with_salary()

    if not rows_with_salary:

        st.info(
            "No salary structures yet, so there is nothing to estimate. "
            "Create a salary structure first."
        )

        return

    as_of = datetime.date.today()

    records = []

    for row in rows_with_salary:

        estimate = estimate_tax(gross_annual(row))

        so_far = tds_so_far(
            estimate, fy_start, row["joining_date"], as_of
        )

        records.append({
            "Employee": row["employee_name"],
            "Employee ID": row["employee_id"],
            "Annual gross": estimate["gross"],
            "Taxable income": estimate["taxable_income"],
            "Estimated tax (year)": estimate["annual_tax"],
            "Monthly TDS": estimate["monthly_tax"],
            "Months": len(
                tds_months(fy_start, row["joining_date"], as_of)
            ),
            "TDS so far": so_far,
            "Form 16": (
                "Issued"
                if row["employee_id"] in issued else "— not issued"
            )
        })

    total_tax = sum(record["Estimated tax (year)"] for record in records)

    total_so_far = sum(record["TDS so far"] for record in records)

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric("Employees", len(records), border=True)

    with col2:

        st.metric(
            "Estimated tax for the year",
            _rupees(total_tax),
            border=True
        )

    with col3:

        st.metric("TDS so far (estimate)", _rupees(total_so_far),
                  border=True)

    frame = pd.DataFrame(records)

    st.dataframe(
        frame,
        hide_index=True,
        width="stretch",
        column_config={
            "Employee": st.column_config.TextColumn(
                "Employee", width="medium"
            ),
            "Employee ID": st.column_config.TextColumn(
                "Employee ID", width="small"
            ),
            "Annual gross": st.column_config.NumberColumn(
                "Annual gross", format="%.2f"
            ),
            "Taxable income": st.column_config.NumberColumn(
                "Taxable income", format="%.2f"
            ),
            "Estimated tax (year)": st.column_config.NumberColumn(
                "Estimated tax (year)", format="%.2f"
            ),
            "Monthly TDS": st.column_config.NumberColumn(
                "Monthly TDS", format="%.2f"
            ),
            "Months": st.column_config.NumberColumn(
                "Months", format="%d", width="small"
            ),
            "TDS so far": st.column_config.NumberColumn(
                "TDS so far", format="%.2f"
            ),
            "Form 16": st.column_config.TextColumn(
                "Form 16", width="small"
            )
        }
    )

    _estimate_caption()


# ============================================================
# HR — UPLOADING FORM 16s
# ============================================================

REVIEW_KEY = "tax_review"


def _clear_review():

    st.session_state.pop(REVIEW_KEY, None)


def _read_and_match(uploads, model):
    """Read every uploaded form, match it, and hold it for review."""

    employees = all_employees()

    available, reason = ai_available()

    if not available:

        # Still usable: HR can pick the employee by hand.
        st.warning(
            reason + " You can still issue them by choosing the "
            "employee yourself below."
        )

    review = []

    total = len(uploads)

    progress = st.progress(0.0, text="Starting…")

    for position, uploaded in enumerate(uploads, start=1):

        progress.progress(
            (position - 1) / total,
            text=f"Reading {uploaded.name} ({position}/{total})…"
        )

        data = uploaded.getvalue()

        item = {
            "file_name": uploaded.name,
            "size": len(data),
            "data": data,
            "ai": {},
            "match": {},
            "problem": ""
        }

        text = ""

        try:

            text = extract_text(uploaded)

        except Exception as exc:  # noqa: BLE001

            item["problem"] = f"could not read the PDF ({exc})"

        if not item["problem"] and not (text or "").strip():

            item["problem"] = (
                "no readable text — is it a scanned (picture-only) PDF?"
            )

        if not item["problem"] and available:

            try:

                item["ai"] = ai_read_form16(text, model=model)

            except Exception as exc:  # noqa: BLE001

                item["problem"] = f"AI could not read it ({exc})"

        if not item["problem"]:

            item["match"] = match_employee(
                item["ai"].get("employee_name", ""),
                employees,
                file_name=item["file_name"]
            )

        review.append(item)

    progress.progress(1.0, text="Done.")

    st.session_state[REVIEW_KEY] = review


def _default_fy_for(item, fallback):
    """The year to file a form under: what it says, else the batch year."""

    read_year = parse_tax_year(item["ai"].get("tax_year"))

    if read_year is None:

        read_year = parse_tax_year(
            item["ai"].get("assessment_year"), assessment=True
        )

    options = _fy_options(fallback)

    if read_year is not None and read_year in options:

        return read_year

    return fallback


def _render_review(user, batch_fy):
    """The preview: what was read, what matched, and the Issue button."""

    review = st.session_state.get(REVIEW_KEY) or []

    if not review:

        return

    st.subheader(
        f" Check these {len(review)} form(s) before issuing",
        icon=":material/fact_check:"
    )

    st.caption(
        "The name and year come from the form. Fix the employee on any "
        "line that looks wrong — nothing is filed until you press Issue."
    )

    employee_labels = _employee_labels()

    skip_label = "— do not issue —"

    for position, item in enumerate(review):

        ai = item.get("ai") or {}

        match = item.get("match") or {}

        read_name = ai.get("employee_name") or "(nothing read)"

        label = match.get("label", "No match")

        emoji = match.get("emoji", "")

        title = (
            f"{emoji} {item['file_name']} — {read_name} "
            f"· {label}"
        )

        with st.expander(title, expanded=True):

            if item.get("problem"):

                st.warning(
                    f"AI could not read this file: {item['problem']}"
                )

            left, right = st.columns(2)

            with left:

                st.markdown(f"**Name read from the form:** {read_name}")

                facts = [
                    ("PAN", ai.get("employee_pan")),
                    ("Employer", ai.get("employer_name")),
                    ("Year on the form", ai.get("tax_year")),
                    ("Assessment year", ai.get("assessment_year")),
                    ("Gross salary", (
                        _rupees(ai["gross_salary"])
                        if ai.get("gross_salary") else ""
                    )),
                    ("TDS on the form", (
                        _rupees(ai["total_tds"])
                        if ai.get("total_tds") else ""
                    )),
                    ("Notes", ai.get("notes"))
                ]

                for name, value in facts:

                    if value:

                        st.caption(f"{name}: {value}")

            with right:

                if match.get("employee_name"):

                    st.markdown(
                        f"**Matched to:** {match['employee_name']} "
                        f"({match['employee_id']})"
                    )

                    st.caption(
                        f"Confidence: {label} "
                        f"({match.get('score', 0):.0%}) · "
                        f"matched on {match.get('method') or 'name'}"
                    )

                else:

                    st.markdown("**Matched to:** _nobody yet_")

                    st.caption(
                        "The name did not clearly match anyone on file. "
                        "Choose the employee below."
                    )

                if match.get("conflict"):

                    hint = match.get("file_hint") or {}

                    st.warning(
                        f"The file name points to "
                        f"{hint.get('employee_name')} "
                        f"({hint.get('employee_id')}), but the name on "
                        f"the form matched "
                        f"{match.get('employee_name')}. Please check "
                        "which one is right before issuing."
                    )

                others = [
                    candidate
                    for candidate in match.get("candidates", [])
                    if candidate["score"] >= 0.4
                    and candidate["employee_id"] != match.get("employee_id")
                ]

                if others:

                    st.caption(
                        "Close names: " + ", ".join(
                            f"{candidate['employee_name']} "
                            f"({candidate['score']:.0%})"
                            for candidate in others[:3]
                        )
                    )

            pick_col, fy_col = st.columns([2, 1])

            with fy_col:

                st.selectbox(
                    "Financial year",
                    _fy_options(batch_fy),
                    index=_fy_options(batch_fy).index(
                        _default_fy_for(item, batch_fy)
                    ),
                    format_func=fy_label,
                    key=f"tax_fy_{position}"
                )

            with pick_col:

                chosen = match.get("employee_id", "")

                default_label = (
                    next(
                        (
                            candidate
                            for candidate in employee_labels
                            if _employee_id_from_label(candidate) == chosen
                        ),
                        skip_label
                    )
                )

                st.selectbox(
                    "Issue to",
                    [skip_label] + employee_labels,
                    index=(
                        ([skip_label] + employee_labels).index(default_label)
                        if default_label in [skip_label] + employee_labels
                        else 0
                    ),
                    key=f"tax_pick_{position}"
                )

    st.divider()

    col1, col2 = st.columns([1, 1])

    with col1:

        if st.button(
            "Issue the selected Form 16s",
            type="primary",
            key="tax_issue",
            width="stretch"
        ):

            _issue(user, batch_fy)

    with col2:

        if st.button(
            "Cancel",
            key="tax_cancel_review",
            width="stretch"
        ):

            _clear_review()

            st.rerun()


def _issue(user, batch_fy):
    """File every reviewed form that has an employee chosen."""

    review = st.session_state.get(REVIEW_KEY) or []

    issued = 0

    skipped = 0

    for position, item in enumerate(review):

        chosen = st.session_state.get(f"tax_pick_{position}", "")

        year = st.session_state.get(
            f"tax_fy_{position}", _default_fy_for(item, batch_fy)
        )

        if not chosen or chosen.startswith("—"):

            skipped += 1

            continue

        employee_id = _employee_id_from_label(chosen)

        if not employee_id:

            skipped += 1

            continue

        save_form16(
            employee_id,
            int(year),
            item["data"],
            file_name=item["file_name"],
            ai=item.get("ai"),
            match=item.get("match"),
            issued_by=user.get("username")
        )

        notify_employee(
            employee_id,
            "Form 16 issued",
            f"Your Form 16 for {fy_label(int(year))} is ready to "
            "download from My tax.",
            category="Tax",
            page="tax"
        )

        issued += 1

    _clear_review()

    st.session_state.tax_flash = (
        f"Issued {issued} Form 16(s)."
        + (f" Skipped {skipped}." if skipped else "")
    )

    st.rerun()


def _render_uploader():
    """The upload box and the "read and match" button."""

    with st.expander("Upload Form 16 files", expanded=True):

        st.caption(
            "Upload one PDF per employee — you can pick several at once. "
            "The app reads each one and suggests which employee it "
            "belongs to; you check and issue."
        )

        uploads = st.file_uploader(
            "Form 16 PDFs (you can pick several)",
            type=["pdf", "txt"],
            accept_multiple_files=True,
            key="tax_uploads"
        )

        model = DEFAULT_MODEL

        available, _reason = ai_available()

        if st.button(
            "Read & match",
            type="primary",
            key="tax_read",
            disabled=not uploads
        ):

            _read_and_match(uploads, model)


# ============================================================
# HR — ISSUED FORM 16s
# ============================================================

def _render_issued(fy_start):
    """What has been filed for a year, with downloads."""

    records = get_form16_index(tax_year=fy_start)

    st.subheader(
        f"Issued Form 16s — {fy_label(fy_start)} ({len(records)})",
        icon=":material/folder_open:"
    )

    if not records:

        st.info(
            f"No Form 16 has been issued for {fy_label(fy_start)} yet."
        )

        return

    names = {
        row["employee_id"]: row["employee_name"]
        for row in all_employees()
    }

    for record in records:

        size_kb = (record["size_bytes"] or 0) / 1024.0

        title = (
            f"{names.get(record['employee_id'], record['employee_id'])}"
            f" · {record['file_name']} · {size_kb:,.0f} KB"
        )

        with st.expander(title):

            st.caption(
                f"Issued to {record['employee_id']} on "
                f"{record['issued_on']}"
                + (
                    f" by {record['issued_by']}"
                    if record["issued_by"] else ""
                )
            )

            facts = [
                ("Name on the form", record["matched_name"]),
                ("PAN", record["employee_pan"]),
                ("Employer", record["employer_name"]),
                ("Matched on", record["match_method"]),
                ("Gross salary", (
                    _rupees(record["gross_salary"])
                    if record["gross_salary"] else ""
                )),
                ("TDS on the form", (
                    _rupees(record["total_tds"])
                    if record["total_tds"] else ""
                )),
                ("Notes", record["notes"])
            ]

            for name, value in facts:

                if value:

                    st.caption(f"{name}: {value}")

            data = get_form16_data(record["id"])

            col1, col2 = st.columns([3, 1])

            with col1:

                if data:

                    st.download_button(
                        "Download this Form 16",
                        data=data,
                        file_name=record["file_name"],
                        mime="application/pdf",
                        key=f"dl_form16_{record['id']}",
                        width="stretch"
                    )

                else:

                    st.warning("The stored PDF is missing.")

            with col2:

                if st.button(
                    "Remove",
                    key=f"del_form16_{record['id']}",
                    width="stretch"
                ):

                    delete_form16(record["id"])

                    st.session_state.tax_flash = (
                        "Form 16 removed — the employee no longer sees it."
                    )

                    st.rerun()


# ============================================================
# HR PAGE
# ============================================================

def show_tax_page(go_home=None):
    """HR: issue Form 16s and see the monthly TDS estimate."""

    user = st.session_state.get("auth_user") or {}

    if user.get("role") != "hr":

        st.error("This screen is only available to HR.")

        st.stop()

    create_form16_table()

    st.title("Income tax", icon=":material/request_quote:")

    st.caption(
        "Form 16 for every employee, and the month-by-month TDS "
        "estimate from their salary."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="tax_back",
        width="content"
    ):

        go_home()

        st.rerun()

    flash = st.session_state.pop("tax_flash", None)

    if flash:

        st.success(flash)

    default_fy = financial_year_start()

    tab1, tab2 = st.tabs(["TDS (monthly)", "Form 16"])

    # -----------------------------------------------------
    # TDS
    # -----------------------------------------------------

    with tab1:

        fy_start = _fy_picker("tax_tds_fy", default_fy)
        st.divider()

        st.subheader(
            f"Monthly TDS estimate — {fy_label(fy_start)}",
            icon=":material/percent:"
        )

        _render_tds_overview(fy_start, issued_employee_ids(fy_start))

        st.divider()

        _render_employee_statement(fy_start)

    # -----------------------------------------------------
    # FORM 16
    # -----------------------------------------------------

    with tab2:

        # A Form 16 is issued once a year has finished, so this tab
        # starts on the year that has just ended.
        fy_start = _fy_picker("tax_form_fy", default_fy - 1)

        st.divider()

        _render_uploader()

        st.divider()

        _render_review(user, fy_start)

        st.divider()

        _render_issued(fy_start)


# ============================================================
# SHARED — ONE EMPLOYEE'S MONTH BY MONTH STATEMENT
# ============================================================

def _render_employee_statement(fy_start):
    """Pick an employee and show their month-by-month TDS."""

    with st.expander("Month-by-month statement for one employee"):

        labels = _employee_labels()

        if not labels:

            st.info("No employees on file yet.")

            return

        chosen = st.selectbox(
            "Employee",
            labels,
            key=f"tax_statement_{fy_start}"
        )

        employee_id = _employee_id_from_label(chosen)

        row = next(
            (
                item for item in employees_with_salary()
                if item["employee_id"] == employee_id
            ),
            None
        )

        if not row:

            st.info(
                "This employee has no salary structure yet, so no "
                "estimate can be made."
            )

            return

        estimate = estimate_tax(gross_annual(row))

        rows = monthly_tds_rows(
            estimate, fy_start, row["joining_date"]
        )

        if not rows:

            st.info(
                f"{row['employee_name']} was not on the rolls in "
                f"{fy_label(fy_start)}."
            )

            return

        col1, col2, col3 = st.columns(3)

        with col1:

            st.metric(
                "Taxable income",
                _rupees(estimate["taxable_income"]),
                border=True
            )

        with col2:

            st.metric(
                "Estimated tax (year)",
                _rupees(estimate["annual_tax"]),
                border=True
            )

        with col3:

            st.metric(
                "Monthly TDS",
                _rupees(estimate["monthly_tax"]),
                border=True
            )

        st.table([
            {
                "Month": item["period"],
                "TDS": _rupees(item["tds"]),
                "TDS so far (YTD)": _rupees(item["ytd"])
            }
            for item in rows
        ])

        st.caption(
            f"Gross salary {_rupees(estimate['gross'])} · "
            f"standard deduction "
            f"{_rupees(estimate['standard_deduction'])} · "
            f"tax {_rupees(estimate['tax_after_rebate'])} + "
            f"cess {_rupees(estimate['cess'])}"
            + (
                f" · rebate {_rupees(estimate['rebate'])}"
                if estimate["rebate"] else ""
            )
        )

        _estimate_caption()


# ============================================================
# EMPLOYEE PAGE
# ============================================================

def show_my_tax():
    """Employee: my Form 16s and my monthly TDS."""

    employee = require_employee()

    if employee is None:

        return

    create_form16_table()

    employee_id = employee["employee_id"]

    st.title("My tax", icon=":material/request_quote:")

    st.caption(
        "Your Form 16 documents and the month-by-month TDS estimated "
        "from your salary."
    )

    today = datetime.date.today()

    fy_start = financial_year_start(today)

    # -----------------------------------------------------
    # FORM 16
    # -----------------------------------------------------

    st.subheader("My Form 16", icon=":material/description:")

    records = get_form16_index(employee_id=employee_id)

    if not records:

        st.info(
            "No Form 16 has been issued to you yet. It appears here as "
            "soon as HR issues it, and you will get a notification."
        )

    for record in records:

        with st.container(border=True):

            st.markdown(
                f"**{fy_label(record['tax_year'])}** · "
                f"{record['file_name']}"
            )

            facts = " · ".join(
                part for part in [
                    (
                        f"Employer: {record['employer_name']}"
                        if record["employer_name"] else ""
                    ),
                    (
                        f"Gross salary: {_rupees(record['gross_salary'])}"
                        if record["gross_salary"] else ""
                    ),
                    (
                        f"TDS: {_rupees(record['total_tds'])}"
                        if record["total_tds"] else ""
                    ),
                    (
                        f"Issued on {record['issued_on']}"
                        if record["issued_on"] else ""
                    )
                ] if part
            )

            if facts:

                st.caption(facts)

            data = get_form16_data(record["id"])

            if data:

                st.download_button(
                    "Download Form 16",
                    data=data,
                    file_name=record["file_name"],
                    mime="application/pdf",
                    key=f"my_form16_{record['id']}"
                )

            else:

                st.warning("The stored PDF is missing — ask HR.")

    st.divider()

    # -----------------------------------------------------
    # TDS
    # -----------------------------------------------------

    st.subheader(
        "My TDS (monthly estimate)",
        icon=":material/percent:"
    )

    row = next(
        (
            item for item in employees_with_salary()
            if item["employee_id"] == employee_id
        ),
        None
    )

    if not row:

        st.info(
            "Your salary structure is not set up yet, so no tax can be "
            "estimated."
        )

        return

    years = _fy_options(fy_start)

    fy_start = st.selectbox(
        "Financial year",
        years,
        index=years.index(financial_year_start(today)),
        format_func=fy_label,
        key="my_tax_fy"
    )

    estimate = estimate_tax(gross_annual(row))

    rows = monthly_tds_rows(estimate, fy_start, row["joining_date"])

    if not rows:

        st.info(
            f"You were not on the rolls in {fy_label(fy_start)}."
        )

        return

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            f"TDS so far ({fy_label(fy_start)})",
            _rupees(rows[-1]["ytd"]),
            border=True
        )

    with col2:

        st.metric(
            "Monthly TDS",
            _rupees(estimate["monthly_tax"]),
            border=True
        )

    with col3:

        st.metric(
            "Estimated tax (year)",
            _rupees(estimate["annual_tax"]),
            border=True
        )

    st.table([
        {
            "Month": item["period"],
            "TDS": _rupees(item["tds"]),
            "TDS so far (YTD)": _rupees(item["ytd"])
        }
        for item in rows
    ])

    st.caption(
        f"Worked out from a gross salary of {_rupees(estimate['gross'])}: "
        f"standard deduction {_rupees(estimate['standard_deduction'])}, "
        f"taxable income {_rupees(estimate['taxable_income'])}, "
        f"tax {_rupees(estimate['tax_after_rebate'])} plus cess "
        f"{_rupees(estimate['cess'])}."
    )

    _estimate_caption()
