# KIBANA-OO Project

## ⛔ READ FIRST — [RULES.md](RULES.md)

**Before changing ANY existing/working code, read [RULES.md](RULES.md) and ask
permission first.** Do not modify existing working code without an explicit "yes"
— **especially the certificate / TLS code** (`backend/certificates.py`,
`backend/cert_monitor.py`), which is FROZEN. New files/features are fine; editing
existing working code is not, without asking.

## Overview

This is the KIBANA-OO project. Update this section with project description as it evolves.

## Development Guidelines

- Follow conventional commits: `type(scope): description`
  - Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`
- Write tests before or alongside implementation
- Keep PRs focused and small
- All code must pass linting and tests before commit
- Never commit `.env` files or secrets

## Architecture

- **Databases:** see [docs/database.md](docs/database.md) — `incidents.db` (durable
  incident store) and the shared `kibana_oo.db` (feature run/audit logs, one table
  per feature, via `backend/db.py`).
- **Regression test:** see [docs/regression-test.md](docs/regression-test.md) — the
  post-release health gate for open.overheid.nl (Beheer → Regressietest).
- **Aanleverfouten:** see [docs/aanleverfouten.md](docs/aanleverfouten.md) — monitors
  documents rejected at delivery (detect in logs → reconcile → durable incidents).
- **Time range:** see [docs/time-range.md](docs/time-range.md) — shared presets +
  custom from→to window (additive `from`/`to`; the `period` path is unchanged).
- **Authorization:** see [docs/authorization.md](docs/authorization.md) +
  [docs/KIBANA-OO/Autorisatie.md](docs/KIBANA-OO/Autorisatie.md) (NL) — super admin
  (config) + per-user × per-feature grant matrix; `require_feature` enforces server-side.
  Plus an **approval gate**: new users are `pending` (zero access, no chat) until the
  super admin approves them; `is_super` is always approved + existing users are
  grandfathered (fail-safe, no lock-out).
- **RabbitMQ DLQ:** see [docs/rabbitmq-dlq.md](docs/rabbitmq-dlq.md) — dead-letter-queue
  monitor (Management API, read-only); background poll + alerts + `/dashboard/dlq`.
- **AI architecture & compliance:** see [docs/KIBANA-OO/AI-architectuur.md](docs/KIBANA-OO/AI-architectuur.md)
  (NL) — the app is **RAG** (Elasticsearch → prompt → LLM) + background monitors; **no
  agents/sub-agents/MCP** (those are Claude Code build-time tooling). Includes Mermaid
  diagrams and an honest EU AI Act / AVG privacy posture (not a "100% compliant" claim —
  needs a DPIA + DPO sign-off).

_Document further architecture decisions here as the project develops._

## Custom Slash Commands

- `/status` — Show project status: recent commits, uncommitted changes, TODOs
- `/review` — Review uncommitted changes for quality, security, naming
- `/clean` — Scan for TODOs, dead code, oversized files

## Conventions

- Use clear, descriptive variable and function names
- Prefer composition over inheritance
- Handle errors explicitly — no silent failures
- Keep functions small and focused (single responsibility)
- Use `.editorconfig` settings (2-space indent, LF line endings, UTF-8)

## Project Structure

```
.claude/              # Claude Code configuration
  commands/           # Custom slash commands
  hooks/              # Automation hooks
  settings.json       # Permission rules
.github/              # GitHub templates and CI
  ISSUE_TEMPLATE/     # Bug report and feature request templates
  workflows/          # GitHub Actions CI pipeline
  pull_request_template.md
.editorconfig         # Editor-agnostic formatting rules
.gitignore            # Ignored files and directories
CLAUDE.md             # This file — project guidelines for Claude
```

## Important Files

_Track key files and their purposes here as the project grows._
