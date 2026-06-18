"""DLQ Intelligence engine.

Reuses rabbitmq_dlq for the base DLQ list, then peeks each non-empty queue
read-only (ackmode=reject_requeue_true — messages are requeued untouched) to read
x-death headers, tracks depth history for a trend, and computes a smart, human
verdict (depth + age + trend + dominant reason) with a recommended action. Inert
unless settings.dlq_intel_enabled. Never raises into a request; never deletes or
consumes a message; never touches FROZEN code.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import closing
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

import db
import rabbitmq_dlq
from config import settings

logger = logging.getLogger(__name__)

SEV_RANK = {"ok": 0, "warn": 1, "critical": 2}
# RabbitMQ x-death reason → human label.
_REASON_LABEL = {"delivery_limit": "max-retries", "rejected": "rejected",
                 "expired": "expired", "maxlen": "maxlen"}


def _parse_death_time(value) -> datetime | None:
    """x-death 'time' may be an ISO string or epoch seconds. Best-effort → UTC dt."""
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, TypeError):
        return None


def _parse_failure(message: dict, now: datetime | None = None) -> dict:
    """One peeked message → {reason, source, routing, age_seconds}."""
    now = now or datetime.now(timezone.utc)
    headers = ((message or {}).get("properties") or {}).get("headers") or {}
    deaths = headers.get("x-death") or []
    if not deaths:
        return {"reason": "onbekend", "source": "—", "routing": "—", "age_seconds": None}
    d = deaths[0] or {}
    reason = _REASON_LABEL.get(d.get("reason", ""), d.get("reason") or "onbekend")
    rks = d.get("routing-keys") or []
    dt = _parse_death_time(d.get("time"))
    age = int((now - dt).total_seconds()) if dt else None
    return {
        "reason": reason,
        "source": d.get("exchange") or d.get("queue") or "—",
        "routing": (rks[0] if rks else "—"),
        "age_seconds": age,
    }


# ── depth history → trend ─────────────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS dlq_intel_history (
    queue TEXT NOT NULL, ts TEXT NOT NULL, depth INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dlqih_queue ON dlq_intel_history(queue);
"""


def _conn():
    conn = db.connect()
    conn.executescript(_SCHEMA)
    return conn


def _record_depth(queue: str, depth: int) -> None:
    """Append a depth sample and prune to the last dlq_intel_history per queue."""
    now = datetime.now(timezone.utc).isoformat()
    with closing(_conn()) as conn:
        conn.execute("INSERT INTO dlq_intel_history (queue, ts, depth) VALUES (?,?,?)",
                     (queue, now, int(depth)))
        conn.execute(
            "DELETE FROM dlq_intel_history WHERE queue=? AND ts NOT IN "
            "(SELECT ts FROM dlq_intel_history WHERE queue=? ORDER BY ts DESC LIMIT ?)",
            (queue, queue, settings.dlq_intel_history))
        conn.commit()


def _trend(queue: str, current: int) -> str:
    """growing / draining / stable vs the most recent prior sample; unknown if none.
    NB: scan() computes the trend BEFORE recording the new sample, so the most recent
    stored sample is the previous depth."""
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT depth FROM dlq_intel_history WHERE queue=? ORDER BY ts DESC LIMIT 1",
            (queue,)).fetchone()
    if not row:
        return "unknown"
    delta = settings.dlq_intel_grow_delta
    base = row["depth"]
    if current >= base + delta:
        return "growing"
    if current <= base - delta:
        return "draining"
    return "stable"


# ── smart verdict ─────────────────────────────────────────────────────────────
_ACTION = {
    "max-retries": "Poison-message: herstel of skip het falende bericht en controleer de consumer.",
    "expired": "Controleer of de downstream-consumer draait (TTL verlopen voordat verwerkt).",
    "rejected": "Controleer de validatie/het schema van de afzender.",
    "maxlen": "Queue-limiet bereikt: schaal de consumer of verhoog de limiet.",
    "onbekend": "Open de queue en onderzoek de oorzaken.",
}


def _human_age(seconds: int | None) -> str:
    if seconds is None:
        return "?"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}u"
    return f"{seconds // 86400}d"


def _verdict(depth, source_consumers, trend, oldest_age, reasons, source) -> dict:
    """Smart verdict: depth + age + trend + dominant reason → severity/headline/action."""
    if depth <= 0:
        return {"severity": "ok", "headline": "Leeg — niets dead-lettered.",
                "action": "", "trend": trend}
    dominant = reasons[0]["reason"] if reasons else "onbekend"
    parked = oldest_age is not None and oldest_age >= settings.dlq_intel_parked_days * 86400
    critical = (trend == "growing"
                or source_consumers == 0
                or depth >= settings.rabbitmq_critical_messages)
    severity = "critical" if critical else "warn"

    bits = [f"{depth} berichten", f"oudste {_human_age(oldest_age)}"]
    if trend == "growing":
        state = "groeit"
    elif trend == "draining":
        state = "loopt leeg"
    elif parked:
        state = "geparkeerd"
    else:
        state = "stabiel"
    reason_txt = f"vooral {dominant}" + (f" op {source}" if source and source != "—" else "")
    if len({r["reason"] for r in reasons}) > 1 and dominant == "onbekend":
        reason_txt = "gemengde oorzaken"
    icon = "🔴" if severity == "critical" else "🟡"
    label = "Actief probleem" if severity == "critical" else (
        "Geparkeerd" if parked else "Lichte ophoping")
    headline = f"{icon} {label} — {state} · {' · '.join(bits)} · {reason_txt}"
    return {"severity": severity, "headline": headline,
            "action": _ACTION.get(dominant, _ACTION["onbekend"]), "trend": trend}


# ── read-only peek ────────────────────────────────────────────────────────────
async def _peek(vhost: str, name: str) -> tuple[list[dict], list[dict]]:
    """Read-only peek: get messages with ackmode=reject_requeue_true (requeued
    untouched). Returns (sample failures, reason groups). Best-effort → ([],[]) on
    error so a single bad queue never breaks the pass."""
    base = settings.rabbitmq_api_url.rstrip("/")
    url = f"{base}/api/queues/{quote(vhost, safe='')}/{name}/get"
    body = {"count": settings.dlq_intel_peek_max,
            "ackmode": "reject_requeue_true", "encoding": "auto", "truncate": 5000}
    try:
        async with httpx.AsyncClient(timeout=settings.rabbitmq_timeout) as client:
            r = await client.post(url, json=body,
                                  auth=(settings.rabbitmq_user, settings.rabbitmq_password),
                                  headers={"Accept": "application/json"})
            r.raise_for_status()
            messages = r.json()
    except Exception as e:  # noqa: BLE001
        logger.error("dlq_intel: peek %s failed: %s", name, e)
        return [], []
    sample = [_parse_failure(m) for m in (messages or [])]
    counts: dict[str, int] = {}
    for s in sample:
        counts[s["reason"]] = counts.get(s["reason"], 0) + 1
    reasons = sorted(({"reason": k, "count": v} for k, v in counts.items()),
                     key=lambda d: -d["count"])
    return sample, reasons


# ── scan orchestration ────────────────────────────────────────────────────────
_latest: dict | None = None


def is_configured() -> bool:
    return settings.dlq_intel_enabled and settings.rabbitmq_configured


async def scan(now: datetime | None = None) -> dict:
    """One intelligence pass. Reuses rabbitmq_dlq for the base list, peeks each
    non-empty DLQ, records trend, builds smart verdicts. Never raises."""
    global _latest
    if not is_configured():
        _latest = {"configured": False}
        return _latest
    try:
        base = await rabbitmq_dlq.latest()
    except Exception as e:  # noqa: BLE001
        logger.error("dlq_intel: base fetch failed: %s", e)
        return _latest or {"configured": True, "queues": [], "verdict": "OK",
                           "error": "rabbitmq unreachable"}
    dlqs = base.get("dlqs", []) if base.get("configured") is not False else []
    queues: list[dict] = []
    for d in dlqs:
        depth = int(d.get("depth") or 0)
        # Trend BEFORE recording, so the stored sample is the previous depth.
        trend = _trend(d["name"], depth)
        _record_depth(d["name"], depth)
        if depth > 0:
            sample, reasons = await _peek(d.get("vhost", "/"), d["name"])
            peeked = bool(sample)
            oldest = max((s["age_seconds"] for s in sample if s["age_seconds"] is not None),
                         default=None)
        else:
            sample, reasons, peeked, oldest = [], [], True, None
        v = _verdict(depth, d.get("source_consumers"), trend, oldest, reasons,
                     d.get("source") or "")
        queues.append({
            "name": d["name"], "source": d.get("source"), "depth": depth,
            "source_consumers": d.get("source_consumers"),
            "severity": v["severity"], "headline": v["headline"], "action": v["action"],
            "trend": v["trend"], "oldest_age_seconds": oldest,
            "reasons": reasons, "sample": sample, "peeked": peeked,
        })
    queues.sort(key=lambda q: (-SEV_RANK[q["severity"]], -q["depth"]))
    crit = sum(1 for q in queues if q["severity"] == "critical")
    warn = sum(1 for q in queues if q["severity"] == "warn")
    verdict = "CRITICAL" if crit else ("WARN" if warn else "OK")
    _latest = {"configured": True, "verdict": verdict, "crit": crit, "warn": warn,
               "queues": queues}
    return _latest


async def latest() -> dict:
    return _latest if _latest is not None else await scan()


async def run_dlq_intel_loop() -> None:
    """Background poll so the intelligence (and richer alerts) stay warm."""
    interval = max(30, settings.dlq_intel_interval)
    await asyncio.sleep(18)
    while True:
        if is_configured():
            try:
                await scan()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error("dlq_intel: cycle failed: %s", e)
        await asyncio.sleep(interval)
