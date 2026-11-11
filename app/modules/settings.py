"""Signed-in user profile and appearance settings."""

import json
import re

import streamlit as st

from database.connection import get_connection
from modules.session import employee_details
from modules.theme import DEFAULT_THEME, THEME_PRESETS


_DEFAULT_PREFERENCES = {
    "theme": DEFAULT_THEME,
    "colors": dict(THEME_PRESETS[DEFAULT_THEME]),
}


def _validated_preferences(value):
    """Validate persisted theme settings before they reach the CSS layer."""

    if not isinstance(value, dict):
        raise ValueError("Saved appearance settings must be an object.")

    theme = value.get("theme", DEFAULT_THEME)
    if theme == "Custom":
        theme = DEFAULT_THEME
    if theme not in THEME_PRESETS:
        raise ValueError("Saved appearance settings contain an unknown theme.")

    return {"theme": theme, "colors": dict(THEME_PRESETS[theme])}


def get_user_preferences(username):
    """Load one user's saved appearance preferences."""

    connection = get_connection()
    try:
        row = connection.execute(
            """
            SELECT preferences_json
            FROM user_preferences
            WHERE username = ? COLLATE NOCASE
            """,
            (username,),
        ).fetchone()
    finally:
        connection.close()

    if row is None:
        return {
            "theme": _DEFAULT_PREFERENCES["theme"],
            "colors": dict(_DEFAULT_PREFERENCES["colors"]),
        }

    try:
        stored = json.loads(row[0])
    except json.JSONDecodeError as error:
        raise ValueError("Saved appearance settings are not valid JSON.") from error

    return _validated_preferences(stored)


def save_user_preferences(username, preferences):
    """Save validated appearance settings for the signed-in user."""

    validated = _validated_preferences(preferences)
    connection = get_connection()
    try:
        connection.execute(
            """
            INSERT INTO user_preferences (username, preferences_json)
            VALUES (?, ?)
            ON CONFLICT(username) DO UPDATE SET
                preferences_json = excluded.preferences_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (username, json.dumps(validated, separators=(",", ":"))),
        )
        connection.commit()
    finally:
        connection.close()


def render_settings(user, key="global_settings"):
    """Render the settings popover for a signed-in user."""

    username = user["username"]
    preferences = get_user_preferences(username)
    current_theme = preferences["theme"]
    widget_suffix = re.sub(r"[^A-Za-z0-9_-]", "_", username)

    with st.container(key=key):
        with st.expander(
            "Settings",
            icon=":material/settings:",
            expanded=False,
        ):
            profile_tab, theme_tab = st.tabs(["Profile", "Theme"])

            with profile_tab:
                st.markdown("#### Profile")
                if user["role"] != "hr" and user.get("employee_id"):
                    employee = employee_details(user["employee_id"])
                    if employee:
                        st.write(f"**Name:** {employee['employee_name']}")
                        st.write(f"**Employee ID:** {employee['employee_id']}")
                        st.write(f"**Department:** {employee['department']}")
                        st.write(f"**Role:** {employee['designation']}")
                else:
                    role_label = (
                        "HR administrator"
                        if user["role"] == "hr"
                        else "Employee"
                    )
                    st.write(f"**Role:** {role_label}")

                if user["role"] != "hr" and user.get("employee_id"):
                    if st.button(
                        "Profile",
                        key=f"settings_profile_{widget_suffix}",
                        icon=":material/person:",
                        width="stretch",
                    ):
                        st.session_state.current_page = "profile"
                        st.rerun()

                st.caption(
                    "Manage your password and sign out from your sidebar account panel."
                )

            with theme_tab:
                st.markdown("#### Application Theme")
                st.caption(
                    "Choose one theme to update the dashboard and sidebar. "
                    "Text colors adjust automatically for readability."
                )

                with st.form(f"settings_theme_form_{widget_suffix}"):
                    selected_theme = st.selectbox(
                        "Theme",
                        list(THEME_PRESETS),
                        index=list(THEME_PRESETS).index(current_theme),
                        key=f"settings_theme_{widget_suffix}",
                    )

                    saved = st.form_submit_button(
                        "Apply theme",
                        type="primary",
                        icon=":material/palette:",
                        width="stretch",
                    )

                if saved:
                    save_user_preferences(
                        username,
                        {
                            "theme": selected_theme,
                            "colors": dict(THEME_PRESETS[selected_theme]),
                        },
                    )
                    st.rerun()
