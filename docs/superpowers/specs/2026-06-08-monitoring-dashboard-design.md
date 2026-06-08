# KIBANA-OO — Admin Monitoring Dashboard — Design Spec

**Date:** 2026-06-08
**Author:** Brainstormed with the user (acting as Kibana engineer + full-stack dev)
**Status:** Approved design — pending spec review → implementation plan

---

## 1. Purpose

Give an administrator a single page to check, **every day**, what is critically wrong
with the application — which system, which errors, when, and a plain-language briefing
of likely causes. Optimised for fast daily triage and post-incident review.

Non-goals (v1): real-time NOC wall display, full alerting platform, configurable rule DSL.

---

## 2. Decisions (from 10-question brainstorm)

| # | Topic | Decision |
|---|-------|----------|
| 1 | Location | New `/dashboard` page **inside KIBANA-OO** (reuse auth, proxy, design, LLM) |
| 2 | "Critical" | **Error logs + HTTP 5xx + APM errors**. Spike/baseline detection → phase 2 |
| 3 | Scope | **Per-data-view breakdown**, driven by the existing whitelist; overview header |
| 4 | Time window | **Calendar day (today) + date picker** + **comparison deltas**; tz Europe/Amsterdam |
| 5 | Panels | **7-panel "Standard"** set; AI briefing auto-once-per-day, cached |
| 6 | Refresh | **~60s server cache + "data as of" + manual Refresh**; opt-in auto-refresh (default off) |
| 7 | Alerting | **Pull-only v1**; daily digest architected as clean phase-2 add (Slack likely) |
| 8 | Access | **Keycloak role/group gating, backend-enforced**; env allowlist fallback |
| 9 | AI triage | **Grounded** — deterministic facts are the source of truth; LLM narrates only; evidence shown |
| 10 | Robustness | **Graceful degradation + single-snapshot consistency** + timeouts/size caps |

---

## 3. Architecture

No new services. A dashboard module added to the existing FastAPI backend and React frontend.

### Backend
- `backend/monitoring.py` — **fact layer**. Pure Elasticsearch aggregations (via the
  existing `elastic._es_search` Kibana proxy + index whitelist). Returns a typed,
  deterministic snapshot. Callable by the web endpoint now and the phase-2 digest cron later.
- `backend/dashboard.py` — router exposing:
  - `GET /dashboard/summary?date=YYYY-MM-DD` → full deterministic snapshot (admin-gated, cached ~60s).
  - `GET /dashboard/briefing?date=YYYY-MM-DD` → grounded AI triage (separate endpoint, lazy,
    cached per day, never blocks the numeric panels).
- `backend/auth.py` — `require_admin` dependency; resolves admin status from Keycloak
  session (role/group) or env allowlist fallback.
- `backend/main.py` — include the router.
- `backend/config.py` — new settings: cache TTL, timezone, admin source/allowlist.

### Frontend
- `frontend/src/Dashboard.jsx` — page + panel components.
- `frontend/src/App.jsx` — nav toggle **Chat ⇄ Dashboard** (Dashboard link shown to admins only).
- `frontend/src/styles.css` — dashboard styles (reuse existing tokens).
- `frontend/nginx.conf` — proxy `location /dashboard/`.

### Key principle
The **fact layer is the backbone**. Every number displayed comes from deterministic
aggregations. The LLM never produces a metric — only narration over facts it is handed.

---

## 4. Fact layer — definition of "critical"

Per data view, bounded to the resolved day window (Europe/Amsterdam → UTC under the hood).

**Critical filter** (`bool.should`, minimum_should_match 1):
- `log.level` ∈ {error, fatal, critical} (case-insensitive) OR `error.message` exists
- OR HTTP status ≥ 500 (`http.response.status_code` and common ECS variants)
- OR APM error docs (`processor.event: error`) when an APM index is in scope

**Aggregations per snapshot:**
- `total` criticals + `date_histogram` (hourly, tz-offset) → time-series
- `terms` by data view and by `service.name` → per-system & affected-services breakdowns
- `terms` by normalized **error signature** (error type / message keyword) → top signatures
  (with first/last seen via min/max `@timestamp`)
- status-code `terms` (filtered ≥ 500) + top failing URLs → 5xx panel
- **Deltas**: same total for *yesterday* and a *7-day same-window average* → ▲/▼ %

**Guards:** per-query `timeout`, bounded `terms` size, bounded `track_total_hits`,
document-ID dedup for any cross-view total (handles `logs-*` overlap with `ds-prod5-*`).

**Output:** one typed JSON snapshot consumed by all panels (single-snapshot consistency).

---

## 5. Panels & layout

Single scrollable column (chat-width), overview → detail:

1. **Status banner + KPIs** — `All clear / Degraded / Critical` (thresholded on counts+deltas);
   total criticals + delta; # systems affected; error-rate %.
2. **Criticals over time** — hourly bars.
3. **By system** — Plooi / SP / other tiles, counts + deltas; failed tile → "unavailable — retry".
4. **Top error signatures** — grouped, counts, first/last seen.
5. **Affected services / hosts** — top offenders.
6. **HTTP 5xx** — status codes + top failing endpoints.
7. **AI Daily Triage** — grounded briefing, lazy-loaded, evidence links; "AI summary unavailable"
   if Ollama is down.

**Controls header:** date picker · Refresh + "data as of HH:MM:SS" · auto-refresh toggle (off).
**Every panel** has explicit loading / empty / error / stale states.

---

## 6. AI triage (grounded)

`/dashboard/briefing` consumes the computed snapshot and builds a strict prompt:

> "Here are the exact counts, top signatures, affected services, and spike times.
> Explain what is wrong and prioritise. Use ONLY these facts, cite the numbers, never
> invent causes, and say 'insufficient data' when unclear."

Returns markdown; each claim is tied to a fact (evidence shown). Auto-generated on first
load of the day, cached; manual **Regenerate**. Runs independently of panels 1–6, so a slow
or offline LLM never blocks the dashboard.

---

## 7. Security

- `require_admin` dependency on **every** `/dashboard/*` endpoint (API enforced, not just UI hiding).
- Admin resolution:
  - **Primary (B):** Keycloak group/role (e.g. `koop-admin`) if the `sid` session / userinfo exposes it.
  - **Fallback (C):** env allowlist `DASHBOARD_ADMINS=a@x,b@y`.
  - **Open item:** verify what the Keycloak session actually exposes at implementation start.
    Fallback is safe either way.
- No new secrets; index whitelist reused (no new index strings).
- Frontend hides the Dashboard nav link for non-admins as courtesy only.

---

## 8. Robustness, caching & consistency

- **Single snapshot per load**: window resolved once → all aggregations → one payload;
  panels always reconcile (no "header says 47, chart sums to 51").
- **Concurrent** Kibana queries with **per-view isolation** (one failure ≠ total failure).
- **TTL cache** (~60s, env-tunable) keyed by `(date, data_view)`; briefing cached per day.
- **Timeouts + size caps** protect Kibana and the UI; pathological days degrade, not hang.
- **"Data as of" stamp + health indicator** surface freshness and trust.

---

## 9. Testing

- Unit-test the **fact layer** with mocked Kibana responses (the trust-critical part),
  including failure paths: timeout, partial, empty, malformed.
- Test `require_admin`: admin allowed, non-admin → 403, no session → 401.
- Test the **briefing prompt builder** (facts in → grounded prompt out) without the live LLM.

---

## 10. Phase 2 (architected for, not built in v1)

- **Spike/baseline detection** — "critical only if abnormal vs. trailing baseline".
- **Daily digest** — scheduled job runs the fact layer + briefing, pushes to Slack/email/Teams.
- **Scheduled snapshots** — precompute for instant loads and resilience to Kibana hiccups.

---

## 11. Files (new / changed)

```
backend/monitoring.py       # NEW — fact layer (aggregations)
backend/dashboard.py        # NEW — /dashboard/* router
backend/auth.py             # NEW — require_admin (Keycloak role / allowlist)
backend/main.py             # CHANGED — include router
backend/config.py           # CHANGED — cache TTL, tz, admin settings
frontend/src/Dashboard.jsx  # NEW — page + panels
frontend/src/App.jsx        # CHANGED — nav toggle Chat <-> Dashboard (admin only)
frontend/src/styles.css     # CHANGED — dashboard styles
frontend/nginx.conf         # CHANGED — proxy /dashboard/
.env.example                # CHANGED — new settings documented
```

---

## 12. Open items / risks

- **Keycloak roles** — exact claim availability unverified; resolve at build start (fallback: allowlist).
- **APM index/schema** — field names (`processor.event`, status code path) to be confirmed against
  real `.ds-logs-apm.error-*` docs during build.
- **LLM quality** — `llama3.2:3b` on CPU is modest; grounding + deterministic facts carry correctness;
  briefing is assistive, never authoritative.
- **Data-view overlap** — `logs-*` may be a superset of `ds-prod5-*`; handled by doc-ID dedup or by
  excluding `logs-*` from rollup totals (confirm against real data).
