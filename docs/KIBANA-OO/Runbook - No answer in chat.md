---
title: Runbook — No answer in chat
tags: [runbook, troubleshooting]
---

# Runbook — "No matching data found" / no answer

Back to [[Home]]. Diagnoses the most common chat complaint.

## Symptom

The chat replies *"No matching data found for this time range."* (italic) or the
bubble stays blank, often after a long wait.

## Decode the message

That italic line is the **frontend's empty-content fallback** — it appears only
when the LLM streamed **zero tokens**. It does **not** necessarily mean ES had no
data. Three independent causes:

> [!tip]- Colour legend
> 🟦 check · 🟩 resolved · 🟧 workaround

```mermaid
flowchart TD
    S(["empty / 'No matching data'"]) --> A{selected view<br/>has data?}
    A -->|"logs-* is empty"| A1["use ds-prod5-koop-plooi*<br/>(auto-escalates anyway)"]
    A -->|yes| B{time window<br/>too narrow?}
    B -->|"Last 15 min"| B1["widen range<br/>(auto-escalates to 24h)"]
    B -->|no| C{model returned<br/>tokens?}
    C -->|no| C1["switch AI model<br/>(Ollama) and retry"]
    C -->|yes| OK(["answer"])
    A1 --> OK
    B1 --> OK
    C1 --> OK

    classDef ok fill:#10241c,stroke:#10b981,color:#bbf7d0;
    classDef warn fill:#3a2418,stroke:#e3934d,color:#ffd9b0;
    class OK ok;
    class A1,B1,C1 warn;
```

### 1. Wrong data view (empty index)
`logs-*` is often nearly empty; the real logs live in **`ds-prod5-koop-plooi*`**
(see [[KOOP Plooi log schema]]).
→ **Fixed:** generic questions auto-escalate to **all data views over 24h**.
→ **Tip:** select `KOOP Plooi (prod5)` explicitly for best results.

### 2. Narrow time window
"Last 15 min" may have no recent activity even in the right index.
→ **Fixed:** the escalation widens the window to 24h (`chat_widen_minutes`).

### 3. The LLM returned empty
A transient provider issue (or an over-strict refusal) can make the model emit
nothing. This is what caused the misleading "No matching data".
→ **Fixed:** the stream **never ends empty** — the user gets
"The AI model returned an empty response… try again, or switch the AI model."
→ **Workaround:** flip the [[LLM providers|header switcher]] to **Ollama** and retry.

## Quick checks (operator)

```bash
# Is the request reaching ES, and what view?
docker compose logs --tail=40 backend | grep "Question:"

# Is the backend healthy?
curl -s http://localhost:3000/health
```

## For a specific document

Paste/type its **id** (UUID or `ronl-…`) — the chat traces it across **every**
view over 30 days regardless of the selected view/window. See [[Document tracer]]
and [[Chat pipeline]].

## Related

- [[Chat pipeline]] · [[LLM providers]] · [[KOOP Plooi log schema]]
