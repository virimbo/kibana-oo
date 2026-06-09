---
title: Architecture
tags: [architecture]
---

# Architecture

Back to [[Home]].

## Services (Docker Compose)

| Service | Image / build | Role |
|---|---|---|
| `frontend` | `frontend/` (React 19 + Vite, served by nginx) | UI on `localhost:3000`, proxies `/` → backend |
| `backend` | `backend/` (FastAPI, Python 3.13) | Auth, chat, dashboard, document APIs |
| `ollama` | `ollama/ollama` | Local LLM runtime (`llama3.2:3b`, CPU) |

## Request flow

```
Browser ──> nginx (frontend) ──> FastAPI (backend) ──> Kibana console proxy ──> Elasticsearch
                                          │
                                          └──> LLM (Ollama local | Mistral cloud)
```

- **Never** hits Elasticsearch directly — everything goes through Kibana's
  `/api/console/proxy` with a Keycloak OIDC **`sid` cookie** captured at login.
- The LLM only ever narrates **facts computed from ES** (grounded). See
  [[Chat pipeline]] and [[Monitoring dashboard]].

## Backend modules (`backend/`)

- `main.py` — FastAPI app, `/login`, `/chat`, `/health`, `/llm-provider`. See [[Chat pipeline]].
- `elastic.py` — Kibana proxy client, search helpers, `keycloak_login`, doc-id detection.
- `llm.py` — Ollama + Mistral clients, streaming, `polish_text`, `provider_model`. See [[LLM providers]].
- `ocr.py` — Tesseract OCR for uploaded screenshots. See [[Chat pipeline]].
- `dashboard.py` / `monitoring.py` / `briefing.py` — admin dashboard. See [[Monitoring dashboard]].
- `documents.py` — document activity + the tracer. See [[Document tracer]].
- `portal.py` — official metadata from [[open.overheid.nl API]].
- `config.py` — `Settings` (env-driven). `cache.py` — tiny TTL cache. `session.py` — token→session.

## Auth & admin gating

- Login = Keycloak OIDC; the backend stores the `sid` cookie against a session token.
- Admin features (dashboard, documents) are gated by an env allowlist
  `DASHBOARD_ADMINS`. Keycloak group-claim gating is a documented phase-2.

## Data views (whitelist)

`logs-*`, `ds-prod5-koop-plooi*`, `ds-prod5-koop-sp`. The real KOOP pipeline logs
live in `ds-prod5-koop-plooi*`; `logs-*` ("All logs") is often nearly empty —
this matters for [[Runbook - No answer in chat]].
