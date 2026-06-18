---
title: Backlog — TODO Anton
tags: [backlog, todo, beheer, nl]
aliases: [TODO Anton, Backlog Anton, Openstaande acties]
eigenaar: Anton
bijgewerkt: 2026-06-17
---

# Backlog — TODO Anton 📌

Terug naar [[Home]]. Persoonlijke actielijst met openstaande zaken die input/rechten
van Anton (of een ander team) nodig hebben vóórdat ze afgebouwd kunnen worden.

---

## 🔴 Grafana live-metrics kaarten (CloudNativePG) — GEBLOKKEERD op token

**Doel:** op het dashboard **live metrics-kaarten** tonen zoals het Grafana-dashboard
*CloudNativePG* (cluster `cnpg-cluster-v5`, namespace `koop-plooi-prd`): de blokken
**Health** (Replication / Lag / Storage / CPU / Memory / Connections / Backups / WAL =
*Healthy*), **Overview** (Last failover, Version, TPS, CPU %, Memory %/GiB, Replication/
Write/Flush/Replay lag) en **Storage** (Volume Space %, Database Size). Native KIBANA-OO
kaarten — eigen kleuren, gauges en eventueel alerting — niet alleen een plaatje.

**Waarom geblokkeerd:** dit vereist read-only toegang tot de Prometheus achter Grafana.
Anton is in Grafana **alleen Viewer** (geen Admin) en kan zelf **geen service account /
token** aanmaken. Dat moet het Grafana-/platformteam doen.

**Gekozen aanpak (A):** de backend bevraagt Prometheus **via Grafana's datasource-proxy**
met één **read-only service-account token** — geen aparte Prometheus-toegang of DB-creds
nodig, en het token is in Grafana intrekbaar (Zero-Trust).

### Acties
- [ ] **Vraag het Grafana-/platformteam** (beheerder van `grafana-prod.cicd.s15m.nl`) om een
  **read-only service account + token** (rol **Viewer**, naam `kibana-oo-readonly`).
- [ ] **Ontvang het token veilig** (secrets-kluis, niet via chat) en zet het in `.env` als
  `GRAFANA_TOKEN=glsa_…` — **nooit committen**.
- [ ] **Bevestig de Prometheus datasource-UID** (`koop-plooi-proxy`) — te zien in
  *Connections → Data sources → …/edit/<UID>*; geef de `<UID>` door.
- [ ] **Bevestig netwerk/VPN**: mag de KIBANA-OO-backend `grafana-prod.cicd.s15m.nl` read-only bereiken?
- [ ] **Daarna (Claude):** bouw de live **Health / Overview / Storage**-kaarten via
  `/api/datasources/proxy/uid/<UID>/api/v1/query` (PromQL), met achtergrond-poll,
  feature-vlag + `grafana`-recht, en nette degradatie ("niet bereikbaar / niet geconfigureerd").

### Verzoek om door te sturen naar de Grafana-beheerder
> **Verzoek: read-only Grafana service-account token voor KIBANA-OO**
> Voor het monitoring-dashboard willen we de CloudNativePG-metrics live tonen. Graag:
> 1. Een **service account** (Administration → Users and access → Service accounts), rol **Viewer**, naam `kibana-oo-readonly`.
> 2. Daarvan een **token** genereren en veilig delen (secrets-kluis).
> 3. De **UID van de Prometheus-datasource** (`koop-plooi-proxy`) bevestigen.
> 4. Bevestigen dat de KIBANA-OO-backend `grafana-prod.cicd.s15m.nl` read-only mag bereiken.

### Tussenoplossing (nu al live)
- De **[[Grafana en infrastructuur|Infrastructuur — Grafana]]**-kaart op het dashboard
  geeft met één klik toegang tot het volledige CloudNativePG-dashboard. Voldoende tot de
  live-kaarten er zijn.

---

## Andere openstaande zaken
- [x] **Alerting → Mattermost-kanaal** — ✅ gedaan (18 jun 2026). `DIGEST_WEBHOOK_URL`
  staat op de Mattermost incoming webhook; de motor post een **rijke kaart**
  (gekleurde balk, kop, samenvatting, veldenraster, aanbevolen actie) als afzender
  **FB-OO:Anton**. Zie [[Alerting (meldingen)]].
- [ ] **Alerting → eigen domein bij Resend verifiëren** — nu kan Resend (ongeverifieerd
  account) alléén naar `fb.open.overheid@gmail.com` sturen. Verifieer een domein op
  resend.com/domains en zet `SMTP_FROM` op een adres van dat domein; dán kunnen ook
  andere ontvangers (bijv. antonio.partono@gmail.com / een teamlijst) gemaild worden.
- [ ] (voeg hier nieuwe to-do's toe — gebruik `- [ ]` zodat ze afvinkbaar zijn)

> [!tip] Hoe bijwerken
> Vink af met `- [x]` zodra iets klaar is, en werk `bijgewerkt:` bovenin bij. Nieuwe
> blokken kun je gewoon onder een nieuw `##`-kopje zetten.
