"""Unattended daily digest — for cron / Windows Task Scheduler.

Logs in with a SERVICE-ACCOUNT (DIGEST_KIBANA_USER / DIGEST_KIBANA_PASSWORD),
builds the 'documents needing attention' snapshot, and sends it via the
configured channels (SMTP email and/or webhook). Exit code 0 on success.

Schedule it daily, e.g.:
    docker compose exec -T backend python send_digest.py
"""
import asyncio
import logging
import sys

import notify
from config import settings
from digest import build_digest
from documents import build_pipeline_health
from elastic import keycloak_login

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("send_digest")


async def main() -> int:
    user = settings.digest_kibana_user
    password = settings.digest_kibana_password
    if not user or not password:
        logger.error("DIGEST_KIBANA_USER / DIGEST_KIBANA_PASSWORD not set.")
        return 2
    if not (notify.email_configured() or notify.webhook_configured()):
        logger.error("No delivery channel configured (SMTP_* or DIGEST_WEBHOOK_URL).")
        return 2

    try:
        sid = await keycloak_login(user, password)
    except Exception as e:  # noqa: BLE001
        logger.error(f"Service-account login failed: {e}")
        return 1

    health = await build_pipeline_health(sid, None)
    digest = build_digest(health)
    email_ok = (
        await asyncio.to_thread(notify.send_email, digest["subject"], digest["html"], digest["text"])
        if notify.email_configured() else False
    )
    webhook_ok = await notify.send_webhook(digest["text"]) if notify.webhook_configured() else False

    logger.info(f"Digest: {digest['count']} at risk ({digest['critical']} critical) "
                f"· email={email_ok} webhook={webhook_ok}")
    return 0 if (email_ok or webhook_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
