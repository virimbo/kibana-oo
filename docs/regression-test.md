# Regression test — open.overheid.nl

A post-release health gate for the public portal. Run it after shipping to prod
to confirm the site still works: availability, key journeys, content via the
openbaarmakingen API, and TLS. Lives under **Beheer → 🧪 Regressietest**.

## What it checks

The suite is **data-driven** (see `default_checks()` in `backend/regression.py`) so
checks can be added without code changes. Each check has a **severity**
(`critical` | `warning`). The default set (verified against the live portal):

| Check | Severity | Asserts |
|---|---|---|
| Homepage loads | critical | `GET /` → 200, `text/html`, body contains "Open overheid", ≤5 s |
| Document page reachable | critical | `GET /details/{uuid}` → 200, `text/html` |
| Document file downloadable | critical | streamed `GET /documenten/{uuid}` → 200, `application/pdf` (headers only — no 6.5 MB download; the endpoint 404s on HEAD) |
| Openbaarmakingen API returns metadata | critical | `GET …/openbaarmakingen/api/v0/zoek/{uuid}` → 200 + a document title in the JSON |
| robots.txt served | warning | `GET /robots.txt` → 200 |
| Unknown path returns no server error | warning | a bogus path returns **< 500** (the portal returns 401, not 404) |
| TLS certificate & chain healthy | critical | reuses the TLS audit — grade must not be CRITICAL |

> Response-time-budget breaches are always **soft** (warn), never a hard fail.

## Verdict

Per-check results roll up to one verdict, mirroring the cert **GRADE**:

- **FAIL** — any critical check failed (this is what alerts).
- **WARN** — only warning-level checks failed, or a perf budget was breached.
- **PASS** — everything green.

A **"changed since last run"** note is shown for information only — it never
affects the verdict (the portal's content changes constantly, so a diff is a
signal, not a gate).

## Drill-down evidence

Every check stores, for audit: the **URL**, **method**, **expected vs. actual**
(status / content-type / bytes / timing), and a **bounded (~500-char) evidence
snippet** (the resolved title, the matched marker, the TLS findings, …). Expand a
check in the UI to see exactly why it passed or failed — no need to re-run.

Per-check **reliability** (pass/warn/fail counts over the last N runs) is shown so
a flaky check is obvious at a glance.

## How to run

- **Manually:** Beheer → Regressietest → **Run regression test**. Live per-check
  progress; the result is stored.
- **From CI/CD (on deploy):** set `REGRESSION_TRIGGER_TOKEN` in `.env`, then have
  the pipeline call:
  ```
  POST /regression/trigger
  Header: X-Regression-Token: <REGRESSION_TRIGGER_TOKEN>
  ```
  The endpoint is disabled (404) unless the token is set.

## Alerts

When a run **FAILs**, an alert is sent via the same channels as the cert monitor
(`DIGEST_WEBHOOK_URL` and/or SMTP). Configure at least one so the post-deploy gate
reaches you when nobody's watching the dashboard. Toggle with
`REGRESSION_ALERT_ENABLED`.

## Storage & retention

Runs are persisted in the shared app database (`kibana_oo.db`) across two tables —
`regression_runs` (summary) and `regression_checks` (one row per check) — see
[database.md](database.md). Retention is **failure-aware**: at most
`REGRESSION_HISTORY_CAP` runs (default 1000), pruning oldest **PASS** first so
failures are kept longest; the most recent run is never pruned.

## Configuration (`.env`)

| Var | Default | Purpose |
|---|---|---|
| `REGRESSION_TARGET_URL` | `https://open.overheid.nl` | Site under test |
| `REGRESSION_KNOWN_DOC_ID` | a published UUID | Document used by the content checks |
| `REGRESSION_TRIGGER_TOKEN` | _(empty)_ | Enables the CI trigger endpoint |
| `REGRESSION_ALERT_ENABLED` | `true` | Alert on FAIL |
| `REGRESSION_HISTORY_CAP` | `1000` | Max runs kept |

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| POST | `/dashboard/regression/run` | admin | Start a run |
| GET | `/dashboard/regression/latest` | admin | Latest run (live while running) |
| GET | `/dashboard/regression/runs?limit=` | admin | History (summaries) |
| GET | `/dashboard/regression/runs/{id}` | admin | One run with full check evidence |
| GET | `/dashboard/regression/reliability?limit=` | admin | Per-check pass/warn/fail counts |
| POST | `/regression/trigger` | token | CI trigger (header `X-Regression-Token`) |

## Extending

- **More HTTP checks:** add an entry to `default_checks()` (url, method/kind,
  expected status/content-type/text, severity, time budget).
- **Browser journeys (later):** the engine dispatches by check `kind`; a
  Playwright-backed `kind` can be added without touching the rest.
