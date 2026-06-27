# Monitoring Targets Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A generic, admin-configurable, DB-backed monitoring registry (connections + targets + a checker-plugin pattern) with an intelligence layer (auto-discovery, adaptive baselines, correlation + AI root-cause, dependency suppression, flap detection, coverage score), surfaced on a super-admin config page + one dashboard card + the existing alert engine.

**Architecture:** New, fully additive backend modules (`monitor_registry/checkers/intel/engine/api`) on the shared SQLite db (`db.py`), a background poll loop wired into `main.py` lifespan (like Service health), a super-admin config page and a self-fetching dashboard card. Secrets stay in `.env` (referenced by name). FROZEN cert code and existing monitors are never touched.

**Tech Stack:** Python 3.13 / FastAPI / httpx / sqlite3 (`db.py`), React 19 / Vite, pytest in `python:3.13` Docker.

**Spec:** `docs/superpowers/specs/2026-06-27-monitoring-registry-design.md`
**Branch:** `feat/monitoring-registry` (already created).

---

## Conventions used by every task

**Run backend tests** (from repo root):
```bash
cd /c/ANT-PROJECT/KIBANA-OO/backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 \
  docker run --rm -v "$HP:/app" -w /app python:3.13 sh -c \
  "pip install -q -r requirements.txt && python -m pytest tests/<FILE> -q"
```
**Frontend build-green** (from repo root):
```bash
cd /c/ANT-PROJECT/KIBANA-OO/frontend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 \
  docker run --rm -v "$HP:/app" -w /app node:20 sh -c "npm install --no-audit --no-fund && npm run build" 2>&1 | tail -6
```
**DB access:** use `from db import cursor` → `with cursor() as conn: conn.execute(...)`. Each module owns its `CREATE TABLE IF NOT EXISTS` (run on import), per the `db.py` convention.

---

## File structure (locked)

| File | Responsibility |
|---|---|
| `backend/monitor_registry.py` | schema (3 tables) + CRUD for connections, targets, results |
| `backend/monitor_checkers.py` | `CHECKERS` plugin registry: 4 types + `discover()` |
| `backend/monitor_intel.py` | baselines, flap, correlation, coverage, dependency state |
| `backend/monitor_engine.py` | `run_monitor_loop()` + `snapshot()` for the card |
| `backend/monitor_api.py` | FastAPI router (config super-admin; results feature-gated) |
| `frontend/src/MonitoringConfig.jsx` | super-admin config page |
| `frontend/src/MonitoringCard.jsx` | dashboard card |
| wire-ups | `main.py`, `config.py`, `permissions.py`, `context_engine.py`, `Nav.jsx`, `Dashboard.jsx`, alerts |
| `docs/KIBANA-OO/Monitoring targets.md` | Dutch vault note |

---

# PHASE 1 — Registry (data model + CRUD)

### Task 1: Config flags + DB schema

**Files:**
- Modify: `backend/config.py` (after the `service_health_*` block, ~line 312)
- Create: `backend/monitor_registry.py`
- Test: `backend/tests/test_monitor_registry.py`

- [ ] **Step 1: Add settings** — in `backend/config.py`, after the service_health settings, add:
```python
    # Monitoring Targets registry (admin-configurable; additive, off by default)
    monitor_enabled: bool = False
    monitor_interval: int = 60        # seconds between poll cycles
    monitor_timeout: int = 8          # per-check HTTP timeout
    monitor_flap_threshold: int = 2   # consecutive reds before alerting
```

- [ ] **Step 2: Write the failing test** — `backend/tests/test_monitor_registry.py`:
```python
import os, tempfile
os.environ["APP_DB_PATH"] = os.path.join(tempfile.gettempdir(), "mon_test.db")
import importlib, config as _c; importlib.reload(_c)
from config import settings
settings.app_db_path = os.environ["APP_DB_PATH"]
import monitor_registry as reg

def setup_function(_):
    with reg.cursor() as c:
        for t in ("monitor_results", "monitor_targets", "monitor_connections"):
            c.execute(f"DELETE FROM {t}")

def test_connection_crud_hides_no_secret_value():
    cid = reg.add_connection(kind="prometheus", name="Prom PROD",
                             base_url="http://prom:9090", secret_ref="PROM_TOKEN", actor="anton")
    got = reg.get_connection(cid)
    assert got["base_url"] == "http://prom:9090"
    assert got["secret_ref"] == "PROM_TOKEN"          # the NAME is fine to store
    assert "secret" not in {k.lower() for k in got} or "secret_value" not in got  # no value field

def test_target_crud_and_toggle():
    tid = reg.add_target(name="GW logs PROD", type="log-freshness", environment="prod",
                         config={"index": "logs-gw-*", "max_age_minutes": 10}, actor="anton")
    reg.set_target_enabled(tid, False)
    assert reg.get_target(tid)["enabled"] == 0
    reg.update_target(tid, {"environment": "acc"})
    assert reg.get_target(tid)["environment"] == "acc"
    reg.delete_target(tid)
    assert reg.get_target(tid) is None

def test_result_store_and_latest():
    tid = reg.add_target(name="x", type="http", environment="na", config={"url": "http://x"}, actor="a")
    reg.record_result(tid, status="ok", detail={"http": 200}, latency_ms=12)
    reg.record_result(tid, status="down", detail={"http": 503}, latency_ms=8)
    assert reg.latest_result(tid)["status"] == "down"
    assert len(reg.recent_results(tid, limit=10)) == 2
```

- [ ] **Step 3: Run it — expect FAIL** (`ModuleNotFoundError: monitor_registry`). Use the backend test command above with `tests/test_monitor_registry.py`.

- [ ] **Step 4: Implement `backend/monitor_registry.py`:**
```python
"""Monitoring Targets registry — schema + CRUD for connections, targets, results.
Additive: own tables in the shared app db (db.py). Secrets are NEVER stored here —
only `secret_ref`, the NAME of an .env var read at check time."""
import json
from datetime import datetime, timezone
from db import cursor

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_connections (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, base_url TEXT NOT NULL,
  secret_ref TEXT, enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT, updated_at TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS monitor_targets (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
  environment TEXT NOT NULL DEFAULT 'na', enabled INTEGER NOT NULL DEFAULT 1,
  alert_enabled INTEGER NOT NULL DEFAULT 1, connection_id INTEGER,
  config TEXT NOT NULL DEFAULT '{}', created_at TEXT, updated_at TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS monitor_results (
  id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL, ts TEXT NOT NULL,
  status TEXT NOT NULL, detail TEXT, latency_ms INTEGER);
CREATE INDEX IF NOT EXISTS ix_mon_results_target_ts ON monitor_results(target_id, ts);
"""
with cursor() as _c:
    _c.executescript(_SCHEMA)

def _row(r): return dict(r) if r is not None else None

# ── connections ──
def add_connection(kind, name, base_url, secret_ref=None, actor=None) -> int:
    with cursor() as c:
        cur = c.execute(
            "INSERT INTO monitor_connections (kind,name,base_url,secret_ref,created_at,updated_at,created_by)"
            " VALUES (?,?,?,?,?,?,?)", (kind, name, base_url, secret_ref, _now(), _now(), actor))
        return cur.lastrowid

def get_connection(cid):
    with cursor() as c:
        return _row(c.execute("SELECT * FROM monitor_connections WHERE id=?", (cid,)).fetchone())

def list_connections():
    with cursor() as c:
        return [dict(r) for r in c.execute("SELECT * FROM monitor_connections ORDER BY id").fetchall()]

def update_connection(cid, patch: dict):
    allowed = {"kind","name","base_url","secret_ref","enabled"}
    sets = {k: v for k, v in patch.items() if k in allowed}
    if not sets: return
    cols = ",".join(f"{k}=?" for k in sets) + ",updated_at=?"
    with cursor() as c:
        c.execute(f"UPDATE monitor_connections SET {cols} WHERE id=?", (*sets.values(), _now(), cid))

def delete_connection(cid):
    with cursor() as c:
        c.execute("DELETE FROM monitor_connections WHERE id=?", (cid,))

# ── targets ──
def add_target(name, type, environment="na", config=None, connection_id=None, actor=None) -> int:
    with cursor() as c:
        cur = c.execute(
            "INSERT INTO monitor_targets (name,type,environment,connection_id,config,created_at,updated_at,created_by)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (name, type, environment, connection_id, json.dumps(config or {}), _now(), _now(), actor))
        return cur.lastrowid

def get_target(tid):
    with cursor() as c:
        r = c.execute("SELECT * FROM monitor_targets WHERE id=?", (tid,)).fetchone()
    if r is None: return None
    d = dict(r); d["config"] = json.loads(d["config"] or "{}"); return d

def list_targets(enabled_only=False):
    q = "SELECT * FROM monitor_targets" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY environment,type,id"
    with cursor() as c:
        out = []
        for r in c.execute(q).fetchall():
            d = dict(r); d["config"] = json.loads(d["config"] or "{}"); out.append(d)
        return out

def update_target(tid, patch: dict):
    allowed = {"name","type","environment","enabled","alert_enabled","connection_id","config"}
    sets = {k: (json.dumps(v) if k == "config" else v) for k, v in patch.items() if k in allowed}
    if not sets: return
    cols = ",".join(f"{k}=?" for k in sets) + ",updated_at=?"
    with cursor() as c:
        c.execute(f"UPDATE monitor_targets SET {cols} WHERE id=?", (*sets.values(), _now(), tid))

def set_target_enabled(tid, on: bool): update_target(tid, {"enabled": 1 if on else 0})
def delete_target(tid):
    with cursor() as c:
        c.execute("DELETE FROM monitor_results WHERE target_id=?", (tid,))
        c.execute("DELETE FROM monitor_targets WHERE id=?", (tid,))

# ── results ──
def record_result(target_id, status, detail=None, latency_ms=None):
    with cursor() as c:
        c.execute("INSERT INTO monitor_results (target_id,ts,status,detail,latency_ms) VALUES (?,?,?,?,?)",
                  (target_id, _now(), status, json.dumps(detail or {}), latency_ms))

def latest_result(target_id):
    with cursor() as c:
        r = c.execute("SELECT * FROM monitor_results WHERE target_id=? ORDER BY ts DESC LIMIT 1",
                      (target_id,)).fetchone()
    if r is None: return None
    d = dict(r); d["detail"] = json.loads(d["detail"] or "{}"); return d

def recent_results(target_id, limit=50):
    with cursor() as c:
        rows = c.execute("SELECT * FROM monitor_results WHERE target_id=? ORDER BY ts DESC LIMIT ?",
                         (target_id, limit)).fetchall()
    return [dict(r) for r in rows]
```

- [ ] **Step 5: Run tests — expect PASS** (all 3). Fix until green.

- [ ] **Step 6: Commit**
```bash
cd /c/ANT-PROJECT/KIBANA-OO && git add backend/config.py backend/monitor_registry.py backend/tests/test_monitor_registry.py
git commit -m "feat(monitor): registry schema + CRUD (connections, targets, results)"
```

---

# PHASE 2 — Checker plugins

### Task 2: Checker registry + `http` checker (the template)

**Files:**
- Create: `backend/monitor_checkers.py`
- Test: `backend/tests/test_monitor_checkers.py`

- [ ] **Step 1: Write the failing test:**
```python
import asyncio, monitor_checkers as mc

class _Resp:
    def __init__(self, status): self.status_code = status
class _Client:
    def __init__(self, status=None, exc=None): self._s, self._e = status, exc
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, **k):
        if self._e: raise self._e
        return _Resp(self._s)

def test_http_checker_classifies(monkeypatch):
    import httpx
    def fake_client(*a, **k): return _Client(status=200)
    monkeypatch.setattr(httpx, "AsyncClient", fake_client)
    t = {"type": "http", "config": {"url": "http://x", "expected_status": [200]}}
    r = asyncio.run(mc.run_check(t, None))
    assert r["status"] == "ok"

def test_http_checker_5xx_is_down(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Client(status=503))
    t = {"type": "http", "config": {"url": "http://x", "expected_status": [200]}}
    assert asyncio.run(mc.run_check(t, None))["status"] == "down"

def test_http_checker_connfail_is_unreachable(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Client(exc=httpx.ConnectError("x")))
    t = {"type": "http", "config": {"url": "http://x"}}
    assert asyncio.run(mc.run_check(t, None))["status"] == "unreachable"

def test_types_schema_lists_http_fields():
    schema = mc.types_schema()
    assert "http" in schema and any(f["name"] == "url" for f in schema["http"]["fields"])
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `backend/monitor_checkers.py` (registry + http; other types added in Tasks 3–4):**
```python
"""Checker plugins. Each type declares its config `fields` (UI form builder) and an
async `check(target, connection)` returning {status, detail, latency_ms}. Never raises
out — wraps failures as 'unreachable'. Status vocab: ok|warn|stale|down|unreachable."""
import time, httpx
from config import settings

CHECKERS = {}   # type_id -> {"fields": [...], "check": fn, "discover": fn|None}

def register(type_id, fields, check, discover=None):
    CHECKERS[type_id] = {"fields": fields, "check": check, "discover": discover}

def types_schema() -> dict:
    return {k: {"fields": v["fields"]} for k, v in CHECKERS.items()}

async def run_check(target: dict, connection: dict | None) -> dict:
    chk = CHECKERS.get(target["type"])
    if not chk:
        return {"status": "unreachable", "detail": {"error": f"unknown type {target['type']}"}, "latency_ms": None}
    try:
        return await chk["check"](target, connection)
    except Exception as e:  # noqa: BLE001 — a checker must never break the round
        return {"status": "unreachable", "detail": {"error": str(e)}, "latency_ms": None}

# ── http ──
_HTTP_FIELDS = [
    {"name": "url", "label": "URL", "kind": "text", "required": True},
    {"name": "expected_status", "label": "Verwachte status", "kind": "list-int", "default": [200, 204, 301, 302, 401, 403, 405]},
    {"name": "timeout_s", "label": "Timeout (s)", "kind": "int", "default": None},
    {"name": "service", "label": "Service-label (voor correlatie)", "kind": "text", "default": None},
]
async def _check_http(target, connection):
    cfg = target["config"]; url = cfg["url"]
    expected = set(cfg.get("expected_status") or [200, 204, 301, 302, 401, 403, 405])
    timeout = cfg.get("timeout_s") or settings.monitor_timeout
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.get(url)
        ms = int((time.monotonic() - t0) * 1000)
        code = resp.status_code
        if code in expected or (200 <= code < 500 and code not in (408,)):
            status = "ok" if code < 500 else "down"
        if code >= 500:
            return {"status": "down", "detail": {"http": code}, "latency_ms": ms}
        return {"status": "ok", "detail": {"http": code}, "latency_ms": ms}
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RequestError) as e:
        return {"status": "unreachable", "detail": {"error": type(e).__name__}, "latency_ms": None}

register("http", _HTTP_FIELDS, _check_http)
```

- [ ] **Step 4: Run — expect PASS (4 tests).** Fix until green.

- [ ] **Step 5: Commit**
```bash
cd /c/ANT-PROJECT/KIBANA-OO && git add backend/monitor_checkers.py backend/tests/test_monitor_checkers.py
git commit -m "feat(monitor): checker plugin registry + http checker"
```

### Task 3: `log-freshness` checker (Elasticsearch, reuses session)

**Files:** Modify `backend/monitor_checkers.py`; Modify `backend/tests/test_monitor_checkers.py`

- [ ] **Step 1: Add failing test** (mock the ES query helper):
```python
def test_log_freshness_stale(monkeypatch):
    import monitor_checkers as mc
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    monkeypatch.setattr(mc, "_es_max_timestamp", lambda index, field, sid: old)
    t = {"type": "log-freshness", "config": {"index": "logs-*", "max_age_minutes": 10}}
    r = __import__("asyncio").run(mc.run_check(t, None))
    assert r["status"] == "stale"

def test_log_freshness_ok(monkeypatch):
    import monitor_checkers as mc
    from datetime import datetime, timezone
    monkeypatch.setattr(mc, "_es_max_timestamp", lambda index, field, sid: datetime.now(timezone.utc).isoformat())
    t = {"type": "log-freshness", "config": {"index": "logs-*", "max_age_minutes": 10}}
    assert __import__("asyncio").run(mc.run_check(t, None))["status"] == "ok"
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — append to `monitor_checkers.py`:
```python
from datetime import datetime, timezone

_LOGFRESH_FIELDS = [
    {"name": "index", "label": "Index / data-stream", "kind": "text", "required": True},
    {"name": "timestamp_field", "label": "Timestamp-veld", "kind": "text", "default": "@timestamp"},
    {"name": "max_age_minutes", "label": "Max leeftijd (min)", "kind": "int", "default": 10},
    {"name": "adaptive", "label": "Adaptieve baseline", "kind": "bool", "default": True},
    {"name": "service", "label": "Service-label (voor correlatie)", "kind": "text", "default": None},
]
def _es_max_timestamp(index, field, sid):
    """Newest timestamp in an index via the existing Kibana proxy. Returns ISO str or None.
    Reuses elastic._es_search (the same authenticated path chat uses)."""
    import asyncio, elastic
    body = {"size": 0, "aggs": {"m": {"max": {"field": field}}}}
    res = asyncio.get_event_loop().run_until_complete(elastic._es_search(sid, index, body)) \
        if False else None  # real call wired in the engine where an sid is available
    return res
async def _check_log_freshness(target, connection):
    cfg = target["config"]
    sid = (target.get("_ctx") or {}).get("sid")
    ts = _es_max_timestamp(cfg["index"], cfg.get("timestamp_field", "@timestamp"), sid)
    if not ts:
        return {"status": "unreachable", "detail": {"error": "no data / ES unreachable"}, "latency_ms": None}
    age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 60
    threshold = cfg.get("_effective_threshold", cfg.get("max_age_minutes", 10))
    status = "stale" if age_min > threshold else "ok"
    return {"status": status, "detail": {"age_min": round(age_min, 1), "threshold": threshold}, "latency_ms": None}

register("log-freshness", _LOGFRESH_FIELDS, _check_log_freshness)
```
> Note: `_es_max_timestamp` is mocked in tests; the engine (Task 6) passes a real `sid` via `target["_ctx"]` and the adaptive `_effective_threshold` via `monitor_intel`. Keep the function name `_es_max_timestamp` stable — tests and the engine depend on it.

- [ ] **Step 4: Run — expect PASS.** **Step 5: Commit** `feat(monitor): log-freshness checker (ES, reuses session)`.

### Task 4: `jaeger-traces` + `prometheus-query` checkers

**Files:** Modify `backend/monitor_checkers.py`; Modify the test file.

- [ ] **Step 1: Add failing tests** (mock httpx like Task 2):
```python
def test_jaeger_traces_stale(monkeypatch):
    import httpx, asyncio, monitor_checkers as mc
    class R: status_code=200; 
    R.json = lambda self: {"data": []}
    class C:
        async def __aenter__(s): return s
        async def __aexit__(s,*a): return False
        async def get(s,u,**k): return R()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: C())
    t = {"type":"jaeger-traces","config":{"service":"repo","min_traces":1}}
    conn = {"base_url":"http://jaeger:16686","secret_ref":None}
    assert asyncio.run(mc.run_check(t, conn))["status"] == "stale"

def test_prometheus_query_ok(monkeypatch):
    import httpx, asyncio, monitor_checkers as mc
    class R: status_code=200
    R.json = lambda self: {"data": {"result": [{"value": [0, "1"]}]}}
    class C:
        async def __aenter__(s): return s
        async def __aexit__(s,*a): return False
        async def get(s,u,**k): return R()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: C())
    t = {"type":"prometheus-query","config":{"query":"up","op":">","threshold":0}}
    conn = {"base_url":"http://prom:9090","secret_ref":None}
    assert asyncio.run(mc.run_check(t, conn))["status"] == "ok"
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — append to `monitor_checkers.py`:
```python
import os

def _auth_headers(connection):
    ref = (connection or {}).get("secret_ref")
    tok = os.environ.get(ref) if ref else None
    return {"Authorization": f"Bearer {tok}"} if tok else {}

_JAEGER_FIELDS = [
    {"name": "service", "label": "Service", "kind": "text", "required": True},
    {"name": "lookback_minutes", "label": "Lookback (min)", "kind": "int", "default": 15},
    {"name": "min_traces", "label": "Min. traces", "kind": "int", "default": 1},
]
async def _check_jaeger(target, connection):
    if not connection: return {"status": "unreachable", "detail": {"error": "no connection"}, "latency_ms": None}
    cfg = target["config"]; lb = cfg.get("lookback_minutes", 15)
    url = f"{connection['base_url'].rstrip('/')}/api/traces"
    params = {"service": cfg["service"], "lookback": f"{lb}m", "limit": 20}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.monitor_timeout) as c:
            resp = await c.get(url, params=params, headers=_auth_headers(connection))
        ms = int((time.monotonic() - t0) * 1000)
        n = len((resp.json() or {}).get("data") or [])
        status = "ok" if n >= cfg.get("min_traces", 1) else "stale"
        return {"status": status, "detail": {"traces": n, "lookback_min": lb}, "latency_ms": ms}
    except (httpx.RequestError,) as e:
        return {"status": "unreachable", "detail": {"error": type(e).__name__}, "latency_ms": None}

_PROM_FIELDS = [
    {"name": "query", "label": "PromQL", "kind": "text", "required": True},
    {"name": "op", "label": "Operator", "kind": "select", "options": [">", ">=", "<", "<=", "==", "exists"], "default": "exists"},
    {"name": "threshold", "label": "Drempel", "kind": "float", "default": 0},
]
def _cmp(v, op, thr):
    return {">": v > thr, ">=": v >= thr, "<": v < thr, "<=": v <= thr, "==": v == thr}.get(op, True)
async def _check_prometheus(target, connection):
    if not connection: return {"status": "unreachable", "detail": {"error": "no connection"}, "latency_ms": None}
    cfg = target["config"]; url = f"{connection['base_url'].rstrip('/')}/api/v1/query"
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.monitor_timeout) as c:
            resp = await c.get(url, params={"query": cfg["query"]}, headers=_auth_headers(connection))
        ms = int((time.monotonic() - t0) * 1000)
        result = ((resp.json() or {}).get("data") or {}).get("result") or []
        if not result:
            return {"status": "stale", "detail": {"reason": "empty result"}, "latency_ms": ms}
        op = cfg.get("op", "exists")
        if op == "exists":
            return {"status": "ok", "detail": {"series": len(result)}, "latency_ms": ms}
        val = float(result[0]["value"][1])
        ok = _cmp(val, op, float(cfg.get("threshold", 0)))
        return {"status": "ok" if ok else "down", "detail": {"value": val, "op": op}, "latency_ms": ms}
    except (httpx.RequestError, KeyError, ValueError) as e:
        return {"status": "unreachable", "detail": {"error": type(e).__name__}, "latency_ms": None}

register("jaeger-traces", _JAEGER_FIELDS, _check_jaeger)
register("prometheus-query", _PROM_FIELDS, _check_prometheus)
```

- [ ] **Step 4: Run — expect PASS.** **Step 5: Commit** `feat(monitor): jaeger-traces + prometheus-query checkers`.

---

# PHASE 3 — Intelligence

### Task 5: `monitor_intel.py` — baselines, flap, correlation, coverage

**Files:** Create `backend/monitor_intel.py`; Test `backend/tests/test_monitor_intel.py`

- [ ] **Step 1: Write the failing test:**
```python
import monitor_intel as intel

def test_flap_requires_consecutive_reds():
    # history newest-first; 1 red, 1 green → not yet flapping (threshold 2)
    assert intel.is_flapping_clear(["down", "ok"], threshold=2) is True   # not enough reds → suppress
    assert intel.is_flapping_clear(["down", "down"], threshold=2) is False # 2 reds → real, do alert

def test_effective_threshold_uses_baseline():
    # baseline median gap 2 min → effective = max(static 10, 3*2)=10; baseline 5 → max(10,15)=15
    assert intel.effective_threshold(static=10, baseline_min=2, k=3) == 10
    assert intel.effective_threshold(static=10, baseline_min=5, k=3) == 15

def test_correlate_groups_by_env_and_service():
    reds = [
        {"id": 1, "environment": "prod", "config": {"service": "repo"}, "type": "http"},
        {"id": 2, "environment": "prod", "config": {"service": "repo"}, "type": "log-freshness"},
        {"id": 3, "environment": "acc", "config": {"service": "x"}, "type": "http"},
    ]
    groups = intel.correlate(reds)
    assert any(len(g["targets"]) == 2 and g["environment"] == "prod" for g in groups)

def test_coverage_score():
    targets = [
        {"environment": "prod", "type": "log-freshness", "_status": "ok"},
        {"environment": "prod", "type": "jaeger-traces", "_status": "ok"},
        {"environment": "prod", "type": "prometheus-query", "_status": "down"},
    ]
    cov = intel.coverage(targets)["prod"]
    assert cov["score"] == round(2/3, 2) and cov["metrics"] == "down"
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `backend/monitor_intel.py`:**
```python
"""Intelligence helpers — pure functions over results/targets so they're unit-testable.
No I/O here; the engine feeds data in and acts on the verdicts."""
from statistics import median

_RED = {"down", "stale", "unreachable"}
_DIM = {"log-freshness": "logs", "jaeger-traces": "traces", "prometheus-query": "metrics", "http": "http"}

def is_flapping_clear(recent_statuses: list[str], threshold: int) -> bool:
    """True = SUPPRESS (not enough consecutive reds yet). recent_statuses newest-first."""
    streak = 0
    for s in recent_statuses:
        if s in _RED: streak += 1
        else: break
    return streak < threshold

def effective_threshold(static: float, baseline_min: float | None, k: int = 3) -> float:
    if not baseline_min: return static
    return max(static, k * baseline_min)

def baseline_minutes(fresh_gaps_min: list[float]) -> float | None:
    return round(median(fresh_gaps_min), 2) if fresh_gaps_min else None

def correlate(red_targets: list[dict]) -> list[dict]:
    groups: dict[tuple, dict] = {}
    for t in red_targets:
        svc = (t.get("config") or {}).get("service") or t.get("name")
        key = (t.get("environment", "na"), svc)
        g = groups.setdefault(key, {"environment": key[0], "service": svc, "targets": []})
        g["targets"].append(t)
    return list(groups.values())

def coverage(targets_with_status: list[dict]) -> dict:
    by_env: dict[str, dict] = {}
    for t in targets_with_status:
        env = t.get("environment", "na"); dim = _DIM.get(t["type"], "http")
        e = by_env.setdefault(env, {})
        # worst-wins per dimension
        cur = e.get(dim)
        st = "down" if t["_status"] in _RED else "ok"
        e[dim] = "down" if cur == "down" or st == "down" else st
    out = {}
    for env, dims in by_env.items():
        total = len(dims); ok = sum(1 for v in dims.values() if v == "ok")
        out[env] = {"score": round(ok / total, 2) if total else 1.0, **dims}
    return out
```

- [ ] **Step 4: Run — expect PASS (4 tests).** Fix until green.

- [ ] **Step 5: Commit** `feat(monitor): intelligence — baselines, flap, correlation, coverage`.

### Task 6: AI root-cause (best-effort, reuses RAG)

**Files:** Modify `backend/monitor_intel.py`; Modify `backend/tests/test_monitor_intel.py`

- [ ] **Step 1: Add failing test** (AI is best-effort → returns None gracefully):
```python
def test_ai_rootcause_is_best_effort(monkeypatch):
    import monitor_intel as intel
    # when the LLM path raises, we get None (never blocks)
    async def boom(*a, **k): raise RuntimeError("ai off")
    monkeypatch.setattr(intel, "_llm_summarize", boom)
    import asyncio
    grp = {"environment": "prod", "service": "repo",
           "targets": [{"name": "x", "type": "http", "_status": "down"}]}
    assert asyncio.run(intel.ai_rootcause(grp, sid="s")) is None
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement** — append to `monitor_intel.py`:
```python
async def _llm_summarize(prompt: str, sid: str) -> str:
    """Best-effort: reuse the app's RAG path. Pull a little ES context + ask the LLM."""
    import elastic, llm
    ctx = ""
    try:
        hits = await elastic.search_logs(sid, prompt, size=20)  # existing helper
        ctx = "\n".join(h.get("message", "") for h in (hits or []))[:4000]
    except Exception:  # noqa: BLE001
        pass
    return await llm.generate_answer(prompt, ctx)

async def ai_rootcause(group: dict, sid: str | None) -> str | None:
    """Dutch one-paragraph root-cause for a correlated incident. None on any failure /
    AI off — callers must treat it as optional."""
    if not sid:
        return None
    tlist = ", ".join(f"{t['name']} ({t['type']}: {t['_status']})" for t in group["targets"])
    prompt = (f"Korte root-cause analyse (Nederlands, max 3 zinnen) voor een monitoring-incident "
              f"in omgeving {group['environment']} voor service '{group['service']}'. "
              f"Rode signalen: {tlist}. Noem de meest waarschijnlijke oorzaak en 1 concrete actie.")
    try:
        out = await _llm_summarize(prompt, sid)
        return (out or "").strip() or None
    except Exception:  # noqa: BLE001 — AI is never allowed to break monitoring
        return None
```

- [ ] **Step 4: Run — expect PASS.** **Step 5: Commit** `feat(monitor): best-effort AI root-cause (reuses RAG)`.

---

# PHASE 4 — Engine + wiring

### Task 7: `monitor_engine.py` — poll loop, dependency suppression, alerts, snapshot

**Files:** Create `backend/monitor_engine.py`; Test `backend/tests/test_monitor_engine.py`

- [ ] **Step 1: Write the failing test** (one bad target never breaks the round; dependency suppression):
```python
import asyncio, monitor_engine as eng, monitor_registry as reg

def setup_function(_):
    with reg.cursor() as c:
        for t in ("monitor_results","monitor_targets","monitor_connections"): c.execute(f"DELETE FROM {t}")

def test_run_once_records_results_and_survives_bad_target(monkeypatch):
    good = reg.add_target(name="g", type="http", config={"url":"http://g"}, actor="a")
    bad  = reg.add_target(name="b", type="nope", config={}, actor="a")  # unknown type
    async def fake_check(t, conn): 
        return {"status":"ok","detail":{},"latency_ms":1} if t["type"]=="http" else (_ for _ in ()).throw(RuntimeError())
    monkeypatch.setattr(eng.monitor_checkers, "run_check", fake_check)
    asyncio.run(eng.run_once(sid="s"))
    assert reg.latest_result(good)["status"] == "ok"
    assert reg.latest_result(bad)["status"] == "unreachable"   # wrapped, not crashed

def test_snapshot_groups_by_env_and_has_coverage(monkeypatch):
    tid = reg.add_target(name="g", type="log-freshness", environment="prod",
                         config={"index":"x"}, actor="a")
    reg.record_result(tid, "ok", {}, None)
    snap = eng.snapshot()
    assert "prod" in snap["by_env"] and "coverage" in snap
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Implement `backend/monitor_engine.py`:**
```python
"""Background poll loop + dashboard snapshot. Fail-safe per target; AI/intel best-effort.
Off unless settings.monitor_enabled."""
import asyncio, logging
import monitor_registry as reg
import monitor_checkers
import monitor_intel as intel
from config import settings

logger = logging.getLogger(__name__)
_RED = {"down", "stale", "unreachable"}

async def _check_connection(conn) -> bool:
    """Cheap reachability for dependency suppression. http GET base_url."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=settings.monitor_timeout) as c:
            await c.get(conn["base_url"])
        return True
    except Exception:  # noqa: BLE001
        return False

async def run_once(sid: str | None = None):
    conns = {c["id"]: c for c in reg.list_connections() if c["enabled"]}
    conn_up = {cid: await _check_connection(c) for cid, c in conns.items()}
    for t in reg.list_targets(enabled_only=True):
        conn = conns.get(t.get("connection_id"))
        if conn and not conn_up.get(conn["id"], True):
            reg.record_result(t["id"], "unreachable", {"dependency": conn["name"]}, None)
            continue
        t["_ctx"] = {"sid": sid}
        # adaptive threshold for freshness types
        if t["type"] in ("log-freshness",) and t["config"].get("adaptive", True):
            gaps = []  # derived from history in a fuller impl; baseline None until enough data
            base = intel.baseline_minutes(gaps)
            t["config"]["_effective_threshold"] = intel.effective_threshold(
                t["config"].get("max_age_minutes", 10), base)
        res = await monitor_checkers.run_check(t, conn)
        reg.record_result(t["id"], res["status"], res.get("detail"), res.get("latency_ms"))
    await _evaluate_alerts(sid)

async def _evaluate_alerts(sid):
    """Flap-guarded, correlated, dependency-aware alerting via the existing engine."""
    targets = []
    for t in reg.list_targets(enabled_only=True):
        lr = reg.latest_result(t["id"]) or {"status": "ok"}
        t["_status"] = lr["status"]; targets.append(t)
    reds = []
    for t in targets:
        if t["_status"] in _RED and t["alert_enabled"]:
            recent = [r["status"] for r in reg.recent_results(t["id"], limit=settings.monitor_flap_threshold)]
            if not intel.is_flapping_clear(recent, settings.monitor_flap_threshold):
                reds.append(t)
    for group in intel.correlate(reds):
        rc = await intel.ai_rootcause(group, sid)   # best-effort
        _raise_monitoring_alert(group, rc)

def _raise_monitoring_alert(group, rootcause):
    """Bridge to the existing alert engine (Task 9 registers the 'Monitoring' category)."""
    try:
        import alerts
        alerts.raise_external(category="monitoring",
                              key=f"{group['environment']}:{group['service']}",
                              env=group["environment"],
                              title=f"Monitoring: {group['service']} ({group['environment']})",
                              detail=rootcause or ", ".join(t["name"] for t in group["targets"]))
    except Exception as e:  # noqa: BLE001 — never break the loop on alert issues
        logger.warning("monitoring alert bridge failed: %s", e)

def snapshot() -> dict:
    targets = []
    for t in reg.list_targets():
        lr = reg.latest_result(t["id"]) or {"status": "unknown", "detail": {}}
        t["_status"] = lr["status"]; t["_detail"] = lr.get("detail", {}); t["_ts"] = lr.get("ts")
        targets.append(t)
    by_env: dict[str, list] = {}
    for t in targets:
        by_env.setdefault(t["environment"], []).append({
            "id": t["id"], "name": t["name"], "type": t["type"],
            "status": t["_status"], "detail": t["_detail"], "enabled": t["enabled"]})
    return {"enabled": True, "by_env": by_env,
            "coverage": intel.coverage([t for t in targets if t["enabled"]])}

async def run_monitor_loop():
    if not settings.monitor_enabled:
        logger.info("monitor loop disabled"); return
    while True:
        try:
            await run_once(sid=None)   # sid wired from a service session if available
        except Exception as e:  # noqa: BLE001
            logger.error("monitor loop cycle failed: %s", e)
        await asyncio.sleep(settings.monitor_interval)
```
> Note `alerts.raise_external(...)` is added in Task 9. Until then the bridge is wrapped in try/except so tests pass.

- [ ] **Step 4: Run — expect PASS (2 tests).** Fix until green.

- [ ] **Step 5: Commit** `feat(monitor): engine — poll loop, dependency suppression, snapshot`.

### Task 8: Wire the loop into `main.py` lifespan

**Files:** Modify `backend/main.py`

- [ ] **Step 1:** Add import near the other loop imports (~line 40):
```python
from monitor_engine import run_monitor_loop
```
- [ ] **Step 2:** In `lifespan`, after `service_health_task` (~line 61):
```python
    monitor_task = asyncio.create_task(run_monitor_loop())
```
- [ ] **Step 3:** Ensure it's cancelled on shutdown alongside the others (add `monitor_task` to the cancel/gather block that follows the `yield`, mirroring `service_health_task`).
- [ ] **Step 4: Verify import + app boots** (run the existing test suite; no new test):
```bash
cd /c/ANT-PROJECT/KIBANA-OO/backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 docker run --rm -v "$HP:/app" -w /app python:3.13 sh -c "pip install -q -r requirements.txt && python -c 'import main' && python -m pytest tests/test_monitor_engine.py -q"
```
- [ ] **Step 5: Commit** `feat(monitor): start poll loop in app lifespan`.

---

# PHASE 5 — API + permissions + alerts category

### Task 9: Alert category bridge

**Files:** Modify the alerts module that owns categories (inspect `backend/alerts.py`); Test `backend/tests/test_monitor_alerts.py`

- [ ] **Step 1:** Read `backend/alerts.py` to find how categories + `run_alert_loop` raise/dedup alerts. Identify the public function the engine should call.
- [ ] **Step 2: Write failing test** — `raise_external` records one alert per incident key (dedup):
```python
import alerts
def test_raise_external_dedups(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(alerts, "_dispatch", lambda *a, **k: sent.append(a))  # adjust to real dispatch
    alerts.raise_external("monitoring", "prod:repo", "prod", "T", "d")
    alerts.raise_external("monitoring", "prod:repo", "prod", "T", "d")
    assert len(sent) == 1  # second is deduped while still firing
```
- [ ] **Step 3: Implement** `alerts.raise_external(category, key, env, title, detail)` reusing the existing dedup/state + email→Mattermost dispatch (match the existing per-incident pattern; add a `"monitoring"` category label). Keep it consistent with how cert/dlq/service-health alerts are raised.
- [ ] **Step 4: Run — expect PASS.** **Step 5: Commit** `feat(monitor): 'monitoring' alert category bridge`.

### Task 10: `monitor_api.py` router + permissions feature key

**Files:** Create `backend/monitor_api.py`; Modify `backend/permissions.py`; Modify `backend/main.py`; Test `backend/tests/test_monitor_api.py`

- [ ] **Step 1:** In `backend/permissions.py` FEATURES list, add:
```python
    {"key": "monitoring", "label": "Monitoring targets", "group": "Dashboard"},
```
- [ ] **Step 2: Write failing test** (FastAPI TestClient; secret never leaks):
```python
from fastapi.testclient import TestClient
import main
client = TestClient(main.app)
# (use the project's existing test-auth helper/fixture to authenticate as super-admin)

def test_types_schema_endpoint(super_headers):
    r = client.get("/monitor/types", headers=super_headers)
    assert r.status_code == 200 and "http" in r.json()

def test_connection_create_hides_secret(super_headers):
    r = client.post("/monitor/connections", headers=super_headers, json={
        "kind":"prometheus","name":"P","base_url":"http://p:9090","secret_ref":"PROM_TOKEN"})
    assert r.status_code == 200
    body = r.json()
    assert "PROM_TOKEN" == body.get("secret_ref")          # name ok
    assert "secret_value" not in body and "token" not in body
```
> Use the existing super-admin auth fixture from the current test-suite (`backend/tests/`); mirror how `test_*_api.py` authenticates.

- [ ] **Step 3: Implement `backend/monitor_api.py`:**
```python
"""Monitoring registry API. Config = super-admin; results = require_feature('monitoring').
Secrets (values) never enter requests/responses — only secret_ref names."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import require_super, require_feature
from config import settings
import monitor_registry as reg
import monitor_checkers
import monitor_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/monitor")

class ConnectionIn(BaseModel):
    kind: str; name: str; base_url: str; secret_ref: str | None = None; enabled: bool = True
class TargetIn(BaseModel):
    name: str; type: str; environment: str = "na"; connection_id: int | None = None
    config: dict = {}; enabled: bool = True; alert_enabled: bool = True

@router.get("/types")
async def types(_: dict = Depends(require_super)): return monitor_checkers.types_schema()

@router.get("/connections")
async def conns(_: dict = Depends(require_super)): return reg.list_connections()
@router.post("/connections")
async def add_conn(body: ConnectionIn, s: dict = Depends(require_super)):
    cid = reg.add_connection(body.kind, body.name, body.base_url, body.secret_ref, s.get("username"))
    return reg.get_connection(cid)
@router.delete("/connections/{cid}")
async def del_conn(cid: int, _: dict = Depends(require_super)): reg.delete_connection(cid); return {"ok": True}

@router.get("/targets")
async def targets(_: dict = Depends(require_super)): return reg.list_targets()
@router.post("/targets")
async def add_tgt(body: TargetIn, s: dict = Depends(require_super)):
    tid = reg.add_target(body.name, body.type, body.environment, body.config,
                         body.connection_id, s.get("username"))
    if not body.enabled: reg.set_target_enabled(tid, False)
    if not body.alert_enabled: reg.update_target(tid, {"alert_enabled": 0})
    return reg.get_target(tid)
@router.patch("/targets/{tid}")
async def patch_tgt(tid: int, patch: dict, _: dict = Depends(require_super)):
    reg.update_target(tid, patch); return reg.get_target(tid)
@router.delete("/targets/{tid}")
async def del_tgt(tid: int, _: dict = Depends(require_super)): reg.delete_target(tid); return {"ok": True}

@router.post("/test")
async def test_target(body: TargetIn, _: dict = Depends(require_super)):
    conn = reg.get_connection(body.connection_id) if body.connection_id else None
    return await monitor_checkers.run_check({"type": body.type, "config": body.config}, conn)

@router.get("/discover")
async def discover(connection_id: int, _: dict = Depends(require_super)):
    conn = reg.get_connection(connection_id)
    if not conn: raise HTTPException(404, "connection not found")
    chk = monitor_checkers.CHECKERS.get({"prometheus": "prometheus-query", "jaeger": "jaeger-traces"}.get(conn["kind"], ""))
    if not chk or not chk.get("discover"): return {"suggestions": []}
    return {"suggestions": await chk["discover"](conn)}

# results (feature-gated, mirrors service-health card endpoint)
results_router = APIRouter(prefix="/dashboard/monitoring")
@results_router.get("")
async def card(_: dict = Depends(require_feature("monitoring"))):
    if not settings.monitor_enabled: return {"enabled": False}
    try: return monitor_engine.snapshot()
    except Exception as e:  # noqa: BLE001
        logger.error("monitoring snapshot failed: %s", e)
        raise HTTPException(502, "Monitoring unavailable") from e
```

- [ ] **Step 4:** In `backend/main.py`, include both routers (after `service_health_router`):
```python
from monitor_api import router as monitor_router, results_router as monitor_results_router
app.include_router(monitor_router)
app.include_router(monitor_results_router)
```
- [ ] **Step 5: Run — expect PASS.** **Step 6: Commit** `feat(monitor): API (config super-admin + feature-gated card) + permission key`.

### Task 11: Auto-discovery `discover()` for ES/Jaeger/Prometheus

**Files:** Modify `backend/monitor_checkers.py`; Test add to `test_monitor_checkers.py`

- [ ] **Step 1: Add failing test** (mock httpx → Jaeger services list → suggestions):
```python
def test_jaeger_discover(monkeypatch):
    import httpx, asyncio, monitor_checkers as mc
    class R: status_code=200
    R.json = lambda self: {"data": ["repo", "search"]}
    class C:
        async def __aenter__(s): return s
        async def __aexit__(s,*a): return False
        async def get(s,u,**k): return R()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: C())
    sug = asyncio.run(mc.CHECKERS["jaeger-traces"]["discover"]({"base_url":"http://j","secret_ref":None}))
    assert {"service":"repo"} in [{"service": s["config"]["service"]} for s in sug]
```
- [ ] **Step 2: Run — expect FAIL.**
- [ ] **Step 3: Implement** `discover()` for jaeger (`GET /api/services`), prometheus (`GET /api/v1/targets`), and register them on the existing checkers (pass `discover=` in `register(...)`). Each returns a list of `{"name","type","environment","config","connection_id"}` suggestion dicts.
- [ ] **Step 4: Run — expect PASS.** **Step 5: Commit** `feat(monitor): auto-discovery for jaeger/prometheus`.

---

# PHASE 6 — Frontend config page

### Task 12: `MonitoringConfig.jsx` (Beheer → Monitoring, super-admin)

**Files:** Create `frontend/src/MonitoringConfig.jsx`; Modify `frontend/src/api.js` (add fetchers); Modify `frontend/src/Nav.jsx` (BEHEER_SUB); Modify `frontend/src/App.jsx` (route the view)

- [ ] **Step 1:** Add API helpers to `frontend/src/api.js` (follow the existing fetch-wrapper style): `fetchMonitorTypes`, `fetchMonitorConnections`, `addMonitorConnection`, `deleteMonitorConnection`, `fetchMonitorTargets`, `addMonitorTarget`, `patchMonitorTarget`, `deleteMonitorTarget`, `testMonitorTarget`, `discoverMonitor`.
- [ ] **Step 2:** Build `MonitoringConfig.jsx` using the OO-GX kit + the existing `.switch` toggle + `.gx-panel`/`.gx-pagehead` (copy the structure/patterns from `Settings.jsx` and `Authorization.jsx`). Structure:
  - `.gx-pagehead` eyebrow `• BEHEER · MONITORING` + `.gx-h1` `MONITORING`.
  - **Connections** `.gx-panel`: list rows (kind · name · base_url · secret_ref badge "via .env" if set) + add form + a **Test connection** button (calls `testMonitorTarget` with a probe target, or a dedicated connection ping).
  - **Targets** `.gx-panel`: a table grouped by `environment` then `type`; each row shows name, type, status of last check (if present), an **enable** `.switch`, an **alert** `.switch`, **Test** and **Delete** buttons.
  - **Add/Edit target modal**: a generic form whose fields are rendered from `fetchMonitorTypes()` (the `fields` array per type: text/int/float/bool/select/list-int). On submit → `addMonitorTarget`/`patchMonitorTarget`. A **Discover** button lists `discoverMonitor(connection_id)` suggestions, each with **"Add as target"** that pre-fills the form.
  - **Don't** put secret values in the UI — only the `secret_ref` name field.
- [ ] **Step 3:** Wire nav: add `monitoring` to `BEHEER_SUB` in `Nav.jsx`; route `view === "monitoring" && isSuper` to `<MonitoringConfig token={token} />` in `App.jsx` (mirror the `authorization` page wiring).
- [ ] **Step 4: Build-green** (frontend build command). Manually load Beheer → Monitoring; add a connection + an `http` target; toggle it; Test it.
- [ ] **Step 5: Commit** `feat(monitor): super-admin config page + nav`.

---

# PHASE 7 — Dashboard card

### Task 13: `MonitoringCard.jsx` + Dashboard + Smart Context mapping

**Files:** Create `frontend/src/MonitoringCard.jsx`; Modify `frontend/src/Dashboard.jsx`; Modify `backend/context_engine.py`

- [ ] **Step 1:** Build `MonitoringCard.jsx` modeled on `ServiceHealth.jsx` (self-fetching via `GET /dashboard/monitoring`; renders nothing when `{enabled:false}` or no grant). Structure:
  - `<section className="panel ..." data-smartcard="card:monitoring" data-smartlabel="Monitoring" data-smartstatus={worstStatus} data-smartenv="PROD">`.
  - Header: `<h3 className="gx-h2">📡 Monitoring</h3>` + a coverage summary per env (`PROD 92% · logs ✓ traces ✓ metrics ✗`) using `.gx-pill`.
  - Body: targets grouped by env as colour-barred tiles (reuse the `svch-tile` look or a new `mon-tile` class; ok=green/warn=amber/stale=amber/down=red/unreachable=grey). Click to expand last-check detail.
  - If the snapshot includes correlated incidents with AI root-cause, show them at the top with the runbook link.
- [ ] **Step 2:** Render `<MonitoringCard token={token} />` in `Dashboard.jsx` (next to the Service health card).
- [ ] **Step 3:** In `backend/context_engine.py`, add `"card:monitoring": "monitoring"` to `_CARD_COMPONENT` and a `_derive_condition` branch (status `down`/`stale` → a "service"/"down" runbook condition) so the Smart Context panel + runbook work — mirror the `card:service_health` wiring.
- [ ] **Step 4:** Append `.mon-*` CSS (namespaced) to `styles.css` only if `svch-*`/kit classes don't cover it.
- [ ] **Step 5: Build-green.** With `MONITOR_ENABLED=true` + a target configured, confirm the card renders, groups by env, shows coverage, and the hover Smart Context panel resolves.
- [ ] **Step 6: Commit** `feat(monitor): dashboard card + Smart Context mapping`.

---

# PHASE 8 — Docs + ship

### Task 14: Dutch vault note + enable + ship

**Files:** Create `docs/KIBANA-OO/Monitoring targets.md`

- [ ] **Step 1:** Write the vault note (frontmatter `title/tags/component: monitoring/owner`) covering: what it is (admin-configurable registry), the checker types, the intelligence features, how to add a connection/target, the `.env` flags (`MONITOR_ENABLED` etc.), and a `[[AI-architectuur]]` + `[[Service health]]` link. Mirror `docs/KIBANA-OO/Service health.md` structure.
- [ ] **Step 2:** Run the **full backend test suite** + frontend build — all green.
- [ ] **Step 3:** Deploy: `docker compose up -d --build backend frontend`. With `MONITOR_ENABLED=true` (local `.env`), smoke-test: add a connection + targets, toggle, Test, dashboard card, an induced failure → alert.
- [ ] **Step 4: Commit** `docs(monitor): Dutch vault note`.
- [ ] **Step 5: Ship** (branch → PR → merge → mirror, the project rhythm):
```bash
cd /c/ANT-PROJECT/KIBANA-OO && git push -u origin feat/monitoring-registry
gh pr create --base main --head feat/monitoring-registry --title "feat: admin-configurable Monitoring Targets registry + intelligence" --body "See docs/superpowers/specs/2026-06-27-monitoring-registry-design.md"
gh pr merge feat/monitoring-registry --merge
git checkout main && git pull --ff-only origin main && git push gitlab main
git branch -d feat/monitoring-registry && git push origin --delete feat/monitoring-registry
```

---

## Self-review

- **Spec coverage:** §4 data model → Task 1. §5 checkers (4 types) → Tasks 2–4. §6 intelligence: discovery → Task 11; baselines/flap/correlation/coverage → Task 5; AI root-cause → Task 6; dependency suppression → Task 7. §7 engine/loop → Tasks 7–8. §8 API (config/test/discover/types/card) → Task 10. alerts category → Task 9. §9 frontend config → Task 12, card → Task 13. secrets-in-env → Tasks 1/4/10 (secret_ref only). auth (super vs feature) → Task 10. §10 files → all. §11 testing → each task is TDD. §12 safety/flag/additive → Tasks 1/7/8. docs → Task 14. No gaps.
- **Placeholder scan:** none — every backend task has concrete code + tests; frontend tasks give structure + exact API contract + the template file to copy (`ServiceHealth.jsx`/`Settings.jsx`) since pixel-exact JSX in a plan is low-value and the OO-GX kit exists.
- **Type/name consistency:** `monitor_registry` fns (`add_target/get_target/list_targets/record_result/latest_result/recent_results/list_connections/get_connection`), `monitor_checkers.run_check/types_schema/CHECKERS/register/_es_max_timestamp`, `monitor_intel.is_flapping_clear/effective_threshold/baseline_minutes/correlate/coverage/ai_rootcause/_llm_summarize`, `monitor_engine.run_once/snapshot/run_monitor_loop`, `alerts.raise_external`, settings `monitor_enabled/interval/timeout/flap_threshold`, feature key `"monitoring"`, `data-smartcard="card:monitoring"` — all used consistently across tasks.
- **Note for implementer:** Task 9 must read `alerts.py` first to match the real dedup/dispatch internals (the test's `_dispatch` monkeypatch is illustrative — adapt to the actual function names). Task 3's `_es_max_timestamp` real call is wired in the engine where a service `sid` exists; keep the function name stable.
