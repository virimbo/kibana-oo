---
title: Woo Gateway — the front door (auth & delivery APIs)
tags: [architecture, koop, woo, gateway, security, reference]
aliases: [Gateway, API Gateway, IAM, OAS, CAM]
---

# 🚪 Woo Gateway — the front door

Back to [[Home]] · part of the [[Woo platform]].

> [!abstract] In one sentence
> The **Gateway** is the platform's **secure reception desk**: every document
> delivery and every public lookup passes through it, it **checks who's allowed
> in**, and it **routes** the traffic to the right place. Nothing reaches the
> intake or the processing pipeline without going through here first.

> [!note] About the names (best-effort)
> - **OAS** — *OpenAPI Specification*: the published "contract" for the delivery
>   API (so other systems know exactly how to hand documents over). "OAS 1.2" and
>   "OAS Web" are two flavours of that delivery door.
> - **IAM** — *Identity & Access Management*: login, tokens and permissions.
> - **CAM** — a **shared KOOP access/authentication service** (a *generic*
>   service reused across KOOP). Exact expansion uncertain; its role — shared
>   access/auth — is clear from the architecture.

---

## 1 · How a delivery comes in

```mermaid
flowchart TB
    sysA["Automatic delivery<br/>Automatische aanlevering"]
    sysB["Automatic retrieval<br/>Automatisch ophalen"]
    rijks["Rijksoverheid.nl systems<br/>(SCP · public-key auth)"]
    citizen(["👤 Public<br/>consults documents"])

    subgraph GW["Woo Gateway — the front door"]
        direction TB
        oas["OAS 1.2 / OAS Web<br/>standard delivery APIs"]
        api["API Gateway<br/>single entry point + routing"]
        iam["IAM<br/>identity & access"]
        cam["CAM<br/>shared KOOP access service"]
    end

    docu["DocuLoket<br/>(intake)"]
    portal["open.overheid.nl<br/>(public website)"]

    sysA --> oas
    sysB --> oas
    rijks --> api
    oas --> api
    api <--> iam
    api <--> cam
    api --> docu
    citizen --> portal

    classDef gw fill:#0f243d,stroke:#2f6feb,color:#dbeafe;
    classDef sec fill:#3a1d1d,stroke:#ef4444,color:#fecaca;
    classDef pub fill:#241a3a,stroke:#8b5cf6,color:#e9d5ff;
    class oas,api gw;
    class iam,cam sec;
    class portal,citizen pub;
```

Delivering systems knock on a **standard door** (OAS), the **API Gateway** is the
single point that takes every call, the call is **checked** against **IAM/CAM**,
and only then is it **forwarded to [[Woo platform|DocuLoket]]** for intake.

---

## 2 · An authenticated delivery, step by step

```mermaid
sequenceDiagram
    autonumber
    participant S as Delivering system
    participant GW as API Gateway
    participant IAM as IAM / CAM
    participant DL as DocuLoket

    S->>GW: deliver document (+ key / token)
    GW->>IAM: is this caller allowed?
    alt not authorised
        IAM-->>GW: denied
        GW-->>S: 401 / 403 rejected
    else authorised
        IAM-->>GW: ok
        GW->>DL: forward the document
        DL-->>GW: accepted
        GW-->>S: 200 received
    end
```

---

## 3 · The pieces, in plain words

**OAS 1.2 / OAS Web (the delivery doors).** A **published API contract** — like a
clearly labelled mail slot with instructions, so any approved system knows exactly
how to hand a document over. "Web" is the browser-friendly variant.

**API Gateway (the single entry point).** Every request goes through *one* door.
That makes it the natural place to **route** traffic, enforce rules, and keep an
eye on everything — instead of dozens of unguarded back doors.

**IAM (identity & access).** Decides **who** may do **what** — issues/validates
tokens and checks permissions. (In [[Architecture|KIBANA-OO]] the equivalent is
Keycloak OIDC + the `sid` cookie.)

**CAM (shared KOOP access service).** A **generic, reused** KOOP service the
Gateway leans on for access/authentication — so each platform doesn't reinvent it.

**SCP with public-key authentication.** A separate, hardened **file-transfer**
channel (secure copy) used with Rijksoverheid.nl systems — authenticated with
**public keys** instead of passwords.

**open.overheid.nl.** The **public** side reached *through* the gateway layer for
the [[Woo platform|Raadplegen]] (consult) function — where citizens read documents.

---

## 4 · Why have a gateway at all? (the "so what")

- **One guarded door, not many.** A single entry point means **one** place to
  authenticate, authorise, rate-limit, log and monitor — far safer than each
  service exposing its own endpoint.
- **Separation of concerns.** Delivery systems only need to know the **OAS
  contract**; they don't touch the pipeline directly.
- **Defence in depth.** IAM/CAM + public-key SCP mean a document only reaches
  intake after the **caller is proven trustworthy**.

> [!tip] Same pattern, smaller scale
> KIBANA-OO uses the exact same idea: the browser talks to **one** backend, which
> authenticates via **Keycloak** and reaches data only through the **Kibana
> console proxy** — never the database directly. See [[Architecture]] §2–3.

---

## 5 · Glossary (Gateway terms)

| Dutch / term | Plain meaning |
|---|---|
| **Gateway** | Single secure entry point for all traffic |
| **Generieke Woo functionaliteit** | Generic/shared Woo functionality (reused building blocks) |
| **OAS** | *OpenAPI Specification* — the published delivery-API contract |
| **API Gateway** | Routes and secures every API call through one door |
| **IAM** | *Identity & Access Management* — login, tokens, permissions |
| **CAM** | Shared KOOP access/authentication service (best-effort) |
| **SCP op basis van public-key authenticatie** | Secure file copy (SCP) authenticated with public keys |
| **Aanlevering** | Delivery / intake of documents |
| **Raadplegen** | Consult / search (the public side) |

---

## 6 · Where it sits in the platform

```mermaid
flowchart LR
    in["Delivering systems"] --> gw["🚪 Gateway<br/>(OAS · API GW · IAM · CAM)"]
    gw --> intake["📥 Aanlevering<br/>(DocuLoket)"]
    intake --> proc["⚙️ Verwerking<br/>(OVS / NVS)"]
    proc --> search["🔎 Raadplegen"]
    search --> oo["🌐 open.overheid.nl"]

    classDef gw fill:#0f243d,stroke:#2f6feb,color:#dbeafe;
    classDef pub fill:#241a3a,stroke:#8b5cf6,color:#e9d5ff;
    class gw gw;
    class oo pub;
```

The Gateway is **step 0** of the [[Woo platform|whole journey]] — everything
downstream ([[Document tracer|the pipeline KIBANA-OO traces]]) only happens after
a delivery clears this front door.

## Related

- [[Woo platform]] · [[ROO - Applicatieketen]] · [[Architecture]] · [[Document tracer]] · [[Home]]
