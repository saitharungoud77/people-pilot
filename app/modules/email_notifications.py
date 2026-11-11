import re
import smtplib
import ssl
from email.message import EmailMessage

from modules.config import get_secret


_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def send_leave_request_email(request):
    """Email a TL the submitted leave request details."""

    recipient = (request.get("manager_email") or "").strip()
    if not _EMAIL_PATTERN.fullmatch(recipient):
        raise ValueError("The TL email address is missing or invalid.")

    host = get_secret("SMTP_HOST")
    username = get_secret("SMTP_USERNAME")
    password = get_secret("SMTP_PASSWORD")
    sender = get_secret("SMTP_FROM_EMAIL", username)
    if not all((host, username, password, sender)):
        raise RuntimeError(
            "Email delivery is not configured. Set SMTP_HOST, "
            "SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM_EMAIL in "
            ".streamlit/secrets.toml or environment variables."
        )

    try:
        port = int(get_secret("SMTP_PORT", "587"))
    except ValueError as error:
        raise RuntimeError("SMTP_PORT must be a valid port number.") from error

    use_ssl = get_secret("SMTP_USE_SSL", "false").lower() in {
        "1", "true", "yes"
    }

    employee_name = request.get("employee_name") or request["employee_id"]
    leave_type = request["leave_type"]
    subject = f"Leave request from {employee_name}"
    body = "\n".join(
        [
            "A new leave request has been submitted and is pending review.",
            "",
            f"Employee: {employee_name}",
            f"Employee ID: {request['employee_id']}",
            f"Leave type: {leave_type}",
            f"Dates: {request['from_date']} to {request['to_date']}",
            f"Working days: {request['days']:g}",
            f"Day portion: {request.get('portion') or 'Full day'}",
            f"Reason: {request['reason']}",
            f"Request ID: {request['id']}",
        ]
    )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = recipient
    message.set_content(body)

    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(
            host,
            port,
            context=context,
            timeout=20
        ) as server:
            server.login(username, password)
            server.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=20) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(username, password)
            server.send_message(message)
