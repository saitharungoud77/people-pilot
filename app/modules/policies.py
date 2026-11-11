import os
import re

import streamlit as st

from modules.theme import hero


# ============================================================
# POLICIES
# ============================================================
# Read-only company policies. The wording lives in a markdown file
# under data/ so HR can change it without touching any code - the page
# simply renders the file. Right now this holds the POSH policy.

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))          # app/modules
PROJECT_ROOT = os.path.dirname(os.path.dirname(MODULE_DIR))      # project root

POLICY_PATH = os.path.join(PROJECT_ROOT, "data", "posh_policy.md")

# Used when the file is missing, so the page still opens sensibly.
FALLBACK = """
## Policy file not found

The POSH policy file could not be read. Ask HR to restore
**data/posh_policy.md**.
""".strip()


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def load_policy():
    """Read the POSH policy file as markdown.

    HTML comment blocks are stripped first, so the editor notes at the
    top of the file never reach the screen.
    """

    try:

        with open(POLICY_PATH, encoding="utf-8") as handle:

            text = handle.read()

    except OSError:

        return FALLBACK

    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)

    return text.strip()


def _body(text):
    """Drop the document's first heading.

    The page banner already shows the title, so rendering it a second
    time inside the card would only repeat it.
    """

    lines = text.splitlines()

    if lines and lines[0].startswith("# "):

        return "\n".join(lines[1:]).lstrip("\n")

    return text


def _at_a_glance():
    """Four quick facts taken from the Act."""

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "Applies to",
            "Everyone",
            icon=":material/groups:",
            border=True,
            help="Employees, interns, contractors and visitors."
        )

    with col2:

        st.metric(
            "Raise within",
            "3 months",
            icon=":material/timer:",
            border=True,
            help=(
                "From the date of the incident. The committee may "
                "extend this by three months."
            )
        )

    with col3:

        st.metric(
            "Inquiry time",
            "90 days",
            icon=":material/gavel:",
            border=True,
            help="How long the committee has to finish an inquiry."
        )

    with col4:

        st.metric(
            "Confidential",
            "Always",
            icon=":material/lock:",
            border=True,
            help="Complaint details are kept confidential."
        )


def _render(go_home=None, hr=False):
    """The shared policy screen for both roles."""

    hero(
        "POSH policy",
        "Prevention of Sexual Harassment at AIT Solutions - what counts, "
        "how to complain and what happens next.",
        icon="policy",
        badges=[
            ("Read-only", "lock"),
            ("Applies to everyone", "groups"),
            ("POSH Act, 2013", "balance")
        ]
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="policies_back",
        width="content"
    ):

        go_home()

        st.rerun()

    _at_a_glance()

    st.info(
        "To raise a complaint, or to ask who is currently on the "
        "committee, write to **posh@aitsolutions.com** or contact HR. "
        "You do not need to put your name in an email to ask a "
        "question first.",
        icon=":material/mail:"
    )

    st.space("medium")

    body = _body(load_policy())

    if not body.strip():

        st.warning(
            "The policy file appears to be empty.",
            icon=":material/warning:"
        )

        return

    with st.container(border=True, key="lift_policy"):

        st.markdown(body)

    st.space("small")

    if hr:

        st.caption(
            "Read-only for employees. To change the wording, edit "
            "data/posh_policy.md - the page picks it up on the next "
            "refresh."
        )

    else:

        st.caption(
            "Read-only policy. The same wording is shown to everyone "
            "at AIT Solutions."
        )


# ---------------------------------------------------------
# PAGES
# ---------------------------------------------------------

def show_policies_page(go_home=None):
    """HR: the company policy library (currently POSH)."""

    _render(go_home=go_home, hr=True)


def show_my_policies():
    """Employee: the company policy library (currently POSH)."""

    _render()
