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

## TO DO

- [ ] Trendgrafiek van succespercentage over meerdere dagen
- [ ] Drill-down export naar CSV
