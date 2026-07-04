---
title: Dashboard — statusoverzicht (overzichtsrij)
tags: [dashboard, monitoring, beheer, nl]
component: criticals
purpose-business: Geeft de beheerder in één oogopslag de algehele gezondheid van het platform.
purpose-technical: Telt error-logs, HTTP 5xx en APM-fouten in het venster, met trend t.o.v. de vorige periode.
dependencies: [Elasticsearch, Kibana, APM]
related: [Monitoring dashboard, Document lifecycle (pipeline)]
risk: medium
owner: KOOP Beheer
category: "Monitoring & signalen"
created: 2026-06-17
updated: 2026-06-29
---

# Dashboard — statusoverzicht 🟢🟠🔴

Terug naar [[Home]] · zie ook [[Monitoring dashboard]] en
[[Document lifecycle (pipeline)]].

> [!info] Voor wie is dit?
> Voor de **beheerder** die in één oogopslag wil zien of het platform gezond is,
> vóórdat hij de details induikt. Deze notitie legt de **bovenste rij tegels** op
> het Dashboard uit, plus de **inklapbare zones** eronder.

## Wat & waarom

Bovenaan het Dashboard staat een rij **statustegels** ("control tower"). Elke
tegel vat één onderwerp samen tot één getal met een kleur, zodat je niet eerst
alle kaarten hoeft te lezen. De rest van de pagina is daaronder gegroepeerd in
**zones** die je kunt in- en uitklappen, zodat iedereen alleen ziet wat hij
belangrijk vindt.

De tegels en zones respecteren je **rechten**: je ziet alleen waar je toegang
toe hebt (zie [[Navigatie]] en de autorisatie­matrix).

## Waar vind ik het?

**Beheer → Dashboard** (of de knop **Dashboard** in de menubalk). De tegels staan
direct onder de balk met **Periode** en **Data view**. De getallen gelden voor de
**geselecteerde periode** (bijv. *Laatste 1 uur*) en de **gekozen data view**
(bijv. `logs-*`).

## De tegels uitgelegd

| Tegel | Wat het getal betekent | Wanneer kleur |
|---|---|---|
| **System status** | Het eindoordeel voor de gekozen periode: **All clear**, **Degraded** of **Critical**. Een samenvatting van alle andere tegels. | groen = gezond · oranje = verminderd · rood = kritiek |
| **Criticals** | Aantal **error-logs + HTTP 5xx serverfouten + APM-fouten** in deze periode. Het mini-grafiekje toont het **verloop** over de periode (pieken = uitbarstingen van fouten). | rood zodra > 0 |
| **Docs at risk** | Het grote getal = documenten met een **echt probleem** (kúnnen niet gepubliceerd worden) — hierop moet je actie ondernemen. De regel eronder ("… still processing") toont hoeveel er nog **in behandeling** zijn: normale doorstroom, die publiceren meestal gewoon. **Klik** om te traceren. | rood zodra er een probleem is; anders groen |
| **Aanleverfouten** | Documenten die een bronhouder probeerde aan te leveren maar die **bij aanlevering geweigerd** zijn — ze kwamen de pipeline nooit in en moeten opnieuw aangeleverd worden. | oranje zodra > 0 |
| **Dead-letter queues** | RabbitMQ-wachtrijen met **vastgelopen berichten** (werk dat mislukte en blijft staan, niets verwerkt het). | oranje zodra > 0 |

> [!note] TLS-certificaten staan hier bewust **niet**
> Certificaatstatus heeft een **eigen, gedetailleerde kaart** verderop op de
> pagina (*Certificate & TLS health*, met de resterende dagen per site en
> eventuele keten-/vertrouwensproblemen). Een aparte tegel bovenaan zou dubbelop
> zijn en alleen ruis toevoegen — daarom is die tegel verwijderd.

### Kleurcodes (algemeen)

- 🟩 **Groen** — niets aan de hand (waarde 0 / status All clear).
- 🟧 **Oranje** — let op: er is iets dat aandacht verdient, maar niet acuut kritiek.
- 🟥 **Rood** — kritiek: hier nú naar kijken.

## Een echt voorbeeld

Stel, de beheerder opent 's ochtends het Dashboard met **Periode = Laatste 1 uur**
en **Data view = logs-* — All logs**, en ziet:

- **System status: Critical** (rood)
- **Criticals: 115** (rood) — met een grafiekje dat halverwege het uur een piek laat zien
- **Docs at risk: 3** (rood) — *of 3.589 still processing*
- **Aanleverfouten: 0** (groen)
- **Dead-letter queues: 0** (groen)

**Hoe lees je dit?**
1. *System status: Critical* zegt: er is iets serieus — niet wegklikken.
2. *Criticals: 115* met een piek halverwege → rond dat tijdstip is er een uitbarsting
   van fouten geweest. Klap de zone **Overview & diagnostics** open en bekijk
   **HTTP 5xx** en **Foutsignaturen** om te zien wélke fouten.
3. *Docs at risk: 3* (rood) → er zijn **3 documenten met een echt probleem**; de
   **3.589** eronder zijn gewoon **in behandeling** (normale doorstroom). **Klik de
   tegel** → je springt naar **Documents** en ziet per probleemdocument wáár het
   misgaat (bijv. `ronl-abc123…` faalt in stap *indexering*).
4. *Aanleverfouten 0* en *Dead-letter queues 0* → de aanlevering en de
   berichtenverwerking zijn op dit moment in orde; de oorzaak zit dus in de
   pipeline/zoekkant, niet in de aanlevering.

> [!important] Niet schrikken van een groot "in behandeling"-getal
> Het getal **"still processing"** (bijv. 3.589) zijn documenten die **nog door de
> pipeline lopen** — dat is normale doorstroom, géén storing. Alleen het grote
> getal op de tegel (**Docs at risk**, de documenten met een **echt probleem**) is
> de actie-knop. Daarom staat dit **rustig op het Dashboard** en is de oude,
> alarmerende **"… stuck"-knop uit de menubalk verwijderd** — "stuck" suggereerde
> ten onrechte dat alles kapot was.

## Inklapbare zones

Onder de tegels is de pagina opgedeeld in zones, elk met een kop die je kunt
**in-/uitklappen** (klik op de kop). Je keuze wordt **per zone onthouden** (ook na
herladen), zodat ervaren beheerders alleen tonen wat ze volgen:

1. **Needs attention** (oranje accent) — Aanleverfouten · Dead-letter queues · Certificaten
2. **Throughput & outcomes** — gepubliceerd / bijgewerkt / ingetrokken / mislukt per pipeline
3. **Overview & diagnostics** — statusbanner, KPI's, 404, foutsignaturen, per systeem, services, HTTP 5xx, *documenten die aandacht nodig hebben*
4. **AI insights** — de AI-triage (alleen als AI aanstaat)

## Kleine details die helpen

- **Trendlijntje (sparkline)** op *Criticals*: laat in één blik zien of het stijgt of daalt.
- **Skeleton-laadbalkjes**: terwijl de cijfers laden zie je een zacht "shimmer"-balkje
  in plaats van een leeg streepje, zodat duidelijk is dat er nog data binnenkomt.
- **Tooltip**: houd de muis op een tegel voor een uitgebreidere uitleg.
- **Uitleg-regel onder de kaarten**: de diagnose-kaarten (*Pipeline outcomes*,
  *Documents not found (404)*, *HTTP 5xx*) tonen direct onder de titel één regel
  in gewone taal wat de kaart betekent — zo hoef je niet eerst te hoveren. De
  "i"-knop blijft voor de uitgebreide uitleg.

## Configuratie & randgevallen

- **Periode**: kies een preset (rollend venster) of een eigen **van→tot** bereik —
  ook heel oude data. Alle tegels en zones volgen deze keuze.
- **Data view**: bepaalt welke dataset wordt geanalyseerd (`logs-*` = alles; de
  andere beperken tot één systeem, bijv. `ds-prod5-koop-plooi*`).
- **Geen toegang tot een onderwerp?** Dan verschijnt die tegel/zone niet — dat is
  geen fout maar je rechten (zie [[Navigatie]] / autorisatie).
- **Dead-letter queues niet zichtbaar?** Die tegel verschijnt alleen als de
  RabbitMQ-monitoring is geconfigureerd én je het recht `rabbitmq` hebt.

## Zelf zones tonen/verbergen (per gebruiker)

In **Beheer → Instellingen → Dashboard experience** kun je hele blokken aan/uit
zetten met schakelaars (los van autorisatie; per sessie onthouden):

- **Beschikbaarheid** (uptime-bord), **Infrastructuur** (Grafana-links),
  **Overzichtstegels** (hero), **Certificaten & TLS**, **Dead-letter queues**,
  **Aanleverfouten**.
- **Standaard staat alles AAN** — zet uit wat je niet wilt zien. Een blok is pas
  zichtbaar als je er óók recht op hebt (autorisatie blijft leidend).
- Daar staat ook **"Show card detail panel (hover)"** (het [[Smart context paneel]]).

## Gerelateerd

- [[Navigatie]] · [[Monitoring dashboard]] · [[Document tracer]] · [[Document lifecycle (pipeline)]]

## Onderdelen tonen/verbergen (admin · ⚙ Aanpassen)

Een beheerder kan elk dashboard-onderdeel aan- of uitzetten — rechtstreeks op het
dashboard. Klik rechtsboven (bij Vernieuwen) op **⚙ Aanpassen**: er verschijnt een
paneel met een schakelaar per onderdeel:

- Beschikbaarheid (uptime) · Service health · Grafana & servers · Overzichtstegels ·
  Vereist aandacht · Aanleverfouten · Dead-letter queues · Certificaten & TLS ·
  Throughput & outcomes · Logs & fouten · AI insights.

Zet je iets uit, dan verdwijnt het blok meteen; weer aan = terug. Klik **⚙ Klaar**
om het paneel te sluiten — daarbuiten blijft het dashboard schoon (geen schakelaars
in beeld). Alleen zichtbaar voor admins; gewone gebruikers zien alleen het resultaat.

> **Onthouden (durable):** je keuze staat in `localStorage` (`kibana_oo_dash_sections`)
> en blijft bewaard, ook na het sluiten van de tab. Dezelfde schakelaars staan ook in
> **Beheer → Instellingen → Dashboard-weergave** — beide sturen dezelfde status aan.
