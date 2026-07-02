"""Notification delivery for the digest: SMTP email and/or a Slack/Teams/Discord/
generic incoming webhook. Both are best-effort and non-fatal — a delivery failure
returns False, it never raises into the request."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

import httpx

import webhooks_store
from config import settings

logger = logging.getLogger(__name__)


def email_configured() -> bool:
    return bool(settings.smtp_host and settings.smtp_from and settings.digest_recipient_list)


def webhook_configured() -> bool:
    # active_url() = the admin-managed active webhook, or DIGEST_WEBHOOK_URL fallback.
    return bool(webhooks_store.active_url())


def send_email(subject: str, html: str, text: str) -> bool:
    """Send the digest as a multipart (plain + HTML) email. Blocking — call via
    asyncio.to_thread. Returns False (not raises) if unconfigured or on error."""
    if not email_configured():
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(settings.digest_recipient_list)
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
    except Exception as e:  # noqa: BLE001 — delivery must never break the request
        logger.error(f"Digest email failed: {e}")
        return False


async def send_webhook(text: str) -> bool:
    """Post the digest text to the configured webhook. Uses the `text` field,
    which Slack, Teams (via a workflow) and Discord all accept."""
    if not webhook_configured():
        return False
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhooks_store.active_url(), json={"text": text})
            resp.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        logger.error(f"Digest webhook failed: {e}")
        return False
