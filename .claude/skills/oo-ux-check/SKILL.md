---
name: oo-ux-check
description: >
  Audit and fix the UX of a page or component in the Open Overheid - Monitoring
  (KIBANA-OO) frontend for consistency with the established design system. Use when
  building a NEW page/component, when a page "looks off / not professional / not
  consistent", or when asked to align/polish/verify the UI. Checks design tokens,
  the provider-aware accent theme, shared components, Dutch-with-English-tech-terms
  copy, layout/responsive patterns and accessibility — then applies additive,
  build-verified fixes.
---

# OO-UX-CHECK — UX consistency audit & fix

Audit a page/component against the Open Overheid - Monitoring design system, report
findings by severity, then fix them additively. Frontend lives in
`frontend/src/`; the design system is `frontend/src/styles.css`.

**Announce:** "Using oo-ux-check to audit <target> for design-system consistency."

## When to run
- A **new** page/component before it ships.
- An **existing** page that "looks not professional / inconsistent / off".
- After any visible UI change, as a consistency gate.

## Workflow

1. **Scope** — identify the target file(s) (e.g. `frontend/src/Foo.jsx`) and the
   shared CSS (`styles.css`). If the user gave a screenshot, map it to the component.
2. **Read** the target component + the relevant `styles.css` sections. Compare
   against the **Checklist** below.
3. **Report** findings as a table: `Area | Issue | Severity (🔴/🟡/🟢) | Fix`.
4. **Fix** — apply the fixes (see **Fix rules**). Reuse existing classes/tokens;
   add new CSS only as **namespaced, appended** rules. Never change logic, data
   keys, classNames used in code, or API paths.
5. **Verify** — `cd frontend && npm run build` (must pass). If the stack is running,
   `docker compose up -d --build frontend` to deploy, and ask the user to hard-refresh.
6. **Ship** (only if asked) — branch → commit (`feat(ui)…`) → PR → merge → mirror to
   GitLab, per the project's branch→PR→merge rhythm.

## The design system (gold standard)

**Reference pages to copy from:** `Alerts.jsx` (hero + env-matrix + tiles),
`Settings.jsx` (toggle rows), `DlqIntel.jsx` (insight page), `Dashboard.jsx`
(cards/hero stats). Match these, don't reinvent.

### Tokens (use these — never hardcode hex)
- Surfaces: `--bg-app` `--bg-panel` `--bg-elevated` `--bg-input`
- Lines: `--border` `--border-strong`
- Text: `--text-primary` `--text-secondary` `--text-faint`
- **Accent (interactive):** `--accent` / `--accent-hover` / `--accent-soft` — these
  are remapped onto `--provider-accent` (the active AI model's colour: Ollama
  emerald / Mistral amber / off grey). Use the accent for **interactive** things
  (buttons, focus rings, links, active states), NOT for status.
- Provider accent direct: `--provider-accent` `--provider-accent-2` `--provider-glow`
- **Status (semantic — never theme these):** `--success` 🟢 `--warn` 🟠 `--error` 🔴
- Environments: `--env-prod` (blue) `--env-acc` (amber) `--env-test` (teal)
- Shape/type: `--radius` (12) `--radius-sm` (8) `--font` `--mono`

### Components to reuse (don't rebuild)
- **Card:** `<section className="panel set-panel">` with `<h3>` + optional
  `<span className="page-eyebrow">…</span>` eyebrow + `<p className="muted set-intro">`.
- **Toggle/switch:** the `Switch`/`Toggle` pattern → `<button role="switch"
  className="switch is-on"><span className="switch-knob"/></button>` inside a
  `.set-row` (label + hint). Copy from `Settings.jsx`/`Alerts.jsx`.
- **Status tile:** `.up-tile up-tile--{up|warn|down}` (left colour bar) or the
  `.alerts-mtile` magazine tile. Severity → colour via `--success/--warn/--error`.
- **Env badge:** `.env-badge env-badge--{prod|acc|tst}`.
- **Pills:** `.alerts-pill alerts-pill--{ok|warn|crit}`.
- **Table:** `.dash-table`.
- **Buttons:** `.btn`, `.btn--primary` (provider gradient), `.btn--ghost`.
- **Page shell:** `<><TopNav active="…" brandMark brandName brandSub …/><div
  className="chat-scroll"><div className="dash"> … </div></div></>`. Beheer sub-pages:
  add the view to `BEHEER_SUB` in `Nav.jsx`.

### Copy / language
- **UI text in Dutch**; keep familiar **technical terms in English** (error, log,
  uptime, up/down, latency, timeout, request, endpoint, queue, service, deployment,
  dashboard, certificate, root cause, pipeline, stuck, 5xx, HTTP, TLS, DLQ). Mix
  naturally like a Dutch engineer.
- Keep proper nouns/identifiers as-is (Kibana, Elasticsearch, RabbitMQ, OVS/NVS,
  koop-plooi-prod, Ollama, Mistral, Open Overheid - Monitoring).
- AI chat **answers** are also Dutch (set in `backend/llm.py` system prompts).

## Checklist

**Tokens & colour**
- [ ] No hardcoded hex/rgb for accent/surfaces/text — all via tokens.
- [ ] Interactive accents use `--accent`/`--provider-accent`; status uses
      `--success/--warn/--error`; envs use `--env-*`. No status colour used as theme.

**Components & layout**
- [ ] Reuses `.panel`/`.switch`/`.up-tile`/`.dash-table`/`.btn*` — not bespoke clones.
- [ ] Page uses the `TopNav` + `.chat-scroll > .dash` shell; eyebrow + `<h*>` hierarchy.
- [ ] Spacing/radius consistent (`--radius`, gaps ~10–14px); cards `.panel`.
- [ ] New CSS is namespaced (`.foo-*`) and appended; nothing leaks to other pages.

**Copy**
- [ ] Visible text is Dutch; tech terms English; no leftover English UI strings.
- [ ] No raw IDs/keys shown where a human label belongs.

**States & feedback**
- [ ] Loading, empty, and error states exist and are styled (`.muted`, `.alerts-empty`,
      `.error`).
- [ ] Hover/focus/active states present; focus is visible (provider ring/outline).
- [ ] Optimistic/saved feedback for mutations where relevant.

**Accessibility**
- [ ] Interactive elements are real buttons/inputs with `aria-label`/`title`;
      switches use `role="switch" aria-checked`.
- [ ] Sufficient contrast; never colour-only meaning (pair colour with icon/text).
- [ ] Keyboard reachable; `:focus-visible` not removed.

**Responsive**
- [ ] Grids use `repeat(auto-fit/fill, minmax(…))`; wraps gracefully; no horizontal
      overflow (tables get `overflow-x:auto` wrapper).

**Consistency with siblings**
- [ ] Matches the look of Alerts/Settings/DlqIntel (eyebrow, hero, tiles, pills).
- [ ] Header/nav/composer accent follows the unified provider theme.

## Fix rules (RULES.md-safe)
- **Additive only.** New CSS appended to `styles.css`, namespaced under a page prefix.
  Don't restructure existing rules; override by appending if needed.
- **Reuse before invent** — prefer an existing class/token over a new one.
- **No logic/markup-key changes** — don't touch classNames referenced in JS, data
  keys, props, state, API paths, or any string compared in code.
- **Never touch FROZEN code** (cert: `backend/certificates.py`, `cert_monitor.py`;
  Mistral settings/path) — UX work is frontend/CSS only.
- **Build before claiming done:** `npm run build` must pass; deploy + ask for a
  hard-refresh (Ctrl+F5) to verify visually.
- Document a genuinely new pattern in the Dutch vault (`docs/KIBANA-OO/`) only when
  the user confirms it's a real, reusable feature (RULES 4).

## Output format
1. One-line scope.
2. Findings table (Area | Issue | Severity | Fix).
3. The applied fixes (diffs/edits).
4. Build result + "hard-refresh to verify".
