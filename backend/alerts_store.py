"""SQLite persistence for unified alerting (shared kibana_oo.db via db.py).

Tables: alert_config (singleton key/value), alert_toggles (only rows that are OFF
exist — absence means ON), alert_state (per-card cooldown/recovery memory),
alert_history (admin-visible send log), alert_audit (config-change trail).
"""
from __future__ import annotations

import json
from contextlib import closing
from datetime import datetime, timezone

import db
from config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_config (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS alert_toggles (
    scope      TEXT NOT NULL,   -- global | category | env | card
    ref        TEXT NOT NULL,   -- '' | environment/dlq/certificate | PROD/ACC/TST | card_id
    enabled    INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT,
    PRIMARY KEY (scope, ref)
);
CREATE TABLE IF NOT EXISTS alert_state (
    card_id      TEXT PRIMARY KEY,
    severity     TEXT NOT NULL,
    last_sent_at TEXT,
    last_kind    TEXT,
    red_since    TEXT
);
CREATE TABLE IF NOT EXISTS alert_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            TEXT NOT NULL,
    card_id       TEXT NOT NULL,
    category      TEXT, env TEXT, kind TEXT,
    severity      TEXT, prev_severity TEXT,
    recipients    TEXT, delivered INTEGER, detail TEXT
);
CREATE TABLE IF NOT EXISTS alert_audit (
    ts TEXT NOT NULL, actor TEXT, action TEXT NOT NULL, target TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS alert_meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn():
    conn = db.connect()
    conn.executescript(_SCHEMA)
    return conn


def ensure_seeded() -> None:
    """Idempotent first-run seed of config defaults from settings."""
    with closing(_conn()) as conn:
        if conn.execute("SELECT value FROM alert_meta WHERE key='seeded'").fetchone():
            return
        seed = {
            "global_enabled": "true",
            "cooldown_minutes": str(settings.alerts_cooldown_minutes),
            "severity_threshold": settings.alerts_default_threshold,
            "recipients": json.dumps(settings.alerts_recipient_seed_list),
        }
        for k, v in seed.items():
            conn.execute("INSERT OR IGNORE INTO alert_config (key, value) VALUES (?,?)", (k, v))
        conn.execute("INSERT OR REPLACE INTO alert_meta (key, value) VALUES ('seeded', ?)", (_now(),))
        conn.commit()


def get_config() -> dict:
    with closing(_conn()) as conn:
        rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM alert_config")}
    return {
        "global_enabled": (rows.get("global_enabled", "true") == "true"),
        "cooldown_minutes": int(rows.get("cooldown_minutes") or settings.alerts_cooldown_minutes),
        "severity_threshold": rows.get("severity_threshold") or settings.alerts_default_threshold,
        "recipients": json.loads(rows.get("recipients") or "[]"),
        "category_thresholds": json.loads(rows.get("category_thresholds") or "{}"),
        "mention": rows.get("mention") or "none",
    }


def set_config(key: str, value, actor: str | None) -> None:
    stored = json.dumps(value) if key in ("recipients", "category_thresholds") else (
        "true" if (key == "global_enabled" and value) else
        "false" if key == "global_enabled" else str(value))
    with closing(_conn()) as conn:
        conn.execute("INSERT OR REPLACE INTO alert_config (key, value) VALUES (?,?)", (key, stored))
        conn.execute("INSERT INTO alert_audit (ts, actor, action, target, detail) VALUES (?,?,?,?,?)",
                     (_now(), actor, "set_config", key, str(value)))
        conn.commit()


def is_enabled(scope: str, ref: str) -> bool:
    """Absent toggle = ON. Only explicit OFF rows suppress."""
    with closing(_conn()) as conn:
        row = conn.execute("SELECT enabled FROM alert_toggles WHERE scope=? AND ref=?",
                           (scope, ref)).fetchone()
    return True if row is None else bool(row["enabled"])


def set_toggle(scope: str, ref: str, enabled: bool, actor: str | None) -> None:
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO alert_toggles (scope, ref, enabled, updated_at, updated_by) "
            "VALUES (?,?,?,?,?)", (scope, ref, 1 if enabled else 0, _now(), actor))
        conn.execute("INSERT INTO alert_audit (ts, actor, action, target, detail) VALUES (?,?,?,?,?)",
                     (_now(), actor, "set_toggle", f"{scope}:{ref}",
                      "enabled" if enabled else "disabled"))
        conn.commit()


def list_toggles() -> list[dict]:
    with closing(_conn()) as conn:
        return [dict(r) for r in conn.execute(
            "SELECT scope, ref, enabled, updated_at, updated_by FROM alert_toggles")]


def get_state(card_id: str) -> dict | None:
    with closing(_conn()) as conn:
        row = conn.execute("SELECT * FROM alert_state WHERE card_id=?", (card_id,)).fetchone()
    return dict(row) if row else None


def set_state(card_id: str, severity: str, last_sent_at: str | None,
              last_kind: str | None, red_since: str | None) -> None:
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO alert_state (card_id, severity, last_sent_at, last_kind, red_since) "
            "VALUES (?,?,?,?,?)", (card_id, severity, last_sent_at, last_kind, red_since))
        conn.commit()


def record_history(*, card_id, category, env, kind, severity, prev_severity,
                   recipients, delivered, detail) -> None:
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO alert_history (ts, card_id, category, env, kind, severity, "
            "prev_severity, recipients, delivered, detail) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (_now(), card_id, category, env, kind, severity, prev_severity,
             json.dumps(recipients), 1 if delivered else 0, detail))
        conn.commit()


def list_history(limit: int = 100) -> list[dict]:
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT ts, card_id, category, env, kind, severity, prev_severity, "
            "recipients, delivered, detail FROM alert_history ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["recipients"] = json.loads(d["recipients"] or "[]")
        out.append(d)
    return out


def record_audit(actor: str | None, action: str, target: str, detail: str) -> None:
    with closing(_conn()) as conn:
        conn.execute("INSERT INTO alert_audit (ts, actor, action, target, detail) VALUES (?,?,?,?,?)",
                     (_now(), actor, action, target, detail))
        conn.commit()


def list_audit(limit: int = 100) -> list[dict]:
    with closing(_conn()) as conn:
        rows = conn.execute("SELECT ts, actor, action, target, detail FROM alert_audit "
                            "ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
