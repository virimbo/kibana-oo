---
title: "Webhooks (Mattermost)"
category: "Beheer & configuratie"
created: 2026-07-02
updated: 2026-07-02
tags: [kibana-oo, beheer]
---

# Webhooks (Mattermost)

> Beheer → **Webhooks**. Houd meerdere Mattermost-webhooks (ACC / TST / PROD)
> naast elkaar en kies met één klik welke **actief** is — dat is de webhook
> waar meldingen naartoe gaan. Zo hoef je nooit meer de `.env` aan te passen en
> de app opnieuw uit te rollen alleen om van kanaal te wisselen.
> Gerelateerd: [[Alerting (meldingen)]], [[Navigatie]].

## Wat & waarom

De app stuurt meldingen (RED-status van omgevingen, DLQ, certificaten, enz.) naar
een **Mattermost incoming webhook**. In de praktijk zijn er meerdere webhooks —
één per omgeving: **ACC**, **TST** en **PROD**. Vroeger stond er precies één URL
in `.env` (`DIGEST_WEBHOOK_URL`); wisselen betekende het bestand aanpassen en de
app opnieuw uitrollen. Foutgevoelig en traag.

Met deze functie beheert een **superadmin** alle webhooks op één plek en kiest
met één klik de **actieve**. Robuust, professioneel en makkelijk te beheren.

## Hoe te gebruiken

1. Ga naar **Beheer → Webhooks** (alleen zichtbaar voor de superadmin).
2. **Webhook toevoegen:** vul een **naam/omgeving** in (snelknoppen: `PROD`,
   `ACC`, `TST`) en plak de volledige **webhook-URL**
   (`https://mattermost…/hooks/xxxxxxxxxxxxx`). Klik **Toevoegen**.
   - De **eerste** webhook die je toevoegt, wordt automatisch **actief**.
3. **Activeren:** klik bij een webhook op **Activeer** om die de actieve te maken.
   Er is altijd precies **één** webhook actief.
4. **Test:** klik op **Test** om een écht proefbericht te sturen. Zie je het in
   Mattermost, dan werkt de webhook. Zo niet, dan zie je meteen de foutmelding —
   test dus altijd vóór je een nieuwe webhook activeert.
5. **Bewerk / Verwijder:** pas naam of URL aan, of verwijder een webhook.
   Bij bewerken mag je het URL-veld **leeg laten** om de bestaande URL te behouden.

## Een echt voorbeeld

- Je voegt **PROD** toe → `https://mattermost.koop…/hooks/pr0dc0de…` → wordt
  meteen actief. In de tabel zie je: **PROD · …c0de · ACTIEF**.
- Je voegt **ACC** en **TST** toe (blijven inactief).
- Tijdens een acceptatietest wil je meldingen even naar het ACC-kanaal. Je klikt
  bij **ACC** op **Test** (proefbericht komt aan) en daarna op **Activeer**.
  Vanaf dat moment gaan alle meldingen naar ACC.
- Klaar met testen? Eén klik **Activeer** bij **PROD** en je bent terug.

## Betekenis van de statusbalk & kleuren

Bovenaan staat een gekleurde balk:

- 🟢 **Groen** — er is een beheerde webhook **actief**; je ziet welke (naam +
  gemaskeerde URL). Meldingen gaan daarheen.
- 🟡 **Geel** — **geen** beheerde webhook actief, maar er is nog wél een
  `DIGEST_WEBHOOK_URL` in `.env`. Meldingen gebruiken die **fallback** (gedrag
  zoals vroeger — er verandert niets tot je hier een webhook activeert).
- 🔴 **Rood** — geen actieve webhook én geen `.env`-fallback → er worden
  **geen** Mattermost-meldingen verstuurd.

In de tabel is de actieve rij subtiel gemarkeerd en draagt een groene
**ACTIEF**-badge.

## Veiligheid

- **Volledige URL's worden nooit teruggegeven.** De lijst toont alleen de host +
  `/hooks/` + de laatste 4 tekens van de code (bijv. `…7890`), zodat je webhooks
  uit elkaar kunt houden zonder dat het geheim zichtbaar is.
- Alle acties zijn **alleen voor de superadmin** (`require_super`); de
  server dwingt dit af (anderen krijgen 403). Bij elke wijziging wordt de
  gebruiker + tijdstip vastgelegd (`Gewijzigd`-kolom).

## Configuratie & randgevallen

- **`.env` → `DIGEST_WEBHOOK_URL`** — nu een **fallback**: alleen gebruikt als er
  geen beheerde webhook actief is. Je kunt hem laten staan als vangnet.
- **Opslag:** de webhooks staan in de gedeelde `kibana_oo.db`
  (tabel `mattermost_webhooks`), naast de andere feature-tabellen. Zie
  [[Testing and CI]] voor de database.
- **Actieve webhook verwijderd?** Dan valt de app automatisch terug op de
  `.env`-fallback (of "geen meldingen" als die leeg is). Activeer daarna een
  andere webhook.
- **Test mislukt** (`✗`): meestal een typefout in de URL, een ingetrokken
  webhook in Mattermost, of netwerk/VPN. Corrigeer de URL (**Bewerk**) en test
  opnieuw.
- **Waar wordt dit gebruikt?** De dispatch leest de actieve URL via
  `webhooks_store.active_url()` (in `notify.py` en `alerts_send.py`), met de
  `.env`-waarde als fail-safe fallback — additief, dus bestaand gedrag blijft
  ongewijzigd tot je bewust een webhook activeert.
