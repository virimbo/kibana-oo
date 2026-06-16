"""RabbitMQ dead-letter-queue monitor.

A non-empty `*.dlq` means messages failed processing and are stuck. We read the
RabbitMQ Management API (`/api/queues`, read-only user), pair each DLQ with its
source queue for context (consumers/state), grade each by depth + whether the
source is being consumed, and keep only lightweight state (first-non-empty time
for age, and an alert-dedup marker) in kibana_oo.db — auto-cleared when a DLQ
drains. A background loop alerts on new/escalated DLQs. Inert until configured.

See docs/rabbitmq-dlq.md.
"""
import asyncio
import logging
from contextlib import closing
from datetime import datetime, timezone

import httpx

import db
import notify
from config import settings

logger = logging.getLogger(__name__)

_latest: dict | None = None  # most recent view, for the badge/endpoint


def is_configured() -> bool:
    return settings.rabbitmq_configured


# ── Fetch + classify ──────────────────────────────────────────────────────────
async def _fetch_queues() -> list[dict]:
    base = settings.rabbitmq_api_url.rstrip("/")
    async with httpx.AsyncClient(timeout=settings.rabbitmq_timeout) as client:
        r = await client.get(
            f"{base}/api/queues",
            auth=(settings.rabbitmq_user, settings.rabbitmq_password),
            headers={"Accept": "application/json"},
            params={"columns": "name,vhost,messages,messages_ready,"
                                "messages_unacknowledged,consumers,state"},
        )
        r.raise_for_status()
        return r.json()


def _severity(depth: int, source_consumers: int | None) -> str:
    """ok | warn | critical. Any message warns; a big pile, or a non-empty DLQ
    whose source queue has no consumer (nothing will drain it), is critical."""
    if depth <= 0:
        return "ok"
    if depth >= settings.rabbitmq_critical_messages or source_consumers == 0:
        return "critical"
    return "warn"


def classify(queues: list[dict]) -> list[dict]:
    """Pick out the DLQs, pair each with its source queue, and grade it."""
    suffix = settings.rabbitmq_dlq_suffix
    by_name = {q.get("name"): q for q in queues}
    out: list[dict] = []
    for q in queues:
        name = q.get("name") or ""
        if not name.endswith(suffix):
            continue
        depth = int(q.get("messages") or 0)
        source_name = name[: -len(suffix)]
        src = by_name.get(source_name)
        src_consumers = int(src["consumers"]) if src and src.get("consumers") is not None else None
        out.append({
            "name": name,
            "vhost": q.get("vhost", "/"),
            "depth": depth,
            "ready": int(q.get("messages_ready") or 0),
            "unacked": int(q.get("messages_unacknowledged") or 0),
            "state": q.get("state"),
            "source": source_name,
            "source_consumers": src_consumers,
            "source_state": (src or {}).get("state"),
            "severity": _severity(depth, src_consumers),
        })
    out.sort(key=lambda d: (-{"critical": 2, "warn": 1, "ok": 0}[d["severity"]], -d["depth"]))
    return out


def _view(dlqs: list[dict]) -> dict:
    nonempty = [d for d in dlqs if d["depth"] > 0]
    crit = sum(1 for d in dlqs if d["severity"] == "critical")
    verdict = "CRITICAL" if crit else ("WARN" if nonempty else "OK")
    if not nonempty:
        headline = f"All {len(dlqs)} DLQs empty — nothing dead-lettered."
    else:
        headline = (f"{len(nonempty)} DLQ{'s' if len(nonempty) != 1 else ''} with messages"
                    + (f" · {crit} critical" if crit else ""))
    return {
        "configured": True,
        "verdict": verdict,
        "count": len(nonempty),
        "total_dlqs": len(dlqs),
        "headline": headline,
        "dlqs": dlqs,
    }


# ── Scan (fetch → classify → state → return view) ─────────────────────────────
async def scan(now: datetime | None = None) -> dict:
    """One pass. Updates lightweight state (age + alert-dedup), alerts on new/
    escalated DLQs, caches and returns the view. Never raises into a request."""
    global _latest
    if not is_configured():
        _latest = {"configured": False}
        return _latest
    now = now or datetime.now(timezone.utc)
    try:
        queues = await _fetch_queues()
    except Exception as e:  # noqa: BLE001
        logger.error(f"RabbitMQ DLQ fetch failed: {e}")
        return _latest or {"configured": True, "error": "could not reach RabbitMQ", "dlqs": [], "count": 0,
                           "verdict": "OK", "total_dlqs": 0, "headline": "RabbitMQ unreachable"}
    dlqs = classify(queues)
    newly = await asyncio.to_thread(_reconcile_state_sync, dlqs, now.isoformat())
    view = _view(dlqs)
    _latest = view
    if newly and settings.rabbitmq_alert_enabled:
        try:
            await _alert(newly)
        except Exception as e:  # noqa: BLE001
            logger.error(f"DLQ alert failed: {e}")
    return view


async def latest() -> dict:
    return _latest if _latest is not None else await scan()


async def run_dlq_monitor_loop() -> None:
    """Background poll so DLQ alerts fire even when nobody's watching."""
    interval = max(0.5, settings.rabbitmq_poll_interval_minutes) * 60
    await asyncio.sleep(15)
    while True:
        if is_configured():
            try:
                await scan()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error(f"DLQ monitor cycle failed: {e}")
        await asyncio.sleep(interval)


async def _alert(newly: list[dict]) -> None:
    lines = ["⚠ RabbitMQ dead-letter queues need attention", ""]
    for d in newly:
        extra = " · source has NO consumer" if d.get("source_consumers") == 0 else ""
        lines.append(f"• {d['name']}: {d['depth']} message(s) [{d['severity'].upper()}]{extra}")
    lines.append("")
    lines.append("Open the dashboard → Dead-letter queues.")
    text = "\n".join(lines)
    await notify.send_webhook(text)
    await asyncio.to_thread(notify.send_email,
                            f"⚠ {len(newly)} RabbitMQ DLQ(s) need attention",
                            "<pre>" + text.replace("<", "&lt;") + "</pre>", text)


# ── Lightweight state (kibana_oo.db) ──────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS dlq_state (
    queue      TEXT PRIMARY KEY,
    first_seen TEXT NOT NULL,   -- when it first went non-empty (→ age)
    alerted    TEXT             -- last severity we alerted on (dedup)
);
"""


def _conn():
    conn = db.connect()
    conn.executescript(_SCHEMA)
    return conn


def _reconcile_state_sync(dlqs: list[dict], now_iso: str) -> list[dict]:
    """Set first_seen for newly non-empty DLQs (→ age), clear drained ones, and
    return the DLQs to alert on (newly non-empty, or escalated to critical)."""
    newly: list[dict] = []
    with closing(_conn()) as conn:
        rows = {r["queue"]: r for r in conn.execute("SELECT queue, first_seen, alerted FROM dlq_state")}
        for d in dlqs:
            name, sev, depth = d["name"], d["severity"], d["depth"]
            row = rows.get(name)
            if depth <= 0:
                if row:
                    conn.execute("DELETE FROM dlq_state WHERE queue = ?", (name,))
                d["first_seen"] = None
                continue
            if row is None:
                conn.execute("INSERT INTO dlq_state (queue, first_seen, alerted) VALUES (?,?,?)",
                             (name, now_iso, sev))
                d["first_seen"] = now_iso
                if sev in ("warn", "critical"):
                    newly.append(d)
            else:
                d["first_seen"] = row["first_seen"]
                if sev == "critical" and row["alerted"] != "critical":
                    newly.append(d)
                if sev != row["alerted"]:
                    conn.execute("UPDATE dlq_state SET alerted = ? WHERE queue = ?", (sev, name))
        conn.commit()
    return newly
