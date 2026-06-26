# Opera GX restyle (OO-GX) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the whole Open Overheid – Monitoring web app to an Opera-GX magazine aesthetic — near-black surfaces, one crimson accent, Chakra-Petch display type, glowing CTAs, stat-card heroes — consistently across all 10 page surfaces, plus a UX-consistency skill + dispatchable auditor agent.

**Architecture:** All styling lives in CSS-variable tokens at the top of `frontend/src/styles.css` (3341 lines, one file). Flipping the token *values* re-themes the entire app in one move because `--accent`/`--provider-accent` are referenced ~165× via `var()`. We add self-hosted web fonts (`@fontsource/*`, Vite-bundled, offline-safe), a reusable namespaced `.gx-*` magazine kit, then redesign each page's markup to use the kit — **layout/markup/CSS only, never logic, handlers, `data-*`, API calls, or JS-referenced classNames.** Status colours (green/amber/red) stay semantic.

**Tech Stack:** React 19 + Vite, plain CSS (no framework), `@fontsource` for fonts. Build verification via `npm run build` in the `node:20` Docker image. Functional verification by reading the diff against the "don't touch" list + the `oo-ux-auditor` subagent.

**Spec:** `docs/superpowers/specs/2026-06-19-opera-gx-restyle-design.md`

**Branch:** `feat/opera-gx-restyle` (already created off `main`).

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `frontend/package.json` | add `@fontsource/chakra-petch`, `@fontsource/ibm-plex-sans`, `@fontsource/jetbrains-mono` | Modify |
| `frontend/src/main.jsx` | import the three font packages (bundled, offline-safe) | Modify |
| `frontend/src/styles.css` | OO-GX token override (top `:root`) + `.gx-*` kit (new section) + per-page tweaks | Modify |
| `frontend/src/App.jsx` | Login + Chat markup → `.gx-*` (login-page, chat shell) | Modify |
| `frontend/src/Dashboard.jsx` | hero stat-row + magazine sections | Modify |
| `frontend/src/Documents.jsx` `Settings.jsx` `Authorization.jsx` `Regression.jsx` `Alerts.jsx` `DlqIntel.jsx` `ServiceHealth.jsx` | eyebrow + display headline + `.gx-panel` | Modify |
| `.claude/skills/oo-ux-check/SKILL.md` | rewrite to OO-GX design system (single source of truth) | Modify |
| `.claude/agents/oo-ux-auditor.md` | new dispatchable read-only consistency auditor | Create |
| `docs/KIBANA-OO/UX design system.md` | Obsidian doc: palette, type scale, kit, per-page notes | Create |

**Verification helper (used by every task):**
```bash
# build-green check (run from repo root)
cd /c/ANT-PROJECT/KIBANA-OO/frontend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 \
  docker run --rm -v "$HP:/app" -w /app node:20 sh -c "npm ci --no-audit --no-fund && npm run build" 2>&1 | tail -8
# Expected: "✓ built in …" with no errors.
```

---

## Task 0: Foundation — fonts + OO-GX tokens + magazine kit

**Files:**
- Modify: `frontend/package.json`, `frontend/src/main.jsx`
- Modify: `frontend/src/styles.css:8-58` (the `:root` token block) + new `.gx-*` section

- [ ] **Step 1: Add the font packages**

In `frontend/package.json`, add to `dependencies` (keep alphabetical with siblings):
```json
"@fontsource/chakra-petch": "^5.0.0",
"@fontsource/ibm-plex-sans": "^5.0.0",
"@fontsource/jetbrains-mono": "^5.0.0",
```

- [ ] **Step 2: Import the fonts (bundled, offline-safe)**

At the TOP of `frontend/src/main.jsx`, above the existing imports:
```js
// OO-GX type system — self-hosted (Vite-bundled), works without internet/VPN.
import "@fontsource/chakra-petch/500.css";
import "@fontsource/chakra-petch/600.css";
import "@fontsource/chakra-petch/700.css";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/jetbrains-mono/500.css";
import "@fontsource/jetbrains-mono/700.css";
```

- [ ] **Step 3: Replace the `:root` token values (OO-GX palette)**

In `frontend/src/styles.css`, replace the token block (`frontend/src/styles.css:9-58`, the first `:root {…}`) with:
```css
:root {
  /* OO-GX — Opera-GX magazine theme. Near-black surfaces, one crimson accent. */
  --bg-app: #0e0a0f;
  --bg-panel: #1a1216;
  --bg-elevated: #221820;
  --bg-input: #251a22;
  --border: #3a2630;
  --border-strong: #4d2f3c;

  --text-primary: #f5eef0;
  --text-secondary: #b9a9b0;
  --text-faint: #7d6b73;

  /* The one crimson accent — drives every interactive element + stat numbers. */
  --accent: #ff1f4c;
  --accent-hover: #ff4d6d;
  --accent-soft: rgba(255, 31, 76, 0.12);
  --accent-glow: rgba(255, 31, 76, 0.35);

  --user-bubble: #b3163b;          /* user chat bubble — deep crimson, not the bright accent */
  --error: #ff3b4e;
  --error-soft: rgba(255, 59, 78, 0.10);
  --success: #3ad07a;
  --warn: #ffb020;
  --warn-soft: rgba(255, 176, 32, 0.12);

  /* Environment accents — re-tuned to the crimson world but kept distinguishable. */
  --env-prod: #ff1f4c;  --env-prod-soft: rgba(255, 31, 76, 0.10);
  --env-acc:  #ffb020;  --env-acc-soft:  rgba(255, 176, 32, 0.10);
  --env-test: #2db6a6;  --env-test-soft: rgba(45, 182, 166, 0.12);
  --env-col-min: 300px;

  /* Provider tokens RETIRED from theming (Q1A): all remapped to the crimson accent,
     so the existing ~88 var(--provider-accent) usages render crimson with no edits.
     The active AI model is still shown as a text label by ProviderSwitcher. */
  --provider-accent: var(--accent);
  --provider-accent-2: var(--accent-hover);
  --provider-glow: var(--accent-glow);
  --provider-name: "AI";

  --radius: 6px;
  --radius-sm: 4px;
  --shadow: 0 10px 34px rgba(0, 0, 0, 0.5);

  --display: "Chakra Petch", "Oswald", system-ui, sans-serif;
  --font: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
}
```

- [ ] **Step 4: Neutralise the per-provider overrides**

The two blocks `:root[data-provider="mistral"]` and `:root[data-provider="none"]` (`frontend/src/styles.css:60-74`) currently recolour the UI per model. Replace BOTH blocks with a single comment so no per-model colour leaks (Q1A):
```css
/* OO-GX: provider no longer recolours the UI (Q1A). The active model shows as a
   text label only. data-provider stays on <html> for any non-colour logic. */
```

- [ ] **Step 5: Update the body background glow to crimson**

In `frontend/src/styles.css` `body { background: … }` (~line 78), change the blue radial to crimson:
```css
  background:
    radial-gradient(1200px 600px at 80% -10%, rgba(255, 31, 76, 0.07), transparent 60%),
    var(--bg-app);
```

- [ ] **Step 6: Append the `.gx-*` magazine kit**

Append this NEW section at the END of `frontend/src/styles.css`:
```css
/* ════════════════════════════════════════════════════════════════════════
   OO-GX magazine kit — reusable, namespaced. Compose these on any page.
   ════════════════════════════════════════════════════════════════════════ */

/* Eyebrow — • UPPERCASE crimson kicker above a headline. */
.gx-eyebrow {
  display: inline-flex; align-items: center; gap: 8px;
  font-family: var(--display);
  font-size: 11px; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
  color: var(--accent);
}
.gx-eyebrow::before {
  content: ""; width: 7px; height: 7px; border-radius: 50%;
  background: var(--accent); box-shadow: 0 0 10px var(--accent-glow);
}

/* Display headlines. */
.gx-h1 {
  font-family: var(--display); font-weight: 700; text-transform: uppercase;
  font-size: clamp(34px, 5vw, 64px); line-height: 1.02; letter-spacing: -0.01em;
  color: var(--text-primary);
}
.gx-h2 {
  font-family: var(--display); font-weight: 700; text-transform: uppercase;
  font-size: clamp(20px, 2.4vw, 28px); letter-spacing: 0.01em; color: var(--text-primary);
}

/* Hero block — eyebrow → headline → sub → CTA. */
.gx-hero { display: flex; flex-direction: column; gap: 18px; max-width: 640px; }
.gx-hero .gx-sub { color: var(--text-secondary); font-size: 15px; line-height: 1.55; }

/* Glowing crimson CTA. */
.gx-cta {
  display: inline-flex; align-items: center; justify-content: center; gap: 10px;
  font-family: var(--display); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase;
  font-size: 14px; padding: 14px 26px; border: 0; border-radius: var(--radius-sm);
  color: #fff; background: var(--accent); cursor: pointer;
  box-shadow: 0 0 0 rgba(255,31,76,0); transition: box-shadow .18s, background .18s, transform .18s;
}
.gx-cta:hover { background: var(--accent-hover); box-shadow: 0 0 24px var(--accent-glow); transform: translateY(-1px); }
.gx-cta:disabled { opacity: .5; cursor: not-allowed; box-shadow: none; transform: none; }

/* Panel — sharp dark card with a faint crimson top-accent. */
.gx-panel {
  position: relative; background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 22px 24px; box-shadow: var(--shadow);
}
.gx-panel::before {
  content: ""; position: absolute; inset: 0 0 auto 0; height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent 70%);
  border-radius: var(--radius) var(--radius) 0 0;
}

/* LIVE / status pill. */
.gx-pill {
  display: inline-flex; align-items: center; gap: 6px;
  font-family: var(--display); font-size: 10px; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; padding: 4px 9px; border-radius: 3px;
  color: var(--accent); background: var(--accent-soft); border: 1px solid var(--border-strong);
}
.gx-pill::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 8px var(--accent-glow); }

/* Stat card — the reference "AD BLOCKER · 3,241" block. */
.gx-stat-card { display: flex; flex-direction: column; gap: 14px; }
.gx-stat-card .gx-stat-head { display: flex; align-items: center; justify-content: space-between; }
.gx-stat-card .gx-stat-label { font-family: var(--display); font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; font-size: 13px; color: var(--text-secondary); }
.gx-stat-card .gx-stat-num { font-family: var(--mono); font-weight: 700; font-size: clamp(30px, 4vw, 52px); color: var(--accent); line-height: 1; }
.gx-stat-card .gx-stat-cap { font-family: var(--display); font-size: 11px; letter-spacing: 0.12em; text-transform: uppercase; color: var(--text-faint); }
.gx-stat-row { display: flex; align-items: center; justify-content: space-between; padding: 12px 0; border-top: 1px solid var(--border); }
.gx-stat-row .gx-stat-rownum { font-family: var(--mono); color: var(--accent); font-weight: 700; }

/* Small chip/tag (the reference's "YouTube ads" pills). */
.gx-tag {
  display: inline-flex; align-items: center; font-size: 12px; padding: 6px 12px;
  border-radius: var(--radius-sm); background: var(--bg-elevated);
  border: 1px solid var(--border); color: var(--text-secondary);
}

/* Page header used by content pages: eyebrow + display H1. */
.gx-pagehead { display: flex; flex-direction: column; gap: 8px; margin-bottom: 22px; }
```

- [ ] **Step 7: Build-green check**

Run the verification helper (top of plan). Expected: `✓ built in …`, no errors. Fix any CSS/JS syntax error before committing.

- [ ] **Step 8: Commit**

```bash
cd /c/ANT-PROJECT/KIBANA-OO && git add frontend/package.json frontend/src/main.jsx frontend/src/styles.css
git commit -m "feat(ui): OO-GX foundation — crimson tokens, Chakra-Petch fonts, .gx-* magazine kit"
```

---

## Task 1: UX enforcer — rewrite skill + create auditor agent

Do this BEFORE the page redesigns so the agent can check each page as we go (Q4C).

**Files:**
- Modify: `.claude/skills/oo-ux-check/SKILL.md`
- Create: `.claude/agents/oo-ux-auditor.md`

- [ ] **Step 1: Rewrite the skill to the OO-GX design system**

Replace `.claude/skills/oo-ux-check/SKILL.md` body so it documents, as the single source of truth: the crimson token table (from spec §3), the type scale (spec §4), the `.gx-*` kit (Task 0 Step 6), and this checklist:
```markdown
## OO-GX consistency checklist
- [ ] Surfaces use --bg-* tokens; NO hard-coded hex backgrounds.
- [ ] Every interactive accent / focus ring / link / primary number uses --accent (crimson). No blue/emerald/amber accents survive (status green/amber/red excepted).
- [ ] Headlines use var(--display) (Chakra Petch), uppercase, with a .gx-eyebrow kicker.
- [ ] Body uses var(--font) (IBM Plex Sans); numbers/IDs use var(--mono).
- [ ] Cards are .gx-panel or .panel (token-driven); radius via --radius/--radius-sm.
- [ ] Primary buttons are .gx-cta (or token-driven) with the crimson glow on hover.
- [ ] No per-provider colour theming (Q1A) — model shown as text only.
- [ ] data-* attributes, handlers, and JS-referenced classNames are UNCHANGED.
```

- [ ] **Step 2: Create the dispatchable auditor agent**

Create `.claude/agents/oo-ux-auditor.md`:
```markdown
---
name: oo-ux-auditor
description: Read-only OO-GX design-system consistency auditor. Dispatch one per page (fan out across all pages) to flag deviations from the Opera-GX crimson/Chakra-Petch design system. Returns findings by severity; does not edit.
tools: Read, Grep, Glob
---

You audit ONE page component against the OO-GX design system (the single source of
truth is `.claude/skills/oo-ux-check/SKILL.md` and `docs/KIBANA-OO/UX design system.md`).

Given a target file (e.g. `frontend/src/Dashboard.jsx`):
1. Read the OO-GX checklist from the skill file.
2. Read the target file and the relevant `.gx-*`/token CSS in `frontend/src/styles.css`.
3. Report findings as a list: `SEVERITY (high|med|low) — file:line — what's inconsistent — suggested fix`.
   - high: hard-coded colours, non-crimson accents, wrong/raw fonts, broken token usage.
   - med: missing eyebrow/display headline, inconsistent card/panel, ad-hoc spacing.
   - low: minor polish.
4. CRITICAL: flag (do NOT fix) any change that would touch logic, handlers, `data-*`,
   API calls, or JS-referenced classNames — those are out of bounds.
You are read-only. Output only the findings list; no file edits.
```

- [ ] **Step 3: Commit**

```bash
cd /c/ANT-PROJECT/KIBANA-OO && git add ".claude/skills/oo-ux-check/SKILL.md" ".claude/agents/oo-ux-auditor.md"
git commit -m "feat(ux): OO-GX design system in oo-ux-check skill + dispatchable oo-ux-auditor agent"
```

---

## Tasks 2–11: per-page redesign (one task each)

**Every page task follows the SAME 6 steps** (shown once here in full; each task lists only its page-specific markup recipe + don't-touch list). Apply the kit; change markup/CSS only.

> **Per-page step template** (do these for each page task):
> 1. **Read** the page file fully; list every `data-*`, `onClick`/handler, `className` referenced in `.jsx` logic or `styles.css` selectors, and API call. These are the **don't-touch set**.
> 2. **Apply the recipe**: wrap the page's header in `.gx-pagehead` with a `.gx-eyebrow` + `.gx-h1`/`.gx-h2`; convert primary buttons to `.gx-cta`; convert top-level cards to `.gx-panel` (additively — keep existing classes used by JS/CSS). Add page CSS only if the kit doesn't cover it.
> 3. **Build-green** via the verification helper. Expected `✓ built`.
> 4. **Functional verify**: diff the file (`git diff <file>`); confirm NOTHING in the don't-touch set changed — only presentational markup/classes/copy. If any handler/`data-*`/API/JS-className changed, revert that hunk.
> 5. **Agent-check**: dispatch the `oo-ux-auditor` agent on the file; fix any high/med findings that are presentational.
> 6. **Commit**: `git add <file> frontend/src/styles.css && git commit -m "feat(ui): OO-GX restyle — <page>"`.

### Task 2: Login (`frontend/src/App.jsx`, the `login-page` block ~line 158)
Recipe: split hero — left column `.gx-hero` (eyebrow `• 100% MONITORING` → `.gx-h1` "OPEN OVERHEID — MONITORING" → `.gx-sub` tagline → `.gx-cta` login button); right column a `.gx-panel.gx-stat-card` preview ("STATUS · live", a couple stat rows). Don't-touch: the login form `onSubmit`, the username/password state + inputs, the error handling (`err.message === "Failed to fetch"`), `login-page` class if CSS targets it.

### Task 3: Chat (`frontend/src/App.jsx`, the chat shell + welcome ~lines 589–660)
Recipe: welcome state → `.gx-hero` (eyebrow + `.gx-h2` + sub); the connection status uses the existing tone logic — restyle the badge with `.gx-pill` only (keep `tone`/`label` logic). Composer: primary send button → `.gx-cta`. Don't-touch: `onKeyDown` (`e.key === "Enter"`), message-render branches (`msg.role`, `msg.status`), streaming/abort logic, `sources` rendering, `sessionStorage` keys.

### Task 4: Dashboard (`frontend/src/Dashboard.jsx`)
Recipe: top → `.gx-pagehead` (eyebrow + `.gx-h1`). The summary/severity cards (Critical / Docs-at-risk / Aanleverfouten / DLQ / Service health) → `.gx-panel.gx-stat-card` with `.gx-stat-num` for the count + `.gx-pill` for live/severity. Section headers → `.gx-eyebrow`. Don't-touch: ALL `data-smartcard`/`data-smartlabel`/`data-smartstatus`/`data-smartenv` attributes, the `panel--alert` class, every fetch/poll, the InfoTip markup, `useCardContext` wiring.

### Task 5: Documents (`frontend/src/Documents.jsx`)
Recipe: `.gx-pagehead` header; the tracer/summary block → `.gx-panel`; table/feed retuned via tokens (no structural change). Primary actions → `.gx-cta`. Don't-touch: table data keys, sorting/filter state, the document-tracer fetch, any `data-*`, row `key`s.

### Task 6: Settings (`frontend/src/Settings.jsx`)
Recipe: `.gx-pagehead`; each settings group → `.gx-panel` with a `.gx-eyebrow` group label; the `.switch` toggles keep their class (CSS retuned by tokens already). Don't-touch: the toggle `onChange`/persist logic, feature keys, `.switch` className (CSS + logic depend on it).

### Task 7: Authorization (`frontend/src/Authorization.jsx`)
Recipe: `.gx-pagehead`; the grant matrix wrapper → `.gx-panel`; column/row heads → display font. Don't-touch: the per-user × per-feature checkbox handlers, the grant `data`/state, the matrix cell keys.

### Task 8: Regression (`frontend/src/Regression.jsx`)
Recipe: `.gx-pagehead` ("• POST-RELEASE GATE"); run/result cards → `.gx-panel`; the run button → `.gx-cta`; pass/fail keep `--success`/`--error`. Don't-touch: the run trigger, polling, result parsing, any `data-*`.

### Task 9: Alerts (`frontend/src/Alerts.jsx`)
Recipe: `.gx-pagehead`; channel/config cards → `.gx-panel`; test/save buttons → `.gx-cta`; status pills → `.gx-pill`. Don't-touch: the email/Mattermost test + save handlers, the config field names, the alert-history fetch.

### Task 10: DLQ Intelligence (`frontend/src/DlqIntel.jsx`)
Recipe: `.gx-pagehead`; queue/intel cards → `.gx-panel.gx-stat-card` (depth as `.gx-stat-num`). Don't-touch: the DLQ fetch, queue keys, any `data-*`, the badge wiring.

### Task 11: Service health (`frontend/src/ServiceHealth.jsx`)
Recipe: keep the self-fetch + `data-smartcard="card:service_health"` section EXACTLY; restyle the `<h3>` to display font + `.gx-pill` for the summary pills; tiles retuned via tokens. Don't-touch: the `data-smartcard`/`data-smartlabel`/`data-smartstatus`/`data-smartenv` attributes (Smart Context depends on them), the `VERDICT` map, the InfoTip, `fetchServiceHealth`, the expand `onClick`, `svch-*` classNames (CSS depends on them — retune via tokens, don't rename).

---

## Task 12: Obsidian doc + full consistency sweep + deploy

**Files:**
- Create: `docs/KIBANA-OO/UX design system.md`

- [ ] **Step 1: Write the Obsidian design-system note**

Create `docs/KIBANA-OO/UX design system.md` with Obsidian frontmatter (`title`, `tags: [ux, design, beheer, nl]`, `owner: KOOP Beheer`) documenting: the crimson palette + token table, the type scale (Chakra Petch / IBM Plex Sans / JetBrains Mono), the `.gx-*` kit with one usage example each, and a short per-page note. Link `[[Runbook - wat te doen]]` and `[[Monitoring dashboard]]`.

- [ ] **Step 2: Full fan-out consistency sweep**

Dispatch the `oo-ux-auditor` agent in parallel across all 10 page files. Collect findings; fix any remaining high/med **presentational** inconsistencies (commit per fix). Re-run until the sweep is clean.

- [ ] **Step 3: Final build-green**

Run the verification helper. Expected `✓ built`.

- [ ] **Step 4: Deploy + smoke-check**

```bash
cd /c/ANT-PROJECT/KIBANA-OO && docker compose up -d --build frontend 2>&1 | tail -1
```
Open the app; confirm every page renders in the crimson theme and all interactions still work (login, chat send, dashboard cards/hover Smart Context, settings toggles, regression run).

- [ ] **Step 5: Commit the doc**

```bash
cd /c/ANT-PROJECT/KIBANA-OO && git add "docs/KIBANA-OO/UX design system.md"
git commit -m "docs(ux): OO-GX design system note (Obsidian)"
```

---

## Ship (after all tasks)

```bash
cd /c/ANT-PROJECT/KIBANA-OO
git push -u origin feat/opera-gx-restyle
gh pr create --base main --head feat/opera-gx-restyle --title "feat(ui): Opera GX (OO-GX) magazine restyle" --body "Full-app crimson/Chakra-Petch magazine restyle across all 10 pages + UX auditor agent. Layout/CSS only — no logic touched. See docs/superpowers/specs/2026-06-19-opera-gx-restyle-design.md."
gh pr merge feat/opera-gx-restyle --merge
git checkout main && git pull --ff-only origin main
git push gitlab main
git branch -d feat/opera-gx-restyle && git push origin --delete feat/opera-gx-restyle
```

---

## Self-review

- **Spec coverage:** §3 tokens → Task 0 Step 3-5. §4 fonts/type → Task 0 Step 1-2,6. §5 `.gx-*` kit → Task 0 Step 6. §6 all 10 pages → Tasks 2–11. §7 skill+agent → Task 1. §8 rollout (foundation→per-page→sweep→docs) → Task order 0,2–11,12. §9 safety → per-page Step 1+4 don't-touch set. No gaps.
- **Placeholders:** none — token values, kit CSS, font imports, agent frontmatter all concrete. Per-page recipes name exact files, classes, and don't-touch sets.
- **Type/name consistency:** `.gx-eyebrow/.gx-h1/.gx-h2/.gx-hero/.gx-cta/.gx-panel/.gx-pill/.gx-stat-card/.gx-tag/.gx-pagehead` defined once in Task 0 Step 6 and referenced verbatim in Tasks 2–11. Token names match `styles.css`. `oo-ux-auditor` agent name matches the dispatch in Task 12.
