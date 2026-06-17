# Environment status / Beschikbaarheid (uptime monitor) — design spec

**Date:** 2026-06-17 · **Status:** Approved → implementation · **Branch:** `feat/uptime-monitor`

## 1. Executive summary
A prominent top-of-dashboard board showing, at a glance, whether each KOOP/Plooi
website is **UP**. A backend background loop HTTP-probes a configured list of
targets (PROD/ACC/TEST), classifies each as UP / DEGRADED / DOWN / UNREACHABLE,
keeps a short rolling history, and alerts (existing webhook/email) when a target
goes genuinely DOWN. Fully additive, behind `UPTIME_ENABLED` (default off) + a
grantable `uptime` feature. Cert/TLS code untouched.

## 2. Decisions (from brainstorm)
1. **Probe = HTTP GET**, up if final status ∈ per-site allowlist; measure latency.
2. **Background poll loop** + cached snapshot + flap-resistant alert (like cert/DLQ).
3. **Dedicated top zone**, first on the page, PROD/ACC/TEST groups, DLQ-tile styling, roll-up header.
4. **Env-configured target list**, unauthenticated GET, allowlist-only (no SSRF), grey UNREACHABLE vs red DOWN.
5. **Status+latency colour** (UP/DEGRADED/DOWN/UNREACHABLE) + latency + sparkline + uptime% + last-checked; flag+grant+alert.

## 3. Architecture
```
backend/uptime.py        # parse targets, async probe, classify, in-memory store+history, alert, poll loop
backend/uptime_api.py    # GET /dashboard/uptime/status  (require_feature("uptime") + flag)
backend/tests/test_uptime.py
frontend/src/UptimeBoard.jsx   # first DashZone: PROD/ACC/TEST groups of site cards
docs/KIBANA-OO/Beschikbaarheid (uptime).md  # Dutch beheerder-note
```
Additive wiring: `config.py` settings; `main.py` start `run_uptime_monitor_loop()` in lifespan + `include_router`; `permissions.py` CATALOG entry; `Dashboard.jsx` render `<UptimeBoard/>` first. nginx: none (`/dashboard/*` already proxied).

## 4. Probe & classification
Per cycle (`UPTIME_INTERVAL`, 60s default): async `httpx` GET, `UPTIME_TIMEOUT` (8s),
follow ≤ a few redirects, ignore body, no credentials. States:
- **up** — reached, status ∈ allowlist, latency ≤ `UPTIME_DEGRADED_MS`
- **degraded** — reached, status ∈ allowlist, but latency > threshold (or recent flap)
- **down** — reached but status ∉ allowlist / 5xx (a confirmable outage)
- **unreachable** — connect/DNS/timeout error (cannot confirm down)

**Honesty rule:** `internal: true` targets (admin, gateway) → network failure =
**unreachable (grey)**; public targets → network failure = **down (red)**.
**Alerts fire only on `down`** (after `UPTIME_SETTLE_MINUTES`), so off-VPN never pages.

State kept **in-memory** per target: rolling history (last N), `since` (when current
state began), `alerted` (dedup). Resets on restart (acceptable for an uptime board).

## 5. Config
```
UPTIME_ENABLED=false
UPTIME_TARGETS=        # one per line: name | env | url | expected | internal?
UPTIME_INTERVAL=60
UPTIME_TIMEOUT=8
UPTIME_DEGRADED_MS=2000
UPTIME_SETTLE_MINUTES=2
UPTIME_ALERT_ENABLED=true
UPTIME_HISTORY=30
```
Default targets = the 6 sites (admin + gateway flagged `internal`). `expected`
tokens: `2xx`,`3xx`,`4xx`,`5xx` or explicit codes (`200,302,401`). Allowlist-only
fetch ⇒ no SSRF.

## 6. API
`GET /dashboard/uptime/status` →
```json
{ "enabled": true,
  "summary": {"up": 6, "total": 6, "down": 0, "degraded": 0, "unreachable": 0, "verdict": "ok"},
  "groups": [ {"env":"PROD","sites":[
    {"name":"open.overheid.nl","url":"…","state":"up","http_status":200,
     "latency_ms":143,"uptime_pct":100,"history":["up","up",…],
     "since":"…","checked_at":"…","internal":false} ]} ] }
```
Off/again: `{"enabled": false}`.

## 7. UX
First `DashZone` "🌐 Beschikbaarheid — Environment status" with roll-up header
(`✓ 6/6 up` green / `⛔ 1 down` red / `⚠ degraded` amber / `⚪ n unreachable`).
PROD / ACC / TEST sub-groups; each site a card (DLQ-tile styling) with: big colour
state, name, response time, uptime %, mini sparkline, "x min ago", "down sinds …".

## 8. Security / a11y / safety
Allowlist-only outbound, no creds, no secrets stored, short timeouts, body ignored
→ OWASP A10/A03 safe. Colour never the only signal (icon + text). Flag default off
= instant rollback. Tests must keep the full suite green.

## 9. Cross-feature
Register the site cards with SmartContextPanel (`REGISTRY` + `component:` frontmatter
on the new vault note) so hover shows purpose/deps/TODOs — optional, additive.

## 10. Roadmap
config → uptime.py → uptime_api.py → wiring → UptimeBoard.jsx + CSS → SmartContext+vault → tests → Dutch doc → verify → PR.
