---
title: Beschikbaarheid (uptime monitor)
tags: [dashboard, monitoring, beheer, uptime, nl]
aliases: [Uptime, Environment status, Beschikbaarheidsbord]
component: availability
purpose-business: Laat de beheerder dagelijks in één oogopslag zien of elke website (PROD/ACC/TEST) bereikbaar is.
purpose-technical: Achtergrond-HTTP-probe per site; classificeert up/traag/down/onbereikbaar met historie en alerting.
dependencies: [open.overheid.nl, doculoket.overheid.nl, Admin (KOOP Plooi), Gateway-zoek, Notifications and digest]
related: [Monitoring dashboard, Certificaten en TLS, Dashboard - statusoverzicht]
risk: medium
owner: KOOP Beheer
---

# Beschikbaarheid (uptime monitor) 🌐

Terug naar [[Home]] · zie ook [[Monitoring dashboard]] en [[Certificaten en TLS]].

> [!info] Voor wie is dit?
> Voor de **beheerder** die elke ochtend in één oogopslag wil zien: *staat alles
> nog online* — over **PRODUCTIE, ACCEPTATIE en TEST** heen.

## Wat & waarom

Het **Beschikbaarheidsbord** staat **bovenaan het Dashboard**. Een
achtergrondproces controleert elke minuut elke geconfigureerde website met een
gewone (niet-ingelogde) HTTP-aanroep en toont per site een gekleurde kaart. Zo zie
je direct of er iets plat ligt — vóórdat gebruikers het melden.

De gemonitorde sites (standaard):

| Omgeving | Site |
| --- | --- |
| **PROD** | open.overheid.nl · doculoket.overheid.nl · admin (login) |
| **ACC** | open-acc.overheid.nl · doculoket-acc.overheid.nl |
| **TEST** | gateway-zoek (test5) |

## Betekenis van de kleuren (statussen)

- 🟢 **UP** — bereikbaar, verwachte HTTP-status, snel genoeg.
- 🟠 **TRAAG (degraded)** — bereikbaar en correct, maar trager dan de drempel
  (`UPTIME_DEGRADED_MS`, standaard 2000 ms), of recent wisselvallig.
- 🔴 **DOWN** — wél bereikt, maar foute/onverwachte status (bijv. 5xx) — een echte,
  bevestigde storing. Of: een **publieke** site die helemaal niet reageert.
- ⚪ **ONBEREIKBAAR** — een **interne** (VPN-only) host die we niet konden bereiken.
  We weten dan niet of de site écht plat ligt of dat alléén deze server geen
  VPN-route heeft — daarom grijs, géén vals alarm.

> [!tip] Eerlijk en betrouwbaar
> **Alarmen gaan alléén af bij DOWN** (en pas nadat het minstens
> `UPTIME_SETTLE_MINUTES` aanhoudt). Een interne host zonder VPN-route (grijs)
> stuurt dus nooit een melding. Eén korte hapering pagineert je ook niet.

## Hoe te gebruiken

1. Open **Dashboard**. Het bord staat bovenaan met een samenvatting in de kop
   (bijv. **✓ 6/6 up** groen, of **⛔ 1 down** rood).
2. Lees per kaart: status, responstijd (ms), **uptime %**, een mini-grafiekje van
   de laatste metingen, en "x min geleden" (of "down sinds …").
3. Beweeg met de muis over een kaart voor het [[Smart context paneel]] met doel,
   afhankelijkheden en openstaande taken.

## Een echt voorbeeld

> **PROD** · 🔴 **DOWN** · doculoket.overheid.nl · HTTP 502 · 87% up · down sinds 4 min geleden

Betekent: doculoket is bereikt maar geeft een serverfout (502); 4 minuten geleden
begonnen, en in de laatste 30 metingen was 87% gezond. Er is (na de settle-tijd)
een melding via webhook/e-mail verstuurd.

## Configuratie & randgevallen

In `.env` (zie ook `.env.example`):

- `UPTIME_ENABLED=true` om aan te zetten (standaard `false`).
- `UPTIME_TARGETS` — één regel per site: `naam | omgeving | url | verwacht | internal?`
  - `verwacht` = toegestane statussen: `2xx,3xx,4xx,5xx` of exacte codes (`200,302,401`).
  - `internal` = VPN-only host → onbereikbaar wordt **grijs** i.p.v. rood.
  - Leeg laten = de ingebouwde standaardlijst van de 6 sites.
- `UPTIME_INTERVAL` (60s), `UPTIME_TIMEOUT` (8s), `UPTIME_DEGRADED_MS` (2000),
  `UPTIME_SETTLE_MINUTES` (2), `UPTIME_ALERT_ENABLED` (true), `UPTIME_HISTORY` (30).
- **Autorisatie:** gebruikers hebben het recht **`uptime`** nodig (Beheer →
  Autorisatie); super admins altijd. Zie [[Navigatie]].

> [!warning] Veiligheid
> Alleen de geconfigureerde sites worden opgehaald (allowlist → geen SSRF), met een
> gewone GET zónder inloggegevens (we proberen dus **niet** in te loggen op de
> admin/gateway — we kijken alleen of de pagina laadt). Geen secrets, korte
> timeouts, body genegeerd. De certificaat-/TLS-code blijft **bevroren**.

## Uitschakelen / rollback

Zet `UPTIME_ENABLED=false` (of laat de standaard staan) en herstart de backend. Het
bord verdwijnt direct; geen datamigratie, niets anders verandert.

## Onder de motorkap

- Backend: `backend/uptime.py` (parsing, probe, classificatie, historie, alert,
  poll-loop) + `backend/uptime_api.py` (`GET /dashboard/uptime/status`). Tests:
  `backend/tests/test_uptime.py`.
- Frontend: `frontend/src/UptimeBoard.jsx` + stijlen in `styles.css` (`.up-*`).
- Achtergrondloop gestart in `main.py` (lifespan), naast de cert- en DLQ-monitor.
