"""Admin-managed Mattermost webhooks (Beheer → Webhooks). Super-admin only.

Lets an admin keep several Mattermost incoming-webhook URLs side by side
(e.g. ACC / TST / PROD) and switch the ACTIVE one — the one alerts post to —
without editing .env or redeploying. Full URLs are never returned (masked); the
`test` endpoint posts a real message so an admin can verify a webhook before
making it live.
"""
import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import webhooks_store
from alerts_send import ALERT_SENDER
from auth import require_super

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/webhooks")

_URL_RE = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)
_MAX_URL = 2048
_MAX_LABEL = 40


def _clean_label(label: str | None) -> str:
    label = (label or "").strip()
    if not (1 <= len(label) <= _MAX_LABEL):
        raise HTTPException(400, f"label must be 1..{_MAX_LABEL} characters")
    return label


def _clean_url(url: str | None) -> str:
    url = (url or "").strip()
    if len(url) > _MAX_URL or not _URL_RE.match(url):
        raise HTTPException(400, "url must be a valid http(s) URL")
    return url


class WebhookBody(BaseModel):
    label: str
    url: str


class WebhookUpdate(BaseModel):
    label: str | None = None
    url: str | None = None


@router.get("")
async def list_webhooks(session: dict = Depends(require_super)):
    return {
        "webhooks": webhooks_store.list_webhooks(),
        "fallback_configured": webhooks_store.fallback_configured(),
    }


@router.post("")
async def create_webhook(body: WebhookBody, session: dict = Depends(require_super)):
    label = _clean_label(body.label)
    url = _clean_url(body.url)
    wh = webhooks_store.add_webhook(label, url, actor=session.get("username"))
    return {"ok": True, "webhook": wh}


@router.put("/{wid}")
async def update_webhook(wid: int, body: WebhookUpdate, session: dict = Depends(require_super)):
    label = _clean_label(body.label) if body.label is not None else None
    url = _clean_url(body.url) if body.url is not None else None
    wh = webhooks_store.update_webhook(wid, label=label, url=url, actor=session.get("username"))
    if wh is None:
        raise HTTPException(404, "webhook not found")
    return {"ok": True, "webhook": wh}


@router.delete("/{wid}")
async def delete_webhook(wid: int, session: dict = Depends(require_super)):
    if not webhooks_store.delete_webhook(wid):
        raise HTTPException(404, "webhook not found")
    return {"ok": True}


@router.post("/{wid}/activate")
async def activate_webhook(wid: int, session: dict = Depends(require_super)):
    wh = webhooks_store.set_active(wid, actor=session.get("username"))
    if wh is None:
        raise HTTPException(404, "webhook not found")
    return {"ok": True, "webhook": wh}


@router.post("/{wid}/test")
async def test_webhook(wid: int, session: dict = Depends(require_super)):
    """Post a real test message to this webhook so the admin can confirm it works
    before activating it. Best-effort: reports the outcome, never raises."""
    wh = webhooks_store.get_webhook(wid, reveal=True)
    if wh is None:
        raise HTTPException(404, "webhook not found")
    payload = {
        "username": ALERT_SENDER,
        "text": (f":white_check_mark: **Testbericht** vanuit Beheer → Webhooks "
                 f"(**{wh['label']}**). Zie je dit in Mattermost, dan werkt de webhook."),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(wh["url"], json=payload)
        return {"ok": resp.is_success, "status": resp.status_code}
    except Exception as e:  # noqa: BLE001 — a failed test must not raise
        logger.warning("webhook test failed (id=%s): %s", wid, e)
        return {"ok": False, "error": str(e)[:200]}
