# DLQ Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only "DLQ Intelligence" engine that peeks dead-lettered messages, explains *why* they failed (reason · age · trend · source), produces a smart human verdict, and feeds it to the dashboard card, a dedicated page, and the alert email/Mattermost — additively, behind a flag.

**Architecture:** `dlq_intel.py` reuses `rabbitmq_dlq.latest()` for the base DLQ list, peeks each non-empty queue read-only (`ackmode=reject_requeue_true`, ≤20 msgs), reads `x-death` headers, tracks depth history for trend, and computes a verdict + recommended action. A read-only API + a React page consume it; the unified alert engine enriches DLQ alerts from it. Inert unless `DLQ_INTEL_ENABLED`.

**Tech Stack:** Python 3.13 / FastAPI / httpx / SQLite (`backend/db.py`) / React + Vite / pytest in `python:3.13` Docker.

**Spec:** `docs/superpowers/specs/2026-06-18-dlq-intelligence-design.md`

---

## File structure

| File | Responsibility |
|---|---|
| `backend/dlq_intel.py` (new) | peek + x-death parse + trend + verdict + scan loop + cache |
| `backend/dlq_intel_api.py` (new) | `GET /dashboard/dlq/intel`, `require_feature("rabbitmq")` |
| `backend/tests/test_dlq_intel.py` (new) | engine + API tests |
| `frontend/src/DlqIntel.jsx` (new) | dedicated DLQ Intelligence page |
| `docs/KIBANA-OO/DLQ intelligentie.md` (new) | Dutch vault note |
| `backend/config.py` (modify, additive) | `DLQ_INTEL_*` settings |
| `backend/main.py` (modify, additive) | register router + start loop |
| `backend/alerts.py` (modify — my file) | DLQ items enriched from dlq_intel |
| `backend/alerts_mattermost.py` / `alerts_email.py` (modify — my files) | render DLQ extras |
| `frontend/src/api.js`, `App.jsx`, `Nav.jsx`, `Dashboard.jsx` (modify, additive) | route/nav + card verdict line |
| `.env.example` (modify) | document `DLQ_INTEL_*` |

**Not modified:** `rabbitmq_dlq.py` (reused via `latest()`), FROZEN cert/Mistral code.

---

## Conventions

- **Tests** (host Python is 3.14 — do NOT use it):
  ```bash
  cd backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 docker run --rm -v "$HP:/app" -w /app python:3.13 \
    sh -c "pip install -q -r requirements.txt && python -m pytest tests/test_dlq_intel.py -q"
  ```
  (On non-Windows just `docker run --rm -v "$(pwd):/app" -w /app python:3.13 sh -c "..."`.)
- **Commit** per task; body ends with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Branch `feat/dlq-intelligence` (already created).
- Never edit `rabbitmq_dlq.py`, `cert_monitor.py`, `certificates.py`.

## Shared shapes (exact names — used across tasks)

```python
# A peeked failure record (per message):
#   {"reason": str, "source": str, "routing": str, "age_seconds": int|None}
# A queue intelligence record:
#   {
#     "name": str, "source": str, "depth": int, "source_consumers": int|None,
#     "severity": str,          # "ok" | "warn" | "critical"  (SMART verdict)
#     "headline": str,          # Dutch one-liner
#     "action": str,            # recommended action
#     "trend": str,             # "growing" | "stable" | "draining" | "unknown"
#     "oldest_age_seconds": int|None,
#     "reasons": list[dict],    # [{"reason": str, "count": int}] sorted desc
#     "sample": list[dict],     # peeked failure records (≤ peek_max)
#     "peeked": bool,           # False if peek failed → count-only verdict
#   }
```

Severity rank: `{"ok": 0, "warn": 1, "critical": 2}`.

---

## Task 1: Config flags

**Files:** Modify `backend/config.py` (after the RabbitMQ block ~line 77), `.env.example`.

- [ ] **Step 1: Add settings** to `class Settings` after `rabbitmq_timeout`:

```python
    # ── DLQ Intelligence (read-only peek + smart verdict) ─────────────────────
    # Additive & OFF by default. When true, dlq_intel peeks dead-lettered messages
    # (read-only, requeued untouched) to explain WHY they failed and produce a smart
    # verdict (depth + age + trend + reason). Feeds the dashboard card, the DLQ
    # Intelligence page and the alert content. See dlq_intel.py.
    dlq_intel_enabled: bool = False
    dlq_intel_interval: int = 90        # seconds between intelligence passes
    dlq_intel_peek_max: int = 20        # max messages peeked per queue per pass
    dlq_intel_parked_days: float = 2.0  # oldest-age beyond this = "geparkeerd" warn
    dlq_intel_grow_delta: int = 5       # depth rise vs prior sample → "growing"
    dlq_intel_history: int = 50         # depth samples kept per queue (trend)
```

- [ ] **Step 2: Document in `.env.example`** (append):

```ini
# ── DLQ Intelligence (read-only peek; explains why messages are stuck) ─────────
DLQ_INTEL_ENABLED=false
DLQ_INTEL_INTERVAL=90
DLQ_INTEL_PEEK_MAX=20
DLQ_INTEL_PARKED_DAYS=2
DLQ_INTEL_GROW_DELTA=5
DLQ_INTEL_HISTORY=50
```

- [ ] **Step 3: Verify**
```bash
cd backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 docker run --rm -v "$HP:/app" -w /app python:3.13 \
  sh -c "pip install -q -r requirements.txt 2>/dev/null && python -c 'from config import settings; print(settings.dlq_intel_enabled, settings.dlq_intel_peek_max)'"
```
Expected: `False 20`

- [ ] **Step 4: Commit**
```bash
git add backend/config.py .env.example
git commit -m "feat(dlq): config flags for DLQ Intelligence (off by default)"
```

---

## Task 2: x-death parsing (pure)

**Files:** Create `backend/dlq_intel.py`; create `backend/tests/test_dlq_intel.py`.

- [ ] **Step 1: Write the failing test** — create `backend/tests/test_dlq_intel.py`:

```python
"""DLQ Intelligence: x-death parsing, trend, smart verdict, peek (mocked), scan,
and API gating. No real RabbitMQ — message payloads/headers are passed in directly."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import dlq_intel


def _msg(reason, exchange="orders", rk="order.created", minutes_ago=10):
    t = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {"properties": {"headers": {"x-death": [
        {"reason": reason, "exchange": exchange, "routing-keys": [rk],
         "queue": "q", "count": 3, "time": t},
    ]}}}


def test_parse_failure_extracts_reason_source_age():
    rec = dlq_intel._parse_failure(_msg("rejected", "orders", "order.created", 10))
    assert rec["reason"] == "rejected"
    assert rec["source"] == "orders"
    assert rec["routing"] == "order.created"
    assert 540 <= rec["age_seconds"] <= 660  # ~10 min


def test_parse_failure_maps_delivery_limit_to_max_retries():
    rec = dlq_intel._parse_failure(_msg("delivery_limit"))
    assert rec["reason"] == "max-retries"


def test_parse_failure_missing_xdeath_is_unknown():
    rec = dlq_intel._parse_failure({"properties": {"headers": {}}})
    assert rec["reason"] == "onbekend" and rec["age_seconds"] is None
```

- [ ] **Step 2: Run → fail** (`ModuleNotFoundError: No module named 'dlq_intel'`).

- [ ] **Step 3: Implement** — create `backend/dlq_intel.py`:

```python
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
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit**
```bash
git add backend/dlq_intel.py backend/tests/test_dlq_intel.py
git commit -m "feat(dlq): parse x-death headers (reason, source, age)"
```

---

## Task 3: Trend from depth history

**Files:** Modify `backend/dlq_intel.py`; append to test file.

- [ ] **Step 1: Write the failing test** — append:

```python
@pytest.fixture()
def store(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings, "dlq_intel_history", 50)
    monkeypatch.setattr(settings, "dlq_intel_grow_delta", 5)
    return settings


def test_trend_growing_stable_draining(store):
    q = "export.dlq"
    # record rising depths
    for d in (10, 12, 20):
        dlq_intel._record_depth(q, d)
    assert dlq_intel._trend(q, current=40) == "growing"      # 40 >> first sample 10
    assert dlq_intel._trend(q, current=20) == "stable"       # within delta of 20
    # falling
    dlq_intel._record_depth(q, 4)
    assert dlq_intel._trend(q, current=2) == "draining"


def test_trend_unknown_without_history(store):
    assert dlq_intel._trend("brand-new.dlq", current=3) == "unknown"
```

- [ ] **Step 2: Run → fail** (`AttributeError: _record_depth`).

- [ ] **Step 3: Implement** — add to `dlq_intel.py` (imports at top: `from contextlib import closing`, `import db`, `from config import settings`):

```python
from contextlib import closing

import db
from config import settings

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
    """growing / draining / stable from the oldest kept sample; unknown if none."""
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT depth FROM dlq_intel_history WHERE queue=? ORDER BY ts ASC LIMIT 1",
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
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit**
```bash
git add backend/dlq_intel.py backend/tests/test_dlq_intel.py
git commit -m "feat(dlq): depth-history trend (growing/stable/draining)"
```

---

## Task 4: Smart verdict

**Files:** Modify `backend/dlq_intel.py`; append to test file.

- [ ] **Step 1: Write the failing test** — append:

```python
def test_verdict_growing_is_critical(store):
    v = dlq_intel._verdict(depth=240, source_consumers=2, trend="growing",
                           oldest_age=3 * 3600,
                           reasons=[{"reason": "max-retries", "count": 200},
                                    {"reason": "rejected", "count": 40}],
                           source="order-service")
    assert v["severity"] == "critical"
    assert "groeit" in v["headline"]
    assert "max-retries" in v["headline"]
    assert v["action"]


def test_verdict_no_consumer_is_critical(store):
    v = dlq_intel._verdict(depth=12, source_consumers=0, trend="stable",
                           oldest_age=600, reasons=[{"reason": "expired", "count": 12}],
                           source="x")
    assert v["severity"] == "critical"


def test_verdict_parked_long_is_warn(store):
    old = int(6 * 86400)  # 6 days
    v = dlq_intel._verdict(depth=12, source_consumers=2, trend="stable",
                           oldest_age=old, reasons=[{"reason": "rejected", "count": 12}],
                           source="x")
    assert v["severity"] == "warn"
    assert "geparkeerd" in v["headline"].lower()


def test_verdict_empty_is_ok(store):
    v = dlq_intel._verdict(depth=0, source_consumers=2, trend="stable",
                           oldest_age=None, reasons=[], source="x")
    assert v["severity"] == "ok"
```

- [ ] **Step 2: Run → fail** (`AttributeError: _verdict`).

- [ ] **Step 3: Implement** — add to `dlq_intel.py`:

```python
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
    if len({r["reason"] for r in reasons}) > 1:
        reason_txt = "gemengde oorzaken" if dominant == "onbekend" else reason_txt
    icon = "🔴" if severity == "critical" else "🟡"
    label = "Actief probleem" if severity == "critical" else (
        "Geparkeerd" if parked else "Lichte ophoping")
    headline = f"{icon} {label} — {state} · {' · '.join(bits)} · {reason_txt}"
    return {"severity": severity, "headline": headline,
            "action": _ACTION.get(dominant, _ACTION["onbekend"]), "trend": trend}
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit**
```bash
git add backend/dlq_intel.py backend/tests/test_dlq_intel.py
git commit -m "feat(dlq): smart verdict (depth+age+trend+reason -> severity/headline/action)"
```

---

## Task 5: Peek (read-only) + reason grouping

**Files:** Modify `backend/dlq_intel.py`; append to test file.

- [ ] **Step 1: Write the failing test** — append:

```python
import httpx


def test_peek_uses_reject_requeue_true_and_groups(monkeypatch, store):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return [_msg("rejected"), _msg("delivery_limit"), _msg("delivery_limit")]

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, auth=None, headers=None):
            captured["url"] = url
            captured["body"] = json
            return FakeResp()

    monkeypatch.setattr(dlq_intel.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(settings, "rabbitmq_api_url", "https://rmq.example")
    monkeypatch.setattr(settings, "rabbitmq_user", "u")
    monkeypatch.setattr(settings, "rabbitmq_password", "p")

    import asyncio
    sample, reasons = asyncio.run(dlq_intel._peek("/", "export.dlq"))
    assert captured["body"]["ackmode"] == "reject_requeue_true"   # non-destructive
    assert captured["body"]["count"] == settings.dlq_intel_peek_max
    assert "/api/queues/%2F/export.dlq/get" in captured["url"]
    # grouped, most-common first
    assert reasons[0] == {"reason": "max-retries", "count": 2}
    assert len(sample) == 3


def test_peek_failure_returns_empty(monkeypatch, store):
    class BoomClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise httpx.HTTPError("boom")
    monkeypatch.setattr(dlq_intel.httpx, "AsyncClient", BoomClient)
    monkeypatch.setattr(settings, "rabbitmq_api_url", "https://rmq.example")
    monkeypatch.setattr(settings, "rabbitmq_user", "u")
    monkeypatch.setattr(settings, "rabbitmq_password", "p")
    import asyncio
    sample, reasons = asyncio.run(dlq_intel._peek("/", "export.dlq"))
    assert sample == [] and reasons == []
```

- [ ] **Step 2: Run → fail** (`AttributeError: _peek`; also add `import httpx` at top of dlq_intel).

- [ ] **Step 3: Implement** — add to `dlq_intel.py` (add `import httpx` and `from urllib.parse import quote` at top):

```python
import httpx
from urllib.parse import quote


async def _peek(vhost: str, name: str) -> tuple[list[dict], list[dict]]:
    """Read-only peek: GET messages with ackmode=reject_requeue_true (requeued
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
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit**
```bash
git add backend/dlq_intel.py backend/tests/test_dlq_intel.py
git commit -m "feat(dlq): read-only peek (reject_requeue_true) + reason grouping"
```

---

## Task 6: scan() orchestration + loop + latest()

**Files:** Modify `backend/dlq_intel.py`; append to test file.

- [ ] **Step 1: Write the failing test** — append:

```python
def test_scan_builds_enriched_view(monkeypatch, store):
    monkeypatch.setattr(settings, "dlq_intel_enabled", True)

    async def fake_base():
        return {"configured": True, "dlqs": [
            {"name": "export.dlq", "vhost": "/", "depth": 240, "source": "export",
             "source_consumers": 2, "severity": "warn", "first_seen": None},
            {"name": "antivirus.dlq", "vhost": "/", "depth": 0, "source": "antivirus",
             "source_consumers": 1, "severity": "ok", "first_seen": None},
        ]}
    monkeypatch.setattr(dlq_intel.rabbitmq_dlq, "latest", fake_base)

    async def fake_peek(vhost, name):
        return ([{"reason": "max-retries", "source": "export", "routing": "x",
                  "age_seconds": 3 * 3600}],
                [{"reason": "max-retries", "count": 240}])
    monkeypatch.setattr(dlq_intel, "_peek", fake_peek)

    import asyncio
    view = asyncio.run(dlq_intel.scan())
    assert view["configured"] is True
    q = {x["name"]: x for x in view["queues"]}
    assert q["export.dlq"]["severity"] == "critical"   # 240 >= rabbitmq_critical_messages
    assert q["export.dlq"]["reasons"][0]["reason"] == "max-retries"
    assert q["antivirus.dlq"]["severity"] == "ok"       # empty, not peeked
    assert view["verdict"] in ("CRITICAL", "WARN", "OK")
```

- [ ] **Step 2: Run → fail** (`AttributeError: scan`; add `import rabbitmq_dlq`).

- [ ] **Step 3: Implement** — add to `dlq_intel.py` (add `import asyncio`, `import rabbitmq_dlq` at top):

```python
import asyncio

import rabbitmq_dlq

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
        return _latest or {"configured": True, "queues": [], "verdict": "OK", "error": "rabbitmq unreachable"}
    dlqs = base.get("dlqs", []) if base.get("configured") is not False else []
    queues: list[dict] = []
    for d in dlqs:
        depth = int(d.get("depth") or 0)
        _record_depth(d["name"], depth)
        if depth > 0:
            sample, reasons = await _peek(d.get("vhost", "/"), d["name"])
            peeked = bool(sample)
            oldest = max((s["age_seconds"] for s in sample if s["age_seconds"] is not None),
                         default=None)
        else:
            sample, reasons, peeked, oldest = [], [], True, None
        v = _verdict(depth, d.get("source_consumers"), _trend(d["name"], depth),
                     oldest, reasons, d.get("source") or "")
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
```

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit**
```bash
git add backend/dlq_intel.py backend/tests/test_dlq_intel.py
git commit -m "feat(dlq): scan orchestration, verdict assembly, background loop"
```

---

## Task 7: API endpoint

**Files:** Create `backend/dlq_intel_api.py`; append to test file.

- [ ] **Step 1: Write the failing test** — append:

```python
def test_api_disabled_returns_flag(monkeypatch):
    import dlq_intel_api
    from config import settings
    monkeypatch.setattr(settings, "dlq_intel_enabled", False)
    import asyncio
    out = asyncio.run(dlq_intel_api.intel(session={"username": "x"}))
    assert out == {"enabled": False}
```

- [ ] **Step 2: Run → fail** (`ModuleNotFoundError: dlq_intel_api`).

- [ ] **Step 3: Implement** — create `backend/dlq_intel_api.py`:

```python
"""DLQ Intelligence API — read-only, gated by the existing `rabbitmq` grant.
200 {enabled:false} when the flag is off (instant rollback)."""
import logging

from fastapi import APIRouter, Depends, HTTPException

import dlq_intel
from auth import require_feature
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard/dlq")


@router.get("/intel")
async def intel(session: dict = Depends(require_feature("rabbitmq"))):
    if not settings.dlq_intel_enabled:
        return {"enabled": False}
    try:
        view = await dlq_intel.latest()
        return {"enabled": True, **view}
    except Exception as e:  # noqa: BLE001 — degrade, never 500 the dashboard
        logger.error("dlq_intel status failed: %s", e)
        raise HTTPException(status_code=502, detail="DLQ intelligence unavailable") from e
```

> The test calls `intel(session=...)` directly; passing `session` bypasses the
> `Depends` (fine for a unit test of the flag branch).

- [ ] **Step 4: Run → pass.**
- [ ] **Step 5: Commit**
```bash
git add backend/dlq_intel_api.py backend/tests/test_dlq_intel.py
git commit -m "feat(dlq): read-only /dashboard/dlq/intel endpoint"
```

---

## Task 8: Wire router + loop into main.py

**Files:** Modify `backend/main.py`.

- [ ] **Step 1:** Add imports near the other feature imports (after `from alerts import run_alert_loop`):

```python
from dlq_intel_api import router as dlq_intel_router
from dlq_intel import run_dlq_intel_loop
```

- [ ] **Step 2:** Add `app.include_router(dlq_intel_router)` after `app.include_router(alerts_router)`.

- [ ] **Step 3:** In `lifespan`, add next to the other tasks:
```python
    dlq_intel_task = asyncio.create_task(run_dlq_intel_loop())
```
and add `dlq_intel_task` to the cancel tuple `for t in (cert_task, dlq_task, uptime_task, alerts_task, dlq_intel_task):`.

- [ ] **Step 4: Verify routes + run module test**
```bash
cd backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 docker run --rm -v "$HP:/app" -w /app python:3.13 \
  sh -c "pip install -q -r requirements.txt 2>/dev/null && python -c 'import main; print([r.path for r in main.app.routes if \"/dlq/intel\" in getattr(r,\"path\",\"\")])' && python -m pytest tests/test_dlq_intel.py -q | tail -3"
```
Expected: `['/dashboard/dlq/intel']` then all tests pass.

- [ ] **Step 5: Commit**
```bash
git add backend/main.py
git commit -m "feat(dlq): register DLQ Intelligence router and background loop"
```

---

## Task 9: Enrich DLQ alerts from the intelligence

**Files:** Modify `backend/alerts.py`, `backend/alerts_mattermost.py`, `backend/alerts_email.py` (all my feature files); append to test file.

- [ ] **Step 1: Write the failing test** — append:

```python
def test_alert_item_enriched_from_intel(monkeypatch, store):
    import alerts
    monkeypatch.setattr(settings, "dlq_intel_enabled", True)
    intel_view = {"configured": True, "queues": [
        {"name": "export.dlq", "source": "export", "depth": 240, "severity": "critical",
         "headline": "🔴 Actief probleem — groeit · 240 berichten · oudste 3u · vooral max-retries op export",
         "action": "Poison-message...", "trend": "growing", "oldest_age_seconds": 10800,
         "reasons": [{"reason": "max-retries", "count": 240}], "sample": [], "peeked": True}]}
    items = alerts._normalize_dlq_intel(intel_view)
    it = items[0]
    assert it["category"] == "dlq" and it["severity"] == "critical"
    assert "max-retries" in it["status"]      # reason surfaced into the alert status
    assert it["detail"]                        # recommended action carried along
```

- [ ] **Step 2: Run → fail** (`AttributeError: _normalize_dlq_intel`).

- [ ] **Step 3: Implement.** In `backend/alerts.py` add a new normalizer (next to `_normalize_dlq`):

```python
def _normalize_dlq_intel(view: dict | None) -> list[dict]:
    """Richer DLQ items from dlq_intel: severity = smart verdict; status/detail carry
    the reason + headline + action so the email/Mattermost can show *why*."""
    if not view or not view.get("configured"):
        return []
    out: list[dict] = []
    for q in view.get("queues", []):
        top = q["reasons"][0]["reason"] if q.get("reasons") else "onbekend"
        status = f"{q['depth']} berichten · {q.get('trend','?')} · vooral {top}"
        item = _item(CATEGORY_DLQ, "PROD", q["name"], q["severity"], status,
                     q.get("action", ""))
        item["headline"] = q.get("headline", "")
        item["reasons"] = q.get("reasons", [])
        item["oldest_age_seconds"] = q.get("oldest_age_seconds")
        out.append(item)
    return out
```

Then in `_collect()`, replace the DLQ branch to prefer intel when enabled:

```python
    try:
        if settings.dlq_intel_enabled:
            import dlq_intel
            items += _normalize_dlq_intel(await dlq_intel.latest())
        else:
            items += _normalize_dlq(await rabbitmq_dlq.latest())
    except Exception as e:  # noqa: BLE001
        logger.error("alerts: dlq collect failed: %s", e)
```

- [ ] **Step 4:** Make the renderers show the extras when present. In `alerts_mattermost.py`, inside `payload(...)` after building `fields`, add (before the action append):

```python
    if item.get("category") == "dlq" and item.get("reasons"):
        top = item["reasons"][0]
        fields.append({"short": True, "title": "Top-oorzaak",
                       "value": f"{top['reason']} ({top['count']}×)"})
```

In `alerts_email.py` `render(...)`, add `("Oorzaak (DLQ)", ...)` to `fields` when present — insert before the `("Suggested action", action)` line:

```python
    if item.get("reasons"):
        top = item["reasons"][0]
        fields.append(("Top-oorzaak (DLQ)", f"{top['reason']} ({top['count']}×)"))
```

(Place this list-append just before the `("Dashboard", dashboard_url)` entry by building `fields` first, then inserting — keep it simple: append after the base fields list is created and before `text`/`rows` are computed.)

- [ ] **Step 5: Run the alerts + dlq tests**
```bash
cd backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 docker run --rm -v "$HP:/app" -w /app python:3.13 \
  sh -c "pip install -q -r requirements.txt 2>/dev/null && python -m pytest tests/test_dlq_intel.py tests/test_alerts.py -q | tail -4"
```
Expected: all pass.

- [ ] **Step 6: Commit**
```bash
git add backend/alerts.py backend/alerts_mattermost.py backend/alerts_email.py backend/tests/test_dlq_intel.py
git commit -m "feat(dlq): enrich DLQ alerts with reason/trend/action from intelligence"
```

---

## Task 10: Frontend — page, card verdict line, nav

**Files:** Create `frontend/src/DlqIntel.jsx`; modify `frontend/src/api.js`, `App.jsx`, `Nav.jsx`, `Dashboard.jsx`.

> No frontend unit tests; verify by `npm run build` + manual smoke.

- [ ] **Step 1: API helper** — append to `frontend/src/api.js`:
```js
export const fetchDlqIntel = (token) => getJSON("/dashboard/dlq/intel", token);
```

- [ ] **Step 2: Create `frontend/src/DlqIntel.jsx`** (built on the dashboard design system — `.panel`, `.up-tile`, `.dash-table`, severity colours):

```jsx
import { useEffect, useState, useCallback } from "react";
import TopNav from "./Nav";
import { fetchDlqIntel } from "./api";

const SEV = { ok: "#3fb950", warn: "#d29922", critical: "#f85149" };
const TILE = { ok: "up", warn: "warn", critical: "down" };

function age(s) {
  if (s == null) return "?";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}u`;
  return `${Math.floor(s / 86400)}d`;
}

export default function DlqIntelPage({
  token, username, onLogout, onNavigate, llmProvider, onProviderChange,
  can = () => true, isAdmin = false, aanleverCount, dlqCount,
}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try { setData(await fetchDlqIntel(token)); setError(null); }
    catch (e) { setError(String(e.message || e)); }
  }, [token]);
  useEffect(() => { load(); }, [load]);

  const nav = (
    <TopNav active="dlq-intel" brandMark="🐰" brandName="DLQ Intelligentie" brandSub="Dead-letter queues · admin"
            can={can} isAdmin={isAdmin} username={username} onLogout={onLogout}
            onNavigate={onNavigate} llmProvider={llmProvider} onProviderChange={onProviderChange}
            aanleverCount={aanleverCount} dlqCount={dlqCount} />
  );

  if (data && data.enabled === false) {
    return <>{nav}<div className="chat-scroll"><div className="dash">
      <section className="panel"><h3>🐰 DLQ Intelligentie</h3>
        <p className="muted">Uitgeschakeld (<code>DLQ_INTEL_ENABLED=false</code>).</p></section>
    </div></div></>;
  }
  if (!data) return <>{nav}<div className="chat-scroll"><div className="dash">
    <section className="panel"><p className="muted">Laden…</p></section></div></div></>;

  const queues = (data.queues || []).filter((q) => q.depth > 0);
  return <>{nav}<div className="chat-scroll"><div className="dash">
    {error && <div className="error">{error}</div>}
    <section className="panel">
      <h3>🐰 DLQ Intelligentie</h3>
      <p className="muted set-intro">Waarom staan er berichten vast? Per queue: oorzaak, leeftijd, trend en aanbevolen actie. Alleen-lezen.</p>
      {queues.length === 0 && <p className="muted">✓ Alle dead-letter queues zijn leeg.</p>}
    </section>
    {queues.map((q) => (
      <section key={q.name} className={`panel up-tile up-tile--${TILE[q.severity]}`} style={{ marginBottom: 12 }}>
        <h3 style={{ color: SEV[q.severity] }}>{q.headline}</h3>
        <div className="alerts-settings-row" style={{ gap: 28 }}>
          <div className="alerts-field"><label>Queue</label><b>{q.name}</b></div>
          <div className="alerts-field"><label>Diepte</label><b>{q.depth.toLocaleString("nl-NL")}</b></div>
          <div className="alerts-field"><label>Trend</label><b>{q.trend}</b></div>
          <div className="alerts-field"><label>Oudste</label><b>{age(q.oldest_age_seconds)}</b></div>
          <div className="alerts-field"><label>Consumers</label><b>{q.source_consumers ?? "—"}</b></div>
        </div>
        {q.action && <p style={{ marginTop: 8 }}>🛠️ <b>Actie:</b> {q.action}</p>}
        {q.reasons?.length > 0 && (
          <p className="muted">Oorzaken: {q.reasons.map((r) => `${r.reason} (${r.count}×)`).join(" · ")}</p>
        )}
        {q.sample?.length > 0 && (
          <table className="dash-table" style={{ marginTop: 8 }}>
            <thead><tr><th>Oorzaak</th><th>Bron</th><th>Routing</th><th>Leeftijd</th></tr></thead>
            <tbody>
              {q.sample.map((s, i) => (
                <tr key={i}><td>{s.reason}</td><td>{s.source}</td><td>{s.routing}</td><td>{age(s.age_seconds)}</td></tr>
              ))}
            </tbody>
          </table>
        )}
        {!q.peeked && <p className="muted">⚠ Berichten konden niet gelezen worden — alleen telling.</p>}
      </section>
    ))}
  </div></div></>;
}
```

- [ ] **Step 3: Route in `App.jsx`** — add `import DlqIntelPage from "./DlqIntel";` near the other imports, and a render branch (mirror the Alerts branch) before the chat fallback:

```jsx
  if (view === "dlq-intel" && can("rabbitmq")) {
    return (
      <DlqIntelPage
        token={token} username={username} onLogout={handleLogout} onNavigate={navigate}
        llmProvider={effectiveProvider} onProviderChange={handleProviderChange}
        can={can} isAdmin={isAdmin} aanleverCount={aanleverCount} dlqCount={dlqCount}
      />
    );
  }
```

- [ ] **Step 4: Nav** — in `frontend/src/Nav.jsx`, add `"dlq-intel"` to the `BEHEER_SUB` set so the bar stays consistent:
```js
const BEHEER_SUB = new Set(["admin", "settings", "regression", "authorization", "alerts", "dlq-intel"]);
```

- [ ] **Step 5: Card verdict line + link** — in `frontend/src/Dashboard.jsx` `DlqCard`, add a button to the header that navigates to the page. The card receives `onNavigate` — confirm it's threaded; if not, add it to `DlqCard({ data, onNavigate })` and pass it where `<DlqCard` is rendered. Add after the `<span className="dlq-summary">…</span>` block, inside the `<h3>`:

```jsx
        <button type="button" className="btn btn--ghost" style={{ marginLeft: "auto", fontSize: 12 }}
                onClick={() => onNavigate && onNavigate("dlq-intel")}>
          🔍 Intelligentie
        </button>
```

(If `onNavigate` isn't already passed to `DlqCard`, thread it from the Dashboard render: `<DlqCard data={dlq} onNavigate={onNavigate} />`.)

- [ ] **Step 6: Build**
```bash
cd frontend && npm run build
```
Expected: build succeeds, no missing-import errors.

- [ ] **Step 7: Commit**
```bash
git add frontend/src/DlqIntel.jsx frontend/src/api.js frontend/src/App.jsx frontend/src/Nav.jsx frontend/src/Dashboard.jsx
git commit -m "feat(dlq): DLQ Intelligence page + dashboard card link"
```

---

## Task 11: Dutch vault doc + Home link + full regression

**Files:** Create `docs/KIBANA-OO/DLQ intelligentie.md`; modify `docs/KIBANA-OO/Home.md`.

- [ ] **Step 1: Write the Dutch note** (audience = beheerder): Wat & waarom, Hoe te gebruiken (Beheer/Dashboard → 🔍 Intelligentie), een echt voorbeeld (export.dlq, 240 berichten, max-retries), betekenis van de kleuren/verdict/trend, oorzaak-types (rejected/expired/max-retries/maxlen) + acties, configuratie (`DLQ_INTEL_*`), randgevallen (peek faalt → alleen telling), en rollback (`DLQ_INTEL_ENABLED=false`). Link `[[Dead-letter queues]]`/`[[Woo Gateway]]` and `[[Alerting (meldingen)]]`.

- [ ] **Step 2: Link from `Home.md`** — add under the dashboard section:
```markdown
- [[DLQ intelligentie]] — 🇳🇱 waarom staan er berichten vast in een dead-letter queue? Oorzaak, leeftijd, trend, aanbevolen actie (alleen-lezen peek)
```

- [ ] **Step 3: Full backend suite**
```bash
cd backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 docker run --rm -v "$HP:/app" -w /app python:3.13 \
  sh -c "pip install -q -r requirements.txt 2>/dev/null && python -m pytest -q | tail -5"
```
Expected: all pass (existing + new `test_dlq_intel.py`).

- [ ] **Step 4: Commit**
```bash
git add "docs/KIBANA-OO/DLQ intelligentie.md" "docs/KIBANA-OO/Home.md"
git commit -m "docs(dlq): Dutch vault note + Home link for DLQ Intelligence"
```

---

## Self-review — spec coverage

| Spec requirement | Task |
|---|---|
| `dlq_intel` reuses `rabbitmq_dlq`, additive | T6 |
| Read-only peek (`reject_requeue_true`, ≤20, ~90s) | T5, T1 |
| x-death reason/source/age parse | T2 |
| Trend from depth history | T3 |
| Smart verdict (depth+age+trend+reason) + action | T4 |
| `dlq_intel_history` table | T3 |
| Read-only API, `rabbitmq` grant | T7 |
| Card verdict line + dedicated page (Q4 C) | T10 |
| Smarter alerts from same source (Q1 C) | T9 |
| Flag `DLQ_INTEL_ENABLED`, rollback | T1, T7 |
| Graceful peek-failure fallback | T5, T6 |
| Dutch doc | T11 |
| Tests: parse/verdict/trend/peek-non-destructive/peek-fail/api/alert-enrich | T2–T9 |

**Placeholder scan:** none — every code step is complete.
**Type consistency:** queue record keys (`name/source/depth/source_consumers/severity/headline/action/trend/oldest_age_seconds/reasons/sample/peeked`), failure keys (`reason/source/routing/age_seconds`), and `_verdict`/`_trend`/`_peek`/`_parse_failure`/`scan`/`latest`/`_normalize_dlq_intel` names are used identically across T2–T10.
