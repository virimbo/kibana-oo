# Regression test — open.overheid.nl

Een post-release health gate voor het publieke portaal. Draai die na een prod-release
om te bevestigen dat de site nog werkt: beschikbaarheid, belangrijke journeys, content
via de openbaarmakingen-API, en TLS. Te vinden onder **Beheer → 🧪 Regressietest**.

## Wat het controleert

De suite is **data-driven** (zie `default_checks()` in `backend/regression.py`) zodat
checks toegevoegd kunnen worden zonder codewijziging. Elke check heeft een **severity**
(`critical` | `warning`). De default-set (geverifieerd tegen het live portaal):

| Check | Severity | Assert |
|---|---|---|
| Homepage loads | critical | `GET /` → 200, `text/html`, body bevat "Open overheid", ≤5 s |
| Document page reachable | critical | `GET /details/{uuid}` → 200, `text/html` |
| Document file downloadable | critical | streamed `GET /documenten/{uuid}` → 200, `application/pdf` (alleen headers — geen 6.5 MB download; het endpoint 404t op HEAD) |
| Openbaarmakingen API returns metadata | critical | `GET …/openbaarmakingen/api/v0/zoek/{uuid}` → 200 + een document-title in de JSON |
| robots.txt served | warning | `GET /robots.txt` → 200 |
| Unknown path returns no server error | warning | een bogus path geeft **< 500** (het portaal geeft 401, geen 404) |
| TLS certificate & chain healthy | critical | hergebruikt de TLS-audit — grade mag niet CRITICAL zijn |

> Overschrijdingen van het response-time-budget zijn altijd **soft** (warn), nooit een
> hard fail.

## Verdict

Per-check-resultaten rollen op tot één verdict, gespiegeld aan de cert **GRADE**:

- **FAIL** — een critical check is gefaald (dit is wat alert).
- **WARN** — alleen warning-level checks gefaald, of een perf-budget overschreden.
- **PASS** — alles groen.

Een **"changed since last run"**-notitie wordt alleen ter informatie getoond — die heeft
nooit invloed op het verdict (de content van het portaal verandert constant, dus een
diff is een signaal, geen gate).

## Drill-down evidence

Elke check bewaart, voor audit: de **URL**, **method**, **expected vs. actual**
(status / content-type / bytes / timing), en een **bounded (~500-char) evidence-snippet**
(de resolved title, de matched marker, de TLS-findings, …). Klap een check open in de UI
om precies te zien waarom die slaagde of faalde — zonder opnieuw te draaien.

Per-check **reliability** (pass/warn/fail counts over de laatste N runs) wordt getoond
zodat een flaky check in één oogopslag duidelijk is.

## Hoe te draaien

- **Handmatig:** Beheer → Regressietest → **Run regression test**. Live per-check
  progress; het resultaat wordt opgeslagen.
- **Vanuit CI/CD (bij deploy):** zet `REGRESSION_TRIGGER_TOKEN` in `.env`, laat de
  pipeline dan aanroepen:
  ```
  POST /regression/trigger
  Header: X-Regression-Token: <REGRESSION_TRIGGER_TOKEN>
  ```
  Het endpoint is uitgeschakeld (404) tenzij de token gezet is.

## Alerts

Wanneer een run **FAILt**, gaat een alert uit via dezelfde kanalen als de cert-monitor
(`DIGEST_WEBHOOK_URL` en/of SMTP). Configureer er minstens één zodat de post-deploy gate
je bereikt als niemand het dashboard bekijkt. Toggle met `REGRESSION_ALERT_ENABLED`.

## Opslag & retentie

Runs worden gepersisteerd in de gedeelde app-database (`kibana_oo.db`) over twee tabellen —
`regression_runs` (summary) en `regression_checks` (één row per check) — zie
[database.md](database.md). Retentie is **failure-aware**: maximaal
`REGRESSION_HISTORY_CAP` runs (default 1000), waarbij oudste **PASS** eerst geprunet wordt
zodat failures het langst bewaard blijven; de meest recente run wordt nooit geprunet.

## Configuratie (`.env`)

| Var | Default | Doel |
|---|---|---|
| `REGRESSION_TARGET_URL` | `https://open.overheid.nl` | Site under test |
| `REGRESSION_KNOWN_DOC_ID` | een gepubliceerde UUID | Document gebruikt door de content-checks |
| `REGRESSION_TRIGGER_TOKEN` | _(leeg)_ | Activeert het CI-trigger-endpoint |
| `REGRESSION_ALERT_ENABLED` | `true` | Alert op FAIL |
| `REGRESSION_HISTORY_CAP` | `1000` | Max bewaarde runs |

## API

| Method | Path | Auth | Doel |
|---|---|---|---|
| POST | `/dashboard/regression/run` | admin | Start een run |
| GET | `/dashboard/regression/latest` | admin | Laatste run (live tijdens draaien) |
| GET | `/dashboard/regression/runs?limit=` | admin | History (summaries) |
| GET | `/dashboard/regression/runs/{id}` | admin | Eén run met volledige check-evidence |
| GET | `/dashboard/regression/reliability?limit=` | admin | Per-check pass/warn/fail counts |
| POST | `/regression/trigger` | token | CI-trigger (header `X-Regression-Token`) |

## Uitbreiden

- **Meer HTTP-checks:** voeg een entry toe aan `default_checks()` (url, method/kind,
  expected status/content-type/text, severity, time budget).
- **Browser-journeys (later):** de engine dispatcht op check-`kind`; een
  Playwright-backed `kind` kan toegevoegd worden zonder de rest aan te raken.
