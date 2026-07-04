---
title: Verwerkingsstraat queues (RabbitMQ)
tags: [rabbitmq, pipeline, beheer, nl]
component: [rabbitmq-queues, antivirus, document-harvester, documentopslag, export, indexatie, orchestratie]
purpose-business: Verwerkt binnenkomende publicatiedocumenten betrouwbaar en in volgorde.
purpose-technical: RabbitMQ-queues per verwerkingsstap; dead-letter-queues (*.dlq) vangen mislukte berichten op.
dependencies: [RabbitMQ, Documentopslag, Indexatie, Antivirus]
related: [Document lifecycle (pipeline), Dead-letter queues, Aanleverfouten]
risk: low
owner: KOOP Beheer
category: "Monitoring & signalen"
created: 2026-06-17
updated: 2026-06-17
---

# Verwerkingsstraat queues (RabbitMQ)

Terug naar [[Home]] · zie ook [[Document lifecycle (pipeline)]].

De verwerkingsstraat van KOOP Plooi bestaat uit een reeks **RabbitMQ-queues**, één
per stap. Een document stroomt van queue naar queue: **Antivirus → Document-Harvester
→ Documentopslag → Indexatie → Export**, met **Orchestratie** als regie. Elke queue
heeft een **dead-letter-queue** (`*.dlq`) die berichten opvangt die niet verwerkt
konden worden.

## Wat betekent een kaart?

- **0 / empty + ▶ 1 consumer** = gezond: geen vastgelopen berichten, er luistert een
  verwerker.
- **aantal > 0** = berichten staan vast in de dead-letter-queue (mislukte verwerking).
- **⛔ no consumer** = niemand verwerkt deze queue — werk blijft liggen (kritiek).

## TO DO

- [ ] Verbeter retry-afhandeling (exponential backoff per queue)
- [ ] Voeg queue-lag monitoring toe (ouderdom oudste bericht alerten)
- [ ] Review dead-letter routing (waarheen, en wie ruimt op)
- [x] Basismonitoring van DLQ-diepte via de Management API

## Configuratie & randgevallen

Zie `.env`: `RABBITMQ_*`. De monitor is read-only via de Management API en inert tot
`RABBITMQ_USER`/`RABBITMQ_PASSWORD` zijn gezet. Een DLQ op/boven
`RABBITMQ_CRITICAL_MESSAGES` (standaard 100) is kritiek.
