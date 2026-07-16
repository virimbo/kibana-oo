---
title: "HTTP-fouten en latency (PROD)"
category: "Monitoring & signalen"
created: 2026-07-16
updated: 2026-07-16
tags: [kibana-oo, monitoring, http, 5xx, latency, gateway, pods, prod, beheer, nl]
aliases: [Edge health, Ingress health, HTTP 5xx, Gateway errors, Latency, Pod restarts]
---

# HTTP-fouten & latency (PROD)

> Dashboard-kaart die de **voordeur** van PROD bewaakt: gaan er requests mis
> (5xx), zijn er **gateway-fouten** (502/503/504), **time-outs** (504), loopt de
> **latency** op, en zijn er **pod-restarts**? Alles in één oogopslag, met
> kleuren. Gerelateerd: [[Service health]], [[Beschikbaarheid (uptime)]],
> [[Observability]], [[Monitoring targets]].

## Wat & waarom

Als de ingress/gateway van PROD fouten geeft of traag wordt, merkt de burger dat
direct (pagina's laden niet, zoeken hapert). Deze kaart maakt dat **proactief**
zichtbaar door de **ingress-access-logs** samen te vatten over een kort venster
(standaard 15 min), plus — indien beschikbaar — pod-restarts uit Prometheus.

Vijf tegels:

| Tegel | Wat | Bron |
|---|---|---|
| **HTTP 5xx-fouten** | aantal + **percentage** 5xx (500/502/503/504) | ingress-logs (`status`) |
| **Gateway-fouten** | 502 + 503 + 504 samen | idem |
| **Time-outs** | 504 apart | idem |
| **Latency (p95)** | 95-percentiel reactietijd (ms) | ingress-logs (`request_time`) |
| **Pod restarts (1u)** | herstarts laatste uur | **Prometheus** (best-effort) |

## Hoe te gebruiken

- Ga naar **Monitoring** (het dashboard). De kaart **"HTTP-fouten & latency"**
  staat tussen Service health en de Monitoring-targets.
- De kaart **ververst elke minuut** en toont bovenin een **totaalstatus**
  (OK / WAARSCHUWING / KRITIEK) plus het aantal requests in het venster.
- Elke tegel heeft een eigen kleur; bij een probleem zie je meteen **welk** type
  fout en **hoeveel**.

## Een echt voorbeeld

- Normaal: **OK** — bijv. `5xx: 0.1% (3/4.200)`, `Gateway: 0`, `Time-outs: 0`,
  `Latency p95: 210 ms`, `Pod restarts: 0`.
- Een backend valt om → 502/503 stijgen: tegel **Gateway-fouten** wordt oranje/rood
  (`28`), **HTTP 5xx** springt naar `2.4%`, totaalstatus **KRITIEK**.
- Upstream reageert traag → **Time-outs (504)** loopt op en **Latency p95** gaat
  naar `3.500 ms` (rood).
- Een pod crasht in een lus → **Pod restarts (1u)** toont `9` (rood).

## Betekenis van de kleuren & drempels

- 🟢 **OK** · 🟡 **Waarschuwing** · 🔴 **Kritiek** · ⚪ **Onbekend** (geen data / bron
  onbereikbaar). De totaalstatus = de **zwaarste** tegel.
- Standaard­drempels (instelbaar in `.env`):
  - **5xx-ratio:** waarschuwing ≥ `1%`, kritiek ≥ `5%` — pas berekend vanaf
    `EDGE_MIN_REQUESTS` (50) requests, zodat een paar fouten bij weinig verkeer
    geen vals alarm geven.
  - **Gateway / time-outs:** waarschuwing ≥ `1`, kritiek ≥ `20` in het venster.
  - **Latency p95:** waarschuwing ≥ `1.000 ms`, kritiek ≥ `3.000 ms`.
  - **Pod restarts:** waarschuwing ≥ `1`, kritiek ≥ `5` (laatste uur).

## Configuratie & randgevallen

- **Instellingen** (`.env` / `config.py`, prefix `EDGE_`): `EDGE_ENABLED`,
  `EDGE_DATA_VIEW` (default `ds-prod5-koop-plooi*`), `EDGE_WINDOW_MINUTES`,
  `EDGE_5XX_RATIO_WARN/CRIT`, `EDGE_GATEWAY_WARN/CRIT`,
  `EDGE_LATENCY_WARN_MS/CRIT_MS`, `EDGE_MIN_REQUESTS`,
  `EDGE_PXX…` en `EDGE_POD_RESTART_QUERY`.
- **Latency-tegel "onbekend"?** Dan is het latency-veld (`request_time`) in de
  index niet numeriek gemapt; pas `EDGE_LATENCY_FIELD` aan (bijv.
  `upstream_response_time`).
- **Pod restarts "n.v.t."?** Er is (nog) **geen Prometheus-connection**
  geconfigureerd (zie [[Monitoring targets]]). Zodra die er is, vult de tegel
  zich; anders blijft hij grijs — de rest van de kaart werkt gewoon.
- **Read-only & veilig:** de kaart leest alleen (via de Kibana-proxy met de
  sessie van de beheerder); schrijft niets. Valt een bron weg, dan wordt de tegel
  **onbekend** in plaats van dat de kaart crasht.
- **Verificatie:** de tegels 5xx/gateway/time-outs/latency komen uit de
  ingress-logs; controleer bij ingebruikname eenmalig de veldnamen (`status`,
  `request_time`) en stem de drempels af op het echte verkeer van PROD.
