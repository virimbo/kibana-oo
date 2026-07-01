---
title: Observability (Datastroom & gezondheid)
tags: [kibana-oo, observability, beheer]
---

# Observability 📈

**Beheer → Observability** — één pagina die de kritieke monitoring-signalen in
**gewone taal** toont voor niet-technische beheerders. Elke kaart legt uit: **Wat is
dit? · Waarom kritiek? · Wat te doen?** Bovenaan een intelligente statusbanner
(groen/amber/rood met een samenvattende zin).

## De signalen
1. **🌊 Datastroom (ingestion freshness)** — *nieuw.* Hoe lang geleden kwam de laatste
   log binnen (nieuwste `@timestamp`) in de gekozen dataweergave? Geen nieuwe data =
   de verwerkingsstraat staat mogelijk stil **of** we zijn 'blind'. Drempels:
   `OBS_FRESH_OK_MINUTES` (15) / `OBS_FRESH_WARN_MINUTES` (60).
2. **📤 Publicatie-flow** — bereiken documenten open.overheid.nl? (vastgelopen/mislukte
   documenten, uit de pipeline-health).
3. **📥 Aanleverfouten** — worden aanleveringen geweigerd? (afgewezen aanleveringen).
4. **🚨 Fouten & 5xx** — error-/5xx-piek + de ergst getroffen service.

## Werking & grenzen
- **Live-weergave met je eigen sessie** (alleen-lezen ES-queries via de Kibana-proxy),
  dus alles rekent in real time zolang je bent ingelogd. Endpoint:
  `GET /dashboard/observability`. Robuust: één falende bron → status `unknown`, de
  pagina blijft werken (nooit een harde error).
- **Achtergrond-alerting** van deze ES-signalen (paging zonder dat iemand kijkt)
  vereist het **service-account** (de achtergrond-loop draait met `sid=None`) — zie
  [[stuck-document-alert-deferred]] / de AI-architectuurnotitie. Tot dan maakt deze
  pagina het gat **zichtbaar** i.p.v. het te verbergen.

## Betrouwbare 'vastgelopen'-telling (settle-gate + incident-expiry)

De Publicatie-telling was opgeblazen (bv. 6534 → "Kritiek"). Oorzaken + fixes:
- **Settle-gate** (`PIPELINE_SETTLE_MINUTES`, 90): een document telt pas als
  'vastgelopen' als het langer dan de normale verwerkingstijd níet gepubliceerd is.
  Documenten die nog *in verwerking* zijn tellen niet meer mee.
- **Incident-expiry** (`INCIDENT_MAX_AGE_HOURS`, 72): oude, nooit-opgeloste incidenten
  verlopen automatisch (reden `stale`), zodat de telling **actueel & actiegericht**
  blijft i.p.v. een historische stapel. (Effect: 6534 → ~1627 direct.)
- **Zinnige drempel** (`OBS_STUCK_WARN` 1 / `OBS_STUCK_CRIT` 25): "Kritiek" betekent nu
  ≥25 echte, niet ≥10.

> **Bekende beperking:** de grondwaarheid-check tegen open.overheid.nl bevestigt niets
> (`confirmed_published=0`) voor interne hex-id's — die id's mappen niet op een publieke
> open.overheid.nl-UUID. Daardoor kan een document dat wél live is toch als 'vastgelopen'
> blijven staan tot het via de 72h-expiry vervalt. Volledige betrouwbaarheid vereist de
> juiste id-mapping (intern doc-id ↔ open.overheid.nl) — domeininput nodig.
