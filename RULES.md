# RULES — read this BEFORE changing any existing code

> Read this file first at the start of any task that might touch existing code.
> These rules override convenience, momentum, and "it's a small change."

## Rule 1 — Do NOT change existing / working code without explicit permission

- Before editing any **existing file's working code**, STOP and **ask the user first**.
  Describe exactly what you want to change and why, and wait for an explicit "yes".
- This is not about new features in **new files** — adding new modules/files is fine.
  It is about **modifying code that already exists and works**.

## Rule 2 — Certificates are FROZEN 🔒

- **Never** touch the TLS / certificate code without explicit, specific approval:
  - `backend/certificates.py`
  - `backend/cert_monitor.py`
  - the certificate cards / TLS-health UI
- The cert monitoring works and is sensitive. Treat it as read-only. If a change
  seems necessary, explain it and **wait for a yes** — do not edit first.

## Rule 3 — When in doubt, ask

- If a task can only be done by modifying existing working code, **pause and ask**
  rather than proceeding. A blocked task is better than broken working code.
- Prefer additive changes (new files, new functions) over editing existing ones.

## Rule 4 — Document every new feature in the Obsidian vault (in Dutch) 📓

Whenever a **new feature or functionality** is created **and tested**, update the
Obsidian documentation **before considering the work done**:

- **Where:** the Obsidian vault at `docs/KIBANA-OO/`. Add a new note for a new
  feature, or update the relevant existing note. Link it from `Home.md` and any
  related notes (Obsidian `[[wikilinks]]`).
- **When:** *after* it has been tested and verified working — document what
  actually works, not what was planned.
- **Language:** **always in Dutch (Nederlands).** Titles, body, labels — alles in
  het Nederlands. (Code identifiers and config keys stay as-is.)
- **How (audience = an admin/beheerder, not a developer):** make it as
  comprehensive and easy to understand as possible:
  - **Wat & waarom** — wat doet de functie en welk probleem lost het op.
  - **Hoe te gebruiken** — stap voor stap, waar in de UI (Dashboard / Beheer / …).
  - **Een echt voorbeeld** — een concreet, realistisch scenario met echte waarden
    (bijv. een document-id, een melding, een telling) zodat het meteen duidelijk is.
  - **Betekenis van de cijfers/kleuren** — leg statussen, drempels en kleur­codes uit.
  - **Configuratie & randgevallen** — relevante `.env`-instellingen en wat te doen
    als iets misgaat.
- This is **not optional**: a feature without a clear Dutch beheerder-note is not
  finished. Keep the note in sync when the feature later changes.

## What is allowed without asking

- Creating **new** files / features that don't modify existing working code.
- Changes the user **explicitly requested** in the current conversation
  (e.g. "fix X", "change Y") — that request *is* the permission, for X/Y only.
- Reading, analysing, testing, running — anything non-mutating.

## Gotchas that have bitten us (check these)

- **New top-level backend API route ⇒ add it to `frontend/nginx.conf`.** nginx only
  proxies an explicit list of paths; a new route under a *new* prefix (e.g. `/me/`,
  `/admin/`, `/llm-provider`) is NOT proxied by default, so in the browser it 404s/
  405s while working fine on `:8000` directly. New routes under `/dashboard/` are
  already covered. When adding `/<newprefix>/...`, add a `location /<newprefix>/`
  block to nginx.conf and redeploy the frontend.

## Reminder for the assistant

At the start of work: **read RULES.md**, and if the task implies editing existing
code (especially certificates), ask before touching it.
