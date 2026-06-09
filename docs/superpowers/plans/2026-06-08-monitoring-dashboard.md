# Admin Monitoring Dashboard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-only `/dashboard` page to KIBANA-OO that shows the day's critical issues (error logs + HTTP 5xx + APM errors) per data view, with a grounded AI triage briefing, computed from deterministic Elasticsearch aggregations.

**Architecture:** A new FastAPI fact layer (`monitoring.py`) runs ES aggregations via the existing Kibana proxy and returns one consistent snapshot. A `dashboard.py` router exposes admin-gated `/dashboard/summary` and `/dashboard/briefing` endpoints (cached). The React frontend adds a `Dashboard` page reachable via a Chat⇄Dashboard nav toggle shown to admins. Every displayed number comes from the fact layer; the LLM only narrates facts it is handed.

**Tech Stack:** Python 3.13, FastAPI, httpx, pydantic, pytest + pytest-asyncio (new); React 19, Vite; nginx; Docker Compose.

**Reference spec:** `docs/superpowers/specs/2026-06-08-monitoring-dashboard-design.md`

---

## File Structure

```
backend/
  session.py        # NEW — extracted in-memory session store (shared by main + dashboard)
  auth.py           # NEW — require_admin dependency (allowlist gating)
  monitoring.py     # NEW — fact layer: day bounds, critical query, aggregations, snapshot
  briefing.py       # NEW — grounded prompt builder + briefing generation
  dashboard.py      # NEW — /dashboard/* router (admin-gated, cached)
  cache.py          # NEW — tiny TTL cache helper
  config.py         # MODIFY — dashboard settings
  main.py           # MODIFY — use session.py, include dashboard router
  requirements.txt  # MODIFY — add pytest, pytest-asyncio
  tests/            # NEW — pytest suite
    conftest.py
    test_config.py
    test_auth.py
    test_monitoring.py
    test_briefing.py
    test_dashboard.py
frontend/
  src/api.js          # NEW — dashboard API client helpers
  src/Dashboard.jsx   # NEW — dashboard page + panels
  src/App.jsx         # MODIFY — Chat⇄Dashboard nav toggle (admin only)
  src/styles.css      # MODIFY — dashboard styles
  nginx.conf          # MODIFY — proxy /dashboard/
.env.example          # MODIFY — document new settings
```

**Admin gating note:** The spec's primary choice (Keycloak group claim) requires OIDC claims this app does not currently capture — `keycloak_login` returns only the `sid` cookie, not the user's groups. This plan therefore implements the **env allowlist (option C)** concretely and testably, and leaves a documented extension point for the group claim (option B) once claim capture is added. This matches the spec's "verify at build start; fallback is safe either way."

---

## Task 0: Test infrastructure

**Files:**
- Modify: `backend/requirements.txt`
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/conftest.py`
- Create: `backend/pytest.ini`

- [ ] **Step 1: Add test deps to `backend/requirements.txt`**

Append these two lines (keep existing lines unchanged):

```
pytest==8.3.4
pytest-asyncio==0.25.2
```

- [ ] **Step 2: Create `backend/pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 3: Create `backend/tests/__init__.py`** (empty file)

```python
```

- [ ] **Step 4: Create `backend/tests/conftest.py`**

```python
"""Shared test fixtures. Backend modules import from the backend/ root,
so tests run with backend/ on sys.path (pytest rootdir = backend/)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 5: Install deps and verify pytest collects nothing yet**

Run (from `backend/`): `pip install -r requirements.txt && python -m pytest -q`
Expected: `no tests ran` (exit 5) or `0 passed` — pytest is installed and importable.

- [ ] **Step 6: Commit**

```bash
git add backend/requirements.txt backend/pytest.ini backend/tests/__init__.py backend/tests/conftest.py
git commit -m "test: add pytest + pytest-asyncio infrastructure"
```

---

## Task 1: Dashboard config settings

**Files:**
- Modify: `backend/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_config.py
from config import Settings


def test_dashboard_defaults():
    s = Settings()
    assert s.dashboard_cache_ttl == 60
    assert s.dashboard_timezone == "Europe/Amsterdam"
    assert s.dashboard_superset_views == "logs-*"


def test_admin_list_parsing():
    s = Settings(dashboard_admins="a@x.nl, b@y.nl ,a@x.nl")
    assert s.admin_list == ["a@x.nl", "b@y.nl"]  # trimmed + de-duped


def test_rollup_views_excludes_superset():
    s = Settings(
        data_views="logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp",
        dashboard_superset_views="logs-*",
    )
    assert s.rollup_views == ["ds-prod5-koop-plooi*", "ds-prod5-koop-sp"]
    assert s.rollup_index == "ds-prod5-koop-plooi*,ds-prod5-koop-sp"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'dashboard_cache_ttl'`

- [ ] **Step 3: Add settings to `backend/config.py`**

Inside the `Settings` class, after the `default_data_view` field, add:

```python
    # Dashboard
    dashboard_cache_ttl: int = 60          # seconds; summary cache TTL
    dashboard_timezone: str = "Europe/Amsterdam"
    dashboard_admins: str = ""             # comma-separated admin usernames/emails
    # Views treated as a superset of others — excluded from rollup totals to avoid
    # double counting (still shown as their own per-system tile).
    dashboard_superset_views: str = "logs-*"
```

And add these properties after the existing `data_view_list` property:

```python
    @property
    def admin_list(self) -> list[str]:
        seen: list[str] = []
        for name in self.dashboard_admins.split(","):
            name = name.strip()
            if name and name not in seen:
                seen.append(name)
        return seen

    @property
    def rollup_views(self) -> list[str]:
        """Data views used for rollup totals (superset views excluded)."""
        superset = {v.strip() for v in self.dashboard_superset_views.split(",") if v.strip()}
        return [v for v in self.data_view_list if v not in superset]

    @property
    def rollup_index(self) -> str:
        """Comma-joined ES index string for the rollup query."""
        return ",".join(self.rollup_views) or self.es_log_index
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Document settings in `.env.example`**

After the `DEFAULT_DATA_VIEW=logs-*` line, append:

```
# Dashboard (admin monitoring)
DASHBOARD_CACHE_TTL=60
DASHBOARD_TIMEZONE=Europe/Amsterdam
# Comma-separated admin usernames/emails allowed to see the dashboard.
DASHBOARD_ADMINS=anton.partono@koop.overheid.nl
# Views excluded from rollup totals to avoid double counting (still shown per-system).
DASHBOARD_SUPERSET_VIEWS=logs-*
```

- [ ] **Step 6: Commit**

```bash
git add backend/config.py backend/tests/test_config.py .env.example
git commit -m "feat(dashboard): add dashboard config settings"
```

---

## Task 2: Extract session store into `session.py`

**Files:**
- Create: `backend/session.py`
- Modify: `backend/main.py`

This removes the in-memory session dict from `main.py` so both `main.py` and the dashboard router can use it without a circular import.

- [ ] **Step 1: Create `backend/session.py`**

```python
"""In-memory session store: token -> {username, sid}.

Single source of truth for sessions, shared by the auth endpoints and the
dashboard router. In-memory by design (sessions reset on restart).
"""
import secrets

from fastapi import Header, HTTPException

# token -> {"username": str, "sid": str}
_sessions: dict[str, dict] = {}


def create_session(username: str, sid: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"username": username, "sid": sid}
    return token


def drop_session(token: str) -> None:
    _sessions.pop(token, None)


def _token_from_header(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not logged in")
    return authorization[7:]


def require_session(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: validate the Bearer token, return the session dict."""
    token = _token_from_header(authorization)
    session = _sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return session
```

- [ ] **Step 2: Refactor `backend/main.py` to use it**

Remove the module-level `_sessions: dict[str, dict] = {}` line and the local `_get_session` function. Replace the imports and the session usages:

Change the import block to add:

```python
from session import create_session, drop_session, require_session
```

In `login`, replace the token-creation block:

```python
    # Create session token
    token = create_session(username, sid)
```

In `logout`, replace the body with:

```python
    if authorization and authorization.startswith("Bearer "):
        drop_session(authorization[7:])
    return {"status": "ok"}
```

In `chat`, replace `session = _get_session(authorization)` by switching the handler to depend on the shared dependency. Change the signature:

```python
@app.post("/chat")
async def chat(
    request: ChatRequest,
    session: dict = Depends(require_session),
):
```

Add `Depends` to the FastAPI import line:

```python
from fastapi import FastAPI, HTTPException, Header, Depends
```

Delete the now-unused `_get_session` function entirely.

- [ ] **Step 3: Verify the app still imports**

Run (from `backend/`): `python -c "import main; print('ok')"`
Expected: `ok` (no ImportError, no circular import)

- [ ] **Step 4: Commit**

```bash
git add backend/session.py backend/main.py
git commit -m "refactor: extract session store into session.py"
```

---

## Task 3: `require_admin` dependency

**Files:**
- Create: `backend/auth.py`
- Test: `backend/tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_auth.py
import pytest
from fastapi import HTTPException

import auth


def test_admin_allowed(monkeypatch):
    monkeypatch.setattr(auth.settings, "dashboard_admins", "boss@koop.nl")
    session = {"username": "boss@koop.nl", "sid": "x"}
    assert auth.require_admin(session) is session


def test_non_admin_forbidden(monkeypatch):
    monkeypatch.setattr(auth.settings, "dashboard_admins", "boss@koop.nl")
    session = {"username": "intern@koop.nl", "sid": "x"}
    with pytest.raises(HTTPException) as exc:
        auth.require_admin(session)
    assert exc.value.status_code == 403


def test_empty_allowlist_forbids_everyone(monkeypatch):
    monkeypatch.setattr(auth.settings, "dashboard_admins", "")
    session = {"username": "anyone@koop.nl", "sid": "x"}
    with pytest.raises(HTTPException) as exc:
        auth.require_admin(session)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth'`

- [ ] **Step 3: Create `backend/auth.py`**

```python
"""Admin authorization for dashboard endpoints.

v1 gates on an env allowlist (DASHBOARD_ADMINS). Extension point: when the
Keycloak OIDC claims (groups/roles) are captured at login, add a group check
here (e.g. session.get("groups")) before the allowlist fallback.
"""
from fastapi import Depends, HTTPException

from config import settings
from session import require_session


def require_admin(session: dict = Depends(require_session)) -> dict:
    """FastAPI dependency: 401 if not logged in, 403 if not an admin."""
    username = (session.get("username") or "").strip()
    if username and username in settings.admin_list:
        return session
    raise HTTPException(status_code=403, detail="Administrator access required")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_auth.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/auth.py backend/tests/test_auth.py
git commit -m "feat(dashboard): add require_admin allowlist gating"
```

---

## Task 4: Day bounds (timezone-aware calendar day)

**Files:**
- Create: `backend/monitoring.py`
- Test: `backend/tests/test_monitoring.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_monitoring.py
from datetime import datetime, timezone

import monitoring


def test_day_bounds_explicit_date_amsterdam_summer():
    # 2026-06-08 is CEST (UTC+2): local midnight = 22:00 UTC the day before.
    start, end = monitoring.day_bounds("2026-06-08", "Europe/Amsterdam")
    assert start == datetime(2026, 6, 7, 22, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)


def test_day_bounds_utc():
    start, end = monitoring.day_bounds("2026-06-08", "UTC")
    assert start == datetime(2026, 6, 8, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 9, 0, 0, tzinfo=timezone.utc)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_monitoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'monitoring'`

- [ ] **Step 3: Create `backend/monitoring.py` with `day_bounds`**

```python
"""Dashboard fact layer: deterministic Elasticsearch aggregations via the
Kibana console proxy. Every number the dashboard shows is computed here."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from elastic import _es_search
from config import settings


def day_bounds(date_str: str | None, tz_name: str) -> tuple[datetime, datetime]:
    """Return the [start, end) UTC datetimes for the calendar day `date_str`
    (YYYY-MM-DD) in timezone `tz_name`. If date_str is None, use today in tz."""
    tz = ZoneInfo(tz_name)
    if date_str:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        day = datetime.now(tz).date()
    local_start = datetime.combine(day, time.min, tzinfo=tz)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_monitoring.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/monitoring.py backend/tests/test_monitoring.py
git commit -m "feat(dashboard): timezone-aware day bounds"
```

---

## Task 5: Critical query + aggregation body builders

**Files:**
- Modify: `backend/monitoring.py`
- Test: `backend/tests/test_monitoring.py`

- [ ] **Step 1: Write the failing test (append)**

```python
def test_critical_query_has_all_three_signals():
    start, end = monitoring.day_bounds("2026-06-08", "UTC")
    q = monitoring.critical_query(start, end)
    shoulds = q["bool"]["filter"][1]["bool"]["should"]
    kinds = {list(s.keys())[0] for s in shoulds}
    # log.level terms, error.message exists, 5xx range, apm processor.event
    assert "terms" in kinds and "exists" in kinds and "range" in kinds and "term" in kinds
    # time range present
    assert q["bool"]["filter"][0]["range"]["@timestamp"]["gte"] == start.isoformat()


def test_snapshot_body_is_size_zero_with_aggs():
    start, end = monitoring.day_bounds("2026-06-08", "UTC")
    body = monitoring.snapshot_body(start, end, "UTC")
    assert body["size"] == 0
    assert set(body["aggs"]) >= {"over_time", "signatures", "services", "status_codes"}


def test_baseline_body_daily_histogram():
    start, end = monitoring.day_bounds("2026-06-08", "UTC")
    body = monitoring.baseline_body(start, end, "UTC")
    assert body["size"] == 0
    agg = body["aggs"]["per_day"]["date_histogram"]
    assert agg["calendar_interval"] == "1d"
    # spans 7 days before the window start through the window end
    assert body["query"]["bool"]["filter"][0]["range"]["@timestamp"]["gte"] == (
        (start - __import__("datetime").timedelta(days=7)).isoformat()
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_monitoring.py -v`
Expected: FAIL — `AttributeError: module 'monitoring' has no attribute 'critical_query'`

- [ ] **Step 3: Add the builders to `backend/monitoring.py`**

```python
def critical_query(start: datetime, end: datetime) -> dict:
    """ES query: documents in [start, end) that are 'critical' — error-level
    logs, documents with an error.message, HTTP 5xx, or APM error events."""
    return {
        "bool": {
            "filter": [
                {"range": {"@timestamp": {"gte": start.isoformat(), "lte": end.isoformat()}}},
                {
                    "bool": {
                        "minimum_should_match": 1,
                        "should": [
                            {"terms": {"log.level": ["error", "ERROR", "fatal", "FATAL", "critical", "CRITICAL"]}},
                            {"exists": {"field": "error.message"}},
                            {"range": {"http.response.status_code": {"gte": 500}}},
                            {"term": {"processor.event": "error"}},
                        ],
                    }
                },
            ]
        }
    }


def snapshot_body(start: datetime, end: datetime, tz_name: str) -> dict:
    """size:0 aggregation body for one data view's day snapshot."""
    return {
        "size": 0,
        "track_total_hits": True,
        "query": critical_query(start, end),
        "aggs": {
            "over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": "1h",
                    "time_zone": tz_name,
                    "min_doc_count": 0,
                }
            },
            "signatures": {
                "terms": {"field": "error.type", "size": 10, "missing": "(untyped)"},
                "aggs": {
                    "first": {"min": {"field": "@timestamp"}},
                    "last": {"max": {"field": "@timestamp"}},
                },
            },
            "services": {"terms": {"field": "service.name", "size": 10}},
            "status_codes": {
                "filter": {"range": {"http.response.status_code": {"gte": 500}}},
                "aggs": {
                    "codes": {"terms": {"field": "http.response.status_code", "size": 10}},
                    "urls": {"terms": {"field": "url.path", "size": 10}},
                },
            },
        },
    }


def baseline_body(start: datetime, end: datetime, tz_name: str) -> dict:
    """size:0 daily histogram of criticals over the 7 days before `start`
    through `end`, for computing deltas."""
    base_start = start - timedelta(days=7)
    return {
        "size": 0,
        "query": critical_query(base_start, end),
        "aggs": {
            "per_day": {
                "date_histogram": {
                    "field": "@timestamp",
                    "calendar_interval": "1d",
                    "time_zone": tz_name,
                    "min_doc_count": 0,
                }
            }
        },
    }
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_monitoring.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/monitoring.py backend/tests/test_monitoring.py
git commit -m "feat(dashboard): critical query and aggregation bodies"
```

---

## Task 6: Aggregation parsers + status level

**Files:**
- Modify: `backend/monitoring.py`
- Test: `backend/tests/test_monitoring.py`

- [ ] **Step 1: Write the failing test (append)**

```python
SAMPLE_AGG_RESPONSE = {
    "hits": {"total": {"value": 42}},
    "aggregations": {
        "over_time": {"buckets": [
            {"key_as_string": "2026-06-08T09:00:00.000+02:00", "doc_count": 30},
            {"key_as_string": "2026-06-08T10:00:00.000+02:00", "doc_count": 12},
        ]},
        "signatures": {"buckets": [
            {"key": "NullPointerException", "doc_count": 30,
             "first": {"value_as_string": "2026-06-08T09:12:00Z"},
             "last": {"value_as_string": "2026-06-08T09:40:00Z"}},
        ]},
        "services": {"buckets": [{"key": "registration-service", "doc_count": 30}]},
        "status_codes": {"codes": {"buckets": [{"key": 500, "doc_count": 8}]},
                         "urls": {"buckets": [{"key": "/api/submit", "doc_count": 8}]}},
    },
}


def test_parse_aggs():
    parsed = monitoring.parse_aggs(SAMPLE_AGG_RESPONSE)
    assert parsed["total"] == 42
    assert parsed["timeseries"][0] == {"timestamp": "2026-06-08T09:00:00.000+02:00", "count": 30}
    assert parsed["signatures"][0]["signature"] == "NullPointerException"
    assert parsed["signatures"][0]["first_seen"] == "2026-06-08T09:12:00Z"
    assert parsed["services"][0] == {"name": "registration-service", "count": 30}
    assert parsed["status_codes"][0] == {"code": 500, "count": 8}
    assert parsed["failing_urls"][0] == {"url": "/api/submit", "count": 8}


def test_parse_baseline_deltas():
    # 8 daily buckets: 7 history (each 10) + current day (42)
    buckets = [{"doc_count": 10} for _ in range(7)] + [{"doc_count": 42}]
    resp = {"aggregations": {"per_day": {"buckets": buckets}}}
    previous, avg_7d = monitoring.parse_baseline(resp)
    assert previous == 10
    assert avg_7d == 10.0


def test_status_level():
    assert monitoring.status_level(0) == "ok"
    assert monitoring.status_level(5) == "degraded"
    assert monitoring.status_level(500) == "critical"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_monitoring.py -v`
Expected: FAIL — `AttributeError: module 'monitoring' has no attribute 'parse_aggs'`

- [ ] **Step 3: Add parsers to `backend/monitoring.py`**

```python
# Thresholds for the headline status banner (count of criticals in the window).
DEGRADED_AT = 1
CRITICAL_AT = 100


def parse_aggs(resp: dict) -> dict:
    aggs = resp.get("aggregations", {})
    timeseries = [
        {"timestamp": b["key_as_string"], "count": b["doc_count"]}
        for b in aggs.get("over_time", {}).get("buckets", [])
    ]
    signatures = [
        {
            "signature": b["key"],
            "count": b["doc_count"],
            "first_seen": b.get("first", {}).get("value_as_string"),
            "last_seen": b.get("last", {}).get("value_as_string"),
        }
        for b in aggs.get("signatures", {}).get("buckets", [])
    ]
    services = [
        {"name": b["key"], "count": b["doc_count"]}
        for b in aggs.get("services", {}).get("buckets", [])
    ]
    sc = aggs.get("status_codes", {})
    status_codes = [
        {"code": b["key"], "count": b["doc_count"]}
        for b in sc.get("codes", {}).get("buckets", [])
    ]
    failing_urls = [
        {"url": b["key"], "count": b["doc_count"]}
        for b in sc.get("urls", {}).get("buckets", [])
    ]
    return {
        "total": resp.get("hits", {}).get("total", {}).get("value", 0),
        "timeseries": timeseries,
        "signatures": signatures,
        "services": services,
        "status_codes": status_codes,
        "failing_urls": failing_urls,
    }


def parse_baseline(resp: dict) -> tuple[int, float]:
    """Return (previous_day_count, avg_of_7_history_days) from the daily histogram.
    The last bucket is the current day and is excluded from both."""
    buckets = resp.get("aggregations", {}).get("per_day", {}).get("buckets", [])
    history = [b["doc_count"] for b in buckets[:-1]]  # drop current day
    previous = history[-1] if history else 0
    last7 = history[-7:]
    avg_7d = round(sum(last7) / len(last7), 2) if last7 else 0.0
    return previous, avg_7d


def status_level(total: int) -> str:
    if total >= CRITICAL_AT:
        return "critical"
    if total >= DEGRADED_AT:
        return "degraded"
    return "ok"
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_monitoring.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/monitoring.py backend/tests/test_monitoring.py
git commit -m "feat(dashboard): aggregation parsers and status level"
```

---

## Task 7: Snapshot orchestration (concurrent, per-view isolation)

**Files:**
- Modify: `backend/monitoring.py`
- Test: `backend/tests/test_monitoring.py`

- [ ] **Step 1: Write the failing test (append)**

```python
import pytest


@pytest.fixture
def patched_es(monkeypatch):
    """Patch _es_search to return canned responses keyed by index string."""
    calls = {}

    async def fake_es(sid, index, body):
        calls.setdefault(index, []).append(body)
        # baseline body has a per_day agg; snapshot body has over_time
        if "per_day" in body.get("aggs", {}):
            return {"aggregations": {"per_day": {"buckets": (
                [{"doc_count": 10} for _ in range(7)] + [{"doc_count": 42}]
            )}}}
        if body.get("aggs"):  # snapshot agg body
            return SAMPLE_AGG_RESPONSE
        # per-view count body (size:0, track_total_hits, no aggs)
        return {"hits": {"total": {"value": 7 if "plooi" in index else 0}}}

    monkeypatch.setattr(monitoring, "_es_search", fake_es)
    monkeypatch.setattr(monitoring.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")
    monkeypatch.setattr(monitoring.settings, "dashboard_superset_views", "logs-*")
    return calls


async def test_build_snapshot_assembles_consistent_payload(patched_es):
    snap = await monitoring.build_snapshot("sid-123", "2026-06-08")
    assert snap.date == "2026-06-08"
    assert snap.total == 42                       # from rollup agg
    assert snap.delta.previous == 10
    assert snap.delta.avg_7d == 10.0
    assert snap.status_level == "degraded"
    # three per-system tiles, all available
    assert len(snap.systems) == 3
    assert all(s.available for s in snap.systems)
    assert snap.partial is False


async def test_build_snapshot_isolates_view_failure(monkeypatch, patched_es):
    async def flaky_es(sid, index, body):
        if index == "ds-prod5-koop-sp" and not body.get("aggs"):
            raise RuntimeError("view down")
        return await patched_es_original(sid, index, body)

    # wrap the fixture's fake
    patched_es_original = monitoring._es_search
    monkeypatch.setattr(monitoring, "_es_search", flaky_es)
    snap = await monitoring.build_snapshot("sid-123", "2026-06-08")
    sp = next(s for s in snap.systems if s.data_view == "ds-prod5-koop-sp")
    assert sp.available is False
    assert snap.partial is True
    # core numbers still present
    assert snap.total == 42
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_monitoring.py -v`
Expected: FAIL — `AttributeError: module 'monitoring' has no attribute 'build_snapshot'`

- [ ] **Step 3: Add models + orchestration to `backend/monitoring.py`**

Add the pydantic import at the top (with the other imports):

```python
import asyncio

from pydantic import BaseModel
```

Add at the end of the file:

```python
DATA_VIEW_LABELS = {
    "logs-*": "All logs",
    "ds-prod5-koop-plooi*": "KOOP Plooi (prod5)",
    "ds-prod5-koop-sp": "KOOP SP (prod5)",
}


class Delta(BaseModel):
    previous: int
    avg_7d: float
    pct_vs_previous: float | None = None
    pct_vs_avg: float | None = None


class SystemBreakdown(BaseModel):
    data_view: str
    label: str
    count: int = 0
    available: bool = True


class DashboardSnapshot(BaseModel):
    date: str
    window_start: str
    window_end: str
    total: int
    delta: Delta
    status_level: str
    systems: list[SystemBreakdown]
    timeseries: list[dict]
    top_signatures: list[dict]
    affected_services: list[dict]
    status_codes: list[dict]
    failing_urls: list[dict]
    partial: bool


async def _count(sid: str, index: str, start: datetime, end: datetime) -> int:
    body = {"size": 0, "track_total_hits": True, "query": critical_query(start, end)}
    resp = await _es_search(sid, index, body)
    return resp.get("hits", {}).get("total", {}).get("value", 0)


def _pct(curr: int, base: float) -> float | None:
    if not base:
        return None
    return round((curr - base) / base * 100, 1)


async def build_snapshot(sid: str, date_str: str | None) -> DashboardSnapshot:
    """Resolve the window once, fan out concurrent queries, assemble one
    consistent snapshot. Rollup numbers come from a single query over the
    non-superset views; per-system tiles are isolated counts."""
    tz = settings.dashboard_timezone
    start, end = day_bounds(date_str, tz)
    rollup_index = settings.rollup_index
    views = settings.data_view_list

    agg_task = _es_search(sid, rollup_index, snapshot_body(start, end, tz))
    base_task = _es_search(sid, rollup_index, baseline_body(start, end, tz))
    view_tasks = [_count(sid, v, start, end) for v in views]

    results = await asyncio.gather(agg_task, base_task, *view_tasks, return_exceptions=True)
    agg_res, base_res = results[0], results[1]
    view_counts = results[2:]

    if isinstance(agg_res, Exception):
        raise agg_res  # core rollup failed — surfaced as 502 by the router

    parsed = parse_aggs(agg_res)
    if isinstance(base_res, Exception):
        previous, avg_7d = 0, 0.0
    else:
        previous, avg_7d = parse_baseline(base_res)

    systems: list[SystemBreakdown] = []
    partial = isinstance(base_res, Exception)
    for view, count in zip(views, view_counts):
        label = DATA_VIEW_LABELS.get(view, view)
        if isinstance(count, Exception):
            partial = True
            systems.append(SystemBreakdown(data_view=view, label=label, available=False))
        else:
            systems.append(SystemBreakdown(data_view=view, label=label, count=count))

    total = parsed["total"]
    return DashboardSnapshot(
        date=date_str or start.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d"),
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        total=total,
        delta=Delta(
            previous=previous,
            avg_7d=avg_7d,
            pct_vs_previous=_pct(total, previous),
            pct_vs_avg=_pct(total, avg_7d),
        ),
        status_level=status_level(total),
        systems=systems,
        timeseries=parsed["timeseries"],
        top_signatures=parsed["signatures"],
        affected_services=parsed["services"],
        status_codes=parsed["status_codes"],
        failing_urls=parsed["failing_urls"],
        partial=partial,
    )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_monitoring.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/monitoring.py backend/tests/test_monitoring.py
git commit -m "feat(dashboard): snapshot orchestration with per-view isolation"
```

---

## Task 8: TTL cache helper

**Files:**
- Create: `backend/cache.py`
- Test: `backend/tests/test_dashboard.py` (cache tests live here; created now)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_dashboard.py
import cache


def test_ttl_cache_hit_and_expiry():
    clock = {"t": 1000.0}
    c = cache.TTLCache(ttl=60, now=lambda: clock["t"])
    c.set("k", "v")
    assert c.get("k") == "v"          # fresh
    clock["t"] = 1059.0
    assert c.get("k") == "v"          # still within TTL
    clock["t"] = 1061.0
    assert c.get("k") is None         # expired
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'cache'`

- [ ] **Step 3: Create `backend/cache.py`**

```python
"""Tiny in-memory TTL cache. `now` is injectable for testing."""
import time
from typing import Callable


class TTLCache:
    def __init__(self, ttl: float, now: Callable[[], float] = time.monotonic):
        self._ttl = ttl
        self._now = now
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if self._now() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: object) -> None:
        self._store[key] = (self._now() + self._ttl, value)

    def clear(self) -> None:
        self._store.clear()
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: PASS (1 test)

- [ ] **Step 5: Commit**

```bash
git add backend/cache.py backend/tests/test_dashboard.py
git commit -m "feat(dashboard): TTL cache helper"
```

---

## Task 9: Grounded briefing prompt builder

**Files:**
- Create: `backend/briefing.py`
- Test: `backend/tests/test_briefing.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_briefing.py
import briefing
from monitoring import DashboardSnapshot, Delta, SystemBreakdown


def _snapshot():
    return DashboardSnapshot(
        date="2026-06-08", window_start="s", window_end="e",
        total=42, delta=Delta(previous=10, avg_7d=10.0, pct_vs_previous=320.0, pct_vs_avg=320.0),
        status_level="degraded",
        systems=[SystemBreakdown(data_view="ds-prod5-koop-plooi*", label="KOOP Plooi (prod5)", count=42),
                 SystemBreakdown(data_view="ds-prod5-koop-sp", label="KOOP SP (prod5)", count=0)],
        timeseries=[{"timestamp": "2026-06-08T09:00:00+02:00", "count": 30}],
        top_signatures=[{"signature": "NullPointerException", "count": 30,
                         "first_seen": "2026-06-08T09:12:00Z", "last_seen": "2026-06-08T09:40:00Z"}],
        affected_services=[{"name": "registration-service", "count": 30}],
        status_codes=[{"code": 500, "count": 8}], failing_urls=[{"url": "/api/submit", "count": 8}],
        partial=False,
    )


def test_prompt_contains_facts_and_guardrails():
    prompt = briefing.build_prompt(_snapshot())
    assert "42" in prompt                       # total
    assert "NullPointerException" in prompt      # signature
    assert "registration-service" in prompt      # service
    assert "/api/submit" in prompt               # failing url
    # guardrails
    low = prompt.lower()
    assert "only" in low and ("do not invent" in low or "not invent" in low)
    assert "insufficient data" in low


def test_prompt_handles_all_clear():
    snap = _snapshot()
    snap.total = 0
    snap.status_level = "ok"
    snap.top_signatures = []
    prompt = briefing.build_prompt(snap)
    assert "0" in prompt
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_briefing.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'briefing'`

- [ ] **Step 3: Create `backend/briefing.py`**

```python
"""Grounded AI triage: turn a deterministic snapshot into a strict prompt and
generate a plain-language briefing. The LLM only narrates facts it is handed."""
import json

from llm import generate_answer
from monitoring import DashboardSnapshot

SYSTEM = (
    "You are KIBANA-OO's monitoring analyst. You are given EXACT facts computed "
    "from Elasticsearch about today's critical issues. Write a short briefing for "
    "an administrator.\n"
    "Rules:\n"
    "- Use ONLY the facts provided. Do not invent services, causes, or numbers.\n"
    "- Cite the actual numbers from the facts.\n"
    "- If the facts are insufficient to determine a cause, say 'insufficient data'.\n"
    "- Lead with the single most important issue, then list the rest.\n"
    "- Be concise: a few sentences plus a short prioritized list."
)


def build_prompt(snap: DashboardSnapshot) -> str:
    facts = {
        "date": snap.date,
        "total_criticals": snap.total,
        "status": snap.status_level,
        "vs_previous_day_pct": snap.delta.pct_vs_previous,
        "vs_7day_avg_pct": snap.delta.pct_vs_avg,
        "by_system": [{"system": s.label, "count": s.count, "available": s.available} for s in snap.systems],
        "top_error_signatures": snap.top_signatures,
        "affected_services": snap.affected_services,
        "http_5xx": snap.status_codes,
        "failing_urls": snap.failing_urls,
        "data_partial": snap.partial,
    }
    return f"{SYSTEM}\n\n## Facts (JSON)\n{json.dumps(facts, indent=2, default=str)}\n\n## Briefing"


async def generate_briefing(snap: DashboardSnapshot) -> str:
    prompt = build_prompt(snap)
    return await generate_answer(question="Summarize today's critical issues.", context=prompt)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_briefing.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/briefing.py backend/tests/test_briefing.py
git commit -m "feat(dashboard): grounded briefing prompt builder"
```

---

## Task 10: Dashboard router (admin-gated, cached) + wire into main

**Files:**
- Create: `backend/dashboard.py`
- Modify: `backend/main.py`
- Test: `backend/tests/test_dashboard.py`

- [ ] **Step 1: Write the failing test (append to `test_dashboard.py`)**

```python
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import dashboard
import monitoring
from session import _sessions


@pytest.fixture
def client(monkeypatch):
    app = FastAPI()
    app.include_router(dashboard.router)
    monkeypatch.setattr(dashboard.settings, "dashboard_admins", "boss@koop.nl")
    _sessions.clear()
    _sessions["admin-tok"] = {"username": "boss@koop.nl", "sid": "sid1"}
    _sessions["user-tok"] = {"username": "intern@koop.nl", "sid": "sid2"}
    dashboard._summary_cache.clear()

    async def fake_snapshot(sid, date_str):
        return monitoring.DashboardSnapshot(
            date="2026-06-08", window_start="s", window_end="e", total=42,
            delta=monitoring.Delta(previous=10, avg_7d=10.0),
            status_level="degraded", systems=[], timeseries=[], top_signatures=[],
            affected_services=[], status_codes=[], failing_urls=[], partial=False,
        )

    monkeypatch.setattr(dashboard, "build_snapshot", fake_snapshot)
    return TestClient(app)


def test_summary_requires_login(client):
    assert client.get("/dashboard/summary").status_code == 401


def test_summary_forbidden_for_non_admin(client):
    r = client.get("/dashboard/summary", headers={"Authorization": "Bearer user-tok"})
    assert r.status_code == 403


def test_summary_ok_for_admin(client):
    r = client.get("/dashboard/summary", headers={"Authorization": "Bearer admin-tok"})
    assert r.status_code == 200
    assert r.json()["total"] == 42
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard'`

- [ ] **Step 3: Create `backend/dashboard.py`**

```python
"""Admin-gated dashboard endpoints. Numbers come from monitoring.build_snapshot;
the briefing narrates the same snapshot. Both are cached."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_admin
from briefing import generate_briefing
from cache import TTLCache
from config import settings
from monitoring import build_snapshot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard")

_summary_cache = TTLCache(ttl=settings.dashboard_cache_ttl)
_briefing_cache = TTLCache(ttl=24 * 3600)  # per day


@router.get("/summary")
async def summary(
    date: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    key = f"summary:{date or 'today'}"
    cached = _summary_cache.get(key)
    if cached is not None:
        return cached
    try:
        snap = await build_snapshot(session["sid"], date)
    except Exception as e:
        logger.error(f"Dashboard summary failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load dashboard: {e}")
    payload = snap.model_dump()
    _summary_cache.set(key, payload)
    return payload


@router.get("/briefing")
async def briefing(
    date: str | None = Query(default=None),
    regenerate: bool = Query(default=False),
    session: dict = Depends(require_admin),
):
    key = f"briefing:{date or 'today'}"
    if not regenerate:
        cached = _briefing_cache.get(key)
        if cached is not None:
            return cached
    try:
        snap = await build_snapshot(session["sid"], date)
        text = await generate_briefing(snap)
    except Exception as e:
        logger.error(f"Dashboard briefing failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI briefing unavailable: {e}")
    payload = {"briefing": text, "date": snap.date}
    _briefing_cache.set(key, payload)
    return payload
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_dashboard.py -v`
Expected: PASS (4 tests, plus the earlier cache test = 5 total in file)

- [ ] **Step 5: Wire the router into `backend/main.py`**

Add the import near the other local imports:

```python
from dashboard import router as dashboard_router
```

After `app.add_middleware(...)`, add:

```python
app.include_router(dashboard_router)
```

- [ ] **Step 6: Verify the whole app imports and the full suite passes**

Run (from `backend/`): `python -c "import main; print('ok')" && python -m pytest -q`
Expected: `ok` then all tests pass.

- [ ] **Step 7: Commit**

```bash
git add backend/dashboard.py backend/main.py backend/tests/test_dashboard.py
git commit -m "feat(dashboard): admin-gated summary and briefing endpoints"
```

---

## Task 11: Proxy `/dashboard/` in nginx

**Files:**
- Modify: `frontend/nginx.conf`

- [ ] **Step 1: Add the proxy location**

After the `location /data-views { ... }` block, add (the briefing call can be slow on CPU, so give it a long read timeout):

```nginx
    location /dashboard/ {
        proxy_pass http://backend:8000;
        proxy_http_version 1.1;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
```

- [ ] **Step 2: Verify nginx config syntax (after frontend build in Task 15)**

Note: validated during the Task 15 container rebuild (`nginx -t` runs on container start).

- [ ] **Step 3: Commit**

```bash
git add frontend/nginx.conf
git commit -m "feat(dashboard): proxy /dashboard/ to backend"
```

---

## Task 12: Frontend API client + admin/nav plumbing

**Files:**
- Create: `frontend/src/api.js`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Create `frontend/src/api.js`**

```javascript
const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

export async function getJSON(path, token) {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (res.status === 401) throw new Error("unauthorized");
  if (res.status === 403) throw new Error("forbidden");
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `Server error: ${res.status}`);
  }
  return res.json();
}
```

- [ ] **Step 2: Add a Chat⇄Dashboard view toggle to `App.jsx`**

In `ChatPage`'s header `.brand` is unchanged. Add a `view` state and an `isAdmin` probe in the `App` component (the router). Replace the `App` component's body so it tracks the current view and whether the user is an admin (probed by attempting `/dashboard/summary`; 403 → not admin, 200/502 → admin):

```javascript
import { getJSON } from "./api";
// ... existing imports unchanged ...

export default function App() {
  const [token, setToken] = useState(
    () => sessionStorage.getItem("kibana_oo_token") || null
  );
  const [username, setUsername] = useState(
    () => sessionStorage.getItem("kibana_oo_user") || ""
  );
  const [view, setView] = useState("chat"); // "chat" | "dashboard"
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    if (!token) {
      setIsAdmin(false);
      return;
    }
    let active = true;
    getJSON("/dashboard/summary", token)
      .then(() => active && setIsAdmin(true))
      .catch((e) => active && setIsAdmin(e.message !== "forbidden"));
    return () => {
      active = false;
    };
  }, [token]);

  function handleLogin(newToken, user) {
    setToken(newToken);
    setUsername(user);
    sessionStorage.setItem("kibana_oo_token", newToken);
    sessionStorage.setItem("kibana_oo_user", user);
  }

  function handleLogout() {
    setToken(null);
    setUsername("");
    setView("chat");
    sessionStorage.removeItem("kibana_oo_token");
    sessionStorage.removeItem("kibana_oo_user");
  }

  if (!token) return <LoginPage onLogin={handleLogin} />;

  if (view === "dashboard" && isAdmin) {
    return (
      <DashboardPage
        token={token}
        username={username}
        onLogout={handleLogout}
        onSwitchView={() => setView("chat")}
      />
    );
  }
  return (
    <ChatPage
      token={token}
      username={username}
      onLogout={handleLogout}
      isAdmin={isAdmin}
      onSwitchView={() => setView("dashboard")}
    />
  );
}
```

Add `useEffect` to the existing React import if not already present (it is). Import `DashboardPage` at the top:

```javascript
import DashboardPage from "./Dashboard";
```

In `ChatPage`, accept the new props and add a Dashboard link in the header (only when admin). Change the `ChatPage` signature:

```javascript
function ChatPage({ token, username, onLogout, isAdmin, onSwitchView }) {
```

In `ChatPage`'s header `.header-right`, before the `<span className="header-user">`, add:

```javascript
          {isAdmin && (
            <button className="btn btn--ghost" onClick={onSwitchView}>
              Dashboard
            </button>
          )}
```

- [ ] **Step 3: Verify build (after Dashboard.jsx exists in Task 13)**

Note: `App.jsx` now imports `./Dashboard`, so the build is verified at the end of Task 13.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api.js frontend/src/App.jsx
git commit -m "feat(dashboard): API client and admin nav toggle"
```

---

## Task 13: Dashboard page + panels

**Files:**
- Create: `frontend/src/Dashboard.jsx`

- [ ] **Step 1: Create `frontend/src/Dashboard.jsx`**

```javascript
import { useState, useEffect, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { getJSON } from "./api";

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "";

function today() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Amsterdam",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function Delta({ pct }) {
  if (pct == null) return null;
  const up = pct > 0;
  return (
    <span className={`delta ${up ? "delta--up" : "delta--down"}`}>
      {up ? "▲" : "▼"} {Math.abs(pct)}%
    </span>
  );
}

export default function DashboardPage({ token, username, onLogout, onSwitchView }) {
  const [date, setDate] = useState(today());
  const [snap, setSnap] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadedAt, setLoadedAt] = useState(null);
  const [briefing, setBriefing] = useState(null);
  const [briefingState, setBriefingState] = useState("idle"); // idle|loading|error

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getJSON(`/dashboard/summary?date=${date}`, token);
      setSnap(data);
      setLoadedAt(new Date());
    } catch (e) {
      if (e.message === "unauthorized") return onLogout();
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [date, token, onLogout]);

  useEffect(() => {
    load();
  }, [load]);

  const loadBriefing = useCallback(
    async (regenerate = false) => {
      setBriefingState("loading");
      try {
        const data = await getJSON(
          `/dashboard/briefing?date=${date}${regenerate ? "&regenerate=true" : ""}`,
          token
        );
        setBriefing(data.briefing);
        setBriefingState("idle");
      } catch {
        setBriefingState("error");
      }
    },
    [date, token]
  );

  // Auto-load the briefing once the numbers are in.
  useEffect(() => {
    if (snap) loadBriefing(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snap?.date]);

  const max = Math.max(1, ...((snap?.timeseries || []).map((b) => b.count)));

  return (
    <>
      <header className="header">
        <div className="brand">
          <span className="brand-mark">◆</span>
          <div className="brand-text">
            <span className="brand-name">Monitoring</span>
            <span className="brand-sub">Critical issues · {date}</span>
          </div>
        </div>
        <div className="header-right">
          <button className="btn btn--ghost" onClick={onSwitchView}>
            Chat
          </button>
          <span className="header-user">{username}</span>
          <button className="btn btn--ghost" onClick={onLogout}>
            Sign out
          </button>
        </div>
      </header>

      <div className="chat-scroll">
        <div className="dash">
          <div className="dash-controls">
            <input
              type="date"
              className="control-select"
              value={date}
              max={today()}
              onChange={(e) => setDate(e.target.value)}
            />
            <button className="btn btn--ghost" onClick={load} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh"}
            </button>
            {loadedAt && (
              <span className="dash-asof">
                data as of {loadedAt.toLocaleTimeString()}
              </span>
            )}
          </div>

          {error && <div className="alert alert--error">{error}</div>}

          {snap && (
            <>
              <div className={`status-banner status-banner--${snap.status_level}`}>
                <strong>
                  {snap.status_level === "ok"
                    ? "All clear"
                    : snap.status_level === "degraded"
                    ? "Degraded"
                    : "Critical"}
                </strong>
                {snap.partial && <span className="dash-warn">partial data</span>}
              </div>

              <div className="kpis">
                <div className="kpi">
                  <span className="kpi-value">
                    {snap.total} <Delta pct={snap.delta.pct_vs_previous} />
                  </span>
                  <span className="kpi-label">criticals today</span>
                </div>
                <div className="kpi">
                  <span className="kpi-value">
                    {snap.systems.filter((s) => s.count > 0).length}
                  </span>
                  <span className="kpi-label">systems affected</span>
                </div>
                <div className="kpi">
                  <span className="kpi-value">{snap.delta.avg_7d}</span>
                  <span className="kpi-label">7-day avg</span>
                </div>
              </div>

              <section className="panel">
                <h3>Criticals over time</h3>
                <div className="spark">
                  {snap.timeseries.map((b, i) => (
                    <div
                      key={i}
                      className="spark-bar"
                      style={{ height: `${(b.count / max) * 100}%` }}
                      title={`${b.timestamp}: ${b.count}`}
                    />
                  ))}
                </div>
              </section>

              <section className="panel">
                <h3>By system</h3>
                <div className="tiles">
                  {snap.systems.map((s) => (
                    <div
                      key={s.data_view}
                      className={`tile ${s.available ? "" : "tile--down"}`}
                    >
                      <span className="tile-name">{s.label}</span>
                      <span className="tile-count">
                        {s.available ? s.count : "unavailable"}
                      </span>
                    </div>
                  ))}
                </div>
              </section>

              <section className="panel">
                <h3>Top error signatures</h3>
                {snap.top_signatures.length === 0 ? (
                  <p className="muted">None.</p>
                ) : (
                  <table className="dash-table">
                    <thead>
                      <tr><th>Signature</th><th>Count</th><th>First</th><th>Last</th></tr>
                    </thead>
                    <tbody>
                      {snap.top_signatures.map((s, i) => (
                        <tr key={i}>
                          <td>{s.signature}</td>
                          <td>{s.count}</td>
                          <td>{s.first_seen || "—"}</td>
                          <td>{s.last_seen || "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              <section className="panel">
                <h3>Affected services</h3>
                {snap.affected_services.length === 0 ? (
                  <p className="muted">None.</p>
                ) : (
                  <div className="tiles">
                    {snap.affected_services.map((s, i) => (
                      <div key={i} className="tile">
                        <span className="tile-name">{s.name}</span>
                        <span className="tile-count">{s.count}</span>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className="panel">
                <h3>HTTP 5xx</h3>
                {snap.status_codes.length === 0 ? (
                  <p className="muted">No server errors.</p>
                ) : (
                  <>
                    <div className="tiles">
                      {snap.status_codes.map((s, i) => (
                        <div key={i} className="tile">
                          <span className="tile-name">{s.code}</span>
                          <span className="tile-count">{s.count}</span>
                        </div>
                      ))}
                    </div>
                    <ul className="url-list">
                      {snap.failing_urls.map((u, i) => (
                        <li key={i}>
                          <code>{u.url}</code> <span className="muted">{u.count}</span>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </section>

              <section className="panel panel--ai">
                <div className="panel-head">
                  <h3>AI daily triage</h3>
                  <button
                    className="btn btn--ghost"
                    onClick={() => loadBriefing(true)}
                    disabled={briefingState === "loading"}
                  >
                    {briefingState === "loading" ? "Generating…" : "Regenerate"}
                  </button>
                </div>
                {briefingState === "error" ? (
                  <p className="muted">AI summary unavailable.</p>
                ) : briefing ? (
                  <div className="markdown">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{briefing}</ReactMarkdown>
                  </div>
                ) : (
                  <p className="muted">Analyzing…</p>
                )}
              </section>
            </>
          )}
        </div>
      </div>
    </>
  );
}
```

- [ ] **Step 2: Verify the frontend builds**

Run (from `frontend/`): `npm install && npm run build`
Expected: build succeeds with no unresolved imports.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/Dashboard.jsx
git commit -m "feat(dashboard): dashboard page and panels"
```

---

## Task 14: Dashboard styles

**Files:**
- Modify: `frontend/src/styles.css`

- [ ] **Step 1: Append dashboard styles to `frontend/src/styles.css`**

```css
/* ── Dashboard ────────────────────────────────────────── */
.dash {
  max-width: 980px;
  margin: 0 auto;
  padding: 24px 22px 40px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.dash-controls {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dash-asof {
  font-size: 12px;
  color: var(--text-faint);
  margin-left: auto;
}

.dash-warn {
  font-size: 11.5px;
  color: var(--warn);
  border: 1px solid var(--warn);
  border-radius: 999px;
  padding: 2px 9px;
  margin-left: 10px;
}

.status-banner {
  padding: 14px 18px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  font-size: 16px;
  display: flex;
  align-items: center;
}

.status-banner--ok { background: rgba(70, 201, 122, 0.12); border-color: var(--success); }
.status-banner--degraded { background: rgba(227, 179, 65, 0.12); border-color: var(--warn); }
.status-banner--critical { background: var(--error-soft); border-color: var(--error); }

.kpis {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.kpi {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.kpi-value { font-size: 28px; font-weight: 700; }
.kpi-label { font-size: 12.5px; color: var(--text-faint); }

.delta { font-size: 13px; font-weight: 600; }
.delta--up { color: var(--error); }
.delta--down { color: var(--success); }

.panel {
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
}

.panel h3 { font-size: 14px; margin-bottom: 12px; }

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.panel-head h3 { margin-bottom: 0; }
.panel--ai { border-color: var(--accent); }

.spark {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 90px;
}
.spark-bar {
  flex: 1;
  min-height: 2px;
  background: linear-gradient(180deg, var(--accent), #2d6fd6);
  border-radius: 2px 2px 0 0;
}

.tiles { display: flex; flex-wrap: wrap; gap: 10px; }
.tile {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 130px;
  padding: 12px 14px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
}
.tile--down { opacity: 0.6; border-style: dashed; }
.tile-name { font-size: 12.5px; color: var(--text-secondary); }
.tile-count { font-size: 20px; font-weight: 700; }

.dash-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.dash-table th, .dash-table td {
  border: 1px solid var(--border);
  padding: 7px 11px;
  text-align: left;
}
.dash-table th { background: var(--bg-input); }

.url-list { list-style: none; margin-top: 10px; display: flex; flex-direction: column; gap: 5px; }
.url-list code { font-family: var(--mono); font-size: 12.5px; }

.muted { color: var(--text-faint); font-size: 13px; }

@media (max-width: 600px) {
  .kpis { grid-template-columns: 1fr; }
  .dash { padding: 16px 14px 30px; }
}
```

- [ ] **Step 2: Verify the frontend still builds**

Run (from `frontend/`): `npm run build`
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/styles.css
git commit -m "feat(dashboard): dashboard styles"
```

---

## Task 15: Build, deploy, and smoke-test

**Files:** none (operational)

- [ ] **Step 1: Set an admin in `.env`**

Ensure `.env` contains your admin (so gating lets you in):

```
DASHBOARD_ADMINS=anton.partono@koop.overheid.nl
```

- [ ] **Step 2: Rebuild and restart backend + frontend**

Run (from repo root):

```bash
docker compose build backend frontend
docker compose up -d backend frontend
```

Expected: both images build; containers restart healthy.

- [ ] **Step 3: Verify endpoints require admin**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/dashboard/summary
```

Expected: `401` (no token).

- [ ] **Step 4: Smoke-test in the browser**

Log in as the admin user, click **Dashboard** in the header. Verify: KPIs render, the time-series and system tiles appear, "data as of" stamp shows, and the AI triage panel fills in after a few seconds. Switch back to **Chat**. Log in as a non-admin and confirm the Dashboard button is absent.

- [ ] **Step 5: Final full backend test run**

Run (from `backend/`): `python -m pytest -q`
Expected: all tests pass.

- [ ] **Step 6: Commit any final fixes and open a PR**

```bash
git add -A
git commit -m "chore(dashboard): final wiring and smoke-test fixes"
```

(Push and open the PR from `feat/monitoring-dashboard` only when the user asks.)

---

## Self-Review

**Spec coverage:**
- §3 architecture → Tasks 2,3,7,10,12,13 ✓
- §4 fact layer / critical definition → Tasks 4,5,6,7 ✓
- §5 7 panels → Task 13 (KPIs, time-series, by-system, signatures, services, 5xx, AI triage) ✓
- §6 grounded AI → Tasks 9,10,13 ✓
- §7 security (admin gating, backend-enforced) → Tasks 3,10 ✓ (allowlist; group claim documented as extension)
- §8 robustness: single snapshot, per-view isolation, cache, "data as of" → Tasks 7,8,10,13 ✓
- §9 testing: fact layer + failure paths, require_admin, prompt builder → Tasks 1,3,5,6,7,9,10 ✓
- §4 deltas/comparison → Tasks 6,7,13 ✓
- §4 calendar day + date picker + tz → Tasks 4,13 ✓
- §3 per-data-view breakdown via whitelist → Tasks 1,7 ✓

**Placeholder scan:** No TBD/TODO; every code/test step has full code. ✓

**Type consistency:** `DashboardSnapshot`, `Delta`, `SystemBreakdown` fields are defined in Task 7 and used identically in Tasks 9, 10, 13. `build_snapshot(sid, date_str)`, `parse_aggs`, `parse_baseline`, `status_level`, `critical_query`, `snapshot_body`, `baseline_body` names match across tasks. `getJSON(path, token)` consistent in Tasks 12–13. `TTLCache(ttl, now)` consistent in Tasks 8,10. ✓

**Known build-order note:** `App.jsx` (Task 12) imports `./Dashboard` (Task 13) and `./api` (Task 12); the frontend build is first run at the end of Task 13 — intentional and called out.

**Deferred to phase 2 (not in this plan, per spec §10):** spike/baseline detection, daily digest, scheduled snapshots, Keycloak group-claim gating (needs OIDC claim capture).
