"""Unified alerting engine.

Reads the existing monitors read-only (uptime / rabbitmq_dlq / cert_monitor),
normalizes their verdicts into flat items, filters through an admin toggle
hierarchy + severity threshold, applies a per-card cooldown/dedup/recovery state
machine, renders rich emails and sends them via alerts_send/notify, and records
sends + config in kibana_oo.db. Inert unless settings.alerts_enabled. Never raises
into a request; never touches the FROZEN certificate code (only reads
cert_monitor.latest).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import alerts_send
import alerts_store
import cert_monitor
import rabbitmq_dlq
import uptime
from config import settings

logger = logging.getLogger(__name__)

CATEGORY_ENVIRONMENT = "environment"
CATEGORY_DLQ = "dlq"
CATEGORY_CERT = "certificate"
SEV_RANK = {"ok": 0, "warn": 1, "critical": 2}


# ── env + id helpers ──────────────────────────────────────────────────────────
def _norm_env(env: str | None) -> str:
    e = (env or "").strip().upper()
    if e in ("TST", "TEST", "T"):
        return "TST"
    if e.startswith("ACC"):
        return "ACC"
    if e in ("PROD", "PRODUCTION", "PRD"):
        return "PROD"
    return e or "OTHER"


def _env_from_host(host: str) -> str:
    h = (host or "").lower()
    if "acc" in h:
        return "ACC"
    if "tst" in h or "test" in h:
        return "TST"
    return "PROD"


def _item(category: str, env: str, name: str, severity: str,
          status: str = "", detail: str = "") -> dict:
    env = _norm_env(env)
    return {
        "card_id": f"{category}:{env}:{name}",
        "category": category, "env": env, "name": name,
        "severity": severity, "status": status, "detail": detail,
    }


# ── normalization (monitor verdict → items) ───────────────────────────────────
def _normalize_uptime(snap: dict | None) -> list[dict]:
    if not snap or not snap.get("enabled"):
        return []
    out: list[dict] = []
    for group in snap.get("groups", []):
        for site in group.get("sites", []):
            state = site.get("state")
            severity = {"down": "critical", "degraded": "warn"}.get(state, "ok")
            code = site.get("http_status")
            status = f"HTTP {code} / {str(state).upper()}" if code else str(state).upper()
            out.append(_item(CATEGORY_ENVIRONMENT, site.get("env") or group.get("env"),
                             site.get("name", "?"), severity, status,
                             site.get("error") or ""))
    return out


def _normalize_dlq(snap: dict | None) -> list[dict]:
    if not snap or not snap.get("configured"):
        return []
    out: list[dict] = []
    for d in snap.get("dlqs", []):
        severity = d.get("severity", "ok")
        depth = d.get("depth", 0)
        detail = "source has NO consumer" if d.get("source_consumers") == 0 else ""
        out.append(_item(CATEGORY_DLQ, "PROD", d.get("name", "?"), severity,
                         f"{depth} message(s)", detail))
    return out


def _normalize_cert(certs: list) -> list[dict]:
    out: list[dict] = []
    for c in certs or []:
        grade = (getattr(c, "grade", None) or "").upper()
        severity = {"CRITICAL": "critical", "WARN": "warn"}.get(grade, "ok")
        host = getattr(c, "host", "?")
        days = getattr(c, "days_remaining", None)
        out.append(_item(CATEGORY_CERT, _env_from_host(host), host, severity,
                         f"grade {grade or 'OK'} · {days} days left"))
    return out


# ── toggle hierarchy + severity threshold ─────────────────────────────────────
def _toggles_allow(item: dict) -> bool:
    """global ∧ category ∧ env ∧ card — any explicit OFF suppresses."""
    return (alerts_store.is_enabled("global", "")
            and alerts_store.is_enabled("category", item["category"])
            and alerts_store.is_enabled("env", item["env"])
            and alerts_store.is_enabled("card", item["card_id"]))


def _meets_threshold(severity: str, threshold: str) -> bool:
    return SEV_RANK.get(severity, 0) >= SEV_RANK.get(threshold, 2)


def _eligible(item: dict, threshold: str) -> bool:
    return _meets_threshold(item["severity"], threshold) and _toggles_allow(item)


# ── decision machine (new / repeated / escalation / recovery + cooldown) ──────
def _is_red(severity: str) -> bool:
    return SEV_RANK.get(severity, 0) >= 1  # warn or critical


def _decide(item: dict, prev: dict | None, cooldown_min: int, now: datetime):
    """Pure decision. Returns (kind|None, next_state|None).

    next_state is None only when nothing changed and nothing was sent (a green card
    with no prior state) — the caller persists next_state when it is not None.
    """
    sev = item["severity"]
    prev_sev = (prev or {}).get("severity", "ok")
    red, was_red = _is_red(sev), _is_red(prev_sev)
    now_iso = now.isoformat()

    # Recovery: was red, now green → send once, clear red_since.
    if was_red and not red:
        return "recovery", {"severity": sev, "last_sent_at": now_iso,
                            "last_kind": "recovery", "red_since": None}

    if not red:
        return None, None  # green, stays green → nothing

    # From here the item is red.
    if not was_red:
        return "new", {"severity": sev, "last_sent_at": now_iso,
                       "last_kind": "new", "red_since": now_iso}

    # Still red. The ONLY extra alert per incident is a single escalation when the
    # problem worsens into a higher severity (in practice warn → critical).
    if SEV_RANK[sev] > SEV_RANK[prev_sev]:
        return "escalation", {"severity": sev, "last_sent_at": now_iso,
                              "last_kind": "escalation",
                              "red_since": prev.get("red_since") or now_iso}

    # Still red, severity unchanged → STAY SILENT. Exactly one alert when it breaks,
    # then nothing until it recovers. No time-based repeats (cooldown_min unused).
    return None, {**prev, "severity": sev}


# ── orchestration (collect → decide → send → persist) ─────────────────────────
def _dashboard_url() -> str:
    return settings.frontend_origin.rstrip("/") + "/"


async def _collect() -> list[dict]:
    """Read each monitor's latest verdict (read-only) → flat items. Best-effort:
    a failure in one source must not stop the others."""
    items: list[dict] = []
    try:
        items += _normalize_uptime(await uptime.latest())
    except Exception as e:  # noqa: BLE001
        logger.error("alerts: uptime collect failed: %s", e)
    try:
        items += _normalize_dlq(await rabbitmq_dlq.latest())
    except Exception as e:  # noqa: BLE001
        logger.error("alerts: dlq collect failed: %s", e)
    try:
        certs, _ = cert_monitor.latest()
        items += _normalize_cert(certs)
    except Exception as e:  # noqa: BLE001
        logger.error("alerts: cert collect failed: %s", e)
    return items


async def scan(now: datetime | None = None) -> dict:
    """One evaluation pass. Never raises into a request."""
    if not settings.alerts_enabled:
        return {"enabled": False}
    alerts_store.ensure_seeded()
    cfg = alerts_store.get_config()
    if not cfg["global_enabled"]:
        return {"enabled": True, "global_enabled": False, "sent": 0}
    now = now or datetime.now(timezone.utc)
    items = _collect()
    if asyncio.iscoroutine(items):
        items = await items
    sent = 0
    for item in items:
        try:
            if _is_red(item["severity"]) and not _eligible(item, cfg["severity_threshold"]):
                continue  # red but suppressed by toggle/threshold
            prev = alerts_store.get_state(item["card_id"])
            # Skip recovery work for cards we never alerted on.
            if not _is_red(item["severity"]) and prev is None:
                continue
            kind, nxt = _decide(item, prev, cfg["cooldown_minutes"], now)
            if nxt is not None:
                alerts_store.set_state(item["card_id"], nxt["severity"],
                                       nxt["last_sent_at"], nxt["last_kind"],
                                       nxt["red_since"])
            if kind is None:
                continue
            await _dispatch(item, kind, (prev or {}).get("severity", "ok"),
                            cfg["recipients"])
            sent += 1
        except Exception as e:  # noqa: BLE001 — one bad card never breaks the pass
            logger.error("alerts: card %s failed: %s", item.get("card_id"), e)
    return {"enabled": True, "global_enabled": True, "sent": sent, "checked": len(items)}


async def _dispatch(item: dict, kind: str, prev_severity: str, recipients: list[str]) -> None:
    import alerts_email
    import alerts_mattermost
    url = _dashboard_url()
    subject, html, text = alerts_email.render(item, kind, prev_severity, url)
    delivered = False
    try:
        # Both channels are branded with alerts_send.ALERT_SENDER and leave notify.py
        # untouched. Email → ADMIN-managed recipient list; webhook → a rich
        # Mattermost attachment card (colour bar, lead, field grid, action).
        delivered = await asyncio.to_thread(alerts_send.send_email_to, recipients,
                                            subject, html, text)
        payload = alerts_mattermost.payload(item, kind, prev_severity, url,
                                            alerts_send.ALERT_SENDER)
        await alerts_send.post_webhook(payload)
    except Exception as e:  # noqa: BLE001
        logger.error("alerts: dispatch failed for %s: %s", item["card_id"], e)
    alerts_store.record_history(
        card_id=item["card_id"], category=item["category"], env=item["env"],
        kind=kind, severity=item["severity"], prev_severity=prev_severity,
        recipients=recipients, delivered=delivered, detail=item.get("status", ""))


async def run_alert_loop() -> None:
    """Background poll so alerts fire even when nobody is watching the dashboard."""
    interval = max(10, settings.alerts_interval)
    await asyncio.sleep(12)
    while True:
        if settings.alerts_enabled:
            try:
                await scan()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error("alerts: scan cycle failed: %s", e)
        await asyncio.sleep(interval)
