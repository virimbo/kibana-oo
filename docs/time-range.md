# Time range — presets + custom date ranges

The Dashboard and Documents pages share a **TimeRange** control: quick presets for
the common case, plus a **custom absolute from→to window** so an admin can analyse
**any dates, including very old data**.

## The control

- **Presets** (rolling window ending now): 15 min · 30 min · 1 h · 6 h · 24 h ·
  **7 d · 30 d · 90 d · 1 year**.
- **Custom range…** reveals two `datetime-local` pickers (from / to) and an
  **Apply** button. Validates: start before end, end not in the future.
- The **resolved window** is always shown (📅 absolute dates for a custom range),
  and a *"large range (may be slower)"* hint appears for windows over 90 days.
- The choice is **persisted** (`sessionStorage`, key `kibana_oo_timerange`) and
  **shared** across Dashboard ↔ Documents, so the window follows you.

`TimeRange.jsx` exposes helpers: `timeParams(range)` (the query fragment),
`rangeLabel(range)`, `loadRange()`, `saveRange()`.

## Backend (additive — the period path is unchanged)

Endpoints (`/summary`, `/briefing`, `/documents`, `/outcomes`) accept optional
`from` / `to` query params **alongside** the existing `period`:

- `?period=60` → rolling last-hour window (exactly as before).
- `?from=<ISO|epoch-ms>&to=<ISO|epoch-ms>` → that absolute window.

One helper, `monitoring.resolve_window(period, from, to)`, owns the logic: with a
valid `from`/`to` it returns that window (validated — end clamped to now, start <
end); otherwise it falls back to `period_bounds(period)`. The builders
(`build_snapshot`, `build_document_activity`, `build_pipeline_outcomes`) gained an
optional explicit `(start, end)` that overrides the period; **when omitted, the
behaviour is byte-for-byte identical to before.**

### Robustness for large / very old ranges

- The dashboard timeseries uses **`auto_date_histogram`** (target ~60 buckets) for
  custom windows, so a 2-year range never explodes the bucket count; the document
  activity chart uses `interval_for_span()` to the same effect.
- An out-of-retention / empty window renders the normal empty state (no crash).
- The AI briefing receives `window_start` / `window_end`, so it states the real
  range instead of "the last N minutes".

## Allowed presets

Preset minutes are validated server-side (`ALLOWED_PERIODS`): 15, 30, 60, 360,
1440, 10080, 43200, 129600, 525600. Arbitrary windows go through `from`/`to`, not
this list.
