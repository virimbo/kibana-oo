---
title: LLM providers
tags: [llm, ollama, mistral]
---

# LLM providers

Back to [[Home]]. `backend/llm.py`, `frontend/src/ProviderSwitcher.jsx`.

## Two providers, per-session switch

| Provider | Model (default) | Where it runs |
|---|---|---|
| **Ollama** | `llama3.2:3b` | Local container, CPU. Free, always available, slower on CPU. |
| **Mistral** | `mistral-large-latest` | Cloud (OpenAI-compatible API). Needs a valid `MISTRAL_API_KEY`. Faster, smarter. |

- The active provider is chosen per session and synced to the backend
  (`POST /llm-provider?provider=`). `llm._get_provider(session)` reads the session
  preference, else `settings.llm_provider` (env `LLM_PROVIDER`, default `ollama`).
- `llm.provider_model(session)` returns the `(provider, model)` shown in the UI.

> [!tip]- Colour legend
> 🟩 local (Ollama) · 🟧 cloud (Mistral)

```mermaid
flowchart LR
    req["chat / triage / explain"] --> g["_get_provider(session)"]
    g --> c{session<br/>preference?}
    c -->|set| use[use it]
    c -->|none| env["settings.llm_provider<br/>(env LLM_PROVIDER)"]
    env --> use
    use --> sw{provider}
    sw -->|ollama| ol["Ollama · llama3.2:3b<br/>local · CPU"]
    sw -->|mistral| mi["Mistral · large-latest<br/>cloud · API key"]

    classDef ok fill:#10241c,stroke:#10b981,color:#bbf7d0;
    classDef warn fill:#3a2418,stroke:#e3934d,color:#ffd9b0;
    class ol ok;
    class mi warn;
```

## The header switcher (every page)

A colour-coded pill in **every** header (Chat / Dashboard / Documents). The whole
header is themed via `data-provider` on `:root`:

- **Ollama → emerald**, **Mistral → amber**. Accent bar + pill + brand mark.

## Installing / rotating a Mistral key

Use the guarded installer (it tests the key against the live API and only saves
it if it returns HTTP 200):

```powershell
.\set-mistral-key.ps1
```

- Refuses to save on 401/403/429 and explains why.
- Writes `MISTRAL_API_KEY` into `.env` (git-ignored) and recreates the backend.
- A 401 means the key is wrong/revoked — not a billing throttle.

## Robustness

- Provider errors surface as friendly messages (`llm._llm_error_message`).
- The chat stream **never ends empty** even if a provider returns nothing — see
  [[Chat pipeline]] and [[Runbook - No answer in chat]].

## Related

- [[Chat pipeline]] · [[Monitoring dashboard]] · [[Architecture]]
