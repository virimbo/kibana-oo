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

import logging
from datetime import datetime

import alerts_store

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

    # Still red. Escalation (severity rank increased) bypasses cooldown.
    if SEV_RANK[sev] > SEV_RANK[prev_sev]:
        return "escalation", {"severity": sev, "last_sent_at": now_iso,
                              "last_kind": "escalation",
                              "red_since": prev.get("red_since") or now_iso}

    # Same/lower severity and still red → repeat only after cooldown.
    last_sent = (prev or {}).get("last_sent_at")
    if last_sent:
        elapsed_min = (now - datetime.fromisoformat(last_sent)).total_seconds() / 60
        if elapsed_min >= cooldown_min:
            return "repeated", {"severity": sev, "last_sent_at": now_iso,
                                "last_kind": "repeated", "red_since": prev.get("red_since")}
    return None, {**prev, "severity": sev}  # within cooldown: update sev, no send
