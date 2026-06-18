"""DLQ Intelligence engine.

Reuses rabbitmq_dlq for the base DLQ list, then peeks each non-empty queue
read-only (ackmode=reject_requeue_true — messages are requeued untouched) to read
x-death headers, tracks depth history for a trend, and computes a smart, human
verdict (depth + age + trend + dominant reason) with a recommended action. Inert
unless settings.dlq_intel_enabled. Never raises into a request; never deletes or
consumes a message; never touches FROZEN code.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

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
