---
title: Architecture
tags: [architecture]
---

# Architecture

Back to [[Home]]. A comprehensive view of how the pieces fit together — Docker
topology, the Kibana authorization handshake, and the chat/LLM data flow.

> [!tip] Mermaid diagrams
> These render natively in Obsidian (and on GitHub). Use the graph view to see
> how the notes link.

---

## 1. System context (containers + external systems)

```mermaid
flowchart LR
    user(["Admin / user<br/>(browser)"])

    subgraph compose["Docker Compose — private bridge network"]
        fe["frontend<br/>nginx · :3000<br/>(serves React SPA, reverse-proxies API)"]
        be["backend<br/>FastAPI · :8000"]
        ol["ollama<br/>:11434<br/>llama3.2:3b (CPU)"]
    end

    subgraph ext["External systems (corporate network / internet)"]
        kc["Keycloak<br/>OIDC IdP"]
        kb["Kibana<br/>console proxy"]
        es[("Elasticsearch<br/>logs / APM / metrics")]
        mi["Mistral API<br/>(cloud LLM)"]
        ov["open.overheid.nl<br/>openbaarmakingen API"]
    end

    user -->|"HTTPS :3000"| fe
    fe -->|"/login /chat /dashboard/*"| be

    be -->|"OIDC login"| kc
    be -->|"_search via sid cookie"| kb
    kb --> es

    be -->|"/api/chat"| ol
    be -->|"/v1/chat/completions + Bearer key"| mi
    be -->|"document title / metadata"| ov

    classDef ext fill:#1b222e,stroke:#3a4659,color:#cbd5e1;
    classDef box fill:#10243a,stroke:#2f6feb,color:#dbeafe;
    class kc,kb,es,mi,ov ext;
    class fe,be,ol box;
```

**Key invariant:** the backend **never** queries Elasticsearch directly — every
search goes through **Kibana's console proxy** carrying the user's Keycloak `sid`
cookie. The LLM only ever sees **facts already computed from ES** (grounding).

---

## 2. Authentication — Keycloak OIDC handshake

`POST /login` exchanges credentials for a Kibana `sid` cookie, then mints an
opaque session token for the browser. The `sid` never leaves the server.

```mermaid
sequenceDiagram
    autonumber
    actor U as Browser
    participant BE as backend
    participant KB as Kibana
    participant KC as Keycloak

    U->>BE: POST /login {username, password}
    BE->>KB: POST /internal/security/login (start OIDC)
    KB-->>BE: 200 { location: Keycloak auth URL }
    BE->>KC: GET auth form
    KC-->>BE: HTML login form (action URL)
    BE->>KC: POST credentials to action URL
    alt invalid credentials
        KC-->>BE: 200 form with error
        BE-->>U: 401 Invalid username or password
    else success
        KC-->>BE: 302 redirect (callback URL)
        BE->>KB: GET callback
        KB-->>BE: Set-Cookie: sid=...
        BE->>BE: create_session(user, sid) -> token
        BE-->>U: 200 { token, username }
    end
    Note over U,BE: token kept in sessionStorage;<br/>sid stays server-side in the session store
```

If Kibana is unreachable (VPN down / DNS), the backend returns a friendly **503**
("connect to the company network or VPN") instead of a raw error.

---

## 3. Authorization + the chat data flow

Every protected call carries `Authorization: Bearer <token>`. `require_session`
resolves it to `{sid, username, llm_provider}`; admin routes additionally check
the `DASHBOARD_ADMINS` allowlist.

```mermaid
sequenceDiagram
    autonumber
    actor U as Browser
    participant BE as backend
    participant KB as Kibana proxy
    participant ES as Elasticsearch
    participant LLM as LLM (Ollama | Mistral)

    U->>BE: POST /chat (Bearer token, question, image?, data_view, range)
    BE->>BE: require_session(token) -> {sid, user, provider}

    par Search (grounding) and Polish run concurrently
        alt question contains a document id
            BE->>KB: search id across ALL views, 30 days (sid cookie)
            KB->>ES: _search
            ES-->>KB: hits
            KB-->>BE: events  (+ title from open.overheid.nl)
        else generic question
            BE->>KB: recent logs + errors (selected view + window)
            Note over BE,KB: empty? escalate to ALL views over 24h
            KB->>ES: _search
            ES-->>KB: hits
            KB-->>BE: events
        end
    and
        BE->>LLM: polish_text(question)  (spelling/grammar, id-safe)
    end

    alt data found
        BE->>LLM: grounded prompt (facts only)
        LLM-->>BE: streamed tokens
        BE-->>U: SSE  question -> chunk... -> sources -> done
    else genuinely no data anywhere
        BE-->>U: SSE instant message (no LLM call)
    end
```

The answer is **streamed** over Server-Sent Events. The stream is guaranteed to
**never end empty** — if the model returns zero tokens, the backend emits a
clear "try again / switch model" message. See [[Runbook - No answer in chat]].

---

## 4. Chat request — decision logic

```mermaid
flowchart TD
    A["POST /chat"] --> B{"image attached?"}
    B -->|yes| C["OCR with Tesseract<br/>(off-thread, eng+nld)"]
    B -->|no| D["use typed text"]
    C --> E["combine text"]
    D --> E
    E --> F{"contains a doc id?<br/>(UUID or ronl-…)"}

    F -->|yes| G["trace id across ALL views, 30 days<br/>+ official title from portal"]
    F -->|no| H["search selected view + window"]
    H --> I{"found data?"}
    I -->|no| J["escalate: ALL views over 24h"]
    I -->|yes| K["build grounded context"]
    J --> L{"found data?"}
    L -->|no| M["instant actionable message<br/>(skip the slow LLM)"]
    L -->|yes| K
    G --> K

    K --> N["LLM stream (grounded prompt)"]
    N --> O{"model produced tokens?"}
    O -->|no| P["fallback message:<br/>'try again / switch AI model'"]
    O -->|yes| Q["streamed answer + sources"]

    classDef warn fill:#3a2418,stroke:#e3934d,color:#ffd9b0;
    class M,P warn;
```

See [[Chat pipeline]] for the code-level walkthrough.

---

## 5. Document trace flow

A document id is resolved into a full journey + an AI verdict. Same engine backs
the chat doc-id path and the **Documents** tab. See [[Document tracer]].

```mermaid
flowchart LR
    id["doc id<br/>(UUID / ronl-…)"] --> dv{"for each data view"}
    dv --> q["_search by id<br/>(wide window)"]
    q --> merge["merge + dedupe + sort<br/>(tolerate per-view failures)"]
    merge --> stages["group into per-service stages<br/>(events, errors, timing)"]

    id --> portal["open.overheid.nl API"]
    portal --> meta["official title, type,<br/>organization, status"]

    stages --> ui["Journey flow diagram<br/>(green = ok, red = error)"]
    meta --> ui
    stages --> ai["/document-trace/explain<br/>grounded LLM"]
    meta --> ai
    ai --> verdict["Verdict: HEALTHY /<br/>NEEDS ATTENTION"]
```

---

## 6. Deployment topology (Docker Compose)

```mermaid
flowchart TB
    subgraph host["Host (Windows / Docker Desktop)"]
        p3["localhost:3000"]:::port
        p8["localhost:8000"]:::port
        p11["localhost:11434"]:::port

        subgraph net["compose network (depends_on order)"]
            ol["ollama<br/>volume: ollama_data"]
            be["backend<br/>build ./backend<br/>env_file .env"]
            fe["frontend<br/>build ./frontend"]
        end
    end

    p3 --> fe
    p8 --> be
    p11 --> ol
    fe -->|depends_on| be
    be -->|depends_on| ol

    classDef port fill:#10243a,stroke:#2f6feb,color:#dbeafe;
```

- **Startup order:** `ollama` → `backend` → `frontend` (compose `depends_on`).
- **Backend image** installs `tesseract-ocr` (+ Dutch) at build for [[Chat pipeline|OCR]].
- **Config** comes from `.env` (git-ignored) via `env_file`; secrets such as
  `MISTRAL_API_KEY` never enter the image or git. See [[LLM providers]].
- `OLLAMA_BASE_URL` is overridden in compose to the in-network `http://ollama:11434`.

---

## 7. Backend modules (`backend/`)

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app; `/login`, `/chat`, `/health`, `/llm-provider`. See [[Chat pipeline]]. |
| `elastic.py` | Kibana proxy client, `keycloak_login`, search helpers, doc-id detection. |
| `llm.py` | Ollama + Mistral clients, streaming, `polish_text`, `provider_model`. See [[LLM providers]]. |
| `ocr.py` | Tesseract OCR for uploaded screenshots (offline, non-fatal). |
| `dashboard.py` · `monitoring.py` · `briefing.py` | Admin dashboard fact-layer + grounded triage. See [[Monitoring dashboard]]. |
| `documents.py` | Document activity feed + the tracer. See [[Document tracer]]. |
| `portal.py` | Official metadata from the [[open.overheid.nl API]]. |
| `config.py` · `cache.py` · `session.py` | Settings, TTL cache, token→session store. |

---

## 8. Security & resilience model

- **No direct ES access** — only via Kibana's authenticated console proxy.
- **Secrets** live in `.env` (git-ignored); the Mistral key is validated before
  it is ever saved (`set-mistral-key.ps1`).
- **Admin gating** via `DASHBOARD_ADMINS` allowlist (Keycloak group claims = phase-2).
- **Grounding** — the LLM narrates only facts computed from ES; it never invents
  numbers (enforced by strict system prompts in `briefing.py` / `llm.py`).
- **Graceful degradation** — per-view query failures are isolated; the chat never
  blanks; unreachable Kibana → friendly 503; portal/OCR/polish are best-effort.

## Data views (whitelist)

`logs-*`, `ds-prod5-koop-plooi*`, `ds-prod5-koop-sp`. The real KOOP pipeline logs
live in `ds-prod5-koop-plooi*`; `logs-*` ("All logs") is often nearly empty —
this matters for [[Runbook - No answer in chat]] and [[KOOP Plooi log schema]].
