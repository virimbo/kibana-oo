# Monitoring Targets Registry — Design Spec

- **Date:** 2026-06-27
- **Status:** Approved design (Q1 A · Q2 B · Q3 A · Q4 A · Q5 A + Intelligence layer 1–6), ready for implementation plan
- **Author:** Anton Partono (with Claude, acting as observability/monitoring engineer)
- **Trigger:** Ingress → Gateway API migration (all apps migrated, prod-rolled across PROD/ACC/TEST). Need to verify not just app function but that **logging/metrics/tracing still flow** to Kibana/Grafana/Jaeger — and a generic, admin-configurable way to add monitoring targets in future (incl. Prometheus/Jaeger URLs supplied by devs later).

## 1. Goal

A **generic, DB-backed, admin-configurable "Monitoring Targets" registry** so admins can
add/edit/toggle monitoring checks **from the UI, without code changes** — and an
**intelligence layer** that discovers what to watch, learns normal, correlates failures,
and explains likely causes by reusing the app's existing RAG/Smart-Context/runbook/alert
engines.

**Hard constraints:**
- **Additive only.** Existing monitors (Service health, Uptime, **Certificates — FROZEN**,
  DLQ) keep reading `.env` and are **not touched**. New subsystem, new tables, new files;
  existing code touched only via small additive wire-ups (router include, nav item,
  dashboard card, feature key, alert category).
- **No secrets in the DB or API.** Secrets live only in gitignored `.env`, referenced by
  name (RULES.md). The API never returns secret values.
- Must not regress any existing functionality.

## 2. Decisions (the 5 questions + intelligence)

1. **(Q1 A) Additive-only** — registry powers new + future targets; existing/FROZEN
   monitors untouched. Optional migration of non-frozen monitors is a *later* sprint.
2. **(Q2 B) Generic `http` + observability triad** — checker types in v1:
   `http`, `log-freshness`, `jaeger-traces`, `prometheus-query`. Plugin pattern → more
   types later (`tls-cert`, `tcp-port`, …).
3. **(Q3 A) URLs/config in DB (UI-editable); secrets in `.env` by `secret_ref`.**
   Elasticsearch reuses the app's existing authenticated session — no new secret.
4. **(Q4 A) Per-target `environment`** (prod/acc/test/na); config + dashboard grouped by env.
5. **(Q5 A) One unified "Monitoring targets" dashboard card** + reuse the existing alert
   engine (new "Monitoring" category, per-target alert toggle).
6. **Intelligence layer (build 1–6):** auto-discovery, adaptive baselines, correlation +
   AI root-cause, dependency-aware suppression, flap detection, coverage score.
   Roadmap (not now): synthetic canaries, maintenance windows, ML anomaly.

**Seeding:** ship the registry **empty** (checker types ready); admins add targets as the
dev-supplied URLs arrive.

## 3. Architecture (overview)

```
Admin UI (super-admin)                Background poller (every N s)
  Connections + Targets  ──writes──▶  monitor_registry (SQLite)
        │  "Test"                          │  reads enabled targets
        ▼                                  ▼
  monitor_api (FastAPI)              monitor_checkers.run(type) ──▶ monitor_results
        ▲                                  │
  Dashboard card  ◀──reads results────────┘   │ on red/clear:
  (grouped by env)                            ▼
                                        intelligence: correlate + (LLM root-cause)
                                              ▼
                                        existing alert engine (email→Mattermost)
```

Each unit has one responsibility and a clear interface (see §10 file structure).

## 4. Data model (SQLite, via `db.py`, in the shared `kibana_oo.db`)

```sql
-- shared backend URLs, set once (DRY: many targets reuse one connection)
CREATE TABLE IF NOT EXISTS monitor_connections (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,            -- 'prometheus' | 'jaeger'  (ES is implicit/existing)
  name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  secret_ref TEXT,              -- name of an .env var holding a token; never the value
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT, updated_at TEXT, created_by TEXT
);

-- the actual checks
CREATE TABLE IF NOT EXISTS monitor_targets (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL,           -- 'http'|'log-freshness'|'jaeger-traces'|'prometheus-query'
  environment TEXT NOT NULL DEFAULT 'na',  -- 'prod'|'acc'|'test'|'na'
  enabled INTEGER NOT NULL DEFAULT 1,      -- the on/off toggle
  alert_enabled INTEGER NOT NULL DEFAULT 1,
  connection_id INTEGER,        -- FK for prometheus/jaeger types (nullable)
  config TEXT NOT NULL DEFAULT '{}',       -- JSON, type-specific fields
  created_at TEXT, updated_at TEXT, created_by TEXT
);

-- last result per target (+ short history for baselines/flap)
CREATE TABLE IF NOT EXISTS monitor_results (
  id INTEGER PRIMARY KEY,
  target_id INTEGER NOT NULL,
  ts TEXT NOT NULL,
  status TEXT NOT NULL,         -- 'ok'|'warn'|'stale'|'down'|'unreachable'
  detail TEXT,                  -- JSON: measured value, threshold, message
  latency_ms INTEGER
);
CREATE INDEX IF NOT EXISTS ix_monitor_results_target_ts ON monitor_results(target_id, ts);
```

`config` JSON per type, e.g.:
- `http`: `{ "url": "...", "expected_status": [200,204], "timeout_s": 8 }`
- `log-freshness`: `{ "index": "logs-gateway-*", "timestamp_field": "@timestamp",
  "max_age_minutes": 10, "adaptive": true }`
- `jaeger-traces`: `{ "service": "repository", "lookback_minutes": 15, "min_traces": 1 }`
- `prometheus-query`: `{ "query": "up{job=\"gateway\"}", "op": ">", "threshold": 0 }`

## 5. Checker plugin pattern (`monitor_checkers.py`)

A registry `CHECKERS: dict[str, Checker]`. Each `Checker` declares:
- `type_id: str`
- `fields: list[Field]` — config schema (name, label, kind, default) so the **UI builds
  the form automatically** and `GET /monitor/types` exposes it.
- `async def check(target, connection, ctx) -> Result` — returns
  `{status, detail, latency_ms}`. Never raises out (wraps errors → `unreachable`).
- `async def discover(connection) -> list[Suggestion]` (optional) — for auto-discovery.

v1 checkers:
- **`http`** — GET `url`; status in `expected_status` → `ok` (or `degraded` if slow), 5xx →
  `down`, connect-fail/timeout → `unreachable`. (Mirrors Service-health classification.)
- **`log-freshness`** — query ES (reuse `elastic.py`) for `max(timestamp_field)` on
  `index`; age > threshold → `stale`; ES error → `unreachable`. Adaptive: see §6.2.
- **`jaeger-traces`** — `GET {jaeger}/api/traces?service=…&lookback=…` (or count API);
  traces < `min_traces` → `stale`.
- **`prometheus-query`** — `GET {prometheus}/api/v1/query?query=…`; evaluate `op`/`threshold`
  → `ok|warn|down`; empty result → `stale`/`down` per config.

Adding a type = add one `Checker` and register it. No other code changes.

## 6. Intelligence layer (v1 items 1–6)

### 6.1 Auto-discovery (`discover()` per connection/source)
- ES → list indices/data-streams (`GET _cat/indices` via the existing proxy).
- Jaeger → `GET /api/services`.
- Prometheus → `GET /api/v1/targets` (+ `/label/__name__/values`).
- API: `GET /monitor/discover?connection_id=…` → suggestions; the UI shows them with a
  one-click **"Add as target"** (pre-fills the config form). Admin stays in control
  (suggest, don't auto-create).

### 6.2 Adaptive freshness baselines
- For `log-freshness`/`jaeger-traces`, compute a rolling **expected interval** from
  `monitor_results` history (e.g. median inter-arrival of "fresh" observations over the
  last 24h). Flag `stale` when the gap exceeds `max(static_threshold, k × baseline)`.
- Falls back to the static `max_age_minutes` until enough history exists. `adaptive` flag
  per target (default on).

### 6.3 Correlation + AI root-cause
- After each poll round, group **currently-red** targets by `(environment, service/host)`
  into an **incident** (a target's `config` may carry a `service` label; `http`/`log`/
  `trace`/`metric` for the same service+env correlate).
- For a new correlated incident, call the **existing LLM/RAG** (`llm.generate_answer` +
  `elastic` retrieval, the same path chat uses) to produce a short **Dutch** root-cause
  summary, and attach the matching **runbook** action via the existing `context_engine`
  runbook parser. Shown on the dashboard card + included in the alert.
- AI is **best-effort**: if AI is off or fails, the incident still shows the raw
  correlated facts (never blocks the alert).

### 6.4 Dependency-aware suppression
- If a `connection` is unreachable, emit **one** "`<connection>` unreachable" status and
  mark its dependent targets `unreachable (dependency)` **without** firing per-target
  alerts — prevents alert storms. Same idea for a fully-down service vs. one pipeline.

### 6.5 Flap detection
- A target must be red for **N consecutive** poll rounds (configurable, default 2–3)
  before it alerts; clears after M consecutive greens. Uses `monitor_results` history.

### 6.6 Observability coverage score (per environment)
- Roll up per env: are `log`/`trace`/`metric`/`http` all green for the tracked services?
  Produce `coverage = healthy_dimensions / total_dimensions` and a one-line summary
  (`"PROD 92% — logs ✓ · traces ✓ · metrics ✗"`). Surfaced at the top of the card.

## 7. Background poller (`monitor_engine.py`)

`run_monitor_loop()` (started in `main.py` lifespan, like the other monitors):
1. Load enabled connections; probe each (for §6.4 dependency state).
2. For each enabled target: run its checker (skip/short-circuit if its connection is down),
   store a `monitor_results` row.
3. Apply intelligence: baselines (6.2), flap (6.5), correlation+AI (6.3), coverage (6.6).
4. For `alert_enabled` targets/incidents that crossed a threshold, raise/clear via the
   **existing** alert engine (new "Monitoring" category). Fail-safe per target.
Interval/timeout from `config.py` (`MONITOR_INTERVAL`, `MONITOR_TIMEOUT`), feature flag
`MONITOR_ENABLED` (default false for instant rollback, like Service health).

## 8. API (`monitor_api.py`, router included in `main.py`)

Config (super-admin, `require_super`):
- `GET/POST /monitor/connections`, `PUT/PATCH/DELETE /monitor/connections/{id}`
- `GET/POST /monitor/targets`, `PUT/PATCH/DELETE /monitor/targets/{id}`
- `PATCH /monitor/targets/{id}/toggle` (enabled), …/alert-toggle
- `POST /monitor/test` (run a target/connection config **live** before save — "Test")
- `GET /monitor/types` (checker schemas → UI form builder)
- `GET /monitor/discover?connection_id=…` (auto-discovery suggestions)

Results (grant-gated, `require_feature("monitoring")`):
- `GET /dashboard/monitoring` → targets grouped by env + latest results + coverage +
  active incidents. Returns `200 {enabled:false}` when the feature is off (card hides),
  matching Service health.

Secrets: requests/responses never include secret values; only `secret_ref` (the env-key
name) and a boolean "is set".

## 9. Frontend

### 9.1 Admin config page — `MonitoringConfig.jsx` (Beheer → Monitoring, super-admin)
- **Connections** section: list + add/edit (kind, name, base_url, optional secret_ref) +
  **"Test connection"** button (calls `/monitor/test`).
- **Targets** section: table **grouped by environment & type**; add/edit modal whose
  fields are **driven by `/monitor/types`** (generic form builder); the **enable toggle**,
  **alert toggle**, a per-target **"Test"** (live check before save), and a **"Discover"**
  action that lists suggestions from the chosen connection with one-click add.
- Reuses the OO-GX kit + the `.switch` toggle pattern. Added to `BEHEER_SUB` in `Nav.jsx`.

### 9.2 Dashboard card — `MonitoringCard.jsx`
- Self-fetching (like `ServiceHealth.jsx`); hidden when feature off / no grant.
- Top: **coverage score** per env. Body: targets **grouped by env**, each a colour-barred
  tile (ok/warn/stale/down/unreachable) with detail; click to expand (last check, value
  vs threshold/baseline). Correlated **incidents** show the AI root-cause + runbook link.
- `data-smartcard="card:monitoring"` so the Smart Context panel works (add mapping in
  `context_engine`). Added to `Dashboard.jsx`.

## 10. File structure

| File | Responsibility | Action |
|---|---|---|
| `backend/monitor_registry.py` | schema + CRUD for connections & targets & results | Create |
| `backend/monitor_checkers.py` | checker plugin registry (4 types) + `discover()` | Create |
| `backend/monitor_intel.py` | baselines, correlation, AI root-cause, coverage, flap | Create |
| `backend/monitor_engine.py` | poll loop + result store + alert eval (uses the above) | Create |
| `backend/monitor_api.py` | FastAPI router (config + results + test + discover) | Create |
| `frontend/src/MonitoringConfig.jsx` | super-admin config page | Create |
| `frontend/src/MonitoringCard.jsx` | dashboard card | Create |
| `backend/main.py` | include router + start loop (lifespan) | Modify (additive) |
| `backend/config.py` | `monitor_enabled/interval/timeout` settings | Modify (additive) |
| `backend/permissions.py` | `"monitoring"` feature key | Modify (additive) |
| `backend/context_engine.py` | `card:monitoring` → component + runbook condition | Modify (additive) |
| `frontend/src/Nav.jsx` | Beheer sub-item "Monitoring" | Modify (additive) |
| `frontend/src/Dashboard.jsx` | render `MonitoringCard` | Modify (additive) |
| alerts (`alerts*.py`) | register a "Monitoring" category | Modify (additive) |
| `docs/KIBANA-OO/Monitoring targets.md` | Dutch vault note | Create |

## 11. Testing

- **Checkers:** unit tests per type with mocked HTTP/ES/Jaeger/Prometheus responses →
  correct status classification (incl. timeout → unreachable, 5xx → down, stale).
- **Registry/CRUD:** create/update/toggle/delete; secret_ref never leaks in API output.
- **Intelligence:** baseline staleness math; flap (N-consecutive) transitions; correlation
  grouping; dependency suppression (connection down → no per-target alert storm);
  coverage score computation.
- **Engine:** one bad target never breaks the round; feature flag off → inert.
- Run in the `python:3.13` Docker image alongside existing tests.

## 12. Safety, rollback, additivity

- New tables, new files; existing monitors and **FROZEN cert code untouched**.
- `MONITOR_ENABLED=false` default → poller inert, card hidden (instant rollback).
- Read-only checks on admin-configured URLs (no user-typed URL reaches a server without
  super-admin); short timeouts; fail-safe per target; AI best-effort (never blocks).
- Secrets only in `.env`; API never returns them.

## 13. Out of scope (roadmap)

Synthetic canaries (inject a log/trace/metric and confirm arrival), maintenance windows,
ML-grade anomaly detection, migrating the existing `.env` monitors into the registry.
