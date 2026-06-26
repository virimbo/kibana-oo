---
name: oo-ux-check
description: >
  Audit and fix the UX of a page or component in the Open Overheid - Monitoring
  (KIBANA-OO) frontend for consistency with the OO-GX design system (Opera-GX
  magazine theme: near-black surfaces, one crimson accent, Chakra-Petch display
  type). Use when building a NEW page/component, when a page "looks off / not
  professional / not consistent", or when asked to align/polish/verify the UI.
  Checks design tokens, the crimson accent, the .gx-* magazine kit, shared
  components, Dutch-with-English-tech-terms copy, layout/responsive patterns and
  accessibility — then applies additive, build-verified fixes.
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

## The OO-GX design system (gold standard)

**Theme:** Opera-GX magazine — deep near-black surfaces, ONE bold crimson accent,
squared **Chakra-Petch** display headlines, **IBM Plex Sans** body, **JetBrains Mono**
numbers, glowing crimson CTAs, sharp 6px corners, stat-card heroes. Full spec:
`docs/superpowers/specs/2026-06-19-opera-gx-restyle-design.md` and the Dutch vault note
`docs/KIBANA-OO/UX design system.md`.

**Reference pages to copy from:** any page using the `.gx-*` kit (Dashboard hero
stat-row, Login split-hero, Alerts/Settings panels). Match these, don't reinvent.

### Tokens (use these — never hardcode hex)
- Surfaces: `--bg-app` (#0e0a0f) `--bg-panel` `--bg-elevated` `--bg-input`
- Lines: `--border` `--border-strong`
- Text: `--text-primary` `--text-secondary` `--text-faint`
- **Accent (interactive — THE crimson):** `--accent` (#ff1f4c) / `--accent-hover` /
  `--accent-soft` / `--accent-glow`. Use for ALL interactive things (buttons, focus
  rings, links, active states) AND primary stat numbers — NOT for status.
- Provider tokens are RETIRED from theming: `--provider-accent` etc. are remapped to
  the crimson `--accent` (no per-model colour). The active AI model is a text label only.
- **Status (semantic — never theme these):** `--success` 🟢 `--warn` 🟠 `--error` 🔴
- Environments: `--env-prod` (crimson) `--env-acc` (amber) `--env-test` (teal)
- Shape/type: `--radius` (6) `--radius-sm` (4) `--display` (Chakra Petch) `--font`
  (IBM Plex Sans) `--mono` (JetBrains Mono)

### The `.gx-*` magazine kit (compose these first)
- **`.gx-eyebrow`** — `• UPPERCASE` crimson kicker above a headline.
- **`.gx-h1` / `.gx-h2`** — Chakra-Petch uppercase display headlines.
- **`.gx-hero`** (+ `.gx-sub`) — eyebrow → headline → sub → CTA block.
- **`.gx-cta`** — glowing crimson primary button.
- **`.gx-panel`** — sharp dark card with a faint crimson top-accent line.
- **`.gx-pill`** — `● LIVE`/status pill.
- **`.gx-stat-card`** (+ `.gx-stat-head/-label/-num/-cap`, `.gx-stat-row/-rownum`) —
  the Opera-GX "AD BLOCKER · 3,241" stat block.
- **`.gx-tag`** — small chip. **`.gx-pagehead`** — eyebrow + display H1 page header.

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
- [ ] Every interactive accent / focus ring / link / primary number uses `--accent`
      (crimson). No blue/emerald/amber accent survives (status green/amber/red excepted).
- [ ] No per-provider colour theming — the active model is shown as text only.

**Typography**
- [ ] Headlines use `var(--display)` (Chakra Petch), uppercase, with a `.gx-eyebrow`.
- [ ] Body uses `var(--font)` (IBM Plex Sans); numbers/IDs use `var(--mono)`.

**Components & layout**
- [ ] Composes the `.gx-*` kit (`.gx-pagehead`/`.gx-hero`/`.gx-panel`/`.gx-cta`/
      `.gx-pill`/`.gx-stat-card`); reuses `.panel`/`.switch`/`.dash-table` — not clones.
- [ ] Page uses the `TopNav` + `.chat-scroll > .dash` shell; eyebrow + display headline.
- [ ] Spacing/radius consistent (`--radius` 6 / `--radius-sm` 4); cards `.gx-panel`/`.panel`.
- [ ] New CSS is namespaced and appended; nothing leaks to other pages.

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
- [ ] Matches the OO-GX look (crimson accent, Chakra-Petch eyebrow + display headline,
      `.gx-panel` cards, `.gx-stat-card` heroes, glowing `.gx-cta`).
- [ ] Header/nav/composer accent is the single crimson `--accent` (no model colour).

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
