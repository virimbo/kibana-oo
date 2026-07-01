"""Unified-alerting API. Viewing requires the `alerts` feature grant; every
mutation is super-admin-only. All inputs validated server-side; no secrets are
ever returned. Inert (200 {enabled:false}) when settings.alerts_enabled is off."""
import asyncio
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import alerts
import alerts_send
import alerts_store
from auth import require_feature, require_super
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_VALID_SCOPES = {"global", "category", "env", "card"}
_VALID_CATEGORIES = {"environment", "dlq", "certificate"}
_VALID_THRESHOLDS = {"warn", "critical"}
_VALID_MENTIONS = {"none", "here", "channel"}


def _valid_email(addr: str) -> bool:
    return bool(addr) and len(addr) <= 254 and bool(_EMAIL_RE.match(addr))


class ToggleBody(BaseModel):
    scope: str
    ref: str = ""
    enabled: bool


class ConfigBody(BaseModel):
    recipients: list[str] | None = None
    cooldown_minutes: int | None = None
    severity_threshold: str | None = None
    global_enabled: bool | None = None
    category_thresholds: dict[str, str] | None = None
    mention: str | None = None


class TestBody(BaseModel):
    recipients: list[str] | None = None


@router.get("/status")
async def status(session: dict = Depends(require_feature("alerts"))):
    if not settings.alerts_enabled:
        return {"enabled": False}
    alerts_store.ensure_seeded()
    return {
        "enabled": True,
        "config": alerts_store.get_config(),
        "toggles": alerts_store.list_toggles(),
        "items": [
            {k: it[k] for k in ("card_id", "category", "env", "name", "severity", "status")}
            for it in await alerts._collect()
        ],
    }


@router.get("/history")
async def history(session: dict = Depends(require_feature("alerts"))):
    return {"history": alerts_store.list_history(limit=200)}


@router.get("/audit")
async def audit(session: dict = Depends(require_super)):
    return {"audit": alerts_store.list_audit(limit=200)}


@router.put("/toggle")
async def set_toggle(body: ToggleBody, session: dict = Depends(require_super)):
    if body.scope not in _VALID_SCOPES:
        raise HTTPException(400, "invalid scope")
    if body.scope == "category" and body.ref not in _VALID_CATEGORIES:
        raise HTTPException(400, "invalid category")
    if len(body.ref) > 200:
        raise HTTPException(400, "ref too long")
    alerts_store.set_toggle(body.scope, body.ref, body.enabled,
                            actor=session.get("username"))
    return {"ok": True, "enabled": alerts_store.is_enabled(body.scope, body.ref)}


@router.put("/config")
async def set_config(body: ConfigBody, session: dict = Depends(require_super)):
    actor = session.get("username")
    if body.recipients is not None:
        cleaned = [e.strip() for e in body.recipients if e and e.strip()]
        bad = [e for e in cleaned if not _valid_email(e)]
        if bad:
            raise HTTPException(400, f"invalid email(s): {', '.join(bad[:3])}")
        if len(cleaned) > 50:
            raise HTTPException(400, "too many recipients (max 50)")
        alerts_store.set_config("recipients", cleaned, actor)
    if body.cooldown_minutes is not None:
        if not (1 <= body.cooldown_minutes <= 10080):
            raise HTTPException(400, "cooldown_minutes out of range (1..10080)")
        alerts_store.set_config("cooldown_minutes", body.cooldown_minutes, actor)
    if body.severity_threshold is not None:
        if body.severity_threshold not in _VALID_THRESHOLDS:
            raise HTTPException(400, "invalid threshold")
        alerts_store.set_config("severity_threshold", body.severity_threshold, actor)
    if body.global_enabled is not None:
        alerts_store.set_config("global_enabled", body.global_enabled, actor)
    if body.category_thresholds is not None:
        cleaned = {}
        for cat, val in body.category_thresholds.items():
            if cat not in _VALID_CATEGORIES:
                raise HTTPException(400, f"invalid category: {cat}")
            if val in (None, "", "global"):
                continue  # empty/"global" means: fall back to the global threshold
            if val not in _VALID_THRESHOLDS:
                raise HTTPException(400, f"invalid threshold: {val}")
            cleaned[cat] = val
        alerts_store.set_config("category_thresholds", cleaned, actor)
    if body.mention is not None:
        if body.mention not in _VALID_MENTIONS:
            raise HTTPException(400, "invalid mention")
        alerts_store.set_config("mention", body.mention, actor)
    return {"ok": True, "config": alerts_store.get_config()}


@router.post("/test")
async def send_test(body: TestBody, session: dict = Depends(require_super)):
    """Send a one-off test email to verify SMTP + the recipient addresses, so an
    admin never discovers a broken delivery only during a real incident. Uses the
    given recipients, else the saved config. Never raises on delivery failure —
    reports a structured reason the UI can show in plain Dutch."""
    recips = body.recipients if body.recipients is not None \
        else alerts_store.get_config().get("recipients", [])
    cleaned = [e.strip() for e in (recips or []) if e and e.strip()]
    bad = [e for e in cleaned if not _valid_email(e)]
    if bad:
        raise HTTPException(400, f"invalid email(s): {', '.join(bad[:3])}")
    if not cleaned:
        return {"delivered": False, "reason": "no_recipients", "count": 0}
    if not (settings.smtp_host and settings.smtp_from):
        return {"delivered": False, "reason": "smtp_unconfigured", "count": len(cleaned)}
    subject = "Testmelding — Open Overheid - Monitoring"
    text = ("Dit is een testmelding van Open Overheid - Monitoring (Alerting). "
            "Ontvang je deze mail, dan werkt de e-mailbezorging.")
    html = ("<p>Dit is een <b>testmelding</b> van Open Overheid - Monitoring "
            "(Alerting).</p><p>Ontvang je deze mail, dan werkt de e-mailbezorging "
            "correct en bereiken echte alerts deze ontvanger(s).</p>")
    delivered = await asyncio.to_thread(
        alerts_send.send_email_to, cleaned, subject, html, text)
    return {"delivered": delivered,
            "reason": "sent" if delivered else "send_failed",
            "count": len(cleaned)}
