# Opera GX restyle ("OO-GX") — Design Spec

- **Date:** 2026-06-19
- **Status:** Approved design (Q1A · Q2A · Q3C · Q4C · Q5B), ready for implementation plan
- **Author:** Anton Partono (with Claude)
- **Reference:** Opera GX landing aesthetic — near-black surfaces, one bold crimson, squared
  display type, glowing CTAs, magazine stat cards.

## 1. Goal

Restyle the **whole** Open Overheid – Monitoring web app to an Opera-GX-grade,
magazine-quality dark theme: deep near-black surfaces, a single dominant **crimson**
accent, a **squared technical display font**, big editorial headlines, glowing CTAs and
"stat card" hero blocks — applied consistently across every page. Plus a UX-consistency
**skill + dispatchable agent** so all pages stay consistent over time.

**Hard constraint:** layout/markup/CSS only. **Never** change logic, handlers, data
flow, API calls, `data-*` attributes (e.g. `data-smartcard`), or any className that JS
references. Functionality must be byte-for-byte preserved. Status colours
(green/amber/red) stay semantic and are never themed.

## 2. Decisions (the 5 questions)

1. **Accent (A):** replace the provider-aware accent **entirely** with a fixed Opera-GX
   crimson everywhere; the active AI model stays a text label only.
2. **Fonts (A):** **Chakra Petch** (display/headlines/eyebrows) · **IBM Plex Sans**
   (body) · **JetBrains Mono** (stat numbers). Self-hosted Google Fonts (free).
3. **Depth (C):** full magazine **redesign of every page's layout**, not just a re-skin.
4. **UX enforcer (C):** **both** — update the `oo-ux-check` skill to the new design
   system **and** add a dispatchable `.claude/agents/` subagent that fans out across all
   pages.
5. **Rollout (B):** phased on one branch — global tokens+fonts first, then one page at a
   time, each build-green + functionally verified + agent-checked before the next.

## 3. Design tokens (the OO-GX palette)

Override the existing CSS variables (every component already reads them, so this
re-themes the whole app in one step):

```css
:root {
  /* surfaces — near-black, faint purple */
  --bg-app: #0e0a0f; --bg-panel: #1a1216; --bg-elevated: #221820; --bg-input: #251a22;
  --border: #3a2630; --border-strong: #4d2f3c;
  /* text — warm off-whites */
  --text-primary: #f5eef0; --text-secondary: #b9a9b0; --text-faint: #7d6b73;
  /* accent — the Opera GX crimson (interactive ONLY) */
  --accent: #ff1f4c; --accent-hover: #ff4d6d;
  --accent-soft: rgba(255,31,76,.12); --accent-glow: rgba(255,31,76,.35);
  /* status — SEMANTIC, never themed */
  --success: #3ad07a; --warn: #ffb020; --error: #ff3b4e;
  /* shape — sharper, mechanical */
  --radius: 6px; --radius-sm: 4px;
  --shadow: 0 10px 34px rgba(0,0,0,.5);
  /* type */
  --display: "Chakra Petch", "Oswald", system-ui, sans-serif;
  --font: "IBM Plex Sans", system-ui, sans-serif;
  --mono: "JetBrains Mono", "SFMono-Regular", monospace;
}
```

- The provider tokens (`--provider-accent` etc.) are **retired from theming**: they're
  remapped to the crimson accent so any lingering `var(--provider-accent)` usages stay
  crimson (no per-model colour). The AI-model pill keeps its text label.
- Crimson interactive elements carry a subtle **glow** (`0 0 20px var(--accent-glow)`);
  panels get a faint crimson **top-accent** hairline.

## 4. Typography system

- **Fonts:** self-host Chakra Petch (400/500/600/700), IBM Plex Sans (400/500/600),
  JetBrains Mono (already present) — via an `@font-face`/Google-Fonts `<link>` in
  `index.html` (no JS dependency).
- **Type scale (display = Chakra Petch, uppercase, tight tracking):**
  - Hero H1: `clamp(40px, 6vw, 72px)`, weight 700, `letter-spacing:-.01em`, line 1.02.
  - Page H1 / card H2: 22–28px, 700, uppercase.
  - Section eyebrow: 11px, 700, `letter-spacing:.16em`, uppercase, crimson, leading `•`.
  - Body: IBM Plex Sans 14–15px / 1.55.
  - Stat number: JetBrains Mono (or Chakra Petch) 30–56px, crimson, tabular.

## 5. The magazine layout kit (reusable, namespaced `.gx-*`)

- **`.gx-eyebrow`** — `• UPPERCASE` crimson kicker.
- **`.gx-hero`** — eyebrow → giant display headline → sub → glowing crimson CTA.
- **`.gx-stat-card`** — the reference's "AD BLOCKER · 3,241" block: header row
  (`LABEL` + `● LIVE` pill), big crimson number + caption, then list rows
  (`YOUTUBE … 1,847 Blocked`). Becomes our status cards (Critical / Service health / …).
- **`.gx-pill`** (`● LIVE`), **`.gx-cta`** (glowing crimson button), **`.gx-panel`**
  (sharp dark card + crimson top-accent), **`.gx-tag`** (the small chips).
- Full-width/edge-to-edge containers, generous negative space, uppercase section heads.

These compose the new look; existing structural classes (`.panel`, `.dash-table`,
`.switch`, `.up-tile`, etc.) are **retuned via tokens**, not removed — so the magazine
kit and the existing components coexist.

## 6. Per-page redesign (Q3C — all 10)

Each page is rebuilt on the kit (hero/eyebrow + stat-cards + magazine spacing), preserving
all logic/handlers/`data-*`:

| Page | Magazine treatment |
|---|---|
| **Login** | Opera-GX split hero: eyebrow + giant headline + crimson CTA on the left, a live "stat card" on the right. |
| **Dashboard** | Hero stat-row (Critical / Docs-at-risk / Aanleverfouten / DLQ / Service health) as `.gx-stat-card`s; sections as magazine blocks with eyebrows. |
| **Chat** | Immersive composer + welcome hero; provider pill as a label. |
| **Documents** | Editorial header + tracer hero; tables/feeds retuned. |
| **Settings / Authorization / Regression / Alerts / DLQ Intelligence / Service health** | Eyebrow + display headline per page; panels → `.gx-panel`; existing controls retuned via tokens. |

## 7. The UX enforcer (Q4C)

- **Skill:** rewrite `.claude/skills/oo-ux-check/SKILL.md` to the OO-GX design system —
  the crimson tokens, the Chakra-Petch type scale, the `.gx-*` kit, the magazine
  patterns, and the consistency checklist. Single source of truth.
- **Subagent:** add `.claude/agents/oo-ux-auditor.md` — a read-only agent (Read/Grep/Glob)
  that audits a given page file against the skill's rules and reports findings by
  severity. Dispatchable via the Task tool and **fan-out-able across all 10 pages in
  parallel** ("check the whole web for consistency").

## 8. Rollout plan (Q5B)

Phased on `feat/opera-gx-restyle`:
1. **Foundation** — add the fonts + the OO-GX token override + the `.gx-*` kit CSS;
   build-green. Re-themes every page instantly (safe, no markup change yet).
2. **Per page** — redesign one page's layout at a time → `npm run build` green →
   deploy + verify the page still *works* (data loads, buttons/handlers fire,
   `data-smartcard` intact) → run the `oo-ux-auditor` agent → commit. Then the next.
3. **Sweep** — final fan-out of the agent across all pages; fix any inconsistency.
4. **Docs** — `docs/KIBANA-OO/UX design system.md` (palette, type scale, `.gx-*` kit,
   per-page notes) — RULES 4.

Ship per page (or one PR at the end), mirror to GitHub + GitLab as usual.

## 9. Safety & rollback

- Tokens/fonts/kit are **additive**; per-page redesign changes markup/CSS only — no
  logic, data keys, API paths, `data-*`, or JS-referenced classNames touched.
- Status colours and the user chat bubble stay their own tokens (not crimson).
- Each page is build-green + functionally verified before the next; git is the
  rollback (revert a page's commit). The whole branch can be abandoned without
  touching `main`.
- **FROZEN** code (cert backend, Mistral) is never touched — this is frontend CSS/markup.

## 10. Out of scope (YAGNI)

A light theme; a theme toggle (we're committing to OO-GX, Q5 rejected C); animation-heavy
effects beyond the glow/hover/staggered-reveal already in the system.
