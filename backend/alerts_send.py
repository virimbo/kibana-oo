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

import webhooks_store
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


async def post_webhook(payload: dict) -> bool:
    """Post a prebuilt JSON payload to the configured webhook (Mattermost/Slack
    incoming webhook — supports {username, text, attachments}). Returns False
    (never raises) if unconfigured or on error."""
    # Admin-managed active webhook, or DIGEST_WEBHOOK_URL fallback (see webhooks_store).
    url = webhooks_store.active_url()
    if not url or not payload:
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001 — delivery must never break the loop
        logger.error("alerts: webhook post failed: %s", e)
        return False
