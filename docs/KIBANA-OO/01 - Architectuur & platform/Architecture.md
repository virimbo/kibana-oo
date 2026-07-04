---
title: Architecture
tags: [architecture]
aliases: [System Design, Arch]
category: "Architectuur & platform"
created: 2026-06-09
updated: 2026-06-09
---

# 🏗️ Architecture

Back to [[Home]]. A senior-level reference for how KIBANA-OO fits together —
container topology, the Kibana authorization handshake, the grounded chat/LLM
data flow, and the resilience model.

> [!abstract] At a glance
> A React SPA → FastAPI backend → **Kibana console proxy** (never raw
> Elasticsearch) using a Keycloak **OIDC `sid` cookie**. An LLM
> ([[LLM providers|Ollama or Mistral]]) narrates **only facts computed from ES**.
> Everything ships as three Docker containers.

> [!tip]- Diagram colour legend
> 🟦 our services · ⬜ external systems · 🟪 LLM · 🟥 security/auth · 🟧 fallback/degraded path

---

## 1 · System context

How the containers and external systems connect, and the one rule that shapes
everything: **all data access is mediated by Kibana**.

```mermaid
flowchart LR
    user(["👤 Admin / user<br/>browser"])

    subgraph compose["🐳 Docker Compose — private bridge network"]
        direction TB
        fe["frontend<br/>nginx · :3000<br/>SPA + reverse proxy"]
        be["backend<br/>FastAPI · :8000"]
        ol["ollama · :11434<br/>llama3.2:3b (CPU)"]
    end

    subgraph ext["☁️ External systems"]
        direction TB
        kc["Keycloak<br/>OIDC IdP"]
        kb["Kibana<br/>console proxy"]
        es[("Elasticsearch<br/>logs · APM · metrics")]
        mi["Mistral API<br/>cloud LLM"]
        ov["open.overheid.nl<br/>openbaarmakingen API"]
    end

    user -->|HTTPS :3000| fe
    fe -->|"/login · /chat · /dashboard/*"| be
    be -->|OIDC login| kc
    be -->|"_search · sid cookie"| kb --> es
    be -->|/api/chat| ol
    be -->|"chat/completions · Bearer key"| mi
    be -->|title · metadata| ov

    classDef app fill:#0f243d,stroke:#2f6feb,stroke-width:1.5px,color:#dbeafe;
    classDef ext fill:#1b222e,stroke:#3a4659,color:#cbd5e1;
    classDef llm fill:#241a3a,stroke:#8b5cf6,color:#e9d5ff;
    classDef sec fill:#3a1d1d,stroke:#ef4444,color:#fecaca;
    classDef cli fill:#10241c,stroke:#10b981,color:#bbf7d0;
    class fe,be cli;
    class ol,mi llm;
    class kb,es,ov ext;
    class kc sec;
```

> [!warning] Hard invariant
> The backend **never** talks to Elasticsearch directly — every query traverses
> Kibana's `/api/console/proxy` carrying the user's `sid`. This keeps Kibana's
> RBAC, spaces, and audit in force. The LLM only ever receives **facts already
> computed from ES** ([[Monitoring dashboard|grounding]]).

---

## 2 · Authentication — Keycloak OIDC handshake

`POST /login` trades credentials for a Kibana `sid` cookie, then issues an opaque
session token to the browser. **The `sid` never leaves the server.**

```mermaid
sequenceDiagram
    autonumber
    actor U as Browser
    participant BE as backend
    participant KB as Kibana
    participant KC as Keycloak

    U->>BE: POST /login {username, password}
    BE->>KB: POST /internal/security/login (start OIDC)
    KB-->>BE: { location: Keycloak auth URL }
    BE->>KC: GET auth form
    KC-->>BE: HTML form (action URL)
    BE->>KC: POST credentials
    alt invalid credentials
        KC-->>BE: 200 form + error
        BE-->>U: 401 invalid username or password
    else success
        KC-->>BE: 302 callback
        BE->>KB: GET callback
        KB-->>BE: Set-Cookie sid
        BE->>BE: create_session(user, sid) → token
        BE-->>U: 200 { token, username }
    end
    Note over U,BE: token → sessionStorage · sid → server-side session store
```

> [!info] Failure handling
> Kibana unreachable (VPN down / DNS) → a friendly **503** ("connect to the
> company network or VPN"), never a raw stack trace. See
> [[Runbook - No answer in chat]].

---

## 3 · Authorization + the grounded chat flow

Every protected call carries `Authorization: Bearer <token>`. `require_session`
resolves it to `{sid, username, llm_provider}`; admin routes additionally check
the `DASHBOARD_ADMINS` allowlist. The search and the grammar-polish run **in
parallel**, so correction adds ~no latency.

```mermaid
sequenceDiagram
    autonumber
    actor U as Browser
    participant BE as backend
    participant KB as Kibana proxy
    participant ES as Elasticsearch
    participant LLM as LLM (Ollama·Mistral)

    U->>BE: POST /chat (Bearer, question, image?, view, range)
    BE->>BE: require_session → {sid, user, provider}

    par grounding (search) ∥ polish
        alt question names a document id
            BE->>KB: trace id · ALL views · 30 days (sid)
            KB->>ES: _search
            ES-->>KB: events
            KB-->>BE: events  (+ title via open.overheid.nl)
        else generic question
            BE->>KB: recent logs + errors (selected view)
            Note over BE,KB: empty? → escalate: ALL views · 24h
            KB->>ES: _search
            ES-->>KB: events
            KB-->>BE: events
        end
    and
        BE->>LLM: polish_text(question) — id-safe
    end

    alt data found
        BE->>LLM: grounded prompt (facts only)
        LLM-->>BE: streamed tokens
        BE-->>U: SSE  question → chunk… → sources → done
    else no data anywhere
        BE-->>U: SSE instant message (LLM skipped — fast)
    end
```

---

## 4 · Chat request — decision logic

```mermaid
flowchart TD
    A([POST /chat]) --> B{image<br/>attached?}
    B -->|yes| C["OCR · Tesseract<br/>off-thread · eng+nld"]
    B -->|no| D[use typed text]
    C --> E[combine text]
    D --> E
    E --> F{contains a<br/>doc id?}

    F -->|yes| G["trace id · ALL views · 30d<br/>+ official title"]
    F -->|no| H[search selected view + window]
    H --> I{found?}
    I -->|no| J["escalate · ALL views · 24h"]
    I -->|yes| K[build grounded context]
    J --> L{found?}
    L -->|no| M["⚡ instant message<br/>LLM skipped"]
    L -->|yes| K
    G --> K

    K --> N[LLM stream · grounded]
    N --> O{tokens<br/>produced?}
    O -->|no| P["fallback:<br/>try again / switch model"]
    O -->|yes| Q[[streamed answer + sources]]

    classDef warn fill:#3a2418,stroke:#e3934d,color:#ffd9b0;
    classDef ok fill:#10241c,stroke:#10b981,color:#bbf7d0;
    class M,P warn;
    class Q ok;
```

See [[Chat pipeline]] for the code-level walkthrough.

---

## 5 · Resilience — the chat never dead-ends

Every branch terminates in a **useful answer**: real data, an instant guide, or
an honest "model returned empty" — never a blank bubble or a hung spinner.

```mermaid
stateDiagram-v2
    [*] --> Searching
    Searching --> Selected_view
    Selected_view --> Escalated: empty
    Selected_view --> Generating: data
    Escalated --> Generating: data
    Escalated --> Instant: still empty
    Generating --> Answer: tokens
    Generating --> EmptyGuard: zero tokens
    EmptyGuard --> Answer: try again or switch model
    Instant --> Answer: actionable guidance
    Answer --> [*]

    note right of Instant
        no LLM call → instant
    end note
    note right of EmptyGuard
        guarantees a non-empty stream
    end note
```

---

## 6 · Document trace flow

A document id becomes a full journey + an AI verdict. The same engine backs the
chat doc-id path and the **Documents** tab. See [[Document tracer]].

```mermaid
flowchart LR
    id["doc id<br/>UUID · ronl-…"] --> dv{{for each<br/>data view}}
    dv --> q["_search by id<br/>wide window"]
    q --> merge["merge · dedupe · sort<br/>tolerate per-view failures"]
    merge --> stages["per-service stages<br/>events · errors · timing"]

    id --> portal[["open.overheid.nl API"]]
    portal --> meta["title · type · org · status"]

    stages --> ui["🟢/🔴 Journey diagram"]
    meta --> ui
    stages --> ai["/document-trace/explain<br/>grounded LLM"]
    meta --> ai
    ai --> verdict["Verdict: HEALTHY /<br/>NEEDS ATTENTION"]

    classDef ext fill:#1b222e,stroke:#3a4659,color:#cbd5e1;
    class portal ext;
```

---

## 7 · Admin dashboard — grounded triage

The dashboard computes a deterministic **fact snapshot**, then the LLM *narrates*
it. The model never produces numbers — only prose around facts. See
[[Monitoring dashboard]].

```mermaid
flowchart LR
    snap["build_snapshot()<br/>criticals · 5xx · APM · deltas"] --> facts[/"strict JSON facts"/]
    facts --> llm["LLM (grounded prompt)"]
    llm --> brief["plain-language briefing"]
    snap --> cards["KPI cards · timeline ·<br/>cert-expiry · NVS pipeline"]

    classDef llm fill:#241a3a,stroke:#8b5cf6,color:#e9d5ff;
    class llm llm;
```

---

## 8 · Deployment topology (Docker Compose)

```mermaid
flowchart TB
    subgraph host["🖥️ Host · Docker Desktop"]
        p3([":3000"]):::port
        p8([":8000"]):::port
        p11([":11434"]):::port

        subgraph net["compose network · startup order →"]
            direction LR
            ol["ollama<br/>vol: ollama_data"]
            be["backend<br/>build ./backend<br/>env_file .env<br/>+ tesseract-ocr"]
            fe["frontend<br/>build ./frontend"]
        end
    end

    p3 --> fe -->|depends_on| be -->|depends_on| ol
    p8 --> be
    p11 --> ol

    classDef port fill:#0f243d,stroke:#2f6feb,color:#dbeafe;
```

- **Startup order:** `ollama` → `backend` → `frontend` (`depends_on`).
- **Config** from `.env` (git-ignored) via `env_file`; secrets like
  `MISTRAL_API_KEY` never enter the image or git ([[LLM providers]]).
- `OLLAMA_BASE_URL` is overridden to the in-network `http://ollama:11434`.

---

## 9 · Quality attributes (the "SaaS" bar)

| Attribute | How it's met |
|---|---|
| 🔐 **Security** | No direct ES; Kibana RBAC preserved; secrets in git-ignored `.env`; Mistral key validated before save; admin allowlist. |
| 🎯 **Correctness** | LLM is **grounded** — narrates only ES-computed facts; strict system prompts forbid inventing numbers. |
| ⚡ **Performance** | Concurrent search ∥ polish; doc traces fan out in parallel; **empty results answer instantly** (no LLM). |
| 🛡️ **Reliability** | Per-view failure isolation; chat stream never ends empty; unreachable Kibana → friendly 503; OCR/portal/polish are best-effort. |
| 🔄 **Flexibility** | Per-session LLM switch (Ollama ⇄ Mistral) themed into every header. |
| 🔍 **Observability** | Structured request logs (`[user] [view] Question … doc_ids=…`); `/health` reports model + provider. |

---

## 10 · Backend modules (`backend/`)

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app; `/login`, `/chat`, `/health`, `/llm-provider`. See [[Chat pipeline]]. |
| `elastic.py` | Kibana proxy client, `keycloak_login`, search helpers, doc-id detection. |
| `llm.py` | Ollama + Mistral clients, streaming, `polish_text`, `provider_model`. See [[LLM providers]]. |
| `ocr.py` | Tesseract OCR for uploaded screenshots (offline, non-fatal). |
| `dashboard.py` · `monitoring.py` · `briefing.py` | Dashboard fact-layer + grounded triage. See [[Monitoring dashboard]]. |
| `documents.py` | Document activity feed + the tracer. See [[Document tracer]]. |
| `portal.py` | Official metadata from the [[open.overheid.nl API]]. |
| `config.py` · `cache.py` · `session.py` | Settings, TTL cache, token→session store. |

## Data views (whitelist)

`logs-*`, `ds-prod5-koop-plooi*`, `ds-prod5-koop-sp`. The real KOOP pipeline logs
live in `ds-prod5-koop-plooi*`; `logs-*` ("All logs") is often nearly empty —
this matters for [[Runbook - No answer in chat]] and [[KOOP Plooi log schema]].
