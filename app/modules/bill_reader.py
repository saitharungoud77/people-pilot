import base64
import datetime
import io
import json
import os
import re

from modules.config import get_secret

from modules.offer_letter import (
    ai_available,
    extract_text
)


# ============================================================
# AI BILL READER
# ============================================================
# Employees already upload a photo or PDF of every bill they want
# reimbursed. This module reads that file and pulls out the fields
# the claim form asks for, so nobody has to retype a receipt.
#
# Photos go to the model as an image; PDFs are read as text first.
# A scanned PDF has no text layer, so it is refused with a clear
# message instead of sending an empty page to the model.
#
# The categories are passed in by the reimbursements screen, which
# keeps one list of categories in the app.

MAX_CHARS = 12000

# Photos are shrunk before they are sent: a 12 MP phone photo adds
# nothing to readability but a lot to the request size.
MAX_IMAGE_SIDE = 1600

JPEG_QUALITY = 85

DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

_IMAGE_TYPES = ("png", "jpg", "jpeg", "webp")

SYSTEM_PROMPT = (
    "You read photographs and PDFs of expense receipts for an Indian "
    "company. Return ONLY a single JSON object. Never guess: use an "
    "empty string for missing text, 0 for missing amounts."
)

USER_PROMPT = """Read this bill and return a JSON object with exactly
these keys:

- vendor: shop, restaurant, airline, cab company or service provider (string)
- bill_no: invoice or receipt number if printed (string)
- date: date on the bill as YYYY-MM-DD (string, "" if absent)
- amount: the final total the employee paid, in INR, including GST (number)
- gst_amount: GST / tax portion if shown separately (number, 0 if absent)
- category: exactly one of {categories}
- description: a short line describing what was bought (string)
- confidence: 0 to 1 estimate of how clearly you could read the bill (number)

Rules:
- amount is the grand total actually paid, not a subtotal.
- If the bill shows a round-off, use the final payable figure.
- Pick the closest category from the list. Use "Other" only if none fit.
- Do not include currency symbols in numbers.
- If the image is unreadable, return amount 0 and confidence 0."""


# ---------------------------------------------------------
# VALUES
# ---------------------------------------------------------

_DATE_FORMATS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%b %d, %Y",
    "%B %d, %Y",
    "%d %B, %Y",
    "%d %b, %Y",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%y"
]


def _iso_date(value):
    """Best-effort conversion of the bill date to YYYY-MM-DD."""

    text = str(value or "").strip()

    if not text:

        return ""

    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", text, flags=re.I)

    for fmt in _DATE_FORMATS:

        try:

            return datetime.datetime.strptime(
                cleaned, fmt
            ).date().isoformat()

        except ValueError:

            continue

    return ""


def _number(value):
    """A money string like '₹ 1,240.50' becomes 1240.5."""

    if isinstance(value, (int, float)):

        return round(float(value), 2)

    text = re.sub(r"[^0-9.]", "", str(value or ""))

    if not text:

        return 0.0

    try:

        return round(float(text), 2)

    except ValueError:

        return 0.0


def match_category(value, categories):
    """Snap a free-text category onto the app's own list."""

    text = str(value or "").strip().lower()

    allowed = list(categories)

    if not allowed:

        return "Other"

    for category in allowed:

        if category.lower() == text:

            return category

    for category in allowed:

        if text and (
            category.lower() in text or text in category.lower()
        ):

            return category

    aliases = {
        # Client entertainment is checked first: "client dinner"
        # must not be read as an ordinary meal.
        "client": "Client entertainment",
        "event": "Client entertainment",
        "cab": "Travel",
        "taxi": "Travel",
        "uber": "Travel",
        "ola": "Travel",
        "flight": "Travel",
        "train": "Travel",
        "fuel": "Travel",
        "petrol": "Travel",
        "mileage": "Travel",
        "restaurant": "Food",
        "lunch": "Food",
        "dinner": "Food",
        "meal": "Food",
        "cafe": "Food",
        "coffee": "Food",
        "hotel": "Accommodation",
        "stay": "Accommodation",
        "lodging": "Accommodation",
        "wifi": "Internet",
        "broadband": "Internet",
        "mobile": "Phone",
        "recharge": "Phone",
        "sim": "Phone",
        "medical": "Medical",
        "hospital": "Medical",
        "pharmacy": "Medical",
        "doctor": "Medical",
        "course": "Training",
        "certification": "Training",
        "stationery": "Office supplies",
        "printer": "Office supplies",
        "paper": "Office supplies"
    }

    for word, category in aliases.items():

        if word in text and category in allowed:

            return category

    return "Other" if "Other" in allowed else allowed[0]


def normalise_bill(raw, categories):
    """Clean a raw model answer into the shape the form uses."""

    raw = raw if isinstance(raw, dict) else {}

    amount = _number(raw.get("amount"))

    gst = _number(raw.get("gst_amount"))

    if gst > amount:

        # GST can never be more than the total; that is a misread.
        gst = 0.0

    try:

        confidence = max(
            0.0, min(1.0, float(raw.get("confidence") or 0))
        )

    except (TypeError, ValueError):

        confidence = 0.0

    return {
        "vendor": str(raw.get("vendor") or "").strip(),
        "bill_no": str(raw.get("bill_no") or "").strip(),
        "date": _iso_date(raw.get("date")),
        "amount": amount,
        "gst_amount": gst,
        "category": match_category(raw.get("category"), categories),
        "description": str(raw.get("description") or "").strip(),
        "confidence": confidence
    }


# ---------------------------------------------------------
# INPUT PREPARATION
# ---------------------------------------------------------

def _image_data_url(data, mime):
    """Encode an image for the vision model, shrinking it first."""

    try:

        from PIL import Image

        image = Image.open(io.BytesIO(data))

        image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))

        if image.mode in ("RGBA", "LA", "P"):

            background = Image.new("RGB", image.size, (255, 255, 255))

            background.paste(
                image,
                mask=image.convert("RGBA").split()[-1]
            )

            image = background

        elif image.mode != "RGB":

            image = image.convert("RGB")

        buffer = io.BytesIO()

        image.save(buffer, "JPEG", quality=JPEG_QUALITY)

        payload = buffer.getvalue()

        return (
            "data:image/jpeg;base64,"
            + base64.b64encode(payload).decode("ascii")
        )

    except Exception:  # noqa: BLE001 - fall back to the raw file

        return (
            f"data:{mime or 'image/jpeg'};base64,"
            + base64.b64encode(data).decode("ascii")
        )


def _extension(name):

    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


# ---------------------------------------------------------
# READ
# ---------------------------------------------------------

def read_bill(uploaded, categories, model=DEFAULT_MODEL):
    """Read one uploaded bill and return normalised claim fields.

    Raises ValueError with a message meant for the employee.
    """

    if uploaded is None:

        raise ValueError("Please upload a photo or PDF of the bill first.")

    name = (getattr(uploaded, "name", "") or "").strip()

    extension = _extension(name)

    data = uploaded.getvalue()

    if not data:

        raise ValueError("That file is empty — please attach the bill again.")

    allowed_categories = list(categories)

    prompt = USER_PROMPT.replace(
        "{categories}",
        ", ".join(f'"{category}"' for category in allowed_categories)
    )

    if extension in _IMAGE_TYPES:

        mime = getattr(uploaded, "type", "") or "image/jpeg"

        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": _image_data_url(data, mime),
                    "detail": "high"
                }
            }
        ]

    elif extension == "pdf":

        text = extract_text(uploaded)

        if len(text.strip()) < 40:

            raise ValueError(
                "This PDF has no readable text (it looks scanned). "
                "Please upload a photo of the bill instead — JPG or PNG."
            )

        content = prompt + "\n\nBill text:\n" + text[:MAX_CHARS]

    else:

        raise ValueError(
            "Please upload the bill as a PDF or a photo (JPG/PNG)."
        )

    from openai import OpenAI

    client = OpenAI(api_key=get_secret("OPENAI_API_KEY"))

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        seed=7,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content}
        ]
    )

    raw = response.choices[0].message.content or "{}"

    try:

        parsed = json.loads(raw)

    except json.JSONDecodeError as error:

        raise ValueError(
            "The AI answer could not be read — please type the "
            "details instead."
        ) from error

    bill = normalise_bill(parsed, allowed_categories)

    if bill["amount"] <= 0:

        raise ValueError(
            "AI could not read the total on this bill. Try a clearer "
            "photo, or type the amount yourself."
        )

    return bill
