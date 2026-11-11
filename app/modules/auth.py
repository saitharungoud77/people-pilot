import hashlib
import hmac
import secrets

import streamlit as st

from database.connection import (
    get_connection,
    create_users_table
)


# ============================================================
# AUTHENTICATION & ROLES
# ============================================================
# Lightweight, database-backed sign-in for a local HR portal.
#
# Two roles:
#   * hr       - full access (create / edit / delete employees,
#                salary structures, payslips, database viewer)
#   * employee - read-only access to their own record only
#
# Passwords are stored as salted PBKDF2-SHA256 hashes, never in
# plain text.
#
# NOTE: This is app-level authentication suitable for an internal
# POC/demo. For internet-facing or production deployments, use
# Streamlit's native OIDC login (`st.login`) with a real identity
# provider instead.

import os

DEFAULT_HR_USERNAME = os.getenv("DEFAULT_HR_USERNAME", "hr")
DEFAULT_HR_PASSWORD = os.getenv("DEFAULT_HR_PASSWORD", "change-me-on-first-login")
DEFAULT_EMPLOYEE_PASSWORD = os.getenv("DEFAULT_EMPLOYEE_PASSWORD", "change-me-on-first-login")

_PBKDF2_ITERATIONS = 200_000


# ---------------------------------------------------------
# PASSWORD HASHING
# ---------------------------------------------------------

def _hash_password(password, salt_hex=None):
    """Return (password_hash_hex, salt_hex) for the given password."""

    if salt_hex is None:

        salt = secrets.token_bytes(16)

        salt_hex = salt.hex()

    else:

        salt = bytes.fromhex(salt_hex)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS
    )

    return digest.hex(), salt_hex


def _verify_password(password, password_hash, salt_hex):

    candidate, _ = _hash_password(password, salt_hex)

    return hmac.compare_digest(candidate, password_hash)


# ---------------------------------------------------------
# USER STORE
# ---------------------------------------------------------

def _get_user_row(username):
    """Fetch a user row by username (case-insensitive)."""

    connection = get_connection()

    try:

        row = connection.execute(
            """
            SELECT
                username,
                password_hash,
                password_salt,
                role,
                employee_id
            FROM users
            WHERE username = ? COLLATE NOCASE
            """,
            (username,)
        ).fetchone()

    finally:

        connection.close()

    return row


def create_user(
    username,
    password,
    role,
    employee_id=None,
    overwrite=False
):
    """Insert a user with a hashed password."""

    password_hash, salt = _hash_password(password)

    connection = get_connection()

    try:

        if overwrite:

            connection.execute(
                "DELETE FROM users "
                "WHERE username = ? COLLATE NOCASE",
                (username,)
            )

        connection.execute(
            """
            INSERT INTO users
                (
                    username,
                    password_hash,
                    password_salt,
                    role,
                    employee_id
                )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                username,
                password_hash,
                salt,
                role,
                employee_id
            )
        )

        connection.commit()

    finally:

        connection.close()


def set_password(username, new_password):
    """Change a user's password (keeps the existing salt reset)."""

    password_hash, salt = _hash_password(new_password)

    connection = get_connection()

    try:

        connection.execute(
            """
            UPDATE users
            SET password_hash = ?,
                password_salt = ?
            WHERE username = ? COLLATE NOCASE
            """,
            (password_hash, salt, username)
        )

        connection.commit()

    finally:

        connection.close()


def verify_current_password(username, password):
    """Check a password for an existing user (used to change it)."""

    row = _get_user_row(username)

    if row is None:

        return False

    _username, password_hash, salt, _role, _employee_id = row

    return _verify_password(password, password_hash, salt)


def list_users():
    """Return all login accounts (no password material)."""

    connection = get_connection()

    try:

        rows = connection.execute(
            """
            SELECT
                u.username,
                u.role,
                u.employee_id,
                CASE
                    WHEN u.role = 'hr' THEN u.login_email
                    ELSE e.work_email
                END AS login_email,
                u.created_at
            FROM users AS u
            LEFT JOIN employees AS e
                ON e.employee_id = u.employee_id
            ORDER BY role, username COLLATE NOCASE
            """
        ).fetchall()

    finally:

        connection.close()

    return [
        {
            "username": row[0],
            "role": row[1],
            "employee_id": row[2],
            "login_email": row[3],
            "created_at": row[4]
        }
        for row in rows
    ]


def update_hr_login_email(username, email):
    """Set the email address that an HR account can use to sign in."""

    email = (email or "").strip()
    connection = get_connection()

    try:
        account = connection.execute(
            "SELECT role FROM users WHERE username = ? COLLATE NOCASE",
            (username,)
        ).fetchone()
        if account is None or account[0] != "hr":
            raise ValueError("Select an existing HR account.")

        if email:
            conflicting_hr = connection.execute(
                """
                SELECT 1
                FROM users
                WHERE role = 'hr'
                  AND username != ? COLLATE NOCASE
                  AND login_email = ? COLLATE NOCASE
                LIMIT 1
                """,
                (username, email)
            ).fetchone()
            conflicting_employee = connection.execute(
                """
                SELECT 1
                FROM employees
                WHERE work_email = ? COLLATE NOCASE
                LIMIT 1
                """,
                (email,)
            ).fetchone()
            if conflicting_hr or conflicting_employee:
                raise ValueError(
                    "That email is already assigned to another login."
                )

        connection.execute(
            """
            UPDATE users
            SET login_email = ?
            WHERE username = ? COLLATE NOCASE
            """,
            (email, username)
        )
        connection.commit()
    finally:
        connection.close()


def reset_employee_password(employee_id, new_password=None):
    """Reset (or create) an employee's login password.

    Returns the password that was set.
    """

    password = new_password or DEFAULT_EMPLOYEE_PASSWORD

    if _get_user_row(employee_id) is None:

        connection = get_connection()

        try:

            exists = connection.execute(
                "SELECT 1 FROM employees WHERE employee_id = ?",
                (employee_id,)
            ).fetchone()

        finally:

            connection.close()

        if not exists:

            raise ValueError(
                f"No employee found with ID '{employee_id}'."
            )

        create_user(
            employee_id,
            password,
            "employee",
            employee_id
        )

    else:

        set_password(employee_id, password)

    return password


# ---------------------------------------------------------
# FIRST-RUN SETUP
# ---------------------------------------------------------

def ensure_auth_setup():
    """Create the users table, seed HR, and provision employee logins."""

    create_users_table()

    if _get_user_row(DEFAULT_HR_USERNAME) is None:

        create_user(
            DEFAULT_HR_USERNAME,
            DEFAULT_HR_PASSWORD,
            "hr"
        )

    _provision_employee_accounts()


def _provision_employee_accounts():
    """Give every employee a login: username = Employee ID."""

    connection = get_connection()

    try:

        employees = connection.execute(
            "SELECT employee_id FROM employees"
        ).fetchall()

        existing = {
            row[0].lower()
            for row in connection.execute(
                "SELECT username FROM users"
            ).fetchall()
        }

    finally:

        connection.close()

    for (employee_id,) in employees:

        if employee_id.lower() not in existing:

            create_user(
                employee_id,
                DEFAULT_EMPLOYEE_PASSWORD,
                "employee",
                employee_id
            )


# ---------------------------------------------------------
# SIGN IN / OUT
# ---------------------------------------------------------

def authenticate_any(identifier, password):
    """Sign in with one form, whatever the role.

    Resolve HR username/registered email, or employee ID/work email.
    The role comes from the matching account, so users do not choose it.
    """

    identifier = (identifier or "").strip()
    if not identifier:
        return None

    connection = get_connection()
    try:
        matches = connection.execute(
            """
            SELECT DISTINCT
                u.username,
                u.password_hash,
                u.password_salt,
                u.role,
                u.employee_id
            FROM users AS u
            LEFT JOIN employees AS e
                ON e.employee_id = u.employee_id
            WHERE u.username = ? COLLATE NOCASE
               OR (u.role = 'hr'
                   AND u.login_email = ? COLLATE NOCASE)
               OR (u.role = 'employee'
                   AND e.work_email = ? COLLATE NOCASE)
            """,
            (identifier, identifier, identifier)
        ).fetchall()
    finally:
        connection.close()

    if len(matches) != 1:
        return None

    username, password_hash, salt, user_role, employee_id = matches[0]

    if not _verify_password(password, password_hash, salt):

        return None

    return {
        "username": username,
        "role": user_role,
        "employee_id": employee_id
    }


def _sign_in(user):
    """Store the session user and replay the splash screen."""

    st.session_state.auth_user = user

    st.session_state.current_page = "landing"

    st.session_state.landing_complete = False

    st.rerun()


def sign_out():
    """Clear the signed-in user."""

    st.session_state.auth_user = None

    st.session_state.current_page = "application"

    st.session_state.landing_complete = True

    st.rerun()


# ---------------------------------------------------------
# LOGIN SCREEN
# ---------------------------------------------------------
# Full-screen split sign-in: a story panel fills the left of the
# viewport, the sign-in card floats centred on the right.
#
# _LOGIN_CSS is rendered only while nobody is signed in — once the
# user signs in this code path stops running, Streamlit removes the
# style element, and every rule below goes with it. Nothing here can
# leak into the signed-in app.

_LOGIN_CSS = """
<style>
/* ---- Full-screen chrome (login only) ---- */

[data-testid="stHeader"] { display: none !important; }

[data-testid="stSidebar"],
[data-testid="stSidebarCollapsedControl"] {
    display: none !important;
}

[data-testid="stAppViewContainer"] {
    height: 100vh !important;
    height: 100dvh !important;
    min-height: 0 !important;
    overflow: hidden !important;
    background: linear-gradient(90deg, #116B57 0%, #16856B 40%, #E8F2ED 75%, #F7F6F2 100%) !important;
}

[data-testid="stMain"] {
    height: 100vh !important;
    height: 100dvh !important;
    min-height: 0 !important;
    overflow: hidden !important;
    background: transparent !important;
}

[data-testid="stMainBlockContainer"] {
    box-sizing: border-box !important;
    width: 100% !important;
    height: 100vh !important;
    height: 100dvh !important;
    padding: 0 !important;
    margin: 0 !important;
    max-width: none !important;
    min-height: 0 !important;
    overflow: hidden !important;
    background: transparent !important;
}

[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {
    width: 100% !important;
    height: 100% !important;
    min-height: 0 !important;
    gap: 0 !important;
}

/* the two halves meet with no gutter */
[data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] {
    width: 100% !important;
    height: 100% !important;
    gap: 0 !important;
    min-height: 0 !important;
}

[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    padding: 0 !important;
    margin: 0 !important;
    min-height: 0 !important;
}

[data-testid="stColumn"]:first-child > [data-testid="stVerticalBlock"] {
    padding: 0 !important;
    gap: 0 !important;
    height: 100% !important;
    min-height: 0 !important;
}

/* the sign-in half centres its content vertically */
[data-testid="stColumn"]:last-child,
[data-testid="stColumn"]:last-child > [data-testid="stVerticalBlock"] {
    display: flex;
    flex-direction: column;
    justify-content: center;
}

[data-testid="stColumn"]:last-child {
    padding: 36px clamp(26px, 5vw, 80px) !important;
    background: transparent !important;
}

.ait-story {
    height: 100vh !important;
    height: 100dvh !important;
    min-height: 100vh !important;
    background: transparent !important;
    min-height: 100dvh !important;
    overflow-y: auto !important;
}

.ait-story {
    background: transparent !important;
}

.ait-login-footer {
    margin: 20px 0 0;
    color: #68716F;
    font-size: .76rem;
    line-height: 1.5;
    text-align: center;
}

/* the card keeps a comfortable measure instead of stretching */
[class*="st-key-lift_login"] {
    max-width: 460px;
    width: 100%;
    margin: 24px auto 0;
    padding: 22px !important;
    background: #FFFFFF !important;
    border: 1px solid #E1E5DF !important;
    border-radius: 16px !important;
    color: #252A2A !important;
    box-shadow: 0 18px 48px rgba(37, 42, 42, .12) !important;
}

[class*="st-key-lift_login"] [data-testid="stForm"] {
    padding: 0 !important;
    border: 0 !important;
    background: transparent !important;
}

[class*="st-key-lift_login"] [data-testid="stWidgetLabel"] p,
[class*="st-key-lift_login"] [data-testid="stWidgetLabel"] label {
    color: #34413B !important;
}

[class*="st-key-lift_login"] [data-testid="stTextInput"] input {
    background: #FFFFFF !important;
    border-color: #D7DDD6 !important;
    color: #252A2A !important;
    caret-color: #16856B !important;
}

[class*="st-key-lift_login"] [data-testid="stTextInput"] input::placeholder {
    color: #68716F !important;
    opacity: 1 !important;
}

[class*="st-key-lift_login"] [data-testid="stCaptionContainer"],
[class*="st-key-lift_login"] [data-testid="stCaptionContainer"] p,
[class*="st-key-lift_login"] [data-testid="stMarkdownContainer"] p {
    color: #68716F !important;
}

[class*="st-key-lift_login"] hr {
    border-color: #E1E5DF !important;
}

[class*="st-key-lift_login"] [data-testid="stBaseButton-secondaryFormSubmit"] {
    background: #16856B !important;
    border-color: #116B57 !important;
    color: #FFFFFF !important;
}

/* glass feature cards in the story */
.ait-card {
    color: #173C2E !important;
    background: #E2F2E7 !important;
    border-color: #C4DEC9 !important;
    transition: transform .2s ease, background .2s ease;
}

.ait-card span,
.ait-card div {
    color: #173C2E !important;
}

.ait-card:hover {
    transform: translateY(-2px);
    background: #D4EBDD !important;
}

.ait-login-intro {
    max-width: 460px;
    width: 100%;
    margin: 0 auto 22px;
    padding: 22px 24px;
    border: 0;
    border-radius: 0;
    background: transparent;
    color: #173C2E;
    box-shadow: none;
}

.ait-story-trust {
    background: transparent !important;
    border: 0 !important;
    border-radius: 0;
    color: #FFFFFF !important;
    opacity: 1 !important;
}

.ait-story-trust span {
    color: #FFFFFF !important;
}

@media (max-height: 820px) and (min-width: 861px) {
    .ait-story {
        padding: 18px clamp(26px, 3.5vw, 48px) !important;
    }

    .ait-login-intro {
        padding: 18px 20px;
        margin-bottom: 16px;
    }

    .ait-story > div:first-child {
        justify-content: center !important;
    }

    .ait-story > div:first-child > div:nth-child(2) {
        margin-top: 16px !important;
        font-size: clamp(1.55rem, 2.2vw, 2rem) !important;
    }

    .ait-story > div:first-child > p {
        margin-top: 10px !important;
        font-size: .86rem !important;
        line-height: 1.45 !important;
    }

    .ait-story > div:first-child > div:nth-child(4) {
        margin-top: 14px !important;
        padding: 12px 14px !important;
    }

    .ait-story__grid {
        margin-top: 14px !important;
        gap: 9px !important;
    }

    .ait-card {
        padding: 9px 11px 10px !important;
    }

    .ait-card > div:last-child {
        margin-top: 3px !important;
        font-size: .72rem !important;
        line-height: 1.35 !important;
    }

    .ait-story > div:last-child {
        margin-top: 12px !important;
        padding: 10px 12px !important;
    }

    [data-testid="stColumn"]:last-child {
        padding-top: 18px !important;
        padding-bottom: 18px !important;
    }

    .ait-login-intro {
        padding: 16px 18px;
        margin-bottom: 12px;
    }

    [class*="st-key-lift_login"] {
        margin-top: 14px;
        padding: 18px !important;
    }

    .ait-login-footer {
        margin-top: 10px;
    }
}

/* stacked layout on narrow screens */
@media (max-width: 860px) {
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    [data-testid="stMainBlockContainer"] {
        height: auto !important;
        min-height: 100vh !important;
        min-height: 100dvh !important;
        overflow: visible !important;
        background: transparent !important;
    }

    [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"],
    [data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] {
        height: auto !important;
    }

    .ait-story {
        height: auto !important;
        min-height: auto !important;
        overflow: visible !important;
    }

    [data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] {
        min-height: 0 !important;
    }

    .ait-story__grid {
        grid-template-columns: 1fr !important;
    }

    [data-testid="stColumn"]:last-child {
        padding: 30px 22px !important;
        background: transparent !important;
    }

    .ait-login-intro {
        padding: 18px 0;
    }
}

/* ---- PeoplePilot brand animation ---- */
@keyframes aitBrandIn {
    0%   { opacity: 0; transform: translateY(-14px) scale(.92); filter: blur(6px); }
    60%  { opacity: 1; transform: translateY(2px) scale(1.03); filter: blur(0); }
    100% { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
}
@keyframes aitBrandGlow {
    0%, 100% { text-shadow: 0 0 0 rgba(255,255,255,0); }
    50%      { text-shadow: 0 0 14px rgba(255,255,255,.35); }
}
.ait-brand {
    display: inline-block;
    animation: aitBrandIn .9s cubic-bezier(.2,.8,.2,1) both,
               aitBrandGlow 3.2s ease-in-out 1s infinite;
}
@keyframes aitFloat {
    0%, 100% { transform: translateY(0) rotate(0deg); }
    50%      { transform: translateY(-6px) rotate(6deg); }
}

/* ---- Intro splash ---- */
#ait-splash {
    position: fixed; inset: 0; z-index: 99999;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    background: linear-gradient(165deg, #116B57 0%, #16856B 54%, #315B49 100%);
    color: #fff;
    animation: aitSplash 2.8s ease forwards;
    pointer-events: none;
}
.ait-splash-name {
    font-size: clamp(2.6rem, 6vw, 4.2rem); font-weight: 800;
    letter-spacing: -.03em;
    animation: aitSplashName 2.8s ease forwards;
}
.ait-splash-tag {
    margin-top: 10px; font-size: 1rem; opacity: .85;
    animation: aitSplashName 2.8s ease forwards;
}
@keyframes aitSplash {
    0%   { opacity: 1; }
    75%  { opacity: 1; }
    100% { opacity: 0; visibility: hidden; }
}
@keyframes aitSplashName {
    0%   { opacity: 0; transform: translateY(24px) scale(.85); filter: blur(8px); }
    35%  { opacity: 1; transform: translateY(0) scale(1.05); filter: blur(0); }
    65%  { opacity: 1; transform: translateY(0) scale(1); }
    100% { opacity: 0; transform: translateY(-12px) scale(1.1); }
}

html body [data-testid="stAppViewContainer"] {
    background-color: #FFFFFF !important;
    background-image: linear-gradient(
        90deg in oklab, #0B3D2E 0%, #16856B 22%,
        #6FC4A8 40%, #BFE3D4 55%, #FFFFFF 75%, #FFFFFF 100%
    ) !important;
    background-repeat: no-repeat !important;
    background-size: 100% 100% !important;
}

@media (min-width: 861px) {
    .ait-story > div:first-child {
        max-width: 24vw !important;
    }

    .ait-story > div:first-child > div:nth-child(2) {
        font-size: clamp(1.35rem, 2vw, 2rem) !important;
    }

    .ait-story > div:first-child > p {
        font-size: clamp(.72rem, .9vw, .86rem) !important;
        line-height: 1.45 !important;
    }
}

@media (max-width: 860px) {
    html body [data-testid="stAppViewContainer"] {
        background-image: linear-gradient(
            180deg in oklab, #0B3D2E 0%, #0B3D2E 82%,
            #B9D8C1 92%, #FFFFFF 100%
        ) !important;
    }
}

</style>
"""

# The story panel on the left. One HTML block with inline styles
# only (st.html sanitises <style> away) — the layout rules that
# need media queries live in _LOGIN_CSS and address .ait-story.

_LOGIN_STORY = """
<div class="ait-story" style="
    box-sizing: border-box;
    height: 100vh;
    display: flex;
    flex-direction: column;
    padding: clamp(30px, 5vh, 58px) clamp(30px, 4.5vw, 64px);
    background: transparent;
    color: #ffffff;
    font-family: inherit;">

  <div style="flex: 1; display: flex; flex-direction: column;
              justify-content: center; max-width: 660px;">

    <div style="display: flex; align-items: center; gap: 12px;">
      <div style="
          flex: 0 0 auto;
          width: 46px; height: 46px; border-radius: 13px;
          display: grid; place-items: center;
          background: rgba(255,255,255,.16);
          border: 1px solid rgba(255,255,255,.26);
          font-family: 'Material Symbols Rounded', sans-serif;
          font-size: 26px; line-height: 1;
          animation: aitFloat 3s ease-in-out infinite;">apartment</div>
      <div>
        <div class="ait-brand" style="font-size: 1.12rem; font-weight: 700;
                    letter-spacing: -.01em;">PeoplePilot</div>
        <div style="font-size: .8rem; opacity: .85;">
          AI-First HR &amp; Payroll Platform</div>
      </div>
    </div>

    <div style="margin-top: clamp(26px, 4vh, 44px);
                font-size: clamp(1.7rem, 2.5vw, 2.4rem);
                font-weight: 800; letter-spacing: -.03em;
                line-height: 1.08;">
      AI does the busywork.<br>You get the time back.
    </div>

    <p style="margin: 18px 0 0 0; font-size: .97rem; line-height: 1.7;
              opacity: .93; max-width: 58ch;">
      PeoplePilot automates the busywork. Offer letters and onboarding
      that took hours now import in minutes (saves ~6 hrs/week), AI
      ranks resumes instantly instead of manual screening (saves ~8
      hrs/week), payroll and payslips calculate automatically with
      zero manual entry (saves ~10 hrs/week), the AI assistant
      answers policy and HR queries on demand (saves ~5 hrs/week),
      and leave and reimbursements move through one-click approvals
      (saves ~4 hrs/week). Altogether that is roughly 33 hours saved
      every week versus spreadsheets and email, and employees handle
      their own payslips, Form 16 and requests themselves.
    </p>

    <div class="ait-story-trust" style="margin-top: clamp(24px, 4vh, 40px);
                padding: 14px 18px; display: flex; gap: 12px;
                flex-wrap: wrap; font-size: .8rem;">
      <span>Secure Sign-In</span>
      <span>&middot; Your Data Stays Private</span>
      <span>&middot; AI-Powered Workflows</span>
    </div>

  </div>
</div>
"""
_LOGIN_HEADER = """
        border-radius: 16px;
        background: linear-gradient(120deg,
            rgba(255,255,255,.2), rgba(165,180,252,.12));
        border: 1px solid rgba(255,255,255,.3);
        box-shadow: 0 12px 28px rgba(20, 18, 75, .2);">
      <div style="
          flex: 0 0 auto; display: grid; place-items: center;
          width: 46px; height: 46px; border-radius: 13px;
          background: rgba(255,255,255,.17);
          font-family: 'Material Symbols Rounded', sans-serif;
          font-size: 25px; line-height: 1;">timer</div>
      <div>
        <div style="
            font-size: .72rem; font-weight: 750; letter-spacing: .1em;
            text-transform: uppercase; opacity: .8;">
          LESS TIME ON MANUAL HR WORK</div>
        <div style="
            margin-top: 4px; font-size: 1.22rem; font-weight: 800;
            letter-spacing: -.015em;">
          Save ~2.5–3 hours every workday with AI</div>
        <div style="margin-top: 4px; font-size: .82rem; line-height: 1.5;
                    opacity: .9;">
          Automate offer letters, resume screening, payroll and everyday
          HR tasks.</div>
      </div>
    </div>

    <div class="ait-story__grid" style="margin-top: clamp(24px, 3.5vh, 36px);
                display: grid; grid-template-columns: 1fr 1fr;
                gap: 13px;">

      <div class="ait-card" style="
          background: #E2F2E7;
          border: 1px solid #C4DEC9;
          border-radius: 15px;
          padding: 13px 15px 14px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="
              font-family: 'Material Symbols Rounded', sans-serif;
              font-size: 17px; line-height: 1;">auto_awesome</span>
          <span style="font-size: .86rem; font-weight: 650;">
            AI offer letters</span>
        </div>
        <div style="margin-top: 5px; font-size: .77rem; line-height: 1.5;
                    opacity: .8;">
          Upload a letter in any format &mdash; AI reads it and
          creates the employee record in minutes.</div>
      </div>

      <div class="ait-card" style="
          background: #E2F2E7;
          border: 1px solid #C4DEC9;
          border-radius: 15px;
          padding: 13px 15px 14px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="
              font-family: 'Material Symbols Rounded', sans-serif;
              font-size: 17px; line-height: 1;">smart_toy</span>
          <span style="font-size: .86rem; font-weight: 650;">
            AIT Assist</span>
        </div>
        <div style="margin-top: 5px; font-size: .77rem; line-height: 1.5;
                    opacity: .8;">
          An AI assistant on every page &mdash; books leave, answers
          policy questions, acts for you.</div>
      </div>

      <div class="ait-card" style="
          background: #E2F2E7;
          border: 1px solid #C4DEC9;
          border-radius: 15px;
          padding: 13px 15px 14px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="
              font-family: 'Material Symbols Rounded', sans-serif;
              font-size: 17px; line-height: 1;">person_search</span>
          <span style="font-size: .86rem; font-weight: 650;">
            AI resume screening</span>
        </div>
        <div style="margin-top: 5px; font-size: .77rem; line-height: 1.5;
                    opacity: .8;">
          Name the skills you need &mdash; AI scores every resume
          and shortlists the best fits.</div>
      </div>

      <div class="ait-card" style="
          background: #E2F2E7;
          border: 1px solid #C4DEC9;
          border-radius: 15px;
          padding: 13px 15px 14px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="
              font-family: 'Material Symbols Rounded', sans-serif;
              font-size: 17px; line-height: 1;">account_balance_wallet</span>
          <span style="font-size: .86rem; font-weight: 650;">
            Payroll on autopilot</span>
        </div>
        <div style="margin-top: 5px; font-size: .77rem; line-height: 1.5;
                    opacity: .8;">
          Annual CTC becomes statutory payroll, payslips and PF
          every month &mdash; automatically.</div>
      </div>

      <div class="ait-card" style="
          background: #E2F2E7;
          border: 1px solid #C4DEC9;
          border-radius: 15px;
          padding: 13px 15px 14px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="
              font-family: 'Material Symbols Rounded', sans-serif;
              font-size: 17px; line-height: 1;">supervised_user_circle</span>
          <span style="font-size: .86rem; font-weight: 650;">
            Self-service for everyone</span>
        </div>
        <div style="margin-top: 5px; font-size: .77rem; line-height: 1.5;
                    opacity: .8;">
          Employees book leave and download payslips themselves
          &mdash; no follow-up emails.</div>
      </div>

      <div class="ait-card" style="
          background: #E2F2E7;
          border: 1px solid #C4DEC9;
          border-radius: 15px;
          padding: 13px 15px 14px;">
        <div style="display: flex; align-items: center; gap: 8px;">
          <span style="
              font-family: 'Material Symbols Rounded', sans-serif;
              font-size: 17px; line-height: 1;">gavel</span>
          <span style="font-size: .86rem; font-weight: 650;">
            Compliance built in</span>
        </div>
        <div style="margin-top: 5px; font-size: .77rem; line-height: 1.5;
                    opacity: .8;">
          PF, TDS, Form 16 and POSH &mdash; handled without the
          paperwork.</div>
      </div>

    </div>
  </div>

  <div class="ait-story-trust" style="margin-top: 22px; padding: 14px 18px;
              display: flex;
              gap: 12px; flex-wrap: wrap; font-size: .76rem;
              border-top: 1px solid #C4DEC9;">
    <span>Hi-Tech City, Hyderabad</span>
    <span>&middot;</span>
    <span>AI-first HR platform</span>
    <span>&middot;</span>
    <span>Minutes, not days</span>
    <span>&middot;</span>
    <span>Your data stays private to your sign-in</span>
  </div>
</div>
"""

_LOGIN_HEADER = """
<div class="ait-login-intro">
  <div style="display: flex; align-items: center; gap: 14px;">
    <div style="
        flex: 0 0 auto; display: grid; place-items: center;
        width: 44px; height: 44px; border-radius: 13px;
        background: #CDE7D5; color: #14532D;
        font-family: 'Material Symbols Rounded', sans-serif;
        font-size: 23px; line-height: 1;">verified_user</div>
    <div>
      <div style="
          color: #14532D; font-size: .72rem; font-weight: 750;
          letter-spacing: .1em; text-transform: uppercase;">
        Secure HR Workspace</div>
      <div style="
          margin-top: 3px; color: #173C2E;
          font-size: 1.55rem; font-weight: 750;
          letter-spacing: -.025em;">
        Welcome Back</div>
      <div style="margin-top: 5px; color: #3F5E4E; font-size: .9rem;">
        Sign in to continue to your AI HR &amp; payroll workspace</div>
    </div>
  </div>
</div>
"""


def show_login_page():
    """Render the single sign-in screen (role is auto-detected).

    Full-screen split: a story panel fills the left of the viewport,
    the sign-in card floats centred on the right.
    """

    # Stylesheet only while signed out — it disappears with this
    # element the moment the user signs in.
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)

    st.html('''<div id="ait-splash">
      <div class="ait-splash-name">PeoplePilot</div>
      <div class="ait-splash-tag">AI-First HR &amp; Payroll Platform</div>
    </div>''')

    story, form = st.columns([1.15, 1])

    with story:

        st.html(_LOGIN_STORY)

    with form:

        st.html(_LOGIN_HEADER)

        with st.container(border=True, key="lift_login"):

            with st.form("login_form"):

                identifier = st.text_input(
                    "Email or username",
                    placeholder="Enter your email or username"
                )

                password = st.text_input(
                    "Password",
                    type="password"
                )

                submitted = st.form_submit_button(
                    "Sign in",
                    width="stretch"
                )

            if submitted:

                user = authenticate_any(identifier, password)

                if user:

                    _sign_in(user)

                else:

                    st.error(
                        "Invalid username, ID, email, or password."
                    )

        st.html(
            '<div class="ait-login-footer">'
            '&copy; AIT aithinkers. All rights reserved.'
            '</div>'
        )
