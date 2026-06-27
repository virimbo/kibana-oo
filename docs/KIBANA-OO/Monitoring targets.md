---
title: Monitoring targets
tags: [dashboard, monitoring, beheer, observability, nl]
aliases: [Monitoring targets, Monitoring registry, Observability monitoring]
component: monitoring
purpose-business: Laat een super-admin zélf monitoring-targets toevoegen/aan-uitzetten (zonder code) en bewaakt of logging/tracing/metrics nog binnenkomen na de Ingress→Gateway-migratie.
purpose-technical: DB-backed registry (connections + targets) met een checker-plugin-pattern (http, log-freshness, jaeger-traces, prometheus-query), achtergrond-poller, intelligence-laag en een dashboard-card; additief, alles-uit by default.
dependencies: [Elasticsearch, Prometheus, Jaeger]
related: [Service health, Beschikbaarheid (uptime), AI-architectuur, Runbook - wat te doen, Alerting (meldingen)]
risk: medium
owner: KOOP Beheer
---

# Monitoring targets

> 🇳🇱 Een **admin-configureerbare** monitoring-registry. Een super-admin voegt via
> **Beheer → Monitoring** zélf *targets* toe (en zet ze aan/uit) — zonder code. Gemaakt
> om ná de **Ingress → Gateway API**-migratie te bewaken dat niet alleen de apps
> werken, maar dat **logging, tracing en metrics** nog binnenkomen bij Kibana, Jaeger
> en Grafana/Prometheus.

Gerelateerd: [[Service health]] (vaste backend-services) · [[Beschikbaarheid (uptime)]]
(publieke sites) · [[AI-architectuur]] · [[Runbook - wat te doen]]

---

## Wat & waarom

De bestaande monitors ([[Service health]], [[Beschikbaarheid (uptime)]], certificaten,
DLQ) lezen hun config uit `.env` — vast in code. Deze registry is het **generieke,
uitbreidbare** tegenstuk: targets staan in de database en zijn vanuit de UI te beheren.

Concreet na de Gateway-migratie: een app kan *up* zijn terwijl zijn **observability
stil is gevallen** (de oude Ingress-controller leverde access-logs/metrics; de nieuwe
Gateway doet dat via een ander pad). Functionele checks missen dat — **freshness-checks
op de pipeline** vangen het wél.

Het is **additief**: het raakt de bestaande monitors of de (FROZEN) certificaat-code
niet aan. Standaard **uit** (`MONITOR_ENABLED=false`).

## Begrippen

- **Connection** — een gedeelde backend-URL die je één keer instelt (Prometheus of
  Jaeger). Targets van die soort hergebruiken hem. Elasticsearch heeft géén connection
  nodig — die gebruikt de bestaande, geauthenticeerde sessie van de app.
- **Target** — één check. Heeft een `type`, een `environment` (prod/acc/test/na), een
  **enable-toggle**, een **alert-toggle**, en type-specifieke `config`.

## Checker-types (plugin-pattern)

| Type | Wat het checkt | Antwoordt na migratie |
|------|----------------|------------------------|
| `http` | GET een URL, vergelijk met verwachte status + latency | "monitor elke URL"; bereikbaarheid via de Gateway |
| `log-freshness` | nieuwste `@timestamp` in een ES-index jonger dan drempel | logging stroomt nog naar Kibana |
| `jaeger-traces` | aantal traces voor een service in de laatste N min > 0 | tracing stroomt nog naar Jaeger |
| `prometheus-query` | een PromQL-query levert (of overschrijdt) een drempel | metrics stromen nog naar Grafana |

Een nieuw type toevoegen = één checker registreren (`monitor_checkers.register(...)`).

## Intelligence-laag

- **Auto-discovery** — bij een connection haalt de app de bronnen op (ES-indices,
  Jaeger-services, Prometheus-jobs) en **stelt targets voor** (één klik om toe te voegen).
- **Adaptieve baselines** — `log-freshness`/`jaeger-traces` leren het normale ritme; een
  bron die normaal elke 5 s logt en 2 min stil valt wordt gemarkeerd, ook als een vaste
  drempel het niet zou zien.
- **Correlatie + AI root-cause** — rode signalen voor dezelfde service+omgeving worden
  tot één incident gegroepeerd; de bestaande LLM/RAG schrijft (best-effort, NL) een korte
  oorzaak-analyse + runbook-stap. AI uit/fout → het incident toont gewoon de feiten.
- **Dependency-suppressie** — is een connection (Prometheus) onbereikbaar, dan één
  melding i.p.v. een storm van "target down".
- **Flap-detectie** — pas alarmeren na N opeenvolgende rode rondes (`MONITOR_FLAP_THRESHOLD`).
- **Coverage-score** — per omgeving: `PROD 92% — logs ✓ traces ✓ metrics ✗`.

## Hoe te gebruiken

**Beheer → Monitoring** (alleen super-admin):

1. **Connections**: voeg Prometheus/Jaeger toe (kind, naam, `base_url`). Heeft een
   backend een token nodig? Zet dat in `.env` en vul alleen de **naam** (`secret_ref`)
   in — de waarde staat nooit in de database of de UI.
2. **Targets**: **+ Target** → kies `type`, `environment`, eventueel een connection, en
   de type-specifieke velden. Gebruik **Discover** om bronnen te laten voorstellen.
   **Test** doet de check live vóór opslaan. Met de **toggles** zet je een target of zijn
   alert aan/uit.

Op het **Dashboard** verschijnt de card **📡 Monitoring** (naast Service health):
coverage per omgeving + een tegel per target (klik open voor detail). Bekijken vereist
het recht **`monitoring`** (Beheer → Autorisatie). Alarmen lopen via de bestaande
[[Alerting (meldingen)]] (categorie *Monitoring*, e-mail → Mattermost, per incident).

## Configuratie & randgevallen

`.env` (server):
```ini
MONITOR_ENABLED=false        # functie aan/uit (instant rollback)
MONITOR_INTERVAL=60          # seconden tussen poll-rondes
MONITOR_TIMEOUT=8            # timeout per check
MONITOR_FLAP_THRESHOLD=2     # opeenvolgende rode rondes vóór een alert
# Tokens voor Prometheus/Jaeger (optioneel): zet de waarde in .env en verwijs er per
# connection naar via secret_ref (bv. PROM_TOKEN). Nooit de waarde in de DB/UI.
```

- **Veilig:** alleen super-admin configureert; alleen-lezen checks; secrets uitsluitend
  in `.env` (de API geeft nooit een secret-waarde terug). Geen user-input-URL bereikt
  een server zonder super-admin.
- **Veilig falen:** één kapotte target/connection breekt nooit de ronde; AI is
  best-effort en blokkeert nooit een alert.
- **VPN:** interne endpoints (Prometheus/Jaeger op het cluster) vereisen VPN; anders
  tonen ze eerlijk `unreachable`.

**Rollback:** `MONITOR_ENABLED=false` → card verdwijnt, poller inert, registry blijft staan.

## Architectuur (bestanden)

- `backend/monitor_registry.py` — schema + CRUD (connections/targets/results; lazy schema)
- `backend/monitor_checkers.py` — checker-plugins (4 types) + `discover()`
- `backend/monitor_intel.py` — baselines, flap, correlatie, coverage, AI root-cause
- `backend/monitor_engine.py` — poll-loop (lifespan), dependency-suppressie, snapshot
- `backend/monitor_api.py` — API (config super-admin; card feature-gated)
- `frontend/src/MonitoringConfig.jsx` — beheer-pagina · `frontend/src/MonitoringCard.jsx` — dashboard-card

## Later (additief / roadmap)

Synthetic canaries (een test-log/-trace/-metric injecteren en de aankomst bevestigen),
maintenance-windows, ML-anomaliedetectie, en eventueel de bestaande `.env`-monitors naar
de registry migreren.
