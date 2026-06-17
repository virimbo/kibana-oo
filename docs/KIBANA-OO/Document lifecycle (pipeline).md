---
title: Document lifecycle — the canonical pipeline
tags: [architecture, pipeline, spec, reference]
aliases: [Lifecycle, Canonical pipeline, Pipeline stages]
component: documents-pipeline
purpose-business: Bewaakt of publicatiedocumenten daadwerkelijk live komen op open.overheid.nl.
purpose-technical: Volgt elk document door de verwerkingsstraat (NVS/OVS) en classificeert de gezondheid per fase.
dependencies: [Aanleverloket, RabbitMQ, Documentopslag, Indexatie, open.overheid.nl]
related: [Verwerkingsstraat queues, Aanleverfouten]
risk: medium
owner: KOOP Beheer
---

# 🧭 Document lifecycle — the canonical pipeline

Back to [[Home]]. **The single source of truth** for "where is my document and is
it healthy". The same model drives the **dashboard journey**, this **architecture
doc**, and the **health classification** — so they can never drift apart (the 1-1
guarantee). Mirrored in code: `backend/pipeline.py`.

> [!abstract] Why this exists
> Raw logs are cryptic and per-service. An admin needs one plain answer:
> **how far did this document get, is it healthy, and is it stuck?** This model
> turns dozens of log lines into a simple, ordered story.

---

## The stages (in order)

```mermaid
flowchart LR
    s1["📥 Intake"] --> s2["🗄️ Storage"] --> s3["🛡️ Virus scan"] --> s4["⚙️ Processing"]
    s4 --> s5["📣 Publication"] --> s6["🔎 Indexing"] --> s7["📤 Export"] --> s8["🌐 Live"]
    classDef live fill:#241a3a,stroke:#8b5cf6,color:#e9d5ff;
    class s8 live;
```

| # | Stage | Plain meaning | Log service(s) |
|---|---|---|---|
| 1 | **📥 Intake** | Received at the front desk | `msvc-doculoket`, `gateway-service` |
| 2 | **🗄️ Storage** | Stored safely | `msvc-documentopslag`, `…storageaccess` |
| 3 | **🛡️ Virus scan** | Checked for viruses | `antivirus*` |
| 4 | **⚙️ Processing** | Processing coordinated | `…orkestratie`, `verwerking*` |
| 5 | **📣 Publication** | Marked for publication | `msvc-publicatiebeheer` |
| 6 | **🔎 Indexing** | Made searchable | `msvc-indexatie`, `solr` |
| 7 | **📤 Export** | Exported downstream | `msvc-export`, `…dpc` |
| 8 | **🌐 Live** | Searchable on open.overheid.nl | `zoekportaal`, `search` |

This mirrors the **NVS** path in [[Woo platform]]. Stage 8 is **terminal** — a
document that reaches it is *done*.

---

## Per-stage status (honest health)

Each stage is coloured by what actually happened in its log events:

- 🟢 **OK** — reached, no problems
- 🟠 **Warning** — reached, but the messages contain trouble (404, *connection
  reset*, *broken pipe*, timeout, refused…)
- 🔴 **Problem** — a real error/failure
- ⬜ **Not reached** — no events for this stage yet
- 🔵 **Current** — the furthest stage reached (where the document is *now*)

> [!warning] Why "no errors" was wrong before
> The old check only read the log **level**. Messages like `404 NOT_FOUND`,
> `Connection reset by peer` and `Broken pipe` are logged at INFO level, so they
> showed as green "ok". The lifecycle reads the **message** too, so a stage with
> 12× *connection reset* now honestly shows 🟠 — with a plain explanation.

### Message → plain language

| Log message | What it means |
|---|---|
| `404 NOT_FOUND … openbaarmakingen/api…` | A lookup returned "not found" — often a routine probe to the public API. |
| `Connection reset by peer` | The service briefly lost its link to another service and retried. Fine if rare, worrying if it repeats. |
| `Broken pipe` | A data transfer was cut off part-way. |
| `timeout` | A step took too long. |
| `connection refused` | Another service rejected the connection. |
| `null` | An empty value — usually harmless on its own. |

---

## "Stuck" detection

- Each stage records how long the document spent in it (**first → last**).
- If the furthest stage is **not** the terminal stage **and** there's been no
  activity for a while, the document is flagged **🕒 appears stuck at &lt;stage&gt;**.
- A stage that lingered beyond a threshold is flagged **slow**.

---

## The verdict (one line for the admin)

The tracer rolls all of this into a single, plain headline:

- ✅ **Healthy & complete** — reached Live, no problems
- ⚠️ **Completed with warnings** — reached Live, but had hiccups (with counts)
- ⏳ **In progress** — still moving through the pipeline
- 🕒 **Appears stuck** — hasn't progressed for a while, not yet Live
- ⛔ **Problem** — a real failure occurred

## Related

- [[Woo platform]] · [[Document tracer]] · [[Monitoring dashboard]] · [[KOOP Plooi log schema]] · [[Architecture]]
