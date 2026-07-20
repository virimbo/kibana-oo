---
title: Pipeline outcomes
tags: [dashboard, pipeline, beheer, nl]
component: outcomes
purpose-business: Laat zien wat er met documenten gebeurde: gepubliceerd, bijgewerkt, ingetrokken of mislukt.
purpose-technical: Aggregatie per uitkomst en per pijplijn (NVS/OVS), met publicatie-succespercentage en latency.
dependencies: [Elasticsearch, open.overheid.nl]
related: [Document lifecycle (pipeline), Dashboard - statusoverzicht]
risk: low
owner: KOOP Beheer
category: "Monitoring & signalen"
created: 2026-06-17
updated: 2026-07-16
---

# Pipeline outcomes

Terug naar [[Home]].

Toont per venster hoeveel documenten **gepubliceerd**, **bijgewerkt**, **ingetrokken**
of **mislukt** zijn, gesplitst per verwerkingsstraat (NVS/OVS), plus het
**publicatie-succespercentage** en de tijd-tot-publicatie (p50/p95).

## Betekenis van de cijfers

- **success rate ≥ 95%** = groen, **80–95%** = oranje, **< 80%** = rood.
- "Failed" wordt verzoend tegen open.overheid.nl: een document dat tóch live is, telt
  nooit als mislukking.

## NVS vs OVS — beide zichtbaar (OVS = 0 op dit platform)

De uitkomsten worden per **verwerkingsstraat** getoond: **NVS** (nieuwe) en
**OVS** (oude). Elke tegel toont nu **altijd beide** (bijv. `NVS 25 · OVS 0`),
zodat OVS nooit stilletjes verborgen is.

**Analyse (2026-07-16):** de pijplijn-cluster draait **14 services, allemaal NVS**
(`msvc-*`, `aanleverloket-v2`, `zoekportaal`, `gateway-service`) — er is **geen**
OVS-/"oude"-/`-v1`-service. Nul precieze OVS-documentgebeurtenissen in 7 dagen.
Conclusie: de **oude verwerkingsstraat (OVS) is uitgefaseerd**; het platform draait
volledig op **NVS**. `OVS = 0` is dus de **echte** waarde, geen meetfout.

> Zodra er tóch OVS-verkeer verschijnt (een document dat via de oude straat wordt
> geclassificeerd), telt het hier direct mee. Draait de oude straat in een apart
> systeem/index? Stel dan `PIPELINE_OVS_INDEX` / `PIPELINE_OVS_VALUES` /
> `PIPELINE_NVS_CUTOFF_DATE` in (`config.py`) — dan splitst `_detect_pipeline` het
> correct.

### Aparte OVS-kaart 🏚️

Naast de split op de uitkomst-tegels is er ook een **eigen kaart "Oude
verwerkingsstraat (OVS)"** direct onder *Pipeline-uitkomsten*. Die toont de echte
`by_pipeline.OVS`-tellingen per uitkomst (gepubliceerd/bijgewerkt/ingetrokken/
mislukt/in behandeling). Hij is **standaard ingeklapt zolang OVS 0 is** en klapt
open zodra er OVS-verkeer is. Eerlijk van opzet: geen verzonnen cijfers, alleen
wat er echt is (nu 0, want NVS-only platform). Hover geeft — net als de andere
kaarten — het context-paneel (`card:ovs`).

## TO DO

- [ ] Trendgrafiek van succespercentage over meerdere dagen
- [ ] Drill-down export naar CSV
