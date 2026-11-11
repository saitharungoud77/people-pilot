import datetime

import streamlit as st

from database.connection import (
    get_connection,
    create_asset_table
)
from modules.leave import list_employees
from modules.notifications import notify_employee
from modules.session import require_employee
from modules.theme import hero


# ============================================================
# ASSETS
# ============================================================
# Company property issued to employees (laptops, phones, ID cards
# and so on). HR keeps the register and assigns/returns items;
# employees see only what is currently with them.

# Plain Material Symbols ligature names - Streamlit does not expand
# ":material/..." shortcodes inside st.html, so the chip is given the
# bare icon name and the Material font draws it.
CATEGORY_ICONS = {
    "Laptop": "laptop_mac",
    "Desktop": "desktop_windows",
    "Monitor": "monitor",
    "Mobile Phone": "phone_iphone",
    "Tablet": "tablet_mac",
    "Headset": "headset_mic",
    "Keyboard & Mouse": "keyboard",
    "ID Card": "badge",
    "Access Card": "credit_card",
    "SIM Card": "sim_card",
    "Furniture": "chair",
    "Other": "inventory_2"
}

ASSET_CATEGORIES = list(CATEGORY_ICONS.keys())

ASSET_CONDITIONS = [
    "New",
    "Good",
    "Fair",
    "Damaged"
]

# Available / Returned both mean "in stock" (never issued, or back
# from an employee). Assigned means it is with someone. Retired is
# out of service for good.
STATUS_COLORS = {
    "Available": "green",
    "Assigned": "violet",
    "Returned": "gray",
    "Retired": "red"
}

ASSET_STATUSES = list(STATUS_COLORS.keys())

# Statuses an asset can be assigned from.
ASSIGNABLE = ("Available", "Returned")

# Every asset chip uses the one accent colour, so a busy register
# stays calm. The list is kept so the calling code stays the same.
_ACCENTS = [
    "#47765E"
]

_FIELDS = [
    "id",
    "asset_tag",
    "category",
    "name",
    "serial_number",
    "condition",
    "status",
    "employee_id",
    "assigned_date",
    "returned_date",
    "notes",
    "created_at"
]


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def _now():
    """Local timestamp, matching the notifications table."""

    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse(value):
    """ISO date string -> date, or None when unparseable."""

    try:

        return datetime.date.fromisoformat(str(value))

    except (TypeError, ValueError):

        return None


def _nice_date(value):
    """'2026-10-01' -> '01 Oct 2026'; anything else passes through."""

    day = _parse(value)

    return day.strftime("%d %b %Y") if day else (str(value) if value else "")


def _accent(index):
    return _ACCENTS[index % len(_ACCENTS)]


def _icon(category):
    return CATEGORY_ICONS.get(category, "inventory_2")


def _employee_names():
    """{employee_id: name} for labelling holders."""

    return {employee_id: name for employee_id, name in list_employees()}


def html_escape(value):
    """Minimal HTML escaping for values dropped into a card."""

    text = str(value)

    for char, replacement in (
        ("&", "&amp;"),
        ("<", "&lt;"),
        (">", "&gt;"),
    ):

        text = text.replace(char, replacement)

    return text


# ---------------------------------------------------------
# DATA
# ---------------------------------------------------------

def create_asset_tables():

    create_asset_table()


def _row_to_dict(row):

    return dict(zip(_FIELDS, row))


def list_assets(employee_id=None, status=None):
    """Assets as dicts, newest first, optionally filtered."""

    query = "SELECT " + ", ".join(_FIELDS) + " FROM assets WHERE 1 = 1"

    params = []

    if employee_id is not None:

        query += " AND employee_id = ?"

        params.append(employee_id)

    if status is not None:

        query += " AND status = ?"

        params.append(status)

    query += " ORDER BY category, name"

    connection = get_connection()

    try:

        rows = connection.execute(query, params).fetchall()

    finally:

        connection.close()

    return [_row_to_dict(row) for row in rows]


def get_asset(asset_id):
    """One asset as a dict, or None."""

    connection = get_connection()

    try:

        row = connection.execute(
            "SELECT " + ", ".join(_FIELDS) + " FROM assets WHERE id = ?",
            (asset_id,)
        ).fetchone()

    finally:

        connection.close()

    return _row_to_dict(row) if row else None


def employee_assets(employee_id):
    """Assets currently with an employee (status 'Assigned')."""

    assets = list_assets(employee_id=employee_id)

    return [asset for asset in assets if asset["status"] == "Assigned"]


def assignable_assets():
    """Assets that can be handed to an employee."""

    return [
        asset for asset in list_assets()
        if asset["status"] in ASSIGNABLE
    ]


def asset_summary():
    """Counts per status, ready for the headline metrics."""

    summary = {status: 0 for status in ASSET_STATUSES}

    for asset in list_assets():

        summary[asset["status"]] = summary.get(asset["status"], 0) + 1

    summary["Total"] = sum(summary[status] for status in ASSET_STATUSES)

    summary["In stock"] = (
        summary["Available"] + summary["Returned"]
    )

    return summary


def add_asset(
    category,
    name,
    serial_number="",
    condition="Good",
    asset_tag="",
    notes=""
):
    """Register a new asset. Returns its id. Auto-numbers the tag."""

    connection = get_connection()

    try:

        cursor = connection.execute(
            """
            INSERT INTO assets
                (
                    asset_tag,
                    category,
                    name,
                    serial_number,
                    condition,
                    status,
                    notes,
                    created_at
                )
            VALUES (?, ?, ?, ?, ?, 'Available', ?, ?)
            """,
            (
                asset_tag.strip(),
                category,
                name.strip(),
                serial_number.strip(),
                condition,
                notes.strip(),
                _now()
            )
        )

        asset_id = cursor.lastrowid

        if not asset_tag.strip():

            connection.execute(
                "UPDATE assets SET asset_tag = ? WHERE id = ?",
                (f"AIT-{asset_id:04d}", asset_id)
            )

        connection.commit()

    finally:

        connection.close()

    return asset_id


def update_asset(asset_id, **values):
    """Update the given columns of one asset."""

    columns = [key for key in values if key in _FIELDS]

    if not columns:

        return

    assignments = ", ".join(f"{column} = ?" for column in columns)

    params = [values[column] for column in columns] + [asset_id]

    connection = get_connection()

    try:

        connection.execute(
            f"UPDATE assets SET {assignments} WHERE id = ?",
            params
        )

        connection.commit()

    finally:

        connection.close()


def assign_asset(
    asset_id,
    employee_id,
    assigned_date=None,
    condition=None,
    notes=None
):
    """Hand an asset to an employee and notify them."""

    assigned_date = assigned_date or datetime.date.today()

    asset = get_asset(asset_id)

    if not asset:

        return

    values = {
        "employee_id": employee_id,
        "status": "Assigned",
        "assigned_date": str(assigned_date),
        "returned_date": "",
    }

    if condition:

        values["condition"] = condition

    if notes is not None:

        values["notes"] = notes

    update_asset(asset_id, **values)

    notify_employee(
        employee_id,
        "Asset assigned to you",
        f"{asset['name']} ({asset['asset_tag']}) — {asset['category']}.",
        category="Asset",
        page="assets"
    )


def return_asset(asset_id, returned_date=None, condition=None, notes=None):
    """Take an asset back from an employee."""

    returned_date = returned_date or datetime.date.today()

    asset = get_asset(asset_id)

    if not asset:

        return

    values = {
        "status": "Returned",
        "returned_date": str(returned_date),
    }

    if condition:

        values["condition"] = condition

    if notes is not None:

        values["notes"] = notes

    update_asset(asset_id, **values)

    if asset["employee_id"]:

        notify_employee(
            asset["employee_id"],
            "Asset returned",
            f"{asset['name']} ({asset['asset_tag']}) was taken back "
            f"on {_nice_date(returned_date)}.",
            category="Asset",
            page="assets"
        )


def retire_asset(asset_id):
    """Mark an asset as permanently out of service."""

    update_asset(
        asset_id,
        status="Retired",
        employee_id="",
        returned_date=str(datetime.date.today())
    )


def restore_asset(asset_id):
    """Put a retired asset back in stock."""

    update_asset(asset_id, status="Available")


def delete_asset(asset_id):
    """Remove an asset from the register."""

    connection = get_connection()

    try:

        connection.execute("DELETE FROM assets WHERE id = ?", (asset_id,))

        connection.commit()

    finally:

        connection.close()


# ---------------------------------------------------------
# RENDERING
# ---------------------------------------------------------

def _summary():
    """Headline figures for the register."""

    summary = asset_summary()

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "Total assets",
            summary["Total"],
            icon=":material/inventory_2:",
            border=True,
            help="Everything on the register."
        )

    with col2:

        st.metric(
            "Assigned",
            summary["Assigned"],
            icon=":material/assignment_ind:",
            border=True,
            help="Currently with an employee."
        )

    with col3:

        st.metric(
            "In stock",
            summary["In stock"],
            icon=":material/warehouse:",
            border=True,
            help="Available (new) plus returned items."
        )

    with col4:

        st.metric(
            "Retired",
            summary["Retired"],
            icon=":material/do_not_disturb_on:",
            border=True,
            help="Out of service."
        )


def _asset_card(asset, index, names, can_manage):
    """One asset as a coloured icon-chip card."""

    tag = asset["asset_tag"] or "—"

    meta_bits = [f"{tag} · {asset['category']}"]

    if asset["serial_number"]:

        meta_bits.append(f"SN {asset['serial_number']}")

    meta_bits.append(asset["condition"])

    meta = " · ".join(meta_bits)

    with st.container(border=True, key=f"lift_asset_{asset['id']}"):

        st.html(
            '<div class="ait-asset">'
            f'<div class="ait-asset__chip" '
            f'style="--asset-accent:{_accent(index)}">'
            f'{_icon(asset["category"])}</div>'
            '<div class="ait-asset__body">'
            f'<div class="ait-asset__name">'
            f'{html_escape(asset["name"])}</div>'
            f'<div class="ait-asset__meta">{html_escape(meta)}</div>'
            '</div>'
            '</div>'
        )

        st.badge(
            asset["status"],
            color=STATUS_COLORS.get(asset["status"], "gray")
        )

        holder = asset["employee_id"]

        if holder and asset["status"] == "Assigned":

            name = names.get(holder, holder)

            st.caption(
                f"{name} ({holder}) · since "
                f"{_nice_date(asset['assigned_date'])}"
            )

        elif holder and asset["status"] == "Returned":

            name = names.get(holder, holder)

            st.caption(
                f"Last with {name} ({holder}) · returned "
                f"{_nice_date(asset['returned_date'])}"
            )

        else:

            st.caption(asset["notes"] or "Not issued to anyone.")

        if can_manage:

            action_col, remove_col = st.columns(2)

            with action_col:

                if asset["status"] == "Assigned":

                    if st.button(
                        "Return",
                        key=f"asset_return_{asset['id']}",
                        icon=":material/assignment_return:",
                        type="tertiary",
                        width="stretch",
                        help="Take this asset back today."
                    ):

                        return_asset(asset["id"])

                        st.session_state.asset_flash = (
                            f"'{asset['name']}' marked as returned."
                        )

                        st.rerun()

                elif asset["status"] == "Retired":

                    if st.button(
                        "Restore",
                        key=f"asset_restore_{asset['id']}",
                        icon=":material/restart_alt:",
                        type="tertiary",
                        width="stretch",
                        help="Put this asset back in stock."
                    ):

                        restore_asset(asset["id"])

                        st.session_state.asset_flash = (
                            f"'{asset['name']}' is back in stock."
                        )

                        st.rerun()

                else:

                    if st.button(
                        "Retire",
                        key=f"asset_retire_{asset['id']}",
                        icon=":material/do_not_disturb_on:",
                        type="tertiary",
                        width="stretch",
                        help="Retire this asset from service."
                    ):

                        retire_asset(asset["id"])

                        st.session_state.asset_flash = (
                            f"'{asset['name']}' retired."
                        )

                        st.rerun()

            with remove_col:

                if st.button(
                    "Remove",
                    key=f"asset_delete_{asset['id']}",
                    icon=":material/delete:",
                    type="tertiary",
                    width="stretch",
                    help="Delete this asset from the register."
                ):

                    delete_asset(asset["id"])

                    st.session_state.asset_flash = (
                        f"'{asset['name']}' removed."
                    )

                    st.rerun()


def _asset_grid(assets, names, can_manage):
    """Three-column grid of asset cards."""

    columns = st.columns(3, gap="small")

    for index, asset in enumerate(assets):

        with columns[index % 3]:

            _asset_card(asset, index, names, can_manage)


def _filters(assets):
    """Category / status / search controls. Returns the visible rows."""

    status_options = ["All"] + ASSET_STATUSES
    category_options = ["All"] + ASSET_CATEGORIES

    col1, col2, col3 = st.columns([2, 2, 3])

    with col1:

        status = st.selectbox(
            "Status",
            status_options,
            key="asset_filter_status"
        )

    with col2:

        category = st.selectbox(
            "Category",
            category_options,
            key="asset_filter_category"
        )

    with col3:

        search = st.text_input(
            "Search",
            key="asset_filter_search",
            placeholder="Name, tag or serial number"
        ).strip().lower()

    visible = []

    for asset in assets:

        if status != "All" and asset["status"] != status:

            continue

        if category != "All" and asset["category"] != category:

            continue

        if search:

            haystack = " ".join(
                str(asset[key])
                for key in ("name", "asset_tag", "serial_number")
            ).lower()

            if search not in haystack:

                continue

        visible.append(asset)

    return visible


# ---------------------------------------------------------
# HR PAGE
# ---------------------------------------------------------

def show_assets_page(go_home=None):
    """HR: the asset register."""

    create_asset_tables()

    today = datetime.date.today()

    hero(
        "Assets",
        "Company property issued to employees — laptops, phones, "
        "ID cards and more.",
        icon="devices",
        badges=[
            ("Managed by HR", "build"),
            ("Assigned & tracked", "assignment_ind"),
            ("Employees see their own", "visibility")
        ]
    )

    if go_home and st.button(
        "← Back to dashboard",
        key="assets_back",
        width="content"
    ):

        go_home()

        st.rerun()

    flash = st.session_state.pop("asset_flash", None)

    if flash:

        st.success(flash, icon=":material/check_circle:")

    assets = list_assets()

    names = _employee_names()

    _summary()

    with st.expander(
        "Add, assign or edit an asset",
        icon=":material/add_circle:",
        type="compact"
    ):

        _manage_panel(assets, names)

    st.space("medium")

    if not assets:

        st.info(
            "No assets on the register yet. Add the first one above.",
            title="Empty register",
            icon=":material/inventory_2:"
        )

        return

    st.caption(
        f"{len(assets)} asset(s) on the register. "
        "Use the filters to narrow the list."
    )

    visible = _filters(assets)

    if not visible:

        st.info(
            "No assets match these filters.",
            icon=":material/search_off:"
        )

        return

    _asset_grid(visible, names, can_manage=True)


def _manage_panel(assets, names):
    """Add / Assign / Edit forms inside one compact expander."""

    action = st.segmented_control(
        "Action",
        ["Add", "Assign", "Edit"],
        default="Add",
        key="asset_action"
    )

    if action == "Assign":

        _assign_form(names)

    elif action == "Edit":

        _edit_form(assets)

    else:

        _add_form()


def _add_form():

    with st.form("asset_add_form", clear_on_submit=True):

        col1, col2 = st.columns(2)

        with col1:

            category = st.selectbox("Category", ASSET_CATEGORIES)

            name = st.text_input(
                "Name / model",
                placeholder="e.g. MacBook Pro 14"
            )

        with col2:

            serial = st.text_input(
                "Serial number",
                placeholder="Optional"
            )

            condition = st.selectbox(
                "Condition",
                ASSET_CONDITIONS,
                index=1
            )

        tag = st.text_input(
            "Asset tag",
            placeholder="Leave blank to auto-number (AIT-0001)"
        )

        notes = st.text_area("Notes", placeholder="Optional")

        saved = st.form_submit_button(
            "Add to register",
            icon=":material/add:",
            type="primary",
            width="stretch"
        )

    if saved:

        if not name.strip():

            st.error("Please enter the asset name.")

        else:

            new_id = add_asset(
                category,
                name,
                serial,
                condition,
                tag,
                notes
            )

            asset = get_asset(new_id)

            st.session_state.asset_flash = (
                f"'{asset['name']}' added as {asset['asset_tag']}."
            )

            st.rerun()


def _assign_form(names):

    assignable = assignable_assets()

    if not assignable:

        st.info(
            "There is nothing in stock to assign. Add an asset first.",
            icon=":material/inventory_2:"
        )

        return

    options = {
        f"{asset['name']} · {asset['asset_tag']} ({asset['category']})":
            asset["id"]
        for asset in assignable
    }

    employee_options = {
        f"{name} ({employee_id})": employee_id
        for employee_id, name in list_employees()
    }

    if not employee_options:

        st.info("Add an employee before assigning assets.")

        return

    with st.form("asset_assign_form"):

        chosen = st.selectbox("Asset", list(options.keys()))

        employee = st.selectbox(
            "Assign to",
            list(employee_options.keys())
        )

        col1, col2 = st.columns(2)

        with col1:

            assigned_date = st.date_input(
                "Assigned on",
                value=datetime.date.today()
            )

        with col2:

            condition = st.selectbox(
                "Condition",
                ASSET_CONDITIONS,
                index=1
            )

        saved = st.form_submit_button(
            "Assign asset",
            icon=":material/assignment_ind:",
            type="primary",
            width="stretch"
        )

    if saved:

        asset_id = options[chosen]

        employee_id = employee_options[employee]

        asset = get_asset(asset_id)

        assign_asset(
            asset_id,
            employee_id,
            assigned_date,
            condition
        )

        st.session_state.asset_flash = (
            f"'{asset['name']}' assigned to "
            f"{names.get(employee_id, employee_id)}."
        )

        st.rerun()


def _edit_form(assets):

    if not assets:

        return

    options = {
        f"{asset['name']} · {asset['asset_tag']}": asset["id"]
        for asset in assets
    }

    chosen = st.selectbox(
        "Asset to edit",
        list(options.keys()),
        key="asset_edit_pick"
    )

    asset = get_asset(options[chosen])

    if not asset:

        return

    with st.form(f"asset_edit_form_{asset['id']}"):

        col1, col2 = st.columns(2)

        with col1:

            category = st.selectbox(
                "Category",
                ASSET_CATEGORIES,
                index=(
                    ASSET_CATEGORIES.index(asset["category"])
                    if asset["category"] in ASSET_CATEGORIES
                    else len(ASSET_CATEGORIES) - 1
                )
            )

            name = st.text_input("Name / model", value=asset["name"])

        with col2:

            serial = st.text_input(
                "Serial number",
                value=asset["serial_number"]
            )

            condition = st.selectbox(
                "Condition",
                ASSET_CONDITIONS,
                index=(
                    ASSET_CONDITIONS.index(asset["condition"])
                    if asset["condition"] in ASSET_CONDITIONS
                    else 1
                )
            )

        tag = st.text_input("Asset tag", value=asset["asset_tag"])

        status = st.selectbox(
            "Status",
            ASSET_STATUSES,
            index=(
                ASSET_STATUSES.index(asset["status"])
                if asset["status"] in ASSET_STATUSES
                else 0
            )
        )

        notes = st.text_area("Notes", value=asset["notes"])

        saved = st.form_submit_button(
            "Save changes",
            icon=":material/save:",
            type="primary",
            width="stretch"
        )

    if saved:

        if not name.strip():

            st.error("Please enter the asset name.")

            return

        update_asset(
            asset["id"],
            category=category,
            name=name.strip(),
            serial_number=serial.strip(),
            condition=condition,
            asset_tag=tag.strip(),
            status=status,
            notes=notes.strip()
        )

        st.session_state.asset_flash = f"'{name.strip()}' updated."

        st.rerun()


# ---------------------------------------------------------
# EMPLOYEE PAGE
# ---------------------------------------------------------

def show_my_assets():
    """Employee: read-only list of the assets issued to them."""

    employee = require_employee()

    if employee is None:

        return

    employee_id = employee["employee_id"]

    hero(
        "My assets",
        "Company property issued to you.",
        icon="devices",
        badges=[
            ("Read-only", "lock"),
            ("Company property", "inventory_2"),
            ("Contact HR to return", "support_agent")
        ]
    )

    assets = employee_assets(employee_id)

    if not assets:

        st.info(
            "No company assets are currently issued to you.",
            title="Nothing issued",
            icon=":material/inventory_2:"
        )

        return

    categories = {asset["category"] for asset in assets}

    earliest = min(
        (
            _parse(asset["assigned_date"])
            for asset in assets
        ),
        default=None
    )

    col1, col2, col3 = st.columns(3)

    with col1:

        st.metric(
            "Assets with you",
            len(assets),
            icon=":material/inventory_2:",
            border=True,
            help="Company property currently issued to you."
        )

    with col2:

        st.metric(
            "Categories",
            len(categories),
            icon=":material/category:",
            border=True,
            help="Different kinds of asset you hold."
        )

    with col3:

        st.metric(
            "Held since",
            _nice_date(earliest) if earliest else "—",
            icon=":material/event:",
            border=True,
            help="When your longest-held asset was issued."
        )

    st.space("medium")

    st.caption(
        f"{len(assets)} asset(s) issued to you. "
        "These are company property — please keep them safe."
    )

    names = _employee_names()

    _asset_grid(assets, names, can_manage=False)
