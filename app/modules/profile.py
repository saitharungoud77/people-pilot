import datetime
import json

import streamlit as st

from database.connection import create_employee_table, get_connection
from modules.session import signed_in_employee_id
from modules.avatar import (
    render_avatar,
    render_preview,
    process_upload,
    save_avatar,
    clear_avatar,
    get_avatar
)


# ============================================================
# PROFILE (MY DETAILS)
# ============================================================
# Employee self-service screen for personal details. Employment
# fields (ID, department, designation, salary) are read-only and
# managed by HR; personal details (contact, family, etc.) can be
# edited by the employee from the "My details" screen.

_GENDERS = ["", "Male", "Female", "Other"]

_MARITAL_STATUSES = [
    "",
    "Single",
    "Married",
    "Divorced",
    "Widowed"
]

_BLOOD_GROUPS = [
    "",
    "A+",
    "A-",
    "B+",
    "B-",
    "O+",
    "O-",
    "AB+",
    "AB-"
]

_FAMILY_RELATIONS = [
    "",
    "Father",
    "Mother",
    "Spouse",
    "Son",
    "Daughter",
    "Brother",
    "Sister",
    "Other"
]

_PROFILE_FIELDS = """
    employee_id,
    employee_name,
    department,
    designation,
    joining_date,
    location,
    employment_type,
    annual_ctc,
    health_insurance_opted,
    dob,
    gender,
    marital_status,
    blood_group,
    mobile_number,
    personal_email,
    work_email,
    address,
    emergency_contact_name,
    emergency_contact_number,
    family_details,
    bank_name,
    bank_account_number,
    bank_ifsc,
    uan_number
"""

_PROFILE_KEYS = [
    "employee_id",
    "employee_name",
    "department",
    "designation",
    "joining_date",
    "location",
    "employment_type",
    "annual_ctc",
    "health_insurance_opted",
    "dob",
    "gender",
    "marital_status",
    "blood_group",
    "mobile_number",
    "personal_email",
    "work_email",
    "address",
    "emergency_contact_name",
    "emergency_contact_number",
    "family_members",
    "bank_name",
    "bank_account_number",
    "bank_ifsc",
    "uan_number"
]


def _profile_details(employee_id):
    """Full employee record (employment + personal details) as a dict,
    or None when the record does not exist."""

    connection = get_connection()

    try:

        row = connection.execute(
            f"""
            SELECT {_PROFILE_FIELDS}
            FROM employees
            WHERE employee_id = ?
            """,
            (employee_id,)
        ).fetchone()

    finally:

        connection.close()

    if row is None:

        return None

    profile = dict(zip(_PROFILE_KEYS, row))

    raw_family = profile.get("family_members") or ""

    try:

        members = json.loads(raw_family)

    except (TypeError, ValueError):

        members = []

    if not isinstance(members, list):

        members = []

    profile["family_members"] = [
        member
        for member in members
        if isinstance(member, dict)
    ]

    return profile


def _update_profile(
    employee_id,
    employee_name,
    dob,
    gender,
    marital_status,
    blood_group,
    mobile_number,
    personal_email,
    work_email,
    address,
    emergency_contact_name,
    emergency_contact_number,
    family_members
):
    """Persist the employee's self-edited personal details."""

    connection = get_connection()

    try:

        connection.execute(
            """
            UPDATE employees
            SET
                employee_name = ?,
                dob = ?,
                gender = ?,
                marital_status = ?,
                blood_group = ?,
                mobile_number = ?,
                personal_email = ?,
                work_email = ?,
                address = ?,
                emergency_contact_name = ?,
                emergency_contact_number = ?,
                family_details = ?
            WHERE employee_id = ?
            """,
            (
                employee_name,
                dob,
                gender,
                marital_status,
                blood_group,
                mobile_number,
                personal_email,
                work_email,
                address,
                emergency_contact_name,
                emergency_contact_number,
                json.dumps(family_members),
                employee_id
            )
        )

        connection.commit()

    finally:

        connection.close()


def _parse_dob(value):
    """Return a datetime.date from a YYYY-MM-DD string, or None."""

    try:

        return datetime.date.fromisoformat(str(value))

    except (TypeError, ValueError):

        return None


def _select_index(options, current):
    """Index of current in options, else 0."""

    try:

        return options.index(current)

    except (TypeError, ValueError):

        return 0


def _render_photo_editor(employee_id, name):
    """Add, change or remove the photo — right under the picture."""

    # A successful save asks the next run to clear the uploader, so the
    # preview does not reappear after the photo has been stored. This has
    # to happen before the file_uploader widget is created below.
    if st.session_state.pop("profile_photo_reset", None):

        st.session_state.pop("profile_photo_file", None)

    has_photo = get_avatar(employee_id) is not None

    # The uploader is a plain button here rather than Streamlit's dashed
    # drop box; the styling that removes the box is scoped by this key.
    with st.container(key="profile_photo_upload"):

        uploaded = st.file_uploader(
            "Profile photo",
            type=["png", "jpg", "jpeg", "webp", "bmp"],
            key="profile_photo_file",
            label_visibility="collapsed"
        )

    if uploaded is not None:

        # Let the employee frame the shot before saving it: zoom in,
        # slide the picture left/right and up/down, and straighten it.
        zoom = st.slider(
            "Zoom",
            min_value=1.0,
            max_value=3.0,
            value=1.0,
            step=0.05,
            key="profile_photo_zoom",
            help="Zoom in to crop closer to the face."
        )

        move_x = st.slider(
            "Move left / right",
            min_value=-1.0,
            max_value=1.0,
            value=0.0,
            step=0.05,
            key="profile_photo_x"
        )

        move_y = st.slider(
            "Move up / down",
            min_value=-1.0,
            max_value=1.0,
            value=0.0,
            step=0.05,
            key="profile_photo_y"
        )

        rotation = st.select_slider(
            "Straighten",
            options=[-90, 0, 90, 180],
            value=0,
            key="profile_photo_rotation",
            help="Quarter turns, for a sideways phone photo."
        )

        data, error = process_upload(
            uploaded,
            zoom=zoom,
            offset_x=move_x,
            offset_y=move_y,
            rotation=rotation
        )

        if error:

            st.error(error)

        else:

            # A round preview, so this is exactly what the avatar shows.
            render_preview(data, name, size=120)

            if st.button(
                "Save photo",
                key="profile_photo_save",
                icon=":material/save:",
                type="primary",
                width="stretch"
            ):

                save_avatar(employee_id, data)

                st.session_state.profile_photo_reset = True

                st.session_state.profile_saved = (
                    "Your profile photo was updated."
                )

                st.rerun()

    if has_photo:

        if st.button(
            "Remove photo",
            key="profile_photo_remove",
            icon=":material/delete:",
            width="stretch"
        ):

            clear_avatar(employee_id)

            st.session_state.profile_photo_reset = True

            st.session_state.profile_saved = (
                "Your profile photo was removed."
            )

            st.rerun()


def show_my_profile():

    create_employee_table()

    employee_id = signed_in_employee_id()

    if not employee_id:

        return

    profile = _profile_details(employee_id)

    if profile is None:

        st.warning("Profile not found.")

        return

    st.title("My details", icon=":material/badge:")

    st.caption(
        "Your personal and employment information on record. "
        "Employment fields are managed by HR."
    )

    flash = st.session_state.pop("profile_saved", None)

    if flash:

        st.success(flash)

    with st.container(border=True):

        photo_col, info_col = st.columns([1, 3])

        with photo_col:

            render_avatar(
                profile["employee_name"],
                employee_id,
                size=110
            )

            _render_photo_editor(
                employee_id,
                profile["employee_name"]
            )

        with info_col:

            col1, col2 = st.columns(2)

            with col1:

                st.write(f"**Employee ID:** {employee_id}")
                st.write(f"**Department:** {profile['department']}")
                st.write(f"**Designation:** {profile['designation']}")
                st.write(f"**Joining date:** {profile['joining_date']}")

            with col2:

                st.write(f"**Location:** {profile['location']}")
                st.write(
                    f"**Employment type:** {profile['employment_type']}"
                )
                st.write(
                    "**Health insurance opted:** "
                    f"{'Yes' if profile['health_insurance_opted'] else 'No'}"
                )
                st.write(
                    f"**Annual CTC:** "
                    f"₹ {profile['annual_ctc'] / 100000:,.2f} L"
                )

    st.divider()

    if st.session_state.get("profile_edit_mode"):

        _render_profile_editor(profile)

    else:

        _render_profile_view(profile)

    st.caption(
        "To change your password, use the "
        "“Password” control in the sidebar."
    )


# ============================================================
# PROFILE VIEW / EDIT RENDERERS
# ============================================================

def _render_profile_view(profile):

    st.subheader("Personal details", icon=":material/person:")

    col1, col2 = st.columns(2)

    with col1:

        st.write(
            f"**Full name:** {profile['employee_name']}"
        )
        st.write(f"**Date of birth:** {profile['dob'] or '—'}")
        st.write(f"**Gender:** {profile['gender'] or '—'}")
        st.write(
            f"**Marital status:** {profile['marital_status'] or '—'}"
        )
        st.write(f"**Blood group:** {profile['blood_group'] or '—'}")

    with col2:

        st.write(
            f"**Mobile number:** {profile['mobile_number'] or '—'}"
        )
        st.write(
            f"**Personal email:** {profile['personal_email'] or '—'}"
        )
        st.write(
            f"**Professional email:** {profile['work_email'] or '—'}"
        )
        st.write(f"**Address:** {profile['address'] or '—'}")

    st.write(
        "**Emergency contact:** "
        f"{profile['emergency_contact_name'] or '—'} "
        f"({profile['emergency_contact_number'] or '—'})"
    )

    st.write("**Family details:**")

    family = profile.get("family_members") or []

    if not family:

        st.caption("No family details recorded yet.")

    else:

        for member in family:

            relation = member.get("relation") or "Family"

            line = f"{relation} — {member.get('name') or ''}"

            if member.get("occupation"):

                line += f" ({member.get('occupation')})"

            if member.get("phone"):

                line += f" · Phone: {member.get('phone')}"

            st.caption(line)

    st.divider()
    st.subheader("Bank and UAN details", icon=":material/account_balance:")
    bank_col, uan_col = st.columns(2)

    with bank_col:

        st.write(f"**Bank name:** {profile['bank_name'] or '—'}")
        st.write(
            f"**Account number:** "
            f"{profile['bank_account_number'] or '—'}"
        )
        st.write(f"**IFSC code:** {profile['bank_ifsc'] or '—'}")

    with uan_col:

        st.write(f"**UAN:** {profile['uan_number'] or '—'}")
        st.caption("Contact HR to update these details.")

    if st.button(
        "Edit personal details",
        key="profile_start_edit",
        width="content"
    ):

        st.session_state.profile_edit_mode = True

        st.session_state.profile_family = list(
            profile.get("family_members") or []
        )

        st.rerun()


def _render_profile_editor(profile):

    st.subheader(
        "Edit personal details",
        icon=":material/edit_note:"
    )

    st.caption(
        "Fields marked * are required. Your employment record "
        "(Employee ID, department, designation, salary) is managed "
        "by HR and cannot be changed here."
    )

    col1, col2 = st.columns(2)

    with col1:

        st.text_input(
            "Employee name *",
            value=profile["employee_name"],
            key="prof_name",
            width="stretch"
        )

        st.text_input(
            "Mobile number",
            value=profile["mobile_number"] or "",
            key="prof_mobile",
            width="stretch"
        )

        st.text_input(
            "Personal email",
            value=profile["personal_email"] or "",
            key="prof_personal_email",
            width="stretch"
        )

        st.text_input(
            "Professional email (work)",
            value=profile["work_email"] or "",
            key="prof_work_email",
            width="stretch"
        )

    with col2:

        current_dob = _parse_dob(profile["dob"])
        dob_min = datetime.date(1950, 1, 1)
        dob_max = datetime.date.today()
        if current_dob and current_dob < dob_min:
            dob_min = current_dob
        if current_dob and current_dob > dob_max:
            dob_max = current_dob

        st.date_input(
            "Date of birth",
            value=current_dob,
            min_value=dob_min,
            max_value=dob_max,
            key="prof_dob",
            width="stretch"
        )

        st.selectbox(
            "Gender",
            _GENDERS,
            index=_select_index(
                _GENDERS,
                profile["gender"]
            ),
            key="prof_gender",
            width="stretch"
        )

        st.selectbox(
            "Marital status",
            _MARITAL_STATUSES,
            index=_select_index(
                _MARITAL_STATUSES,
                profile["marital_status"]
            ),
            key="prof_marital",
            width="stretch"
        )

        st.selectbox(
            "Blood group",
            _BLOOD_GROUPS,
            index=_select_index(
                _BLOOD_GROUPS,
                profile["blood_group"]
            ),
            key="prof_blood",
            width="stretch"
        )

    st.text_area(
        "Address",
        value=profile["address"] or "",
        key="prof_address",
        height=80
    )

    emergency_col1, emergency_col2 = st.columns(2)

    with emergency_col1:

        st.text_input(
            "Emergency contact name",
            value=profile["emergency_contact_name"] or "",
            key="prof_emergency_name",
            width="stretch"
        )

    with emergency_col2:

        st.text_input(
            "Emergency contact number",
            value=profile["emergency_contact_number"] or "",
            key="prof_emergency_number",
            width="stretch"
        )

    st.divider()

    st.subheader("Family details", icon=":material/family_restroom:")

    family = list(st.session_state.get("profile_family") or [])

    if st.button(
        "Add family member",
        key="profile_add_family",
        width="content"
    ):

        family.append({
            "relation": "",
            "name": "",
            "occupation": "",
            "phone": ""
        })

        st.session_state.profile_family = family

        st.rerun()

    for index, member in enumerate(family):

        row_cols = st.columns([1.1, 1.4, 1.2, 1.2, 0.3])

        with row_cols[0]:

            st.selectbox(
                "Relation",
                _FAMILY_RELATIONS,
                index=_select_index(
                    _FAMILY_RELATIONS,
                    str(member.get("relation") or "")
                ),
                key=f"fam_relation_{index}",
                width="stretch"
            )

        with row_cols[1]:

            st.text_input(
                "Name",
                value=str(member.get("name") or ""),
                key=f"fam_name_{index}",
                width="stretch"
            )

        with row_cols[2]:

            st.text_input(
                "Occupation",
                value=str(member.get("occupation") or ""),
                key=f"fam_occupation_{index}",
                width="stretch"
            )

        with row_cols[3]:

            st.text_input(
                "Phone",
                value=str(member.get("phone") or ""),
                key=f"fam_phone_{index}",
                width="stretch"
            )

        with row_cols[4]:

            if st.button(
                "Delete",
                key=f"fam_remove_{index}",
                width="stretch"
            ):

                family.pop(index)

                st.session_state.profile_family = family

                st.rerun()

    if not family:

        st.caption("No family members added yet.")

    action_col1, action_col2 = st.columns(2)

    with action_col1:

        if st.button(
            "Save changes",
            key="profile_save",
            type="primary",
            width="stretch"
        ):

            _save_profile(profile)

    with action_col2:

        if st.button(
            "Cancel",
            key="profile_cancel",
            width="stretch"
        ):

            st.session_state.pop("profile_edit_mode", None)

            st.session_state.pop("profile_family", None)

            st.rerun()


def _save_profile(profile):

    employee_id = profile["employee_id"]

    employee_name = str(
        st.session_state.get("prof_name") or ""
    ).strip()

    if not employee_name:

        st.error("Employee name cannot be empty.")

        return

    dob_value = st.session_state.get("prof_dob")

    dob = dob_value.isoformat() if dob_value is not None else ""

    family = []

    count = len(st.session_state.get("profile_family") or [])

    for index in range(count):

        member = {
            "relation": str(
                st.session_state.get(f"fam_relation_{index}") or ""
            ).strip(),
            "name": str(
                st.session_state.get(f"fam_name_{index}") or ""
            ).strip(),
            "occupation": str(
                st.session_state.get(f"fam_occupation_{index}") or ""
            ).strip(),
            "phone": str(
                st.session_state.get(f"fam_phone_{index}") or ""
            ).strip()
        }

        if any(member.values()):

            family.append(member)

    try:

        _update_profile(
            employee_id,
            employee_name,
            dob,
            str(st.session_state.get("prof_gender") or ""),
            str(st.session_state.get("prof_marital") or ""),
            str(st.session_state.get("prof_blood") or ""),
            str(st.session_state.get("prof_mobile") or "").strip(),
            str(
                st.session_state.get("prof_personal_email") or ""
            ).strip(),
            str(st.session_state.get("prof_work_email") or "").strip(),
            str(st.session_state.get("prof_address") or "").strip(),
            str(
                st.session_state.get("prof_emergency_name") or ""
            ).strip(),
            str(
                st.session_state.get("prof_emergency_number") or ""
            ).strip(),
            family
        )

    except Exception as exc:

        st.error(f"Unable to save your details: {exc}")

        return

    st.session_state.pop("profile_edit_mode", None)

    st.session_state.pop("profile_family", None)

    st.session_state.profile_saved = (
        "Your personal details were updated successfully."
    )

    st.rerun()