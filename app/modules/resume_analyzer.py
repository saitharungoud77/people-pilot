"""AI resume analyzer — HR screens resumes against required skills.

How it works, in plain English:

1. HR types the **required skills** (and optionally a job title and
   any extra criteria) for a role.
2. HR uploads one or more resumes (PDF or text).
3. Each resume is read with PyMuPDF and sent to an OpenAI model along
   with those requirements. The model returns a **match score from 0
   to 100**, which required skills the candidate has and which are
   missing, plus a short verdict.
4. Every candidate is stored in the ``candidates`` table so HR can
   rank them and mark them **Shortlisted / Rejected / On hold**.

This screen is HR only. It is registered only in the HR navigation and
the function also refuses to render for an employee login, so the
guard does not rely on the menu alone.
"""

import datetime
import json

import pandas as pd
import streamlit as st

from database.connection import (
    get_connection,
    create_candidate_table
)
from modules.offer_letter import (
    DEFAULT_MODEL,
    MODELS,
    ai_available,
    extract_text
)
from modules.config import get_secret


# ============================================================
# SETTINGS
# ============================================================

# Upper bound on the resume text sent with a single request.
MAX_CHARS = 20000

# What HR can mark a screened candidate as.
DECISIONS = ["New", "Shortlisted", "Rejected", "On hold"]

# Score -> verdict band. Checked top-down, so the first floor the
# score reaches wins.
_SCORE_BANDS = [
    (85, "Perfect fit", ""),
    (70, "Strong match", ""),
    (50, "Possible fit", ""),
    (0, "Not a fit", "")
]


# ============================================================
# PROMPTS
# ============================================================

SYSTEM_PROMPT = (
    "You are an experienced technical recruiter. You score how well "
    "a candidate's resume matches a set of required skills. Be strict "
    "and fair: judge only from what the resume actually shows. Return "
    "ONLY a single JSON object."
)

USER_PROMPT = """Score this resume against the job requirements below.

Job requirements
================
<<<REQUIREMENTS>>>

Return a JSON object with exactly these keys:
- candidate_name: the candidate's full name (string, "" if not stated)
- email: email address (string, "" if none)
- phone: phone number (string, "" if none)
- experience_years: total years of professional experience as a number (number)
- education: highest qualification, e.g. "B.Tech Computer Science" (string)
- current_role: current or most recent job title (string)
- skills: every skill found in the resume (array of strings)
- matched_skills: required skills the candidate clearly has (array of strings)
- missing_skills: required skills the candidate lacks or does not show (array of strings)
- score: overall match from 0 to 100 (number)
- strengths: one or two sentences on what fits (string)
- gaps: one or two sentences on what is missing (string)
- summary: a single-sentence verdict (string)

Scoring rules:
- Score how well the resume covers the REQUIRED SKILLS above.
- Every required skill strongly evidenced -> 85 to 100.
- Most required skills present -> 70 to 84.
- Some required skills present -> 50 to 69.
- Few or none -> below 50.
- Never assume a skill that is not shown in the resume.
- Never invent a name; use "" when it is not stated.

Resume
======
<<<RESUME>>>
"""


# ============================================================
# VALUE NORMALISATION
# ============================================================

def _to_float(value):

    try:

        return float(value)

    except (TypeError, ValueError):

        return 0.0


def _clamp_score(value):
    """Coerce the model's score into a whole number from 0 to 100."""

    try:

        score = int(round(float(value)))

    except (TypeError, ValueError):

        score = 0

    return max(0, min(100, score))


def _as_list(value):
    """Accept a list or a comma/semicolon string and return clean items."""

    if isinstance(value, (list, tuple)):

        items = value

    elif value is None:

        items = []

    else:

        items = str(value).replace(";", ",").split(",")

    cleaned = []

    for item in items:

        text = str(item).strip()

        if text and text not in cleaned:

            cleaned.append(text)

    return cleaned


def _join(items):
    """Store skill lists as readable comma-separated text."""

    return ", ".join(_as_list(items))


def split_list(value):
    """Turn a stored comma-separated string back into a list."""

    return _as_list(value)


def verdict_for(score):
    """(label, emoji) for a match score."""

    for floor, label, emoji in _SCORE_BANDS:

        if score >= floor:

            return label, emoji

    return "Not a fit", ""


def normalise_resume(raw):
    """Make the model's JSON safe and complete before it is used."""

    raw = raw if isinstance(raw, dict) else {}

    result = {
        "candidate_name": str(raw.get("candidate_name") or "").strip(),
        "email": str(raw.get("email") or "").strip(),
        "phone": str(raw.get("phone") or "").strip(),
        "experience_years": round(
            _to_float(raw.get("experience_years")), 1
        ),
        "education": str(raw.get("education") or "").strip(),
        "current_role": str(raw.get("current_role") or "").strip(),
        "skills": _as_list(raw.get("skills")),
        "matched_skills": _as_list(raw.get("matched_skills")),
        "missing_skills": _as_list(raw.get("missing_skills")),
        "score": _clamp_score(raw.get("score")),
        "strengths": str(raw.get("strengths") or "").strip(),
        "gaps": str(raw.get("gaps") or "").strip(),
        "summary": str(raw.get("summary") or "").strip()
    }

    if not result["candidate_name"]:

        result["candidate_name"] = "Unnamed candidate"

    return result


def _requirements_text(job_title, required_skills, extra=""):
    """Combine the HR inputs into one block for the model."""

    parts = []

    if (job_title or "").strip():

        parts.append(f"Job title: {job_title.strip()}")

    parts.append(
        "Required skills and criteria:\n"
        + (required_skills or "").strip()
    )

    if (extra or "").strip():

        parts.append("Additional requirements:\n" + extra.strip())

    return "\n\n".join(parts)


# ============================================================
# AI SCORING
# ============================================================

def ai_score_resume(text, requirements, model=DEFAULT_MODEL):
    """Ask the model to score one resume. Returns a normalised dict."""

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
                    "<<<REQUIREMENTS>>>", requirements
                ).replace(
                    "<<<RESUME>>>", str(text or "")[:MAX_CHARS]
                )
            }
        ]
    )

    content = response.choices[0].message.content or "{}"

    return normalise_resume(json.loads(content))


# ============================================================
# DATABASE
# ============================================================

def save_candidate(
    job_title,
    required_skills,
    result,
    file_name=None,
    created_by=None
):
    """Insert one screened candidate. Returns the new row id."""

    label, _emoji = verdict_for(result["score"])

    connection = get_connection()

    try:

        cursor = connection.execute(
            """
            INSERT INTO candidates (
                job_title, required_skills, candidate_name, email,
                phone, experience_years, education, current_role,
                skills, matched_skills, missing_skills, score,
                verdict, strengths, gaps, summary, file_name,
                decision, created_by
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, 'New', ?)
            """,
            (
                job_title,
                required_skills,
                result["candidate_name"],
                result["email"],
                result["phone"],
                result["experience_years"],
                result["education"],
                result["current_role"],
                _join(result["skills"]),
                _join(result["matched_skills"]),
                _join(result["missing_skills"]),
                result["score"],
                label,
                result["strengths"],
                result["gaps"],
                result["summary"],
                file_name,
                created_by
            )
        )

        connection.commit()

        return cursor.lastrowid

    finally:

        connection.close()


def get_candidates(job_title=None, verdict=None, decision=None, search=None):
    """Screened candidates, best match first, with optional filters."""

    query = "SELECT * FROM candidates WHERE 1 = 1"

    params = []

    if job_title:

        query += " AND job_title = ?"

        params.append(job_title)

    if verdict:

        query += " AND verdict = ?"

        params.append(verdict)

    if decision:

        query += " AND decision = ?"

        params.append(decision)

    if search:

        like = f"%{search.strip()}%"

        query += (
            " AND (candidate_name LIKE ? OR skills LIKE ?"
            " OR current_role LIKE ?)"
        )

        params.extend([like, like, like])

    query += " ORDER BY score DESC, id DESC"

    connection = get_connection()

    try:

        cursor = connection.execute(query, params)

        keys = [column[0] for column in cursor.description]

        rows = cursor.fetchall()

    finally:

        connection.close()

    return [dict(zip(keys, row)) for row in rows]


def count_candidates():
    """Total screened candidates."""

    connection = get_connection()

    try:

        return connection.execute(
            "SELECT COUNT(*) FROM candidates"
        ).fetchone()[0]

    finally:

        connection.close()


def distinct_jobs():
    """Job titles that have at least one screened candidate."""

    connection = get_connection()

    try:

        rows = connection.execute(
            "SELECT DISTINCT job_title FROM candidates "
            "WHERE job_title <> '' ORDER BY job_title"
        ).fetchall()

    finally:

        connection.close()

    return [row[0] for row in rows]


def save_decisions(mapping):
    """Persist {candidate_id: decision} from the editable table."""

    if not mapping:

        return 0

    connection = get_connection()

    try:

        saved = 0

        for candidate_id, decision in mapping.items():

            if decision not in DECISIONS:

                continue

            connection.execute(
                "UPDATE candidates SET decision = ? WHERE id = ?",
                (decision, int(candidate_id))
            )

            saved += 1

        connection.commit()

        return saved

    finally:

        connection.close()


def delete_candidate(candidate_id):

    connection = get_connection()

    try:

        connection.execute(
            "DELETE FROM candidates WHERE id = ?",
            (int(candidate_id),)
        )

        connection.commit()

    finally:

        connection.close()


def clear_candidates():

    connection = get_connection()

    try:

        connection.execute("DELETE FROM candidates")

        connection.commit()

    finally:

        connection.close()


# ============================================================
# UI HELPERS
# ============================================================

def _score_badge(score):
    """A compact coloured score chip for the detail cards."""

    label, emoji = verdict_for(score)

    colour = {
        "Perfect fit": "#16a34a",
        "Strong match": "#16a34a",
        "Possible fit": "#d97706",
        "Not a fit": "#dc2626"
    }.get(label, "#6b7280")

    return (
        f'<span style="display:inline-block;padding:2px 10px;'
        f'border-radius:999px;background:{colour}1a;color:{colour};'
        f'font-weight:700;font-size:0.85rem;border:1px solid {colour}40;">'
        f'{score}/100 · {label}</span>'
    )


def _render_results_table(rows):
    """Ranked, editable table of candidates."""

    frame = pd.DataFrame(
        [
            {
                "ID": index + 1,
                "_candidate_id": row["id"],
                "Candidate": row["candidate_name"],
                "Role": row["current_role"],
                "Exp": row["experience_years"],
                "Score": row["score"],
                "Verdict": row["verdict"],
                "Matched": row["matched_skills"],
                "Missing": row["missing_skills"],
                "Decision": row["decision"]
            }
            for index, row in enumerate(rows)
        ]
    )

    edited = st.data_editor(
        frame,
        key="resume_editor",
        hide_index=True,
        width="stretch",
        column_config={
            "ID": st.column_config.NumberColumn("ID", width="small"),
            "_candidate_id": None,
            "Candidate": st.column_config.TextColumn(
                "Candidate", width="medium"
            ),
            "Role": st.column_config.TextColumn("Current role"),
            "Exp": st.column_config.NumberColumn(
                "Exp (yrs)", format="%.1f", width="small"
            ),
            "Score": st.column_config.ProgressColumn(
                "Match score", min_value=0, max_value=100,
                width="medium"
            ),
            "Verdict": st.column_config.TextColumn(
                "Verdict", width="small"
            ),
            "Matched": st.column_config.TextColumn(
                "Matched skills", width="large"
            ),
            "Missing": st.column_config.TextColumn(
                "Missing skills", width="large"
            ),
            "Decision": st.column_config.SelectboxColumn(
                "Decision", options=DECISIONS, required=True,
                width="small"
            )
        },
        disabled=[
            "ID", "_candidate_id", "Candidate", "Role", "Exp", "Score",
            "Verdict", "Matched", "Missing"
        ]
    )

    original = {
        row["id"]: row["decision"]
        for row in rows
    }

    changed = {}

    for _index, record in edited.iterrows():

        candidate_id = int(record["_candidate_id"])

        decision = record["Decision"]

        if original.get(candidate_id) != decision:

            changed[candidate_id] = decision

    return changed


def _render_detail(row):
    """Full scorecard for one candidate."""

    score = row["score"]

    st.markdown(_score_badge(score), unsafe_allow_html=True)

    meta = " · ".join(
        part for part in [
            row["current_role"],
            (
                f"{row['experience_years']:.1f} yrs"
                if row["experience_years"] else ""
            ),
            row["education"],
            row["email"],
            row["phone"]
        ] if part
    )

    if meta:

        st.caption(meta)

    if row["summary"]:

        st.markdown(f"**Verdict:** {row['summary']}")

    col1, col2 = st.columns(2)

    with col1:

        matched = split_list(row["matched_skills"])

        st.markdown(
            "**Matched skills**\n\n"
            + (
                "\n".join(f"- {item}" for item in matched)
                if matched else "- (none recorded)"
            )
        )

    with col2:

        missing = split_list(row["missing_skills"])

        st.markdown(
            "**Missing skills**\n\n"
            + (
                "\n".join(f"- {item}" for item in missing)
                if missing else "- (none)"
            )
        )

    if row["strengths"]:

        st.success(f"Strengths — {row['strengths']}")

    if row["gaps"]:

        st.warning(f"Gaps — {row['gaps']}")

    all_skills = split_list(row["skills"])

    if all_skills:

        st.caption("All skills found: " + ", ".join(all_skills))

    footer = " · ".join(
        part for part in [
            f"Decision: {row['decision']}",
            f"File: {row['file_name']}" if row["file_name"] else "",
            f"Screened by {row['created_by']}" if row["created_by"] else "",
            row["created_at"]
        ] if part
    )

    st.caption(footer)


# ============================================================
# PAGE
# ============================================================

def show_resume_analyzer_page(go_home=None):
    """HR: screen resumes against required skills with AI."""

    user = st.session_state.get("auth_user") or {}

    if user.get("role") != "hr":

        st.error("This screen is only available to HR.")

        st.stop()

    create_candidate_table()

    st.title("AI resume analyzer", icon=":material/person_search:")

    st.caption(
        "Give the required skills for a role, upload the resumes, and "
        "AI scores each candidate and says how well they fit."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="resume_back",
        width="content"
    ):

        go_home()

        st.rerun()

    available, reason = ai_available()

    if not available:

        st.error(reason)

    flash = st.session_state.pop("resume_flash", None)

    if flash:

        st.success(flash)

    flash_warning = st.session_state.pop("resume_warning", None)

    if flash_warning:

        st.warning(flash_warning)

    # -----------------------------------------------------
    # SCREEN NEW RESUMES
    # -----------------------------------------------------

    with st.expander(
        "Screen new resumes",
        expanded=count_candidates() == 0
    ):

        st.subheader(
            "1 · Job requirements",
            icon=":material/checklist:"
        )

        job_title = st.text_input(
            "Job title",
            placeholder="e.g. Data Analyst",
            key="resume_job_title"
        )

        required_skills = st.text_area(
            "Required skills (one per line, or comma separated)",
            height=140,
            placeholder=(
                "Python\nSQL\nPower BI\n3+ years experience\nB.Tech"
            ),
            key="resume_required_skills"
        )

        extra = st.text_area(
            "Additional criteria (optional)",
            height=80,
            placeholder="e.g. willing to work from Hi-Tech City, notice period under 30 days",
            key="resume_extra"
        )

        st.subheader("2 · Upload resumes", icon=":material/upload_file:")

        uploads = st.file_uploader(
            "Resumes (PDF or text) — you can pick several",
            type=["pdf", "txt", "md"],
            accept_multiple_files=True,
            key="resume_files"
        )

        model = DEFAULT_MODEL

        if st.button(
            "Analyze resumes",
            type="primary",
            key="resume_analyze",
            disabled=not available
        ):

            _run_screening(
                job_title,
                required_skills,
                extra,
                uploads,
                model,
                user
            )

    # -----------------------------------------------------
    # SCREENED CANDIDATES
    # -----------------------------------------------------

    st.divider()

    total = count_candidates()

    st.subheader(
        f"Screened candidates ({total})",
        icon=":material/leaderboard:"
    )

    if total == 0:

        st.info(
            "No candidates yet. Add the required skills and upload "
            "some resumes above to get match scores."
        )

        return

    _render_candidate_browser()

    st.divider()

    confirm = st.checkbox(
        "I understand this deletes every screened candidate.",
        key="resume_clear_confirm"
    )

    if st.button(
        "Clear all candidates",
        key="resume_clear",
        disabled=not confirm
    ):

        clear_candidates()

        st.session_state.resume_flash = "All candidates cleared."

        st.rerun()


def _run_screening(
    job_title,
    required_skills,
    extra,
    uploads,
    model,
    user
):
    """Read, score and store every uploaded resume."""

    if not job_title.strip():

        st.error("Please give the job title.")

        return

    if not required_skills.strip():

        st.error("Please list the required skills.")

        return

    if not uploads:

        st.error("Please upload at least one resume.")

        return

    requirements = _requirements_text(job_title, required_skills, extra)

    stored_skills = required_skills.strip()

    analysed = 0

    problems = []

    progress = st.progress(0.0, text="Starting…")

    total = len(uploads)

    for position, uploaded in enumerate(uploads, start=1):

        progress.progress(
            (position - 1) / total,
            text=f"Reading {uploaded.name} ({position}/{total})…"
        )

        try:

            text = extract_text(uploaded)

        except Exception as exc:

            problems.append(f"{uploaded.name}: could not read ({exc})")

            continue

        if not (text or "").strip():

            problems.append(
                f"{uploaded.name}: no readable text "
                "(is the PDF a scan?)"
            )

            continue

        progress.progress(
            (position - 1) / total,
            text=f"Scoring {uploaded.name} ({position}/{total})…"
        )

        try:

            result = ai_score_resume(text, requirements, model=model)

        except Exception as exc:

            problems.append(f"{uploaded.name}: AI failed ({exc})")

            continue

        save_candidate(
            job_title.strip(),
            stored_skills,
            result,
            file_name=uploaded.name,
            created_by=user.get("username")
        )

        analysed += 1

    progress.progress(1.0, text="Done.")

    st.session_state.resume_flash = (
        f"Analyzed {analysed} of {total} resume(s). "
        "See the ranked list below."
    )

    if problems:

        st.session_state.resume_warning = (
            "Some files were skipped: " + "; ".join(problems)
        )

    st.rerun()


def _render_candidate_browser():
    """Filters, the ranked table and the detail cards."""

    col1, col2, col3, col4 = st.columns([2, 1.2, 1.2, 2])

    jobs = distinct_jobs()

    with col1:

        job_filter = st.selectbox(
            "Job",
            ["All jobs"] + jobs,
            key="resume_filter_job"
        )

    with col2:

        verdict_filter = st.selectbox(
            "Verdict",
            ["All"] + [label for _f, label, _e in _SCORE_BANDS],
            key="resume_filter_verdict"
        )

    with col3:

        decision_filter = st.selectbox(
            "Decision",
            ["All"] + DECISIONS,
            key="resume_filter_decision"
        )

    with col4:

        search = st.text_input(
            "Search name or skill",
            key="resume_filter_search"
        )

    rows = get_candidates(
        job_title=None if job_filter == "All jobs" else job_filter,
        verdict=None if verdict_filter == "All" else verdict_filter,
        decision=None if decision_filter == "All" else decision_filter,
        search=search
    )

    if not rows:

        st.info("No candidates match these filters.")

        return

    st.caption(
        f"Showing {len(rows)} candidate(s), best match first. "
        "Change a Decision and click Save."
    )

    changed = _render_results_table(rows)

    if st.button(
        "Save decisions",
        type="primary",
        key="resume_save_decisions",
        disabled=not changed
    ):

        saved = save_decisions(changed)

        st.session_state.resume_flash = f"Saved {saved} decision(s)."

        st.rerun()

    # -----------------------------------------------------
    # DETAIL CARDS
    # -----------------------------------------------------

    st.markdown("#### Candidate scorecards")

    for row in rows:

        emoji = verdict_for(row["score"])[1]

        title = (
            f"{row['candidate_name']} — "
            f"{row['score']}/100 · {row['verdict']}"
            f" · {row['decision']}"
        )

        with st.expander(title):

            _render_detail(row)

            if st.button(
                "Remove this candidate",
                key=f"resume_delete_{row['id']}"
            ):

                delete_candidate(row["id"])

                st.session_state.resume_flash = (
                    f"Removed {row['candidate_name']}."
                )

                st.rerun()
