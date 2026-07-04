---
title: Aanleverfouten
tags: [aanlevering, beheer, nl]
component: aanleverfouten
purpose-business: Maakt zichtbaar welke documenten bij aanlevering zijn afgekeurd en nooit gepubliceerd.
purpose-technical: Detecteert afkeuringen in de logs, verzoent tegen open.overheid.nl en bewaart durende incidenten.
dependencies: [Aanleverloket, doculoket.overheid.nl, open.overheid.nl]
related: [Document lifecycle (pipeline), Verwerkingsstraat queues]
risk: medium
owner: KOOP Beheer
category: "Monitoring & signalen"
created: 2026-06-17
updated: 2026-06-17
---

# Aanleverfouten

Terug naar [[Home]].

Een **aanleverfout** is een document dat bij de aanlevering (doculoket) is **afgekeurd**
en daardoor **nooit op open.overheid.nl** komt. Het wordt in de logs gedetecteerd,
gegroepeerd per uitgever, en lost automatisch op zodra het gecorrigeerde document
alsnog gepubliceerd is.

## Betekenis van de kleuren

- **groen** ✓ = geen openstaande aanleverfouten — alles correct aangeleverd.
- **NIEUW** = sinds de vorige controle bijgekomen.
- **open** = bekend, nog niet hersteld.

## TO DO

- [ ] Automatische e-mail naar de uitgever bij een nieuwe aanleverfout
- [ ] Rapportage per uitgever (maandoverzicht)
- [ ] Drempel/alert bij meer dan N aanleverfouten in 24u

## Configuratie

Zie `.env`: `AANLEVER_*`. Detectie is structured-field-first met een stage+patroon
fallback.
