# Runbook actions — state-aware "WAT TE DOEN NU" — design spec

**Date:** 2026-06-17 · **Status:** Approved → implementation · **Branch:** `feat/runbook-actions`

## Summary
Turn the SmartContextPanel's TO-DO area into a **state-aware action block**: when a
card shows a problem (site DOWN, or cert near expiry), the panel surfaces the exact
runbook action ("who to call / what to do") for that environment, read live from a
dedicated Obsidian note. The normal vault TO-DOs stay below.

## Decisions (brainstorm)
1. One dedicated, lightly-structured runbook note parsed by condition × environment.
2. Prominent "WAT TE DOEN NU" block only when problematic; normal TO-DOs always below.
3. Wire both uptime cards (today) and cert cards (inert `data-smartcard` wrapper; frozen CertCard untouched).
4. Two conditions: `down` (uptime down/degraded/unreachable) and `cert` (cert warning/critical/expired, reusing the cert card's 30/14-day status); urgent = down/critical/expired.
5. `bijgewerkt:` date shown in panel + amber "verouderd" past `SMART_CONTEXT_RUNBOOK_STALE_DAYS` (180); "geen actie vastgelegd" when missing.

## Runbook note
`docs/KIBANA-OO/Runbook - wat te doen.md`, `component: runbook-actions`, frontmatter
`bijgewerkt`, `eigenaar`. Body: `## Bij DOWN` / `## Bij certificaat bijna verlopen`,
each with `- PROD: …` / `- ACC: …` / `- TEST: …` lines (TST→TEST normalized).

## Backend (`context_engine.py`, additive)
- `parse_runbook()` → `{condition: {env: action}}` + `updated` + `owner`, cached.
  Condition keys: heading containing "down" → `down`; "certificaat"/"cert" → `cert`.
- `runbook_action(condition, env)` → action string or None (env normalized).
- `assemble(card_id, label, status, env)` extended: derive condition from card_id
  prefix + status; attach `action` payload:
  ```json
  {"text":"Bel Firas","label":"Bij DOWN","condition":"down","env":"ACC",
   "urgent":true,"missing":false,"runbook_updated":"2026-06-17",
   "runbook_stale":false,"note":"Runbook - wat te doen"}
  ```
  `action` is null when the card is healthy (no problem condition).
- `_PREFIX_FALLBACK` adds `cert:` → `certificates` (cert hover shows the certificates component).
- Config: `smart_context_runbook_stale_days: int = 180`.

## Frontend
- `useCardContext.js`: read `data-smartenv` → `active.env`.
- `SmartContextPanel.jsx`: pass `env` in the query; render the "⚠ WAT TE DOEN NU"
  block (urgent red / amber) above TO-DO when `info.action`; show updated/stale/missing.
- `UptimeBoard.jsx`: SiteCard gains `data-smartenv={env}`.
- `Dashboard.jsx`: wrap each `CertCard` in a `data-smartcard="cert:<host>"` +
  `data-smartenv` div (CertCard untouched).

## Tests (`tests/test_context.py`)
runbook parse incl. `TST`/case/typo; action lookup + missing; stale flag; condition
derivation per state (down/degraded/cert warning/critical); no action when healthy.

## Safety
Additive; reads only; FROZEN cert code/CertCard untouched (wrapper-only markers).
Flag-gated by the existing `smart_context` feature. Full suite must stay green.
