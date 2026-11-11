import time

import streamlit as st

from modules.theme import hero


# ============================================================
# SPLASH SCREEN
# ============================================================
# Brief branded screen shown on start-up. After LANDING_SECONDS it
# hands over to the dashboard (see main.py routing).

LANDING_SECONDS = 2

_HIGHLIGHTS = [
    ("Employees", "groups"),
    ("Payroll", "payments"),
    ("Payslips", "receipt_long"),
    ("Provident fund", "account_balance"),
    ("Leave", "event_available"),
    ("Attendance", "fact_check"),
]


def show_home():
    """Render the splash screen and auto-advance to the app."""

    if st.session_state.get("landing_complete"):

        return

    if "landing_started_at" not in st.session_state:

        st.session_state.landing_started_at = time.time()

    # Center the splash card.
    _left, center, _right = st.columns([1, 1.8, 1])

    with center:

        with st.container(border=True, key="lift_splash"):

            st.space("medium")

            hero(
                "AIT Solutions",
                "AI HR & Payroll platform · Manage the complete "
                "employee lifecycle from one place.",
                icon="apartment",
                center=True,
                badges=_HIGHLIGHTS
            )

            st.space("medium")

            _advance_from_landing()

            st.space("medium")


@st.fragment(run_every="0.3s")
def _advance_from_landing():
    """Animate the progress bar, then move on once the splash has
    been visible for a few seconds.

    Using a fragment keeps the server responsive instead of
    blocking every user with time.sleep().
    """

    started = st.session_state.get(
        "landing_started_at",
        time.time()
    )

    elapsed = time.time() - started

    st.progress(
        max(0.0, min(elapsed / LANDING_SECONDS, 1.0)),
        text="Preparing your workspace…"
    )

    if elapsed >= LANDING_SECONDS:

        st.session_state.landing_complete = True

        st.session_state.current_page = "application"

        st.rerun()
