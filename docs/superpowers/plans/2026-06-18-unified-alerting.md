# Unified Alerting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-managed alerting layer that emails configured recipients when any monitored card (Environment status, DLQ, Certificate & TLS health) becomes RED, with per-scope toggles, cooldown, recovery emails, audit, and history — without editing existing working logic or the FROZEN cert code.

**Architecture:** A new background engine (`alerts.py`) reads each monitor's already-computed verdict read-only (`uptime.latest()`, `rabbitmq_dlq.latest()`, `cert_monitor.latest()`), normalizes them to flat *items*, filters through a toggle hierarchy + severity threshold, applies a per-card cooldown/dedup/recovery state machine, renders rich emails (`alerts_email.py`), sends via the existing `notify.py`, and records config + sends in `kibana_oo.db`. A super-admin-guarded router (`alerts_api.py`) + a React page (`Alerts.jsx`) manage it. Everything is inert unless `ALERTS_ENABLED=true`.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic-settings / SQLite (`backend/db.py`) / React + Vite / pytest (in a `python:3.13` Docker container).

**Spec:** `docs/superpowers/specs/2026-06-18-unified-alerting-design.md`

---

## File structure

| File | Responsibility |
|---|---|
| `backend/alerts.py` (new) | collect → normalize → filter → decide → persist → loop |
| `backend/alerts_email.py` (new) | pure rendering: `(item, kind, prev) → (subject, html, text)` |
| `backend/alerts_send.py` (new) | additive SMTP send to an explicit recipient list (notify.py untouched) |
| `backend/alerts_api.py` (new) | HTTP surface; auth guards; validation; config/toggles/history |
| `backend/alerts_store.py` (new) | all SQLite access for the feature (schema, config, toggles, state, history, audit) |
| `frontend/src/Alerts.jsx` (new) | admin UI (toggles, recipients, history) |
| `backend/tests/test_alerts.py` (new) | engine + API tests |
| `docs/KIBANA-OO/Alerting (meldingen).md` (new) | Dutch vault doc (RULES 4) |
| `backend/config.py` (modify, additive) | new `ALERTS_*` settings + `alerts_recipient_seed` property |
| `backend/permissions.py` (modify, additive) | one `CATALOG` entry |
| `backend/main.py` (modify, additive) | register router + start loop |
| `frontend/src/App.jsx`, `Nav.jsx`, `api.js` (modify, additive) | route/nav/api behind `alerts` grant |
| `.env.example` (modify) | document new flags; set old `*_ALERT_ENABLED=false` |

**Why split `alerts_store.py` from `alerts.py`:** the engine logic (decision machine) and the persistence (SQL) are separate responsibilities and are tested differently — the store is exercised against a temp DB, the engine against fake snapshots. Keeping them apart keeps each file small and focused.

---

## Conventions for the implementer

- **Run tests** (project convention — host Python is 3.14 and must NOT be used):
  ```bash
  docker run --rm -v "$(pwd)/backend:/app" -w /app python:3.13 \
    sh -c "pip install -q -r requirements.txt && python -m pytest tests/test_alerts.py -v"
  ```
- **Commit** after each task with a conventional message; end the body with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- Work on branch `feat/unified-alerting` (already created).
- Never edit `cert_monitor.py`, `certificates.py`, `notify.py`, or the alert *logic* in `uptime.py`/`rabbitmq_dlq.py`.

---

## Normalized data shapes (used across tasks — keep names exact)

```python
# An Item is a plain dict:
# {
#   "card_id":   str,   # stable id, f"{category}:{env}:{name}"
#   "category":  str,   # "environment" | "dlq" | "certificate"
#   "env":       str,   # "PROD" | "ACC" | "TST" (normalized)
#   "name":      str,   # human label, e.g. "open-acc.overheid.nl"
#   "severity":  str,   # "ok" | "warn" | "critical"
#   "status":    str,   # short current-status text, e.g. "HTTP 404 / DOWN"
#   "detail":    str,   # optional extra context for the email
# }
```

Severity rank: `{"ok": 0, "warn": 1, "critical": 2}`. Alert kinds: `"new" | "repeated" | "escalation" | "recovery"`.

---

## Task 1: Config flags + env example

**Files:**
- Modify: `backend/config.py` (add settings after the uptime block, ~line 287)
- Modify: `.env.example`

- [ ] **Step 1: Add settings to `config.py`**

Add inside `class Settings` (after the `uptime_history` line):

```python
    # ── Unified alerting (admin-managed RED-state email alerts) ───────────────
    # Additive & OFF by default. When true, a background engine reads the existing
    # monitors (uptime/dlq/cert) read-only and sends admin-configured email alerts
    # with per-scope toggles, cooldown, and recovery. When the engine owns alerting
    # the three legacy inline alerters should be turned OFF (set *_ALERT_ENABLED=
    # false) to avoid duplicate mail. Roll back instantly with ALERTS_ENABLED=false.
    # See alerts.py + alerts_api.py + docs/KIBANA-OO/Alerting (meldingen).md.
    alerts_enabled: bool = False
    alerts_interval: int = 60               # seconds between evaluation passes
    alerts_cooldown_minutes: int = 60       # default per-card anti-spam cooldown
    alerts_default_threshold: str = "critical"  # "critical" or "warn" — min severity to alert
    # Comma-separated emails used to SEED the admin-editable recipient list on first
    # run. Empty → seed from digest_recipients. Admin edits live in kibana_oo.db.
    alerts_recipient_seed: str = ""
```

Add this property next to `digest_recipient_list` (after line ~379):

```python
    @property
    def alerts_recipient_seed_list(self) -> list[str]:
        """Seed recipients for first run: explicit seed, else the digest list."""
        raw = self.alerts_recipient_seed or self.digest_recipients
        return [e.strip() for e in raw.split(",") if e.strip()]
```

- [ ] **Step 2: Document in `.env.example`**

Append a section, and set the legacy flags off (find existing `UPTIME_ALERT_ENABLED` etc. if present and set to false; otherwise add):

```ini
# ── Unified alerting (new; owns all RED-state email) ──────────────────────────
ALERTS_ENABLED=false
ALERTS_INTERVAL=60
ALERTS_COOLDOWN_MINUTES=60
ALERTS_DEFAULT_THRESHOLD=critical
ALERTS_RECIPIENT_SEED=

# When ALERTS_ENABLED=true, turn the three legacy inline alerters OFF so mail is
# not duplicated (the new engine takes over). Flip back to true to roll back.
UPTIME_ALERT_ENABLED=false
RABBITMQ_ALERT_ENABLED=false
CERT_ALERT_ENABLED=false
```

- [ ] **Step 3: Verify config imports**

Run:
```bash
docker run --rm -v "$(pwd)/backend:/app" -w /app python:3.13 \
  sh -c "pip install -q -r requirements.txt && python -c 'from config import settings; print(settings.alerts_enabled, settings.alerts_default_threshold, settings.alerts_recipient_seed_list)'"
```
Expected: `False critical []`

- [ ] **Step 4: Commit**
```bash
git add backend/config.py .env.example
git commit -m "feat(alerts): config flags for unified alerting (off by default)"
```

---

## Task 2: Normalization — monitors → items

**Files:**
- Create: `backend/alerts.py`
- Test: `backend/tests/test_alerts.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_alerts.py`:

```python
"""Unified alerting: env normalization, monitor→item normalization, toggle filter,
the cooldown/dedup/recovery decision machine, email rendering, and the API guards.
No real network or monitors — snapshots are passed in directly."""
import importlib

import pytest
from fastapi import HTTPException

import alerts


def test_norm_env_maps_test_variants_to_tst():
    assert alerts._norm_env("TEST") == "TST"
    assert alerts._norm_env("tst") == "TST"
    assert alerts._norm_env("Acceptance") == "ACC"
    assert alerts._norm_env("acc") == "ACC"
    assert alerts._norm_env("PROD") == "PROD"
    assert alerts._norm_env("anything") == "ANYTHING"


def test_env_from_host():
    assert alerts._env_from_host("open-acc.overheid.nl") == "ACC"
    assert alerts._env_from_host("gateway-zoek.koop-plooi-tst.test5.s15m.nl") == "TST"
    assert alerts._env_from_host("open.overheid.nl") == "PROD"


def test_normalize_uptime_snapshot():
    snap = {
        "enabled": True,
        "groups": [
            {"env": "PROD", "sites": [
                {"name": "open.overheid.nl", "env": "PROD", "state": "up",
                 "http_status": 200, "error": None},
            ]},
            {"env": "ACC", "sites": [
                {"name": "open-acc.overheid.nl", "env": "ACC", "state": "down",
                 "http_status": 404, "error": None},
            ]},
        ],
    }
    items = alerts._normalize_uptime(snap)
    by_name = {i["name"]: i for i in items}
    assert by_name["open.overheid.nl"]["severity"] == "ok"
    down = by_name["open-acc.overheid.nl"]
    assert down["severity"] == "critical"
    assert down["category"] == "environment"
    assert down["env"] == "ACC"
    assert down["card_id"] == "environment:ACC:open-acc.overheid.nl"


def test_normalize_dlq_snapshot():
    snap = {"configured": True, "dlqs": [
        {"name": "antivirus.dlq", "depth": 0, "severity": "ok"},
        {"name": "export.dlq", "depth": 250, "severity": "critical",
         "source_consumers": 0},
    ]}
    items = alerts._normalize_dlq(snap)
    by_name = {i["name"]: i for i in items}
    assert by_name["antivirus.dlq"]["severity"] == "ok"
    crit = by_name["export.dlq"]
    assert crit["severity"] == "critical"
    assert crit["category"] == "dlq"
    assert crit["env"] == "PROD"


def test_normalize_cert_list():
    class FakeCert:
        def __init__(self, host, grade, days):
            self.host, self.grade, self.days_remaining = host, grade, days
            self.status = "ok"
    certs = [
        FakeCert("open.overheid.nl", "OK", 50),
        FakeCert("open-acc.overheid.nl", "CRITICAL", 5),
        FakeCert("gateway.koop-plooi-tst.test5.s15m.nl", "WARN", 20),
    ]
    items = alerts._normalize_cert(certs)
    by_name = {i["name"]: i for i in items}
    assert by_name["open.overheid.nl"]["severity"] == "ok"
    assert by_name["open-acc.overheid.nl"]["severity"] == "critical"
    assert by_name["open-acc.overheid.nl"]["env"] == "ACC"
    assert by_name["gateway.koop-plooi-tst.test5.s15m.nl"]["severity"] == "warn"
    assert by_name["gateway.koop-plooi-tst.test5.s15m.nl"]["env"] == "TST"
```

- [ ] **Step 2: Run to verify it fails**

Run the docker pytest command (see Conventions). Expected: FAIL — `ModuleNotFoundError: No module named 'alerts'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/alerts.py`:

```python
"""Unified alerting engine.

Reads the existing monitors read-only (uptime / rabbitmq_dlq / cert_monitor),
normalizes their verdicts into flat items, filters through an admin toggle
hierarchy + severity threshold, applies a per-card cooldown/dedup/recovery state
machine, renders rich emails and sends them via notify.py, and records sends +
config in kibana_oo.db. Inert unless settings.alerts_enabled. Never raises into a
request; never touches the FROZEN certificate code (only reads cert_monitor.latest).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

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
```

- [ ] **Step 4: Run to verify it passes**

Run the docker pytest command. Expected: the 5 normalization tests PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/alerts.py backend/tests/test_alerts.py
git commit -m "feat(alerts): normalize monitor verdicts into flat items"
```

---

## Task 3: Store — schema, config, toggles, history, audit

**Files:**
- Create: `backend/alerts_store.py`
- Test: append to `backend/tests/test_alerts.py`

- [ ] **Step 1: Write the failing test**

Append to `test_alerts.py`:

```python
import alerts_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings, "alerts_cooldown_minutes", 60)
    monkeypatch.setattr(settings, "alerts_default_threshold", "critical")
    monkeypatch.setattr(settings, "alerts_recipient_seed", "ops@example.com")
    alerts_store.ensure_seeded()
    return alerts_store


def test_config_defaults_and_seed(store):
    cfg = store.get_config()
    assert cfg["global_enabled"] is True
    assert cfg["cooldown_minutes"] == 60
    assert cfg["severity_threshold"] == "critical"
    assert cfg["recipients"] == ["ops@example.com"]


def test_toggle_absent_is_on_and_can_disable(store):
    assert store.is_enabled("category", "dlq") is True       # absent = on
    store.set_toggle("category", "dlq", False, actor="admin@x")
    assert store.is_enabled("category", "dlq") is False
    store.set_toggle("category", "dlq", True, actor="admin@x")
    assert store.is_enabled("category", "dlq") is True


def test_history_and_audit_written(store):
    store.record_history(card_id="dlq:PROD:export.dlq", category="dlq", env="PROD",
                         kind="new", severity="critical", prev_severity="ok",
                         recipients=["ops@example.com"], delivered=1, detail="x")
    rows = store.list_history(limit=10)
    assert len(rows) == 1 and rows[0]["kind"] == "new"
    store.record_audit("admin@x", "set_toggle", "category:dlq", "disabled")
    assert store.list_audit(limit=10)[0]["action"] == "set_toggle"
```

- [ ] **Step 2: Run to verify it fails**

Run docker pytest. Expected: FAIL — `ModuleNotFoundError: No module named 'alerts_store'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/alerts_store.py`:

```python
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

_DEFAULTS = {"global_enabled": "true", "cooldown_minutes": None,
             "severity_threshold": None, "recipients": None}


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
    }


def set_config(key: str, value, actor: str | None) -> None:
    stored = json.dumps(value) if key == "recipients" else (
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
```

- [ ] **Step 4: Run to verify it passes**

Run docker pytest. Expected: the 3 store tests PASS (plus Task 2's still green).

- [ ] **Step 5: Commit**
```bash
git add backend/alerts_store.py backend/tests/test_alerts.py
git commit -m "feat(alerts): sqlite store for config, toggles, state, history, audit"
```

---

## Task 4: Toggle filter (hierarchy + threshold)

**Files:**
- Modify: `backend/alerts.py`
- Test: append to `backend/tests/test_alerts.py`

- [ ] **Step 1: Write the failing test**

Append to `test_alerts.py`:

```python
def test_eligible_respects_threshold_and_hierarchy(store):
    crit = alerts._item("dlq", "PROD", "export.dlq", "critical")
    warn = alerts._item("environment", "PROD", "x", "warn")
    # threshold = critical → warn not eligible, critical eligible
    assert alerts._eligible(crit, threshold="critical") is True
    assert alerts._eligible(warn, threshold="critical") is False
    # lower threshold to warn → warn becomes eligible
    assert alerts._eligible(warn, threshold="warn") is True
    # disabling the category suppresses even a critical
    store.set_toggle("category", "dlq", False, actor="a")
    assert alerts._eligible(crit, threshold="critical") is False
```

- [ ] **Step 2: Run to verify it fails**

Run docker pytest. Expected: FAIL — `AttributeError: module 'alerts' has no attribute '_eligible'`.

- [ ] **Step 3: Write minimal implementation**

Add to `backend/alerts.py` (import the store at top: `import alerts_store`):

```python
import alerts_store


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
```

- [ ] **Step 4: Run to verify it passes**

Run docker pytest. Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/alerts.py backend/tests/test_alerts.py
git commit -m "feat(alerts): toggle-hierarchy + severity-threshold filter"
```

---

## Task 5: Email rendering

**Files:**
- Create: `backend/alerts_email.py`
- Test: append to `backend/tests/test_alerts.py`

- [ ] **Step 1: Write the failing test**

Append to `test_alerts.py`:

```python
import alerts_email


def test_render_email_contains_required_fields():
    item = alerts._item("environment", "ACC", "open-acc.overheid.nl", "critical",
                        status="HTTP 404 / DOWN")
    subject, html, text = alerts_email.render(item, kind="new", prev_severity="ok",
                                              dashboard_url="https://dash.example/")
    assert "[ACC]" in subject and "open-acc.overheid.nl" in subject
    for needle in ["CRITICAL", "ACC", "open-acc.overheid.nl", "HTTP 404 / DOWN",
                   "ok", "new", "https://dash.example/"]:
        assert needle in text
    # HTML escapes the status (no raw injection)
    evil = alerts._item("dlq", "PROD", "x", "critical", status="<script>")
    _, ehtml, _ = alerts_email.render(evil, kind="new", prev_severity="ok",
                                      dashboard_url="https://d/")
    assert "<script>" not in ehtml and "&lt;script&gt;" in ehtml


def test_render_recovery_kind():
    item = alerts._item("certificate", "PROD", "open.overheid.nl", "ok",
                        status="grade OK")
    subject, _, text = alerts_email.render(item, kind="recovery", prev_severity="critical",
                                           dashboard_url="https://d/")
    assert "recovery" in text.lower() or "hersteld" in text.lower()
    assert "✅" in subject or "recovery" in subject.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run docker pytest. Expected: FAIL — `ModuleNotFoundError: No module named 'alerts_email'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/alerts_email.py`:

```python
"""Pure rendering for alert emails: (item, kind, prev_severity) → (subject, html,
text). No I/O. All dynamic values are HTML-escaped in the HTML part."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape

# Per-category suggested administrator action (Dutch — audience is the beheerder).
SUGGESTED = {
    "environment": "Controleer de service/ingress en of de host bereikbaar is; "
                   "kijk in de logs en herstart zo nodig de betreffende pod.",
    "dlq": "Open de dead-letter queue, controleer of de bron-consumer draait, "
           "onderzoek de faalreden en requeue of verwijder de berichten.",
    "certificate": "Vernieuw/roteer het certificaat tijdig en controleer de "
                   "volledige keten (chain) en vervaldatum.",
}
KIND_LABEL = {"new": "New alert", "repeated": "Repeated alert",
              "escalation": "Escalation", "recovery": "Recovery"}
KIND_ICON = {"new": "⛔", "repeated": "🔁", "escalation": "🔺", "recovery": "✅"}


def render(item: dict, kind: str, prev_severity: str, dashboard_url: str
           ) -> tuple[str, str, str]:
    icon = KIND_ICON.get(kind, "⛔")
    label = KIND_LABEL.get(kind, kind)
    sev = item["severity"].upper()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    verb = "is hersteld" if kind == "recovery" else f"is {sev}"
    subject = f"{icon} [{item['env']}] {item['name']} {verb} ({label})"
    action = SUGGESTED.get(item["category"], "Onderzoek de melding op het dashboard.")

    fields = [
        ("Kind", label), ("Severity", sev), ("Environment", item["env"]),
        ("Component", item["name"]), ("Category", item["category"]),
        ("Current status", item["status"] or sev),
        ("Previous status", (prev_severity or "ok")),
        ("Time detected", now), ("Suggested action", action),
        ("Dashboard", dashboard_url),
    ]
    text = "\n".join(f"{k}: {v}" for k, v in fields)

    rows = "".join(
        f"<tr><td style='padding:4px 12px;color:#888'>{escape(k)}</td>"
        f"<td style='padding:4px 12px'><b>{escape(str(v))}</b></td></tr>"
        for k, v in fields)
    html = (f"<div style='font-family:sans-serif'>"
            f"<h2>{escape(icon)} {escape(item['name'])} — {escape(label)}</h2>"
            f"<table style='border-collapse:collapse'>{rows}</table></div>")
    return subject, html, text
```

- [ ] **Step 4: Run to verify it passes**

Run docker pytest. Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/alerts_email.py backend/tests/test_alerts.py
git commit -m "feat(alerts): rich HTML+text email rendering (escaped, with actions)"
```

---

## Task 6: Decision machine (new/repeated/escalation/recovery + cooldown)

**Files:**
- Modify: `backend/alerts.py`
- Test: append to `backend/tests/test_alerts.py`

The decision is a **pure** function of the item, the prior persisted state, the cooldown, and "now" — so it is unit-testable without time mocking. It returns a kind or `None` (suppress), plus the next state to persist.

- [ ] **Step 1: Write the failing test**

Append to `test_alerts.py`:

```python
from datetime import datetime, timedelta, timezone


def _iso(dt):
    return dt.isoformat()


def test_decide_new_then_cooldown_then_repeat():
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    crit = alerts._item("dlq", "PROD", "export.dlq", "critical")
    # No prior state, red → NEW
    kind, nxt = alerts._decide(crit, prev=None, cooldown_min=60, now=now)
    assert kind == "new" and nxt["severity"] == "critical" and nxt["red_since"]

    # 30 min later, same severity, within cooldown → suppressed
    prev = nxt
    kind2, _ = alerts._decide(crit, prev=prev, cooldown_min=60,
                              now=now + timedelta(minutes=30))
    assert kind2 is None

    # 61 min after last send, still red → REPEATED
    kind3, _ = alerts._decide(crit, prev=prev, cooldown_min=60,
                              now=now + timedelta(minutes=61))
    assert kind3 == "repeated"


def test_decide_escalation_bypasses_cooldown():
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    warn = alerts._item("dlq", "PROD", "export.dlq", "warn")
    _, prev = alerts._decide(warn, prev=None, cooldown_min=60, now=now)
    crit = alerts._item("dlq", "PROD", "export.dlq", "critical")
    kind, _ = alerts._decide(crit, prev=prev, cooldown_min=60,
                             now=now + timedelta(minutes=1))
    assert kind == "escalation"


def test_decide_recovery_and_rearm():
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    crit = alerts._item("environment", "ACC", "x", "critical")
    _, prev = alerts._decide(crit, prev=None, cooldown_min=60, now=now)
    ok = alerts._item("environment", "ACC", "x", "ok")
    kind, nxt = alerts._decide(ok, prev=prev, cooldown_min=60,
                               now=now + timedelta(minutes=5))
    assert kind == "recovery" and nxt["red_since"] is None and nxt["severity"] == "ok"
    # After recovery, a new red fires NEW again
    kind2, _ = alerts._decide(crit, prev=nxt, cooldown_min=60,
                              now=now + timedelta(minutes=10))
    assert kind2 == "new"


def test_decide_ok_with_no_prior_is_silent():
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    ok = alerts._item("dlq", "PROD", "x", "ok")
    kind, nxt = alerts._decide(ok, prev=None, cooldown_min=60, now=now)
    assert kind is None and nxt is None
```

- [ ] **Step 2: Run to verify it fails**

Run docker pytest. Expected: FAIL — `AttributeError: module 'alerts' has no attribute '_decide'`.

- [ ] **Step 3: Write minimal implementation**

Add to `backend/alerts.py`:

```python
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
                              "last_kind": "escalation", "red_since": prev.get("red_since") or now_iso}

    # Same/lower severity and still red → repeat only after cooldown.
    last_sent = (prev or {}).get("last_sent_at")
    if last_sent:
        elapsed_min = (now - datetime.fromisoformat(last_sent)).total_seconds() / 60
        if elapsed_min >= cooldown_min:
            return "repeated", {"severity": sev, "last_sent_at": now_iso,
                                "last_kind": "repeated", "red_since": prev.get("red_since")}
    return None, {**prev, "severity": sev}  # within cooldown: update sev, no send
```

- [ ] **Step 4: Run to verify it passes**

Run docker pytest. Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/alerts.py backend/tests/test_alerts.py
git commit -m "feat(alerts): cooldown/dedup/recovery/escalation decision machine"
```

---

## Task 7: Orchestration — scan(), send, persist + background loop

**Files:**
- Modify: `backend/alerts.py`
- Test: append to `backend/tests/test_alerts.py`

- [ ] **Step 1: Write the failing test**

Append to `test_alerts.py`:

```python
def test_scan_sends_red_not_green_and_records(store, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "alerts_enabled", True)
    sent = []
    monkeypatch.setattr(alerts.notify, "send_email",
                        lambda subject, html, text: sent.append(subject) or True)

    async def fake_uptime():
        return {"enabled": True, "groups": [{"env": "ACC", "sites": [
            {"name": "open-acc.overheid.nl", "env": "ACC", "state": "down",
             "http_status": 404}]}]}

    async def fake_dlq():
        return {"configured": True, "dlqs": [
            {"name": "antivirus.dlq", "depth": 0, "severity": "ok"}]}

    monkeypatch.setattr(alerts, "_collect", lambda: alerts._normalize_uptime(
        {"enabled": True, "groups": [{"env": "ACC", "sites": [
            {"name": "open-acc.overheid.nl", "env": "ACC", "state": "down",
             "http_status": 404}]}]}) + alerts._normalize_dlq(
        {"configured": True, "dlqs": [
            {"name": "antivirus.dlq", "depth": 0, "severity": "ok"}]}))

    import asyncio
    asyncio.get_event_loop().run_until_complete(alerts.scan())
    assert any("open-acc.overheid.nl" in s for s in sent)        # red → emailed
    assert all("antivirus" not in s for s in sent)               # green → not
    hist = store.list_history()
    assert any(h["card_id"] == "environment:ACC:open-acc.overheid.nl" for h in hist)


def test_scan_disabled_global_sends_nothing(store, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "alerts_enabled", True)
    store.set_config("global_enabled", False, actor="a")
    sent = []
    monkeypatch.setattr(alerts.notify, "send_email",
                        lambda *a, **k: sent.append(1) or True)
    monkeypatch.setattr(alerts, "_collect", lambda: [
        alerts._item("dlq", "PROD", "export.dlq", "critical")])
    import asyncio
    asyncio.get_event_loop().run_until_complete(alerts.scan())
    assert sent == []
```

- [ ] **Step 2: Run to verify it fails**

Run docker pytest. Expected: FAIL — `AttributeError: module 'alerts' has no attribute 'scan'` (and `_collect`).

- [ ] **Step 3: Write minimal implementation**

Add to `backend/alerts.py` (add imports at top: `import notify`, `import uptime`, `import rabbitmq_dlq`, `import cert_monitor`, `from config import settings`):

```python
import notify
import uptime
import rabbitmq_dlq
import cert_monitor
from config import settings


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
    cfg = get_config_safe()
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
                s = nxt
                alerts_store.set_state(item["card_id"], s["severity"],
                                       s["last_sent_at"], s["last_kind"], s["red_since"])
            if kind is None:
                continue
            await _dispatch(item, kind, (prev or {}).get("severity", "ok"), cfg["recipients"])
            sent += 1
        except Exception as e:  # noqa: BLE001 — one bad card never breaks the pass
            logger.error("alerts: card %s failed: %s", item.get("card_id"), e)
    return {"enabled": True, "global_enabled": True, "sent": sent, "checked": len(items)}


def get_config_safe() -> dict:
    return alerts_store.get_config()


async def _dispatch(item: dict, kind: str, prev_severity: str, recipients: list[str]) -> None:
    import alerts_email
    import alerts_send
    subject, html, text = alerts_email.render(item, kind, prev_severity, _dashboard_url())
    delivered = False
    try:
        # Email goes to the ADMIN-managed recipient list (alerts_send, additive —
        # notify.py is untouched). Webhook reuses notify.send_webhook, whose
        # {"text": ...} payload a Mattermost incoming webhook accepts as-is.
        delivered = await asyncio.to_thread(alerts_send.send_email_to, recipients,
                                            subject, html, text)
        await notify.send_webhook(text)
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
```

- [ ] **Step 3b: Create the additive send helper `backend/alerts_send.py`**

A tiny module that sends to an **explicit** recipient list (so the admin-managed
list is the real `To:`). It reuses the existing `settings.smtp_*` config but does
NOT import or modify `notify.py`. Mirrors `notify.send_email`'s SMTP handling.

```python
"""Send an alert email to an EXPLICIT recipient list (the admin-managed list),
reusing the configured SMTP settings. Additive — notify.py is left untouched.
Best-effort: returns False (never raises) if unconfigured or on error."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

from config import settings

logger = logging.getLogger(__name__)


def send_email_to(recipients: list[str], subject: str, html: str, text: str) -> bool:
    """Blocking SMTP send to `recipients`. Call via asyncio.to_thread."""
    recipients = [r.strip() for r in (recipients or []) if r and r.strip()]
    if not (settings.smtp_host and settings.smtp_from and recipients):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            if settings.smtp_use_tls:
                server.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        return True
    except Exception as e:  # noqa: BLE001 — delivery must never break the loop
        logger.error("alerts: email to %s failed: %s", recipients, e)
        return False
```

Update the Task 7 scan test (`test_scan_sends_red_not_green_and_records`) to patch
`alerts_send.send_email_to` instead of `notify.send_email`:

```python
    import alerts_send
    monkeypatch.setattr(alerts_send, "send_email_to",
                        lambda recips, subject, html, text: sent.append(subject) or True)
    monkeypatch.setattr(alerts.notify, "send_webhook",
                        lambda text: _AsyncTrue())
```

where `_AsyncTrue` is a tiny awaitable returning True — or simpler, make the webhook
a no-op coroutine: `async def _noop(*a, **k): return True` and patch with it. In
`test_scan_disabled_global_sends_nothing`, patch `alerts_send.send_email_to` the same
way. (The engine never calls `notify.send_email` for alerts anymore.)

- [ ] **Step 4: Run to verify it passes**

Run docker pytest. Expected: PASS (the two scan tests; all prior tests still green).

- [ ] **Step 5: Commit**
```bash
git add backend/alerts.py backend/alerts_send.py backend/tests/test_alerts.py
git commit -m "feat(alerts): scan orchestration, dispatch, history, background loop"
```

---

## Task 8: API router (super-admin guarded)

**Files:**
- Create: `backend/alerts_api.py`
- Test: append to `backend/tests/test_alerts.py`

- [ ] **Step 1: Write the failing test**

Append to `test_alerts.py`:

```python
def test_email_validation():
    import alerts_api
    assert alerts_api._valid_email("ops@example.com") is True
    assert alerts_api._valid_email("not-an-email") is False
    assert alerts_api._valid_email("a@b") is False
    assert alerts_api._valid_email("x" * 300 + "@e.com") is False


def test_api_requires_super(store, monkeypatch):
    import alerts_api
    # require_super raises 403 for a non-super session
    from session import require_session  # noqa: F401
    with pytest.raises(HTTPException) as ei:
        # call the guard directly with a plain user session
        import permissions
        monkeypatch.setattr(permissions, "is_super", lambda u: False)
        from auth import require_super
        require_super(session={"username": "user@x"})
    assert ei.value.status_code == 403
```

- [ ] **Step 2: Run to verify it fails**

Run docker pytest. Expected: FAIL — `ModuleNotFoundError: No module named 'alerts_api'`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/alerts_api.py`:

```python
"""Unified-alerting API. Viewing requires the `alerts` feature grant; every
mutation is super-admin-only. All inputs validated server-side; no secrets are
ever returned. Inert (200 {enabled:false}) when settings.alerts_enabled is off."""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import alerts
import alerts_store
from auth import require_feature, require_super
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/alerts")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_VALID_SCOPES = {"global", "category", "env", "card"}
_VALID_CATEGORIES = {"environment", "dlq", "certificate"}
_VALID_THRESHOLDS = {"warn", "critical"}


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
    return {"ok": True, "config": alerts_store.get_config()}
```

- [ ] **Step 4: Run to verify it passes**

Run docker pytest. Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/alerts_api.py backend/tests/test_alerts.py
git commit -m "feat(alerts): super-admin-guarded API (status/config/toggles/history/audit)"
```

---

## Task 9: Wire into permissions + main app

**Files:**
- Modify: `backend/permissions.py:34` (CATALOG — add one entry in the "Beheer" group)
- Modify: `backend/main.py` (import + include router + start loop)

- [ ] **Step 1: Add the feature key**

In `backend/permissions.py`, add to the `CATALOG` list (after the `settings` entry):

```python
    {"key": "alerts", "label": "Alerting (meldingen)", "group": "Beheer"},
```

- [ ] **Step 2: Register router + loop in `main.py`**

Add imports near the other feature imports (after line ~33):

```python
from alerts_api import router as alerts_router
from alerts import run_alert_loop
```

In `include_router` block (after `app.include_router(infra_router)`):

```python
app.include_router(alerts_router)
```

In `lifespan` (next to the other `create_task` lines ~50-52):

```python
    alerts_task = asyncio.create_task(run_alert_loop())
```

And ensure it is cancelled on shutdown alongside the others (match the existing pattern; find where `uptime_task` is cancelled and add `alerts_task.cancel()` the same way).

- [ ] **Step 3: Verify the app imports and routes register**

Run:
```bash
docker run --rm -v "$(pwd)/backend:/app" -w /app python:3.13 \
  sh -c "pip install -q -r requirements.txt && python -c 'import main; print([r.path for r in main.app.routes if \"/alerts\" in r.path])'"
```
Expected: a list including `/alerts/status`, `/alerts/config`, `/alerts/toggle`, `/alerts/history`, `/alerts/audit`.

- [ ] **Step 4: Run the full test module**

Run docker pytest for `tests/test_alerts.py`. Expected: all PASS.

- [ ] **Step 5: Commit**
```bash
git add backend/permissions.py backend/main.py
git commit -m "feat(alerts): register alerts feature key, router, and background loop"
```

---

## Task 10: Frontend admin page

**Files:**
- Create: `frontend/src/Alerts.jsx`
- Modify: `frontend/src/api.js` (add API helpers)
- Modify: `frontend/src/App.jsx` (import + route behind `can('alerts')`)
- Modify: `frontend/src/Nav.jsx` (nav entry behind the grant)

> The frontend has no unit-test harness; verify by building and by manual smoke (Step 4). Match the existing fetch/auth pattern (`Authorization: Bearer ${token}`) used elsewhere in `App.jsx`.

- [ ] **Step 1: Add API helpers to `frontend/src/api.js`**

Append (match the existing helper style in that file — `API_BASE`, bearer token):

```js
export async function fetchAlertsStatus(token) {
  return apiGet("/alerts/status", token);
}
export async function fetchAlertsHistory(token) {
  return apiGet("/alerts/history", token);
}
export async function putAlertToggle(token, body) {
  return apiSend("PUT", "/alerts/toggle", token, body);
}
export async function putAlertConfig(token, body) {
  return apiSend("PUT", "/alerts/config", token, body);
}
```

If `apiGet`/`apiSend` helpers don't exist with those names, mirror the exact fetch
pattern already used in `api.js` (read the file first) — do not invent a new client.

- [ ] **Step 2: Create `frontend/src/Alerts.jsx`**

A single page component. Render: master switch (`global_enabled`), category switches (environment/dlq/certificate), env switches (PROD/ACC/TST), a per-card list from `status.items` (each with a toggle + current severity colour), a recipients editor (comma textarea → array, validated on save), cooldown + threshold inputs, and a history table. All mutations call `putAlertToggle`/`putAlertConfig` then re-fetch `fetchAlertsStatus`.

```jsx
import { useEffect, useState, useCallback } from "react";
import {
  fetchAlertsStatus, fetchAlertsHistory, putAlertToggle, putAlertConfig,
} from "./api";

const SEV_COLOR = { ok: "#3fb950", warn: "#d29922", critical: "#f85149" };
const CATEGORIES = ["environment", "dlq", "certificate"];
const ENVS = ["PROD", "ACC", "TST"];

export default function Alerts({ token, onNavigate }) {
  const [status, setStatus] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState(null);
  const [recipients, setRecipients] = useState("");

  const load = useCallback(async () => {
    try {
      const s = await fetchAlertsStatus(token);
      setStatus(s);
      if (s?.config?.recipients) setRecipients(s.config.recipients.join(", "));
      const h = await fetchAlertsHistory(token);
      setHistory(h.history || []);
    } catch (e) { setError(String(e)); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  const toggleOn = (scope, ref) => {
    // absence = ON; a row with enabled=0 = OFF
    const t = (status?.toggles || []).find((x) => x.scope === scope && x.ref === ref);
    return t ? !!t.enabled : true;
  };
  const setToggle = async (scope, ref, enabled) => {
    await putAlertToggle(token, { scope, ref, enabled });
    load();
  };
  const saveConfig = async (patch) => {
    try { await putAlertConfig(token, patch); load(); }
    catch (e) { setError(String(e)); }
  };

  if (status && status.enabled === false) {
    return <div className="card">Alerting is uitgeschakeld (ALERTS_ENABLED=false).</div>;
  }
  if (!status) return <div className="card">Laden…</div>;

  return (
    <div className="alerts-page">
      <h2>Alerting (meldingen)</h2>
      {error && <div className="error">{error}</div>}

      <label>
        <input type="checkbox" checked={toggleOn("global", "")}
               onChange={(e) => setToggle("global", "", e.target.checked)} />
        {" "}Alerting globaal ingeschakeld
      </label>

      <h3>Categorieën</h3>
      {CATEGORIES.map((c) => (
        <label key={c} style={{ marginRight: 16 }}>
          <input type="checkbox" checked={toggleOn("category", c)}
                 onChange={(e) => setToggle("category", c, e.target.checked)} /> {c}
        </label>
      ))}

      <h3>Omgevingen</h3>
      {ENVS.map((env) => (
        <label key={env} style={{ marginRight: 16 }}>
          <input type="checkbox" checked={toggleOn("env", env)}
                 onChange={(e) => setToggle("env", env, e.target.checked)} /> {env}
        </label>
      ))}

      <h3>Kaarten</h3>
      <ul style={{ listStyle: "none", padding: 0 }}>
        {(status.items || []).map((it) => (
          <li key={it.card_id} style={{ padding: "4px 0" }}>
            <input type="checkbox" checked={toggleOn("card", it.card_id)}
                   onChange={(e) => setToggle("card", it.card_id, e.target.checked)} />
            <span style={{ color: SEV_COLOR[it.severity] || "#888", margin: "0 8px" }}>●</span>
            [{it.env}] {it.name} — {it.status}
          </li>
        ))}
      </ul>

      <h3>Ontvangers</h3>
      <textarea value={recipients} onChange={(e) => setRecipients(e.target.value)}
                rows={2} style={{ width: "100%" }} placeholder="ops@example.com, beheer@example.com" />
      <button onClick={() => saveConfig({
        recipients: recipients.split(",").map((s) => s.trim()).filter(Boolean),
      })}>Ontvangers opslaan</button>

      <h3>Instellingen</h3>
      <label>Cooldown (min):{" "}
        <input type="number" min={1} max={10080}
               defaultValue={status.config.cooldown_minutes}
               onBlur={(e) => saveConfig({ cooldown_minutes: Number(e.target.value) })} />
      </label>{" "}
      <label>Drempel:{" "}
        <select defaultValue={status.config.severity_threshold}
                onChange={(e) => saveConfig({ severity_threshold: e.target.value })}>
          <option value="critical">critical (alleen rood)</option>
          <option value="warn">warn (waarschuwing + rood)</option>
        </select>
      </label>

      <h3>Alertgeschiedenis</h3>
      <table>
        <thead><tr><th>Tijd</th><th>Kaart</th><th>Soort</th><th>Severity</th><th>Verzonden</th></tr></thead>
        <tbody>
          {history.map((h, i) => (
            <tr key={i}>
              <td>{h.ts}</td><td>{h.card_id}</td><td>{h.kind}</td>
              <td style={{ color: SEV_COLOR[h.severity] }}>{h.severity}</td>
              <td>{h.delivered ? "✓" : "✗"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 3: Wire route + nav (read the files first, match the pattern)**

In `App.jsx`: `import AlertsPage from "./Alerts";`, add a render branch when the
current view is `"alerts"` and `can("alerts")` is true (mirror how `AuthorizationPage`
is rendered ~line 1094, passing `token` and `onNavigate`). In `Nav.jsx`: add a nav
button for the `alerts` view, shown only when the user has the `alerts` feature
(mirror the existing per-feature nav gating).

- [ ] **Step 4: Build + smoke check**

Run:
```bash
cd frontend && npm run build
```
Expected: build succeeds, no missing-import errors. (Manual: with `ALERTS_ENABLED=true`
and a super-admin login, the "Alerting (meldingen)" entry appears under Beheer and the
page loads `/alerts/status`.)

- [ ] **Step 5: Commit**
```bash
git add frontend/src/Alerts.jsx frontend/src/api.js frontend/src/App.jsx frontend/src/Nav.jsx
git commit -m "feat(alerts): admin UI for toggles, recipients, settings, history"
```

---

## Task 11: Dutch vault doc + recipients note + final pass

**Files:**
- Create: `docs/KIBANA-OO/Alerting (meldingen).md`
- Modify: `docs/KIBANA-OO/Home.md` (add a `[[Alerting (meldingen)]]` link)
- Modify: `.env.example` (note the recipients/DIGEST relationship)

- [ ] **Step 1: Write the Dutch vault note**

Create `docs/KIBANA-OO/Alerting (meldingen).md` (audience = beheerder; cover: Wat & waarom, Hoe te gebruiken, een echt voorbeeld, betekenis van kleuren/drempels, configuratie & randgevallen, rollback). Include the env-flag relationship and that turning the engine on means setting the three legacy `*_ALERT_ENABLED=false`. Link it from related notes (`[[Beschikbaarheid (uptime)]]`, `[[Certificaten en TLS]]`, `[[Woo Gateway]]`/DLQ note).

- [ ] **Step 2: Link from `Home.md`**

Add under the dashboard/beheer section:
```markdown
- [[Alerting (meldingen)]] — e-mailmeldingen bij RED-status (omgevingen, DLQ, certificaten)
```

- [ ] **Step 3: Document recipients in `.env.example`**

Add a comment under the alerting block:
```ini
# The engine delivers via the existing SMTP path, which sends to DIGEST_RECIPIENTS.
# Set DIGEST_RECIPIENTS to your alert recipients, and/or manage the admin recipient
# list in the UI (recorded in alert history). SMTP_* secrets stay server-side only.
```

- [ ] **Step 4: Full backend test run (regression-safe)**

Run the whole backend suite to confirm nothing else broke:
```bash
docker run --rm -v "$(pwd)/backend:/app" -w /app python:3.13 \
  sh -c "pip install -q -r requirements.txt && python -m pytest -q"
```
Expected: all tests pass (existing + new `test_alerts.py`).

- [ ] **Step 5: Commit**
```bash
git add "docs/KIBANA-OO/Alerting (meldingen).md" "docs/KIBANA-OO/Home.md" .env.example
git commit -m "docs(alerts): Dutch vault note, Home link, recipients/env notes"
```

---

## Self-review — spec coverage

| Spec requirement | Task |
|---|---|
| Engine reads monitors read-only, never re-derives | T2, T7 |
| Old inline alerts off via env flags (Q1A) | T1, T11 |
| Admin-managed recipients seeded from env (Q2B) | T1, T3, T8 |
| Toggle hierarchy global∧category∧env∧card, default-ON (Q3A) | T3, T4 |
| Per-card cooldown + escalation bypass + recovery (Q4A) | T6 |
| Super-admin-only config, `alerts` grant to view (Q5A) | T8, T9 |
| Email content (severity/env/component/status/prev/time/link/action/kind) | T5 |
| Data model (config/toggles/state/history/audit) | T3 |
| Feature flag `ALERTS_ENABLED`, instant rollback | T1, T7, T8 |
| Tests: RED sends / GREEN no / disabled / cooldown / escalation / recovery / 403 / invalid email / audit written | T6, T7, T8 |
| Dutch vault doc (RULES 4) | T11 |
| Rollback plan (env flags, drop additive tables) | T1, T11, spec §14 |

**Placeholder scan:** none — every code step contains complete code.
**Type consistency:** item dict keys (`card_id/category/env/name/severity/status/detail`), state keys (`severity/last_sent_at/last_kind/red_since`), kinds (`new/repeated/escalation/recovery`), scopes (`global/category/env/card`) are used identically across T2–T10.

**Note for the implementer on `_collect` in T7 test:** the test monkeypatches `alerts._collect` to a synchronous list; `scan()` handles both via the `iscoroutine` check. Keep that check.
