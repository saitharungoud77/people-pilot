"""Employee profile pictures.

The picture is stored as a small, square JPEG in the ``employees.photo``
column (a BLOB). Keeping it in the database means a photo travels with a
database backup and never leaves an orphan file behind when an employee
leaves or is deleted.

Pillow does the work: the uploaded image is rotated the right way up
(EXIF), cropped square from the centre and resized, then compressed.
The sidebar and the "My details" screen draw it as a circle.
"""

import base64
import io

import streamlit as st

from database.connection import get_connection


# ============================================================
# SETTINGS
# ============================================================

# Stored pictures are cropped square and scaled to this many pixels
# per side, which is plenty for an avatar yet keeps the file small.
PHOTO_SIZE = 400

# Upload formats we accept.
ALLOWED_TYPES = ["png", "jpg", "jpeg", "webp", "bmp"]

# Colours used for the initials circle when there is no photo.
_PALETTE = [
    "#16856B",
    "#116B57",
    "#47765E",
    "#4E9A83",
    "#B45309",
    "#B91C1C",
    "#76528B"
]


# ============================================================
# HELPERS
# ============================================================

def initials(name):
    """Up to two initials for the fallback circle."""

    parts = [part for part in str(name or "").split() if part]

    if not parts:

        return "?"

    if len(parts) == 1:

        return parts[0][:2].upper()

    return (parts[0][0] + parts[-1][0]).upper()


def _colour(name):
    """A stable colour per person, so their circle rarely changes."""

    total = sum(ord(character) for character in str(name or "?"))

    return _PALETTE[total % len(_PALETTE)]


# ============================================================
# IMAGE PROCESSING
# ============================================================

def process_upload(
    uploaded_file,
    zoom=1.0,
    offset_x=0.0,
    offset_y=0.0,
    rotation=0
):
    """Turn an uploaded image into avatar bytes.

    Returns ``(jpeg_bytes, error)``. The image is flipped the right way
    up, rotated, then cropped square and resized to ``PHOTO_SIZE``.

    The optional values come from the "My details" screen so the
    employee can frame the shot themselves:

    ``zoom``     1.0 fits the shorter side; larger zooms in.
    ``offset_x`` -1.0 (left) .. 1.0 (right) of the spare width.
    ``offset_y`` -1.0 (up) .. 1.0 (down) of the spare height.
    ``rotation`` degrees clockwise, in quarter turns.

    Called with no adjustments it behaves exactly like before: a plain
    centre crop.
    """

    try:

        from PIL import Image, ImageOps

    except ImportError:

        return None, (
            "Pillow is not installed. Run `pip install pillow` and "
            "restart the app."
        )

    try:

        data = uploaded_file.getvalue()

        image = Image.open(io.BytesIO(data))

        image = ImageOps.exif_transpose(image)

    except Exception as exc:

        return None, f"Could not read that image ({exc})."

    # Flatten any transparency onto white before saving as JPEG.
    if image.mode in ("RGBA", "LA", "P"):

        image = image.convert("RGBA")

        background = Image.new("RGB", image.size, (255, 255, 255))

        background.paste(image, mask=image.split()[-1])

        image = background

    else:

        image = image.convert("RGB")

    # Straighten the picture first, so the crop sees the final shape.
    # Only whole quarter turns are offered, so no empty corners appear.
    try:

        angle = int(round(float(rotation or 0))) % 360

    except (TypeError, ValueError):

        angle = 0

    if angle:

        image = image.rotate(
            angle,
            resample=Image.Resampling.BICUBIC,
            expand=True
        )

    width, height = image.size

    try:

        zoom = float(zoom)

    except (TypeError, ValueError):

        zoom = 1.0

    zoom = max(1.0, zoom)

    # The square we keep. Zooming in makes it smaller than the shorter
    # side, which is what frees up room to pan the picture around.
    side = min(width, height) / zoom

    side = max(1.0, min(side, float(min(width, height))))

    spare_x = (width - side) / 2
    spare_y = (height - side) / 2

    try:

        offset_x = float(offset_x)
        offset_y = float(offset_y)

    except (TypeError, ValueError):

        offset_x = offset_y = 0.0

    centre_x = width / 2 + offset_x * spare_x
    centre_y = height / 2 + offset_y * spare_y

    left = centre_x - side / 2
    top = centre_y - side / 2

    # Never crop past the edge of the picture.
    left = min(max(left, 0.0), width - side)
    top = min(max(top, 0.0), height - side)

    box = (
        int(round(left)),
        int(round(top)),
        int(round(left + side)),
        int(round(top + side))
    )

    image = image.crop(box)

    image = image.resize(
        (PHOTO_SIZE, PHOTO_SIZE),
        Image.Resampling.LANCZOS
    )

    buffer = io.BytesIO()

    image.save(buffer, format="JPEG", quality=88, optimize=True)

    return buffer.getvalue(), ""


# ============================================================
# STORAGE
# ============================================================

def save_avatar(employee_id, data):
    """Store the photo bytes (or None to clear it)."""

    connection = get_connection()

    try:

        connection.execute(
            "UPDATE employees SET photo = ? WHERE employee_id = ?",
            (data, employee_id)
        )

        connection.commit()

    finally:

        connection.close()


def clear_avatar(employee_id):
    """Remove the employee's photo."""

    save_avatar(employee_id, None)


def get_avatar(employee_id):
    """The stored JPEG bytes for an employee, or None."""

    if not employee_id:

        return None

    connection = get_connection()

    try:

        row = connection.execute(
            "SELECT photo FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()

    finally:

        connection.close()

    if not row or row[0] is None:

        return None

    return bytes(row[0])


def data_uri(employee_id):
    """The photo as a data URI, or None when there is no photo."""

    data = get_avatar(employee_id)

    if not data:

        return None

    return "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")


# ============================================================
# RENDERING
# ============================================================

def avatar_html(name, employee_id, size=64):
    """A circular avatar as HTML — the photo, or coloured initials."""

    uri = data_uri(employee_id)

    if uri:

        inner = (
            f'<img src="{uri}" alt="" '
            'style="width:100%;height:100%;object-fit:cover;'
            'display:block;">'
        )

    else:

        inner = (
            '<span style="display:flex;align-items:center;'
            'justify-content:center;width:100%;height:100%;'
            'color:#ffffff;font-weight:700;'
            f'font-size:{max(12, size // 3)}px;">{initials(name)}</span>'
        )

    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;'
        f'overflow:hidden;background:{_colour(name)};'
        'box-shadow:0 0 0 3px rgba(22,133,107,0.2);">'
        f'{inner}</div>'
    )


def preview_html(data, name="", size=120):
    """A circular preview built from raw image bytes.

    Used on "My details" while the employee zooms and moves the picture
    around, so they see exactly how the round avatar will look before
    saving it.
    """

    if data:

        uri = (
            "data:image/jpeg;base64,"
            + base64.b64encode(data).decode("ascii")
        )

        inner = (
            f'<img src="{uri}" alt="" '
            'style="width:100%;height:100%;object-fit:cover;'
            'display:block;">'
        )

    else:

        inner = ""

    return (
        f'<div style="width:{size}px;height:{size}px;border-radius:50%;'
        f'overflow:hidden;background:{_colour(name)};'
        'box-shadow:0 0 0 3px rgba(22,133,107,0.2);">'
        f'{inner}</div>'
    )


def render_preview(data, name="", size=120):
    """Draw a round preview of raw image bytes."""

    st.markdown(
        preview_html(data, name, size),
        unsafe_allow_html=True
    )


def render_avatar(name, employee_id, size=64):
    """Draw the avatar (photo or initials) with ``st.markdown``."""

    st.markdown(
        avatar_html(name, employee_id, size),
        unsafe_allow_html=True
    )
