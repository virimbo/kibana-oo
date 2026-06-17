---
title: Grafana en infrastructuur
tags: [infra, grafana, beheer, nl]
aliases: [Infrastructuur, Grafana-links]
component: grafana
purpose-business: Geeft de beheerder met één klik toegang tot de Grafana-infradashboards.
purpose-technical: Toont een configureerbare lijst externe dashboardlinks; opent in een nieuw tabblad, geen credentials opgeslagen.
dependencies: [Grafana, Prometheus, CloudNativePG]
related: [Beschikbaarheid (uptime), Monitoring dashboard]
risk: low
owner: KOOP Beheer
---

# Grafana en infrastructuur 🛠

Terug naar [[Home]] · zie ook [[Beschikbaarheid (uptime)]] en [[Backlog - TODO Anton]].

## TO DO
- [ ] Live CloudNativePG-metrics als kaarten tonen (Health/Overview/Storage) — **geblokkeerd**: read-only Grafana service-account token nodig (zie [[Backlog - TODO Anton]]).
- [ ] Token in `.env` zetten (`GRAFANA_TOKEN`) + Prometheus datasource-UID bevestigen.
- [ ] Eventueel extra PROD Grafana-dashboards toevoegen aan `GRAFANA_LINKS`.

> [!info] Wat is dit?
> Een kaart op het **Dashboard** met **één-klik-links** naar de Grafana-dashboards
> voor de infrastructuur (bijv. de **CloudNativePG/Postgres**-cluster). Klik → het
> dashboard opent in een **nieuw tabblad**; je logt in met je eigen Grafana-SSO.

## Hoe te gebruiken

1. Open **Dashboard** → blok **Infrastructuur — Grafana**.
2. Klik op een link (bijv. *CloudNativePG (cnpg-cluster-v5)*) → opent Grafana in een
   nieuw tabblad. De host en omgeving (PROD/ACC/TEST) staan op de kaart.

## Betekenis

- De kaart toont **alleen links** — er worden **geen metrics opgehaald** en **geen
  inloggegevens** bewaard. Toegang en autorisatie tot Grafana lopen via Grafana zelf.

## Configuratie

In `.env` (zie `.env.example`):

- `GRAFANA_LINKS` — één link per regel: `naam | url | omgeving?`. Leeg laten = de
  ingebouwde standaard (de CloudNativePG-cluster). Alleen `http(s)`-URL's worden
  getoond (veiligheid). Voorbeeld:
  ```
  CloudNativePG (cnpg-cluster-v5) | https://grafana-prod.cicd.s15m.nl/d/cloudnative-pg/... | PROD
  ```
- **Autorisatie:** gebruikers hebben het recht **`grafana`** nodig (Beheer →
  Autorisatie); super admins altijd. Zie [[Navigatie]].

> [!warning] Veiligheid
> Links openen met `rel="noopener noreferrer"` in een nieuw tabblad; alleen
> `http(s)`-URL's worden geaccepteerd. Geen tokens/secrets, geen proxy — Zero-Trust:
> authenticatie gebeurt volledig in Grafana.

## Uitbreiden

Voeg gewoon een regel toe aan `GRAFANA_LINKS` (bijv. een ACC/TEST-dashboard of een
ander Grafana-board). Een nieuwe link verschijnt direct als kaart-knop.

## Onder de motorkap

- Backend: `backend/infra_api.py` (`GET /dashboard/infra/links`). Tests: `backend/tests/test_infra.py`.
- Frontend: `frontend/src/InfraLinks.jsx` + stijlen in `styles.css` (`.infra-*`).
