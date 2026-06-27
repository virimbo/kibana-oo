# Document Health intelligence layer — Design Spec

- **Date:** 2026-06-27
- **Status:** Approved design (Q1 A · Q2 A · Q3 C-led-by-A), ready for implementation plan
- **Author:** Anton Partono (with Claude)
- **Trigger:** The Documents page shows raw counts (events / unique / errors / by-action
  "OTHER" / by-type / activity) with no interpretation — an administrator can't tell what
  it means or whether to act. Make it intelligent, plain-language, and proactive.

## 1. Goal

Add a **"Documentgezondheid" intelligence layer** to the Documents page: a plain-Dutch
**health verdict** + **proactive signals** (with recommended actions) that *interpret* the
existing numbers, plus clearer metric labels (kill the meaningless "OTHER"). Reuses the
`_alert_level` + previous-window comparison already in `backend/documents.py`. Designed so
**push alerting (Phase B)** is a localized follow-up.

**Hard constraints:**
- **Additive.** Extend the documents summary payload + add a banner/labels; existing panels,
  feed, and data keys (`events`, `errors`, `by_action`, `by_type`, `timeline`, …) unchanged.
- Backend stays **read-only** (Kibana proxy). No FROZEN code (cert/Mistral) touched.
- All verdict/signal logic in **one backend place** so Phase B (alerts) + a future learned
  baseline are localized swaps.

## 2. Decisions (the 3 questions)

1. **(Q1 A) On-page first, B-ready.** Build the on-page verdict + signals now; design the
   `health` object so push alerting slots in next (effectively C over two steps).
2. **(Q2 A) Previous-window baseline.** "Normal" = the immediately preceding window (reuses
   the existing `prev_start`/`error_pct_change` machinery). A learned baseline is a later swap.
3. **(Q3 C led by A) Honest label + light classification.** Make unmatched actions read
   **"niet-geclassificeerd"** (guaranteed clarity); also widen `classify_action` modestly +
   read a structured action field if present. If "Op actie" stays all-other on real data,
   it's demoted and the verdict never leans on it.

## 3. Current state (verified)

`backend/documents.py` `summary(...)` already returns (dataclass → dict):
`events`, `unique`, `errors`, `error_pct_change` (vs the prior window, via `prev_start`),
`alert_level` (`ok|warning|critical` from `_alert_level(errors, pct_change)`), `by_action`,
`by_type`, `timeline`, plus the feed. It queries the prior window for **errors** but **not
for events**. `classify_action(message)` keyword-matches → `"other"` when nothing matches.

## 4. Backend — `documents.py` (additive)

### 4.1 Previous-window event count
Add a prior-window **events** count alongside the existing prior-window error count (one more
read-only `_es_search` count for `prev_start..start`). Compute `events_pct_change` the same
way `error_pct_change` is computed.

### 4.2 The `health` object
A new pure helper builds, from the counts:
```python
{
  "level": "ok" | "warning" | "critical",          # = alert_level, reused
  "headline": "<plain Dutch one-liner>",            # e.g. "19 documenten verwerkt, 0 fouten"
  "signals": [
    {"kind": "stalled" | "error_spike" | "volume",
     "severity": "warning" | "critical",
     "message": "<plain Dutch>",                    # e.g. "Geen documentactiviteit (was 20) — verwerking mogelijk gestopt."
     "action": "<recommended action, Dutch>"}       # e.g. "Controleer de pipeline-logs in Kibana; zie runbook."
  ]
}
```
Signal rules (pure, unit-tested; thresholds in `config.py`, sensible defaults):
- **stalled** — `events == 0` AND `events_prior >= settings.doc_stall_min_prior` (default 1)
  → critical: *"Geen documentactiviteit (was N) — verwerking mogelijk gestopt."*
- **error_spike** — `errors >= settings.doc_error_threshold` (default 10) OR
  (`errors > 0` and `error_pct_change >= 100`) → severity from `_alert_level`:
  *"X fouten ({+Y%})."*
- **volume** — `events > 0` and `events_prior > 0` and `abs(events_pct_change) >=
  settings.doc_volume_swing_pct` (default 60) → warning:
  *"Volume ongewoon {laag|hoog}: N vs M (vorig venster)."*
Headline: if no signals → *"N documenten verwerkt, E fouten (dit venster)."*; else the most
severe signal's message.

`summary()` adds `"health": <obj>` to its returned dict. `alert_level`/`error_pct_change`
and all existing keys stay. The single helper (`_build_health(events, events_prior, errors,
error_pct_change, events_pct_change)`) is the one place Phase B / a learned baseline touch.

### 4.3 Action classification (Q3 C-led-by-A)
- `classify_action`: add a few more keyword rules; if a hit has a structured action field
  (`event.action` / `action`), prefer it. Whatever still doesn't match → `"other"`.
- Presentation of `"other"` is handled in the frontend label (4.4 / §5), not by renaming the
  data key (keep `by_action` keys stable).

## 5. Frontend — `Documents.jsx` (additive)

- **Health banner** at the TOP of the analytics section (above "Errors per bron"):
  a coloured row (semantic green/amber/red via the existing pill/alert classes) showing
  `health.headline`, and beneath it each `health.signals[]` as a line: icon + message +
  the **recommended action** (with an InfoTip and, where relevant, a "vraag de AI" / runbook
  link — reuse the Smart-Context/runbook hook). Renders nothing extra when `level === "ok"`
  and no signals (just the green "Gezond" headline).
- **KPI context:** the existing `events`/`errors` cards show the prev-window delta
  ("+5% vs vorig uur" / "was 0") from `events_pct_change`/`error_pct_change`.
- **"Op actie" label:** render the `other` bucket as **"niet-geclassificeerd"** with a clear
  tooltip; if `by_action` is *only* `other`, show a one-line note that the action type isn't
  in the log text (don't present it as meaningful). The verdict does not depend on it.
- Reuses the OO-GX kit; no existing panel/feed markup, handlers, or `data-*` removed.

## 6. Smart Context / runbook (reuse)

Add a `card:documents` runbook condition (e.g. **"Bij document-verwerking gestopt"**) in
`backend/context_engine.py` + a section in `docs/KIBANA-OO/Runbook - wat te doen.md`, so a
signal's recommended action can pull a runbook step — mirroring service_health/monitoring.
(Optional within this feature; include if low-cost.)

## 7. Phase B readiness (next step, not now)

The `health` object (`level` + `signals`) is exactly an alert payload. Phase B = when
`level >= warning`, call the existing alert engine (`alerts.raise_external(category=
"documents", key=..., ...)`, per-incident dedup, email→Mattermost) from the documents
background path. No rework — "send the verdict you already compute."

## 8. Files

| File | Responsibility | Action |
|---|---|---|
| `backend/documents.py` | prior-window event count + `_build_health()` + `health` in summary; classify tweaks | Modify (additive) |
| `backend/config.py` | `doc_error_threshold`, `doc_stall_min_prior`, `doc_volume_swing_pct` | Modify (additive) |
| `frontend/src/Documents.jsx` | health banner + signals + KPI deltas + honest "other" label | Modify (additive) |
| `backend/context_engine.py` + runbook note | `card:documents` runbook condition (optional) | Modify (additive) |
| `docs/KIBANA-OO/Documenten.md` (or the documents note) | document the health layer | Modify/Create |

## 9. Testing

- **`_build_health`** (pure, unit-tested): ok when no issues; **stalled** when events 0 &
  prior > 0; **error_spike** at threshold and at pct≥100; **volume** on a big swing; headline
  text picks the most severe signal; thresholds read from settings.
- **classify_action**: prefers a structured action field; new keyword rules classify; else
  `"other"`.
- **summary payload**: includes `health` with the right level/signals on crafted event sets;
  existing keys unchanged.
- Run in the `python:3.13` Docker image; full suite stays green.

## 10. Safety, rollback, additivity

- Additive payload field + a banner; existing panels/feed/data keys untouched → the page
  degrades to today's behaviour if the banner is removed.
- Read-only backend; one extra prior-window count query (cheap).
- All verdict logic in `_build_health` → rollback = stop rendering the banner; Phase B + a
  learned baseline are localized.

## 11. Out of scope (roadmap)

Phase B push alerts (designed-for); a learned/time-of-day baseline (swap the comparison in
`_build_health`); per-source ("bron") health breakdown; AI-written root-cause for a document
incident (could reuse the monitoring `ai_rootcause` pattern later).
