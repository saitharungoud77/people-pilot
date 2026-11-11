import json
import os
import re

import streamlit as st

from database.connection import create_candidate_table

from modules.config import get_secret

from modules.employee import EMPLOYMENT_TYPES

from modules.offer_letter import ai_available

from modules.resume_analyzer import get_candidates


# ============================================================
# AI HIRING PACK
# ============================================================
# Two things HR needs before interviews start:
#
# 1. A role pack - a job description, the skills to screen for,
#    and the questions to ask.
# 2. An interview kit - questions for one screened candidate,
#    aimed at their strengths and their gaps.
#
# The role pack plugs straight into the resume analyzer: one click
# carries the job title and the required skills across, so the same
# list that wrote the JD is the list the resumes are scored against.

MODELS = [
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini"
]

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

if DEFAULT_MODEL not in MODELS:

    MODELS.insert(0, DEFAULT_MODEL)

SENIORITY = [
    "Intern",
    "Junior",
    "Mid-level",
    "Senior",
    "Lead"
]

LOCATION = "Hi-Tech City, Hyderabad"

PACK_PROMPT = """You write hiring material for AIT Solutions, an
AI-first HR and payroll platform based in Hi-Tech City, Hyderabad.

Return ONLY a JSON object with exactly these keys:
- job_description: markdown text for the job advert (string)
- required_skills: 6-10 must-have skills, each 1-4 words (array of strings)
- nice_to_have: 4-6 optional skills (array of strings)
- screening_questions: 5 short questions HR should check on a resume (array of strings)
- interview_focus: 4-6 areas the interview must cover (array of strings)

Rules:
- The job_description must contain: a two-line role summary, a
  "What you will do" bullet list, and a "What we are looking for"
  bullet list. Use markdown bullets.
- Do not invent salary, benefits, funding, clients or company age.
- Use British/Indian English and a professional but human tone.
- Keep the whole description under 350 words."""

INTERVIEW_PROMPT = """You are the interview lead at AIT Solutions, an
Indian company. Build a structured interview kit for one candidate.

Return ONLY a JSON object with exactly these keys:
- questions: 8-10 objects with keys
    question (string), skill (string), listen_for (string)
- gap_questions: 3 questions probing the candidate's missing skills
  (array of strings)
- scorecard: 5 objects with keys criterion (string),
  what_good_looks_like (string)
- red_flags: 3 warning signs to watch for (array of strings)

Rules:
- Questions must be based on the job requirements and the candidate
  summary provided. Do not invent experience they do not have.
- Do not ask about age, gender, marital status, religion, caste,
  pregnancy, family plans or disability.
- "listen_for" is one sentence describing a strong answer.
- Keep every question short enough to say out loud."""


# ---------------------------------------------------------
# NORMALISING
# ---------------------------------------------------------

def _text(value):

    return str(value or "").strip()


def _as_list(value):
    """A list from either a JSON array or a comma/newline string."""

    if isinstance(value, list):

        return [
            _text(item)
            for item in value
            if _text(item)
        ]

    return [
        item.strip()
        for item in re.split(r"[,;\n]", str(value or ""))
        if item.strip()
    ]


def normalise_pack(raw, fallback_title=""):
    """Clean a model answer into the role-pack shape."""

    raw = raw if isinstance(raw, dict) else {}

    description = _text(raw.get("job_description"))

    if not description:

        raise ValueError(
            "AI did not return a job description — please try again."
        )

    return {
        "job_title": _text(raw.get("job_title")) or fallback_title,
        "job_description": description,
        "required_skills": _as_list(raw.get("required_skills")),
        "nice_to_have": _as_list(raw.get("nice_to_have")),
        "screening_questions": _as_list(raw.get("screening_questions")),
        "interview_focus": _as_list(raw.get("interview_focus"))
    }


def normalise_interview(raw):
    """Clean a model answer into the interview-kit shape."""

    raw = raw if isinstance(raw, dict) else {}

    questions = []

    for item in raw.get("questions") or []:

        if not isinstance(item, dict):

            continue

        question = _text(item.get("question"))

        if not question:

            continue

        questions.append(
            {
                "question": question,
                "skill": _text(item.get("skill")),
                "listen_for": _text(item.get("listen_for"))
            }
        )

    scorecard = []

    for item in raw.get("scorecard") or []:

        if not isinstance(item, dict):

            continue

        criterion = _text(item.get("criterion"))

        if not criterion:

            continue

        scorecard.append(
            {
                "criterion": criterion,
                "what_good_looks_like": _text(
                    item.get("what_good_looks_like")
                )
            }
        )

    if not questions:

        raise ValueError(
            "AI did not return interview questions — please try again."
        )

    return {
        "questions": questions,
        "gap_questions": _as_list(raw.get("gap_questions")),
        "scorecard": scorecard,
        "red_flags": _as_list(raw.get("red_flags"))
    }


# ---------------------------------------------------------
# AI CALLS
# ---------------------------------------------------------

def generate_pack(
    job_title,
    department,
    seniority,
    employment_type,
    location,
    must_have,
    responsibilities,
    model=DEFAULT_MODEL
):
    """Ask the model for a complete role pack."""

    if not job_title.strip():

        raise ValueError("Please enter the job title.")

    from openai import OpenAI

    details = [
        f"Job title: {job_title.strip()}",
        f"Department: {department.strip() or 'not specified'}",
        f"Seniority: {seniority}",
        f"Employment type: {employment_type}",
        f"Location: {location.strip() or LOCATION}",
        f"Must-have skills given by HR: {must_have.strip() or 'not specified'}",
        f"Responsibilities given by HR: {responsibilities.strip() or 'not specified'}"
    ]

    client = OpenAI(api_key=get_secret("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model=model,
        temperature=0.4,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": PACK_PROMPT},
            {"role": "user", "content": "\n".join(details)}
        ]
    )

    raw = response.choices[0].message.content or "{}"

    try:

        parsed = json.loads(raw)

    except json.JSONDecodeError as error:

        raise ValueError("AI answer was not valid JSON.") from error

    parsed["job_title"] = job_title.strip()

    return normalise_pack(parsed, fallback_title=job_title.strip())


def _candidate_context(candidate, required_skills):

    return "\n".join(
        [
            f"Job title: {candidate.get('job_title') or 'not specified'}",
            f"Required skills: {required_skills or candidate.get('required_skills') or 'not specified'}",
            f"Candidate name: {candidate.get('candidate_name') or 'not given'}",
            f"Current role: {candidate.get('current_role') or 'not given'}",
            f"Experience: {candidate.get('experience_years') or 0} years",
            f"Education: {candidate.get('education') or 'not given'}",
            f"Skills on resume: {candidate.get('skills') or 'not given'}",
            f"Matched skills: {candidate.get('matched_skills') or 'none'}",
            f"Missing skills: {candidate.get('missing_skills') or 'none'}",
            f"Match score: {candidate.get('score') or 0}/100 "
            f"({candidate.get('verdict') or 'not scored'})",
            f"Screening summary: {candidate.get('summary') or 'not given'}"
        ]
    )


def generate_interview_kit(candidate, required_skills="", model=DEFAULT_MODEL):
    """Ask the model for an interview kit for one screened candidate."""

    from openai import OpenAI

    client = OpenAI(api_key=get_secret("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model=model,
        temperature=0.4,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": INTERVIEW_PROMPT},
            {
                "role": "user",
                "content": _candidate_context(candidate, required_skills)
            }
        ]
    )

    raw = response.choices[0].message.content or "{}"

    try:

        parsed = json.loads(raw)

    except json.JSONDecodeError as error:

        raise ValueError("AI answer was not valid JSON.") from error

    return normalise_interview(parsed)


# ---------------------------------------------------------
# DOWNLOADS
# ---------------------------------------------------------

def pack_markdown(pack):
    """The role pack as a portable markdown file."""

    lines = [
        f"# {pack['job_title']} — hiring pack",
        "",
        pack["job_description"],
        "",
        "## Required skills",
        *[f"- {skill}" for skill in pack["required_skills"]],
        "",
        "## Nice to have",
        *[f"- {skill}" for skill in pack["nice_to_have"]],
        "",
        "## Screening questions",
        *[
            f"{number}. {question}"
            for number, question in enumerate(
                pack["screening_questions"], start=1
            )
        ],
        "",
        "## Interview focus",
        *[f"- {area}" for area in pack["interview_focus"]],
        "",
        "_Prepared with AIT Assist. Review before publishing._"
    ]

    return "\n".join(lines)


def interview_markdown(kit, candidate):
    """The interview kit as a portable markdown file."""

    name = candidate.get("candidate_name") or "Candidate"

    lines = [
        f"# Interview kit — {name}",
        f"Role: {candidate.get('job_title') or 'not specified'} · "
        f"Match score: {candidate.get('score') or 0}/100",
        "",
        "## Questions",
    ]

    for number, item in enumerate(kit["questions"], start=1):

        lines.append(f"{number}. **{item['question']}**")

        if item["skill"]:

            lines.append(f"   - Skill: {item['skill']}")

        if item["listen_for"]:

            lines.append(f"   - Listen for: {item['listen_for']}")

    lines.append("")

    if kit["gap_questions"]:

        lines.append("## Probe the gaps")

        lines.extend(
            f"- {question}" for question in kit["gap_questions"]
        )

        lines.append("")

    if kit["scorecard"]:

        lines.append("## Scorecard")

        for item in kit["scorecard"]:

            lines.append(f"- **{item['criterion']}** — "
                         f"{item['what_good_looks_like']}")

        lines.append("")

    if kit["red_flags"]:

        lines.append("## Red flags")

        lines.extend(f"- {flag}" for flag in kit["red_flags"])

        lines.append("")

    lines.append("_Prepared with AIT Assist. Review before the interview._")

    return "\n".join(lines)


def _slug(value):

    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower())

    return cleaned.strip("-") or "role"


# ---------------------------------------------------------
# PAGE
# ---------------------------------------------------------

def show_hiring_pack_page(go_home=None):
    """HR: build a role pack and an interview kit with AI."""

    user = st.session_state.get("auth_user") or {}

    if user.get("role") != "hr":

        st.error("This screen is only available to HR.")

        st.stop()

    st.title("AI hiring pack", icon=":material/psychology:")

    st.caption(
        "Write the role once — get the job description, the skills to "
        "screen for, and the questions to ask each shortlisted person."
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="hiring_back",
        width="content"
    ):

        go_home()

        st.rerun()

    create_candidate_table()

    available, reason = ai_available()

    if not available:

        st.error(reason)

    tab_role, tab_interview = st.tabs(
        ["Role pack", "Interview kit"]
    )

    # -----------------------------------------------------
    # ROLE PACK
    # -----------------------------------------------------

    with tab_role:

        col1, col2 = st.columns(2)

        with col1:

            job_title = st.text_input(
                "Job title",
                placeholder="e.g. Payroll Executive",
                key="hiring_title"
            )

            department = st.text_input(
                "Department",
                placeholder="e.g. Finance",
                key="hiring_department"
            )

        with col2:

            seniority = st.selectbox(
                "Seniority",
                SENIORITY,
                index=SENIORITY.index("Mid-level"),
                key="hiring_seniority"
            )

            employment_type = st.selectbox(
                "Employment type",
                EMPLOYMENT_TYPES,
                key="hiring_employment"
            )

        location = st.text_input(
            "Location",
            value=LOCATION,
            key="hiring_location"
        )

        must_have = st.text_area(
            "Must-have skills (optional)",
            placeholder="e.g. payroll compliance, PF/ESIC, Excel",
            height=70,
            key="hiring_must_have"
        )

        responsibilities = st.text_area(
            "Responsibilities (optional)",
            placeholder=(
                "e.g. run monthly payroll, file PF returns, answer "
                "employee queries"
            ),
            height=80,
            key="hiring_responsibilities"
        )

        model = DEFAULT_MODEL

        if st.button(
            "Build the role pack",
            type="primary",
            key="hiring_build",
            disabled=not available
        ):

            try:

                with st.spinner("Writing the role pack…"):

                    pack = generate_pack(
                        job_title,
                        department,
                        seniority,
                        employment_type,
                        location,
                        must_have,
                        responsibilities,
                        model=model
                    )

                st.session_state.hiring_pack = pack

            except ValueError as error:

                st.error(str(error))

            except Exception as error:  # noqa: BLE001

                st.error(f"AI could not build the pack: {error}")

        pack = st.session_state.get("hiring_pack")

        if pack:

            st.divider()

            st.subheader(
                pack["job_title"],
                icon=":material/work:"
            )

            with st.container(border=True):

                st.markdown(pack["job_description"])

            col1, col2 = st.columns(2)

            with col1:

                st.markdown("**Required skills**")

                for skill in pack["required_skills"]:

                    st.markdown(f"- {skill}")

                st.markdown("**Nice to have**")

                for skill in pack["nice_to_have"]:

                    st.markdown(f"- {skill}")

            with col2:

                st.markdown("**Screening questions**")

                for number, question in enumerate(
                    pack["screening_questions"], start=1
                ):

                    st.markdown(f"{number}. {question}")

                st.markdown("**Interview focus**")

                for area in pack["interview_focus"]:

                    st.markdown(f"- {area}")

            st.space("small")

            if st.button(
                "Send these skills to the resume analyzer →",
                key="hiring_to_resume",
                icon=":material/person_search:"
            ):

                st.session_state.resume_job_title = pack["job_title"]

                st.session_state.resume_required_skills = "\n".join(
                    pack["required_skills"]
                )

                st.session_state.current_page = "resume"

                st.rerun()

            st.download_button(
                "Download the pack (.md)",
                data=pack_markdown(pack).encode("utf-8"),
                file_name=f"hiring-pack-{_slug(pack['job_title'])}.md",
                mime="text/markdown",
                icon=":material/download:"
            )

    # -----------------------------------------------------
    # INTERVIEW KIT
    # -----------------------------------------------------

    with tab_interview:

        candidates = get_candidates()

        if not candidates:

            st.info(
                "No screened candidates yet. Run the resume analyzer "
                "first, then come back to build the interview kit."
            )

            return

        labels = [
            (
                f"{candidate.get('candidate_name') or 'Unnamed'} · "
                f"{candidate.get('job_title') or 'role'} · "
                f"{candidate.get('score') or 0}/100"
            )
            for candidate in candidates
        ]

        choice = st.selectbox(
            "Candidate",
            range(len(candidates)),
            format_func=lambda index: labels[index],
            key="interview_candidate"
        )

        candidate = candidates[choice]

        required_skills = st.text_area(
            "Skills to test (optional override)",
            value=candidate.get("required_skills") or "",
            height=70,
            key="interview_skills"
        )

        model = DEFAULT_MODEL

        if st.button(
            "Build the interview kit",
            type="primary",
            key="interview_build",
            disabled=not available
        ):

            try:

                with st.spinner("Preparing the questions…"):

                    kit = generate_interview_kit(
                        candidate,
                        required_skills=required_skills,
                        model=model
                    )

                st.session_state.interview_kit = kit

                st.session_state.interview_kit_for = candidate.get("id")

            except ValueError as error:

                st.error(str(error))

            except Exception as error:  # noqa: BLE001

                st.error(f"AI could not build the kit: {error}")

        kit = st.session_state.get("interview_kit")

        if kit and st.session_state.get("interview_kit_for") == candidate.get("id"):

            st.divider()

            st.subheader(
                f"Interview kit — {candidate.get('candidate_name') or 'Candidate'}",
                icon=":material/quiz:"
            )

            st.caption(
                f"Match score {candidate.get('score') or 0}/100 · "
                f"{candidate.get('verdict') or 'not scored'}"
            )

            for number, item in enumerate(kit["questions"], start=1):

                with st.container(border=True):

                    st.markdown(f"**{number}. {item['question']}**")

                    if item["skill"]:

                        st.caption(f"Skill: {item['skill']}")

                    if item["listen_for"]:

                        st.caption(f"Listen for: {item['listen_for']}")

            if kit["gap_questions"]:

                st.markdown("**Probe the gaps**")

                for question in kit["gap_questions"]:

                    st.markdown(f"- {question}")

            if kit["scorecard"]:

                st.markdown("**Scorecard**")

                st.dataframe(
                    [
                        {
                            "Criterion": item["criterion"],
                            "What good looks like": item["what_good_looks_like"]
                        }
                        for item in kit["scorecard"]
                    ],
                    hide_index=True,
                    width="stretch"
                )

            if kit["red_flags"]:

                st.markdown("**Red flags**")

                for flag in kit["red_flags"]:

                    st.markdown(f"- {flag}")

            st.download_button(
                "Download the kit (.md)",
                data=interview_markdown(kit, candidate).encode("utf-8"),
                file_name=(
                    f"interview-kit-"
                    f"{_slug(candidate.get('candidate_name') or 'candidate')}.md"
                ),
                mime="text/markdown",
                icon=":material/download:"
            )