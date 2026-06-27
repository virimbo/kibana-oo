---
title: Runbook — wat te doen
tags: [runbook, beheer, acties, procedures, nl]
aliases: [Wat te doen, Runbook acties, What to do]
component: runbook-actions
bijgewerkt: 2026-06-17
eigenaar: KOOP Beheer
---

# Runbook — wat te doen 🚨

Terug naar [[Home]] · zie ook [[Beschikbaarheid (uptime)]] en [[Certificaten en TLS]].

> [!info] Wat is dit?
> De **actielijst + procedures**: *wie doet wat* als er iets misgaat. Het Smart
> context paneel leest dit bestand **live (on-demand)** — wijzig hieronder een regel
> in Obsidian, sla op, en de volgende keer dat je over een kaart hovert zie je de
> nieuwe tekst onder **"WAT TE DOEN NU"**. Geen herstart nodig.

> [!tip] Hoe het paneel deze runbook leest (de conventie)
> - Een **`##`-kopje** is een **situatie**: `## Bij DOWN`, `## Bij certificaat bijna verlopen`.
> - Eronder **één regel per omgeving**: `- PROD: …` / `- ACC: …` / `- TEST: …`
>   (de `-` mag weg; `TST` telt als `TEST`; hoofdletters/spaties maken niet uit).
> - Alleen regels die met **PROD/ACC/TEST** beginnen worden als actie getoond — alle
>   andere tekst (procedures, stappen, tabellen) is puur ter info en wordt genegeerd.
> - Ontbreekt een omgeving? Dan toont het paneel "geen actie vastgelegd".

---

## Bij DOWN
- PROD: Bel direct de 24/7 storingslijn (iedereen) en open een incident.
- ACC: Bel Firas en dev en andere boys
- TEST: Bel Anton.

## Bij certificaat bijna verlopen
- PROD: Bel iedereen en vernieuw het certificaat vóór de vervaldatum.
- ACC: Bel Firas om het ACC-certificaat te vernieuwen.
- TEST: Bel Anton om het TEST-certificaat te vernieuwen.

## Bij service down
- PROD: Controleer de actuator-health (`/actuator/health`) en de pod-status in OpenShift; bekijk de logs in Kibana, herstart zo nodig de pod en escaleer direct naar het dev-team als het aanhoudt.
- ACC: Bel Firas/dev; controleer de service-logs in Kibana en herstart de pod.
- TEST: Bel Anton; check de logs en herstart de service indien nodig.

## Bij service unreachable
- PROD: Eerst de VPN/het netwerk checken — kun jij de host wél bereiken? Zo niet, dan is het waarschijnlijk de monitoring-connectie (VPN/ingress), niet de service zelf. Controleer ingress/route en DNS; pas als de host echt onbereikbaar is, escaleer naar infra.
- ACC: Check je VPN-verbinding en de ingress/route; bel Firas/infra als de host onbereikbaar blijft.
- TEST: Check VPN en netwerk; bel Anton als het aanhoudt.

## Bij Monitoring-target rood
- PROD: Bepaal eerst het **type** target. **log-freshness** stale → de logging-pipeline staat stil: controleer of de Gateway/Envoy access-logs nog naar Elasticsearch verzonden worden (na de Ingress→Gateway-migratie) en check de index. **jaeger-traces** stale → trace-propagatie: controleer of de Gateway de trace-headers (`traceparent`/B3) doorgeeft en de OTel-collector → Jaeger. **prometheus-query** leeg/down → check of de Gateway nog een scrape-target is in Prometheus (ServiceMonitor/scrape-config). **http** down → controleer de HTTPRoute/Gateway, TLS en DNS. **unreachable** → de Prometheus/Jaeger-connectie of VPN ligt eruit. Escaleer naar het observability/dev-team als de pipeline echt stil ligt.
- ACC: Bel Firas/dev; bepaal het type (logs/traces/metrics/http) en controleer het bijbehorende pad (log-shipping / OTel / Prometheus-scrape / HTTPRoute).
- TEST: Bel Anton; check het type target en het bijbehorende observability-pad.

## Bij document-verwerking gestopt
- PROD: Geen documentactiviteit terwijl er normaal documenten binnenkomen → de verwerkings-pipeline ligt mogelijk stil. Controleer de harvester/ingest-pods in OpenShift en de logs in Kibana; herstart zo nodig en escaleer naar het dev-team. Bij een foutpiek: bekijk 'Errors per bron' en de gefaalde documenten.
- ACC: Bel Firas/dev; check of de ingest draait en bekijk de document-logs in Kibana.
- TEST: Bel Anton; check de pipeline en de logs.

---

# Procedures (stap voor stap)

> Naslag — pas aan naar de praktijk. Deze procedures worden **niet** in het paneel
> getoond (alleen de PROD/ACC/TEST-regels hierboven); je opent ze via de
> **Documentatie**-link in het paneel.

## Procedure — website DOWN
1. **Bevestig** de storing: open de kaart, check HTTP-status/responstijd en of het
   over meerdere omgevingen speelt. Eén omgeving = lokaal; alle = keten/infra.
2. **Classificeer**: PROD = P1 (gebruikers geraakt), ACC = P2, TEST = P3.
3. **Escaleer** volgens "Bij DOWN" hierboven (bel de juiste persoon/lijn).
4. **Communiceer**: melding in #plooi-incidenten en, bij PROD, op de statuspagina.
5. **Diagnose** (snelste eerst): bereikbaarheid/DNS → load balancer → applicatie-pods
   → afhankelijkheden ([[Verwerkingsstraat queues]], DB, [[Certificaten en TLS]]).
6. **Herstel** en **verifieer** dat de kaart weer 🟢 UP is (HTTP 200) en blijft.
7. **Leg vast**: tijdlijn, oorzaak, fix → maak zo nodig een RCA-notitie aan.

## Procedure — traag / degraded
1. Controleer of de responstijd structureel boven de drempel zit of een piek is.
2. Bekijk [[Monitoring dashboard]] (5xx, APM-fouten) in hetzelfde venster.
3. Schaal/herstart de dienst indien nodig; informeer bij aanhoudende traagheid.

## Procedure — onbereikbaar (grijs)
1. Een **interne** host (admin/gateway) grijs = waarschijnlijk **geen VPN-route**
   vanaf de monitor, niet per se down.
2. Verifieer handmatig via VPN of de site echt bereikbaar is.
3. Is hij écht onbereikbaar voor gebruikers? Behandel als **DOWN** (zie boven).

## Procedure — certificaat bijna verlopen / verlopen
1. Bepaal de urgentie via de kaart: < 30 dagen = oranje, < 14 dagen = rood/spoed.
2. Vraag/genereer een nieuw certificaat bij de CA (zie [[Certificaten en TLS]]).
3. Installeer en herlaad; controleer keten + hostname via "Full chain & TLS audit".
4. Verifieer dat de kaart weer **GRADE OK** toont met een nieuwe vervaldatum.

## Procedure — dead-letter queue vol (template)
1. Open [[Verwerkingsstraat queues]]; welke `*.dlq` vult en is er een consumer?
2. Geen consumer = kritiek: herstart/los de verwerker op.
3. Analyseer een voorbeeldbericht, herstel de oorzaak, re-queue of ruim op.

## Procedure — aanleverfouten (template)
1. Open [[Aanleverfouten]]; groepeer per uitgever.
2. Neem contact op met de uitgever om correct opnieuw aan te leveren.
3. De melding verdwijnt automatisch zodra het document gepubliceerd is.

---

## Escalatie & contacten (voorbeeld — vul de echte gegevens in)

| Niveau   | Wie               | Bereikbaar      | Voor      |
| -------- | ----------------- | --------------- | --------- |
| 1e lijn  | 24/7-storingslijn | +31 70 000 0000 | PROD P1   |
| ACC      | Firas (+ dev)     | +31 6 0000 0001 | ACC       |
| TEST     | Anton             | +31 6 0000 0002 | TEST      |
| Eigenaar | KOOP Beheer       | woo@logius.nl   | escalatie |

---

## Een nieuwe procedure / situatie toevoegen
- **Actie aanpassen:** wijzig de PROD/ACC/TEST-regel onder `## Bij DOWN` of
  `## Bij certificaat bijna verlopen` en werk `bijgewerkt:` bovenin bij.
- **Nieuwe procedure:** voeg een `## Procedure — <naam>` blok met genummerde stappen toe.
- **Nieuwe situatie in het paneel:** vereist een kleine code-aanpassing (een nieuwe
  conditie aan een kaartstatus koppelen) — laat het weten.
- Houd `bijgewerkt:` actueel; het paneel waarschuwt "verouderd" na ~180 dagen.
