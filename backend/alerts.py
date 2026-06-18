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
