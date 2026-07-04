---
title: Monitoring dashboard
tags: [dashboard, admin]
category: "Monitoring & signalen"
created: 2026-06-09
updated: 2026-06-27
---

# Monitoring dashboard

Back to [[Home]]. Admin-only (`DASHBOARD_ADMINS`). `frontend/src/Dashboard.jsx`,
`backend/dashboard.py` + `monitoring.py` + `briefing.py`. Endpoints cached.

> 🧠 Hoe werkt de AI hier? Zie [[AI-architectuur]] — RAG + achtergrond-monitors,
> géén agents/sub-agents/MCP, plus de EU AI Act / AVG privacy-posture.

## Panels

- **Critical issues** = error logs + HTTP 5xx + APM errors, with a per-data-view
  breakdown and a delta vs the prior equal period. Rolling **Period**
  (15/30/60/360/1440 min) + **Data view** selectors.
- **Grounded AI triage** (`/dashboard/briefing`) — the LLM narrates the exact ES
  facts from the snapshot; it never invents numbers. See [[LLM providers]].
- **Certificate-expiry countdown cards** — TLS expiry read from Kibana monitoring
  data (Heartbeat/Synthetics, `tls.server.x509.not_after`), **not** by probing URLs.
- **Verwerkingsstraat — NVS** panel — documents processed via the new pipeline
  (NVS). OVS is not present in this data (earlier OVS matches were filename
  false-positives), so the panel is NVS-only.

## Fact flow (grounded triage)

> [!tip]- Colour legend
> 🟦 deterministic facts · 🟪 LLM narration

```mermaid
flowchart LR
    es[("Elasticsearch")] --> snap["build_snapshot()<br/>criticals · 5xx · APM · deltas"]
    snap --> facts[/"strict JSON facts"/]
    facts --> llm["LLM · grounded prompt"]
    llm --> brief["plain-language briefing"]
    snap --> cards["KPI cards · timeline ·<br/>cert-expiry · NVS pipeline"]

    classDef llm fill:#241a3a,stroke:#8b5cf6,color:#e9d5ff;
    classDef ext fill:#1b222e,stroke:#3a4659,color:#cbd5e1;
    class llm llm;
    class es ext;
```

## Design principles

- Deterministic **fact layer** (`monitoring.build_snapshot`) → strict facts →
  the LLM only narrates. Same snapshot feeds the numbers and the briefing.
- Graceful degradation: a failing data view is isolated; the snapshot is marked
  `partial` rather than failing the whole page.

## Related

- [[Document tracer]] · [[KOOP Plooi log schema]] · [[Architecture]]
