# Aanleverfouten monitor

Surfaces documents that were **rejected at delivery** (the doculoket
"Aanleverfouten") so admins can see, at a glance, which publishers have documents
that failed and must be corrected and re-delivered. Lives as a card on the
**Dashboard** plus a global header badge.

## Why it's not in the public API

When a publisher delivers a *set*, some documents process fine (and get
published) while others fail validation. **The failed ones are never published**,
so the public openbaarmakingen API can't see them — only the successful ones.
That's why detection happens in the logs, reconciled against the portal.

## How it works (detect → reconcile → persist → group)

1. **Detect** in `ds-prod5-koop-plooi` (configurable data view). A document is an
   aanleverfout candidate when a log event matches the detection signal:
   - a **structured status field** (`AANLEVER_STATUS_FIELD`) equal to one of
     `AANLEVER_STATUS_VALUES`, if such a field exists (most precise), **or**
   - a fallback: an **error at an intake/aanlever service**
     (`AANLEVER_SERVICES`) or a **message matching** `AANLEVER_PATTERNS`
     (`aanleverfout`, `afgekeurd`, `geweigerd`, `validatie`, `schema`, …).

   The document id is the `ronl-` id if present, else the **UUID** in the message
   (aanleverfouten use the doculoket UUID).

2. **Reconcile** each candidate against open.overheid.nl. If the document is now
   `gepubliceerd`/live, the error was **fixed & re-delivered → auto-resolved**.
   This is what keeps the list free of false positives.

3. **Persist** as a durable incident (`aanlever_incidents` in `kibana_oo.db`):
   - OPEN from first detection, surviving restarts and the scan window;
   - opened only after a **settle delay** (`AANLEVER_SETTLE_MINUTES`) so a
     transient error that immediately retry-succeeds never shows;
   - **auto-resolved** on publication; **manually acknowledged** (dismissed) by an
     admin via the ✓ button.

4. **Group** the open incidents **by publisher + error type**, with a summary
   headline and a **new (last 24 h) vs. persisting** split.

## On the dashboard

- A summary headline ("⚠ N aanleverfouten bij M organisaties — K nieuw").
- Error-type tags (Schema, Validatie, Afgekeurd, …).
- Per-publisher groups; each row shows the document, the error, and:
  - the **title** → click to **trace** the document,
  - **↗** → open it in **doculoket** to fix & re-deliver,
  - **✓** → acknowledge/dismiss.
- A **header badge** on every admin page (open count), polled every 60 s.

## Alerts & digest

On **new** aanleverfouten (deduped — alerted once when the incident opens), an
alert goes out via the digest webhook + email (`AANLEVER_ALERT_ENABLED`). Set
`DIGEST_WEBHOOK_URL` / SMTP for delivery.

## Configuration (`.env`)

| Var | Default | Purpose |
|---|---|---|
| `AANLEVER_ENABLED` | `true` | Master switch |
| `AANLEVER_DATA_VIEW` | `ds-prod5-koop-plooi*` | Index to scan |
| `AANLEVER_LOOKBACK_HOURS` | `48` | Detection window |
| `AANLEVER_STATUS_FIELD` | _(empty)_ | Structured status field, if any (most precise) |
| `AANLEVER_STATUS_VALUES` | `aanleverfout,afgekeurd,…` | Values that mean "rejected" |
| `AANLEVER_SERVICES` | `doculoket,aanlever,…` | Intake services for the fallback signal |
| `AANLEVER_PATTERNS` | `aanleverfout,afgekeurd,…` | Message phrases for the fallback signal |
| `AANLEVER_SETTLE_MINUTES` | `10` | Persist this long before it's an incident |
| `AANLEVER_ALERT_ENABLED` | `true` | Alert on new |

## ⚠️ Calibration

The detection patterns ship with sensible defaults but should be **tuned to the
real `ds-prod5-koop-plooi` logs** — confirm whether a structured status field
exists (set `AANLEVER_STATUS_FIELD` if so; it's the most precise signal) and that
the keyword/service lists match how rejections are actually logged. The
reconciliation step means a mis-tuned pattern produces *no* false positives (a
published doc is always filtered out), only potential misses.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/dashboard/aanleverfouten` | Grouped open list + summary + count (cached) |
| POST | `/dashboard/aanleverfouten/{doc_id}/ack` | Acknowledge / dismiss |
