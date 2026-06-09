---
title: KOOP Plooi log schema
tags: [elasticsearch, schema, koop]
---

# KOOP Plooi log schema

Back to [[Home]]. The single most important "gotcha" for this project.

## The logs are NOT ECS

KOOP Plooi logs are **logback / Logstash JSON**, not Elastic Common Schema:

- `level` — UPPERCASE (`INFO`, `WARN`, `ERROR`) at the **top level** (not `log.level`).
- `message` — the free-text line.
- `logger_name`, `kubernetes.*` — infra fields (excluded from document extraction).
- The **document id** is often embedded *inside the message* (e.g. a `ronl-…`
  path, or a UUID), not in a dedicated field.

Queries therefore check **both** `level` and `log.level`, and free-text search is
unreliable for structured questions.

## Services seen in the pipeline

`msvc-doculoket`, `msvc-documentopslag`, `msvc-indexatie`, `msvc-publicatiebeheer`,
`msvc-export`, `service.StorageAccess`, `search`, `solr`, `gateway-service`,
`zoekportaal`, `controller`, `app`.

## Where the data lives

> [!tip]- Colour legend
> 🟩 has data · 🟥 usually empty

```mermaid
flowchart LR
    q["chat / dashboard query"] --> dv{data view}
    dv -->|"ds-prod5-koop-plooi*"| good[("real pipeline logs<br/>(269+ events / doc)")]
    dv -->|"logs-* — All logs"| bad[("nearly empty<br/>→ 'No matching data'")]
    dv -->|"ds-prod5-koop-sp"| sp[("search-portal logs")]

    classDef ok fill:#10241c,stroke:#10b981,color:#bbf7d0;
    classDef err fill:#3a1d1d,stroke:#ef4444,color:#fecaca;
    class good,sp ok;
    class bad err;
```

- Real pipeline logs: **`ds-prod5-koop-plooi*`**.
- `logs-*` ("All logs") is often **nearly empty** — selecting it is the usual
  cause of an empty chat result. See [[Runbook - No answer in chat]].

## Document title is not in the logs

The official title must be fetched from the [[open.overheid.nl API]].

## Related

- [[Document tracer]] · [[Chat pipeline]] · [[open.overheid.nl API]]
