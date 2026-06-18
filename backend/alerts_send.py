"""Send an alert email to an EXPLICIT recipient list (the admin-managed list),
reusing the configured SMTP settings. Additive — notify.py is left untouched.
Best-effort: returns False (never raises) if unconfigured or on error."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from config import settings

logger = logging.getLogger(__name__)


def send_email_to(recipients: list[str], subject: str, html: str, text: str) -> bool:
    """Blocking SMTP send to `recipients`. Call via asyncio.to_thread."""
    recipients = [r.strip() for r in (recipients or []) if r and r.strip()]
    if not (settings.smtp_host and settings.smtp_from and recipients):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_use_tls:
                server.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001 — delivery must never break the loop
        logger.error("alerts: email to %s failed: %s", recipients, e)
        return False
