---
title: "DLQ intelligentie"
category: "Monitoring & signalen"
created: 2026-06-18
updated: 2026-06-18
tags: [kibana-oo, monitoring]
---

# DLQ intelligentie

> 🇳🇱 Slimme, **alleen-lezen** inzichten in de dead-letter queues: niet alleen
> *hoeveel* berichten vastzitten, maar **waarom** — met oorzaak, leeftijd, trend en
> een aanbevolen actie. Te bereiken via **Dashboard → 🐰 Dead-letter queues →
> 🔍 Intelligentie** (of Beheer-menu). Vereist het recht **`rabbitmq`**.

Gerelateerd: [[Woo Gateway]] · [[Alerting (meldingen)]] · [[Monitoring dashboard]]

---

## Wat & waarom

Een `*.dlq` (dead-letter queue) bevat berichten die **niet verwerkt** konden worden.
De gewone DLQ-kaart laat zien *hoeveel* er vastzitten en of de bron-queue een consumer
heeft. Dat zegt nog niet **waarom** het misgaat.

**DLQ intelligentie** kijkt — alleen-lezen — **in** de berichten (`x-death`-headers) en
maakt er een begrijpelijk verhaal van: de **oorzaak** (rejected / expired / max-retries
/ maxlen), de **leeftijd** van het oudste bericht, de **trend** (groeit / stabiel /
loopt leeg) en een **aanbevolen actie**. Daaruit volgt één **slim oordeel** per queue.

Belangrijk: het is **niet-destructief**. Berichten worden gepeekt met
`ackmode=reject_requeue_true` — gelezen en meteen teruggezet. Niets wordt verwijderd of
verplaatst. Per ronde max **20** berichten per queue, elke ~90 s.

---

## Hoe te gebruiken

1. Op het dashboard, in de kaart **🐰 Dead-letter queues**, klik rechtsboven op
   **🔍 Intelligentie**.
2. Je ziet per niet-lege queue een gekleurde kaart met:
   - het **oordeel** (kop), bijv. *🔴 Actief probleem — groeit · 240 berichten · oudste
     3u · vooral max-retries op export*,
   - **🛠️ Aanbevolen actie**,
   - de **oorzaken** uitgesplitst (bijv. `max-retries (180×) · rejected (60×)`),
   - een **voorbeeldtabel** van gepeekte berichten (oorzaak · bron · routing · leeftijd).

---

## Een echt voorbeeld

`export.dlq` heeft **240** berichten, **groeit**, oudste is **3 uur** oud, en bij het
peeken blijkt **max-retries** (`delivery_limit`) de hoofdoorzaak op bron `export`.

Oordeel: **🔴 Actief probleem — groeit · 240 berichten · oudste 3u · vooral max-retries
op export**.
Actie: *"Poison-message: herstel of skip het falende bericht en controleer de consumer."*

Omdat het groeit én boven de kritieke drempel zit, is dit **kritiek** — er wordt (één
keer) een [[Alerting (meldingen)|melding]] gestuurd, mét deze oorzaak en actie erin.

---

## Betekenis van kleuren, oordeel en trend

- 🟢 **Leeg** — niets dead-lettered.
- 🟡 **Geparkeerd / lichte ophoping** — berichten staan vast maar het is stabiel en/of
  al lang geparkeerd; geen acute groei.
- 🔴 **Actief probleem** — het **groeit**, de bron heeft **0 consumers**, of de diepte
  is boven de kritieke drempel. Dit vraagt nu aandacht.

**Trend:** `groeit` (neemt toe), `stabiel` (gelijk), `loopt leeg` (neemt af) — bepaald
uit de diepte-historie.

**Oorzaken (`x-death`):**
- **rejected** — de consumer heeft het bericht geweigerd → controleer validatie/schema.
- **expired** — TTL verlopen voordat het verwerkt werd → draait de consumer wel?
- **max-retries** (`delivery_limit`) — te vaak opnieuw geprobeerd (poison-message) →
  herstel/skip het bericht en fix de consumer.
- **maxlen** — queue-limiet bereikt → schaal de consumer of verhoog de limiet.

---

## Configuratie & randgevallen

`.env` (server):

```ini
DLQ_INTEL_ENABLED=false      # functie aan/uit (false = oude telling-gedrag)
DLQ_INTEL_INTERVAL=90        # seconden tussen intelligentie-rondes
DLQ_INTEL_PEEK_MAX=20        # max berichten gepeekt per queue per ronde
DLQ_INTEL_PARKED_DAYS=2      # ouder dan dit = "geparkeerd" (waarschuwing)
DLQ_INTEL_GROW_DELTA=5       # diepte-stijging t.o.v. vorige meting = "groeit"
DLQ_INTEL_HISTORY=50         # diepte-metingen bewaard per queue (trend)
```

- **Peek faalt** (geen rechten/onbereikbaar): de queue valt terug op een
  **telling-only** oordeel ("alleen telling beschikbaar"); de motor crasht nooit.
- **Geheugen/DB:** alleen een compacte diepte-historie staat in `kibana_oo.db`
  (`dlq_intel_history`); oorzaken/leeftijd worden live berekend.
- **Alleen-lezen:** er zijn bewust **geen** requeue/purge-knoppen. Dat is een aparte,
  zwaarder beveiligde functie voor later.

**Rollback:** `DLQ_INTEL_ENABLED=false` → de kaart/pagina/alerts vallen terug op het
oude telling-gedrag; tabel `dlq_intel_history` kan gedropt worden. De bestaande
DLQ-monitor (`rabbitmq_dlq`) is nooit gewijzigd.
