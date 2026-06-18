"""Alert delivery: email to an EXPLICIT recipient list (the admin-managed list)
and a Mattermost-compatible webhook — both branded with a fixed sender identity.
Additive — notify.py is left untouched. Best-effort: every function returns False
(never raises) if unconfigured or on error."""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from config import settings

logger = logging.getLogger(__name__)

# Display name the alerts appear to come from, on every channel (email From +
# Mattermost webhook username). The email address stays SMTP_FROM.
ALERT_SENDER = "FB-OO:Anton"


def send_email_to(recipients: list[str], subject: str, html: str, text: str) -> bool:
    """Blocking SMTP send to `recipients`. Call via asyncio.to_thread."""
    recipients = [r.strip() for r in (recipients or []) if r and r.strip()]
    if not (settings.smtp_host and settings.smtp_from and recipients):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((ALERT_SENDER, settings.smtp_from))
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


async def send_webhook_as(text: str, username: str = ALERT_SENDER) -> bool:
    """Post the alert to the configured webhook with a sender username override.
    The {"text", "username"} payload is accepted by Mattermost (and Slack) incoming
    webhooks. Returns False (never raises) if unconfigured or on error."""
    url = settings.digest_webhook_url
    if not url:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"text": text, "username": username})
            resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001 — delivery must never break the loop
        logger.error("alerts: webhook post failed: %s", e)
        return False
