# Service health — Design Spec

- **Date:** 2026-06-19
- **Flag:** `SERVICE_HEALTH_ENABLED` (default **off**)
- **Feature key:** `service_health` (Dashboard group)
- **Status:** approved (1 new card · 2 actuator-JSON+HTTP · 3 on-VPN/honest · 4 dashboard-only)

## Goal
A dedicated, elegant **dashboard card** that monitors the KOOP/Plooi **backend
microservices** (Harvester, Antivirus, Repository, Search, DCN, Keycloak, Solr,
RabbitMQ, …) and shows, per service, whether its **endpoints respond** — so an admin
sees at a glance which service is up / unhealthy / unreachable. Additive; does not
touch the existing uptime board or any other feature.

## Approach (reuse the proven probe, present per service)
A new `service_health.py` HTTP-probes a configured list of services (read-only GET,
short timeout, no credentials). It reuses the **uptime monitor's probing approach**
but is configured + presented for **backend services**, grouped by **service** (not
env). Each service has 1–2 endpoints (an `actuator` + a `service`/UI URL).

### Per-endpoint state
- **up** — HTTP `2xx/3xx/4xx` (responding; 401/403/405 from secured UIs/methods still
  means the service is alive) — *and* an actuator that doesn't report `DOWN`.
- **down** — HTTP `5xx`, **or** a Spring Actuator JSON body with `"status":"DOWN"`
  (reached but unhealthy).
- **degraded** — up but slower than `SERVICE_HEALTH_DEGRADED_MS`.
- **unreachable** — connection error / timeout (can't tell down from off-VPN —
  honest grey, never a false red).

### Actuator awareness
For `actuator` endpoints, parse the JSON `status` (`UP`/`DOWN`) for a true health
signal; fall back to HTTP-status classification when there's no JSON `status`.

### Per-service verdict (worst endpoint wins)
`down > unreachable > degraded > up`. The card shows one verdict per service; expand
a tile to see each endpoint (path · state · HTTP code · latency).

## Components (additive)
- `backend/service_health.py` (new) — parse targets, probe (httpx), per-endpoint
  state, per-service verdict, background loop + cache + `latest()`.
- `backend/service_health_api.py` (new) — `GET /dashboard/service-health`,
  `require_feature("service_health")`. Routed under `/dashboard/` (nginx already
  proxies it). 200 `{enabled:false}` when off.
- `backend/permissions.py` — one CATALOG entry `service_health` (Dashboard group).
- `backend/main.py` — register router + start `run_service_health_loop()`.
- `backend/config.py`, `.env.example` — flags + the default target list.
- `frontend/src/ServiceHealth.jsx` (new) — the card (service-grouped severity tiles,
  expandable endpoints), built on the design system + provider-aware theme.
- `frontend/src/Dashboard.jsx`, `api.js`, `Settings.jsx` — add the card behind
  `can("service_health")` + a dashboard-section toggle (additive).

## Config
```
SERVICE_HEALTH_ENABLED=false
SERVICE_HEALTH_INTERVAL=60         # seconds between probe cycles
SERVICE_HEALTH_TIMEOUT=8           # per-request timeout
SERVICE_HEALTH_DEGRADED_MS=2500    # slower than this (but up) = degraded
SERVICE_HEALTH_TARGETS=...         # one service per line: "Name | url | url"
```
Targets default to the real prod services; one service per line, `kind` inferred
(`actuator` if the URL contains "actuator", else `service`).

## Safety & consistency
- Read-only outbound GETs to a configured allowlist (no user-supplied URL → no SSRF),
  no credentials, short timeout, body parsed only for actuator `status`.
- Gated by the `service_health` grant (deny-by-default); inert unless the flag is on.
- Never raises into a request; one bad endpoint never breaks the pass.
- Internal/VPN-honest: connect-fail = `unreachable` (grey), not a false red — so in
  local dev (off-VPN) the card is honestly grey, not alarming.

## Out of scope (later, additive)
Feeding the unified **Alerting** (a "Services" category → email/Mattermost on down);
per-endpoint history sparklines; actuator detail (DB/disk components).

## Rollback
`SERVICE_HEALTH_ENABLED=false` → card hidden, engine inert. Remove the new files +
the catalog/router/loop registrations. Nothing existing was modified.
