# Document Health intelligence layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Documents page from raw counts into an interpreted, proactive view — a plain-Dutch health verdict + signals (stalled / error-spike / volume) with recommended actions, KPI deltas, and an honest "niet-geclassificeerd" label.

**Architecture:** One pure backend helper `_build_health()` produces a `health` object in the documents summary (additive); `build_document_activity` adds a prior-window event count; the frontend renders a verdict banner + signals + KPI deltas; a `card:documents` runbook condition makes the recommended actions pull a runbook step. Read-only, additive; verdict logic in one place so push-alerts (Phase B) slot in later.

**Tech Stack:** Python 3.13 / FastAPI (`backend/documents.py`), React 19 / Vite, pytest in `python:3.13` Docker.

**Spec:** `docs/superpowers/specs/2026-06-27-document-health-design.md`
**Branch:** `feat/document-health` (already created). Single PR.

---

## Conventions

**Backend tests:**
```bash
cd /c/ANT-PROJECT/KIBANA-OO/backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 \
  docker run --rm -v "$HP:/app" -w /app python:3.13 sh -c \
  "pip install -q -r requirements.txt && python -m pytest tests/<FILE> -q"
```
**Frontend build:**
```bash
cd /c/ANT-PROJECT/KIBANA-OO/frontend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 \
  docker run --rm -v "$HP:/app" -w /app node:20 sh -c "npm install --no-audit --no-fund && npm run build" 2>&1 | tail -6
```

**Verified current shapes:**
- `documents.DocumentActivity` (Pydantic BaseModel) fields incl. `total` (current event count), `errors`, `errors_prior`, `error_pct_change`, `alert_level`, `by_action`, `by_type`, `timeseries`, `events`.
- `build_document_activity(...)` gathers 5 ES queries via `asyncio.gather`; computes `errors_prior` from `_error_count_body(prev_start, start)`; `prev_start = start - (end - start)`.
- `_error_count_body(start, end)` = `{"size":0,"track_total_hits":True,"query":_error_query(...)}`. `_event_query(start,end)` is the base (non-error) event query.
- `classify_action(message)` → keyword match else `"other"`. `summarize_event(hit)` sets `action`/`type`/`status`.

---

### Task 1: Config thresholds + `_build_health()` (pure, TDD)

**Files:** Modify `backend/config.py`, `backend/documents.py`; Test `backend/tests/test_document_health.py`

- [ ] **Step 1:** In `backend/config.py` (near the other feature settings, inside `class Settings`):
```python
    # Document health signals (Documents page intelligence)
    doc_error_threshold: int = 10      # errors at/above this = critical spike
    doc_stall_min_prior: int = 1       # prior-window events needed to call 0-now a "stall"
    doc_volume_swing_pct: int = 60     # |events pct change| at/above this = volume signal
```

- [ ] **Step 2: Write the failing test** — `backend/tests/test_document_health.py`:
```python
from config import settings
import documents as d

def test_health_ok_when_quiet():
    h = d._build_health(events=19, events_prior=18, errors=0, error_pct_change=None, events_pct_change=5.6)
    assert h["level"] == "ok" and h["signals"] == []
    assert "19 documenten" in h["headline"] and "0 fouten" in h["headline"]

def test_health_stalled_is_critical_even_with_zero_errors():
    h = d._build_health(events=0, events_prior=20, errors=0, error_pct_change=None, events_pct_change=-100.0)
    kinds = {s["kind"] for s in h["signals"]}
    assert "stalled" in kinds and h["level"] == "critical"
    assert "verwerking mogelijk gestopt" in h["headline"].lower()

def test_health_error_spike_threshold():
    h = d._build_health(events=50, events_prior=50, errors=settings.doc_error_threshold, error_pct_change=10.0, events_pct_change=0.0)
    assert any(s["kind"] == "error_spike" for s in h["signals"]) and h["level"] == "critical"

def test_health_error_spike_by_pct():
    h = d._build_health(events=50, events_prior=50, errors=3, error_pct_change=150.0, events_pct_change=0.0)
    sig = [s for s in h["signals"] if s["kind"] == "error_spike"][0]
    assert sig["severity"] == "warning" and "+150" in sig["message"]

def test_health_volume_swing_warns():
    h = d._build_health(events=4, events_prior=20, errors=0, error_pct_change=None, events_pct_change=-80.0)
    assert any(s["kind"] == "volume" for s in h["signals"]) and h["level"] == "warning"

def test_health_volume_not_flagged_when_prior_zero():
    h = d._build_health(events=4, events_prior=0, errors=0, error_pct_change=None, events_pct_change=None)
    assert all(s["kind"] != "volume" for s in h["signals"])  # no baseline → no volume signal

def test_every_signal_has_message_and_action():
    h = d._build_health(events=0, events_prior=20, errors=15, error_pct_change=200.0, events_pct_change=-100.0)
    assert h["signals"] and all(s.get("message") and s.get("action") for s in h["signals"])
```

- [ ] **Step 3: Run → FAIL** (`AttributeError: module 'documents' has no attribute '_build_health'`):
```bash
cd /c/ANT-PROJECT/KIBANA-OO/backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 docker run --rm -v "$HP:/app" -w /app python:3.13 sh -c "pip install -q -r requirements.txt && python -m pytest tests/test_document_health.py -q"
```

- [ ] **Step 4: Implement** — add to `backend/documents.py` (near `_alert_level`):
```python
def _build_health(events, events_prior, errors, error_pct_change, events_pct_change):
    """Plain-Dutch health verdict + proactive signals from the window's counts vs the
    previous window. Pure — the single place push-alerts (Phase B) and a learned
    baseline would later hook into. `events` = current event count, `events_prior` =
    previous-window event count."""
    signals = []
    if events == 0 and events_prior >= settings.doc_stall_min_prior:
        signals.append({
            "kind": "stalled", "severity": "critical",
            "message": f"Geen documentactiviteit (was {events_prior}) — verwerking mogelijk gestopt.",
            "action": "Controleer de verwerkings-/pipeline-logs in Kibana; zie de runbook."})
    if errors >= settings.doc_error_threshold or (errors > 0 and (error_pct_change or 0) >= 100):
        sev = "critical" if errors >= settings.doc_error_threshold else "warning"
        pct = f" (+{error_pct_change}%)" if error_pct_change else ""
        signals.append({
            "kind": "error_spike", "severity": sev,
            "message": f"{errors} fouten{pct}.",
            "action": "Bekijk 'Errors per bron' en de gefaalde documenten; zie de runbook."})
    if events > 0 and events_prior > 0 and abs(events_pct_change or 0) >= settings.doc_volume_swing_pct:
        direction = "hoog" if (events_pct_change or 0) > 0 else "laag"
        signals.append({
            "kind": "volume", "severity": "warning",
            "message": f"Volume ongewoon {direction}: {events} vs {events_prior} (vorig venster).",
            "action": "Controleer of dit verwacht is (bv. een batch-run of een storing)."})
    level = ("critical" if any(s["severity"] == "critical" for s in signals)
             else "warning" if signals else "ok")
    headline = (next((s["message"] for s in signals if s["severity"] == "critical"), None)
                or (signals[0]["message"] if signals else None)
                or f"{events} documenten verwerkt, {errors} fouten (dit venster).")
    return {"level": level, "headline": headline, "signals": signals}
```

- [ ] **Step 5: Run → PASS** (7 tests). Fix until green.
- [ ] **Step 6: Commit**
```bash
cd /c/ANT-PROJECT/KIBANA-OO && git add backend/config.py backend/documents.py backend/tests/test_document_health.py
git commit -m "feat(documents): _build_health — verdict + proactive signals (pure)"
```

### Task 2: Prior-window event count + `health` in the summary

**Files:** Modify `backend/documents.py`; Modify `backend/tests/test_document_health.py`

- [ ] **Step 1: Add failing test** (the model carries `health`/`events_prior`/`events_pct_change`):
```python
def test_document_activity_model_has_health_fields():
    from documents import DocumentActivity
    fields = DocumentActivity.model_fields
    assert "health" in fields and "events_prior" in fields and "events_pct_change" in fields
```

- [ ] **Step 2: Run → FAIL** (no `health` field).

- [ ] **Step 3: Implement** three additive edits in `backend/documents.py`:
  (a) Add an event-count body helper near `_error_count_body`:
```python
def _event_count_body(start, end):
    return {"size": 0, "track_total_hits": True, "query": _event_query(start, end)}
```
  (b) Add fields to `DocumentActivity` (after `error_pct_change`):
```python
    events_prior: int = 0
    events_pct_change: float | None = None
    health: dict = {}
```
  (c) In `build_document_activity`, add the prior-window event count to the `asyncio.gather` (add `_es_search(sid, dv, _event_count_body(prev_start, start))` as a new awaited item, e.g. `prior_events_res`), then after `alert_level` is computed:
```python
    events_prior = 0 if isinstance(prior_events_res, Exception) else \
        prior_events_res.get("hits", {}).get("total", {}).get("value", 0)
    events_pct_change = round((total - events_prior) / events_prior * 100, 1) if events_prior else None
    health = _build_health(total, events_prior, errors, error_pct_change, events_pct_change)
```
  and pass `events_prior=events_prior, events_pct_change=events_pct_change, health=health` into the `DocumentActivity(...)` constructor. (Use `total` as the current event count — it's the window's event total.)

- [ ] **Step 4: Run → PASS.** Then full suite green:
```bash
cd /c/ANT-PROJECT/KIBANA-OO/backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 docker run --rm -v "$HP:/app" -w /app python:3.13 sh -c "pip install -q -r requirements.txt && python -m pytest tests/ -q"
```
- [ ] **Step 5: Commit** `feat(documents): prior-window event count + health in summary payload`.

### Task 3: Action classification — structured field + honest remainder

**Files:** Modify `backend/documents.py`; Modify `backend/tests/test_document_health.py`

- [ ] **Step 1: Add failing tests** for `classify_action` reading a structured field + a new keyword:
```python
def test_classify_prefers_structured_action_field():
    import documents as d
    assert d.classify_event_action({"event": {"action": "created"}}, "geen keyword hier") == "created"

def test_classify_falls_back_to_keywords_then_other():
    import documents as d
    assert d.classify_event_action({}, "document deleted from index") == "deleted"
    assert d.classify_event_action({}, "willekeurige logregel") == "other"
```
> We add a new `classify_event_action(hit, message)` that prefers a structured field then delegates to the existing keyword `classify_action`. This keeps `classify_action` (message-only) intact for back-compat.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** in `backend/documents.py`:
```python
_STRUCTURED_ACTION_FIELDS = ("event.action", "action")
_KNOWN_ACTIONS = {"created", "create", "updated", "update", "deleted", "delete",
                  "retrieved", "indexed", "index"}
_ACTION_CANON = {"create": "created", "update": "updated", "delete": "deleted", "index": "indexed"}

def _dig(hit, dotted):
    cur = hit
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur

def classify_event_action(hit, message):
    """Prefer a structured action field on the hit; else keyword-classify the message."""
    for f in _STRUCTURED_ACTION_FIELDS:
        v = _dig(hit, f)
        if isinstance(v, str) and v.strip().lower() in _KNOWN_ACTIONS:
            a = v.strip().lower()
            return _ACTION_CANON.get(a, a)
    return classify_action(message)
```
Then, in `summarize_event(hit)`, change the line that sets `"action"` from `classify_action(message)` to `classify_event_action(hit, message)` (read `hit` — `summarize_event` already receives the raw `hit`; if it works off `_source`, pass the full hit/`_source` dict so `_dig` can find `event.action`).

- [ ] **Step 4: Run → PASS.** Full suite green. **Step 5: Commit** `feat(documents): prefer a structured action field; honest 'other' remainder`.

### Task 4: `card:documents` runbook condition

**Files:** Modify `backend/context_engine.py`, `docs/KIBANA-OO/Runbook - wat te doen.md`; Modify `backend/tests/test_document_health.py` (or a context test)

- [ ] **Step 1:** Add a runbook section to `docs/KIBANA-OO/Runbook - wat te doen.md` (after the `## Bij Monitoring-target rood` block):
```markdown
## Bij document-verwerking gestopt
- PROD: Geen documentactiviteit terwijl er normaal documenten binnenkomen → de verwerkings-pipeline ligt mogelijk stil. Controleer de harvester/ingest-pods in OpenShift en de logs in Kibana; herstart zo nodig en escaleer naar het dev-team. Bij een foutpiek: bekijk 'Errors per bron' en de gefaalde documenten.
- ACC: Bel Firas/dev; check of de ingest draait en bekijk de document-logs in Kibana.
- TEST: Bel Anton; check de pipeline en de logs.
```

- [ ] **Step 2:** In `backend/context_engine.py`:
  (a) `_CARD_COMPONENT`: add `"card:documents": "documents"`.
  (b) `_CONDITION_LABEL`: add `"documents": "Bij document-verwerking gestopt"`.
  (c) `_condition_from_heading`: add (before the generic "down" check) `if "document" in t and ("verwerking" in t or "gestopt" in t): return "documents"`.
  (d) `_derive_condition`: add `if card_id.startswith("card:documents") and s in ("warning", "critical"): return "documents", s == "critical"`.

- [ ] **Step 3: Add a test** verifying the resolve:
```python
def test_documents_runbook_condition():
    import context_engine as ce
    assert ce._condition_from_heading("Bij document-verwerking gestopt") == "documents"
    assert ce._derive_condition("card:documents", "critical") == ("documents", True)
```
- [ ] **Step 4: Run → PASS** + full suite green. **Step 5: Commit** `feat(documents): 'Bij document-verwerking gestopt' runbook condition`.

### Task 5: Frontend — health banner + signals + KPI deltas + honest "other"

**Files:** Modify `frontend/src/Documents.jsx`; (append `frontend/src/styles.css` if needed)

- [ ] **Step 1:** Read `frontend/src/Documents.jsx` around the analytics section (the "Errors per bron" panel ~line 696, the KPI cards "document events / unique documents / errors" ~735–760, "Op actie" ~761, the InfoTip usage). Note the data object (`data`) now carries `data.health = {level, headline, signals[]}`, `data.events_pct_change`, `data.error_pct_change`.

- [ ] **Step 2:** Add a **health banner** as the FIRST element of the analytics section (above "Errors per bron"). Recipe (reuse OO-GX kit + semantic colours; mirror how the app shows status pills):
  - A `.gx-panel` with a status row: an icon + colour from `data.health.level` (`ok`→green ✓ / `warning`→amber ▲ / `critical`→red ⛔ — reuse existing classes like `alerts-pill--ok/--warn/--crit` or the `svch` verdict colours; do NOT invent colours), and `data.health.headline` as the headline text (`.gx-h2`-ish).
  - Below it, render `data.health.signals` (if any) as a list: each row = severity icon + `message` + the `action` (muted) with an InfoTip; if a signal is `stalled`/`critical`, also show a "📖 Wat te doen" link that opens the Smart Context / runbook (reuse the existing runbook/Smart-Context affordance the other cards use; if none is trivially reusable here, a plain text action is fine for v1).
  - When `level === "ok"` and no signals: show just the green "✓ Gezond — <headline>" line (no scary empty panel).
- [ ] **Step 3:** KPI cards: append the prev-window delta to the events + errors cards — e.g. next to "document events" show `data.events_pct_change != null ? `(${data.events_pct_change > 0 ? "+" : ""}${data.events_pct_change}% vs vorig venster)` : ""` (muted, small); same for errors with `data.error_pct_change`. Additive — keep the existing numbers/labels/InfoTips.
- [ ] **Step 4:** "Op actie" panel: render an action labelled `other` as **"niet-geclassificeerd"** (a display map; keep the underlying key). If `data.by_action` has length 1 and it's `other`, add a one-line `muted` note: *"Het actietype staat niet in de logtekst — alleen het aantal events is bekend."* Keep the panel; the verdict doesn't depend on it.
- [ ] **Step 5: Build-green** (frontend build command). Manually (with the stack running): the banner shows "✓ Gezond …" on a healthy window; "niet-geclassificeerd" replaces "OTHER"; KPI deltas appear.
- [ ] **Step 6: Commit** `feat(documents): health banner + proactive signals + KPI deltas + honest 'other' label`.

### Task 6: Docs + deploy + ship

**Files:** Modify/Create `docs/KIBANA-OO/Documenten.md` (or the existing documents note)

- [ ] **Step 1:** Document the health layer (NL): the verdict banner, the 3 signals + their thresholds (`doc_error_threshold`/`doc_stall_min_prior`/`doc_volume_swing_pct`), the previous-window baseline, the honest "niet-geclassificeerd", and that Phase B (push alerts) is the planned next step. Link `[[Runbook - wat te doen]]` + `[[AI-architectuur]]`.
- [ ] **Step 2:** Full backend suite + frontend build → green.
- [ ] **Step 3:** Deploy `docker compose up -d --build backend frontend`; smoke-test: open Documents, confirm the banner + deltas + "niet-geclassificeerd" render and the page still works.
- [ ] **Step 4: Commit** `docs(documents): document health layer note`.
- [ ] **Step 5: Ship** (push → PR → merge → checkout main → pull → push gitlab main → delete branch).

---

## Self-review

- **Spec coverage:** §4.1 prior-window event count → Task 2. §4.2 `_build_health` + `health` object → Tasks 1–2. §4.3 classification → Task 3. §5 frontend banner/signals/KPI deltas/honest-other → Task 5. §6 runbook condition → Task 4. §9 testing → each task TDD + full-suite gates. §10 additivity/rollback → all tasks additive. §7 Phase-B readiness → `_build_health` is the single hook (Task 1). docs → Task 6. No gaps.
- **Placeholder scan:** none — concrete `_build_health` body + 7 unit tests, exact model-field + gather edits, classify helper, runbook text, context_engine edits, frontend recipe with the data contract. Frontend gives the recipe + contract (not full JSX) — correct altitude; reuses existing classes.
- **Type/name consistency:** `_build_health(events, events_prior, errors, error_pct_change, events_pct_change)` signature identical across Tasks 1–2; `health = {level, headline, signals:[{kind,severity,message,action}]}`; model fields `events_prior`/`events_pct_change`/`health`; `_event_count_body`; `classify_event_action(hit, message)`; runbook condition `"documents"` + label "Bij document-verwerking gestopt" + `card:documents`; config keys `doc_error_threshold`/`doc_stall_min_prior`/`doc_volume_swing_pct` — all consistent.
- **Implementer note:** in Task 3, confirm whether `summarize_event` receives the raw `hit` (with `_source`) so `_dig(hit, "event.action")` can resolve; if it works off `_source` only, pass that dict to `classify_event_action`. In Task 5, reuse existing status-colour classes — don't invent new ones.
