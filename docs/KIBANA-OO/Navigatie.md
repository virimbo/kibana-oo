---
title: Navigatie — de menubalk
tags: [navigatie, ui, beheer, nl]
category: "Beheer & configuratie"
created: 2026-06-17
updated: 2026-07-01
---

# Navigatie — de menubalk 🧭

Terug naar [[Home]]. Zie ook [[Dashboard - statusoverzicht]].

> [!info] Voor wie is dit?
> Voor elke gebruiker/beheerder: hoe je je weg vindt in KIBANA-OO. Eén vaste
> menubalk bovenaan élke pagina, die laat zien **waar je bent** en alleen toont
> **waar je toegang toe hebt**.

## Wat & waarom

Vroeger had elke pagina zijn eigen kopbalk; die waren in de loop van de tijd uit
elkaar gaan lopen (andere knoppen, andere volgorde). Nu is er **één gedeelde
menubalk** (`TopNav`) op alle pagina's. Voordelen:

- **Overal hetzelfde** — het menu verspringt nooit tussen pagina's.
- **Je ziet waar je bent** — de actieve bestemming licht op (gemarkeerd in accentkleur).
- **Rechten bepalen wat je ziet** — een knop verschijnt alleen als je het recht hebt
  (deny-by-default).

## De menu-items (van links naar rechts)

1. **Merk/logo** (links) — *KIBANA-OO*. Klik erop om terug naar **Chat** (home) te gaan.
2. **Chat** — de AI-chat over je logs en metrics.
3. **Dashboard** — het [[Dashboard - statusoverzicht|statusoverzicht]] (alleen met recht `dashboard`).
4. **Documents** — documenten traceren/zoeken (alleen met recht `documents`).
5. **Beheer** — het beheercentrum (alleen voor beheerders).
6. **Rechtercluster** — statuspil (verbinding), waarschuwings­badges,
   gebruikerschip en **Afmelden**.

### Actieve pagina

De knop van de pagina waar je bent, is **gemarkeerd** (accentkleur + subtiel kader).
Zit je op een **subpagina van Beheer** (Instellingen, Regressietest, Autorisatie),
dan blijft **Beheer** opgelicht — zo weet je altijd in welk onderdeel je zit.

### Beheer als startpunt

**Beheer** is een hub met kaarten naar: **Instellingen**, **Monitoring (Dashboard)**,
**Documenten**, **Regressietest** en — alleen voor de super admin — **Autorisatie**.
Je ziet alleen de kaarten waar je recht op hebt.

## Het rechtercluster, uitgelegd

- **Statuspil** (alleen op Chat): *Verbonden* (groen) / *Offline* (rood) / *Bezig…* —
  of de backend bereikbaar is.
- **Badges** (verschijnen alleen als er iets is, en als je beheerder bent):
  - 🐰 **DLQ** — aantal dead-letter queues met vastgelopen berichten.
  - **Aanleverfouten** — aantal bij aanlevering geweigerde documenten.
  - *(De oude **"… stuck"-badge is bewust verwijderd** uit de menubalk: dat grote
    getal joeg onnodig schrik aan terwijl het meestal normale doorstroom is. De
    documenten **in behandeling** en de echte **probleemdocumenten** staan nu
    rustig en juist gekaderd op het [[Dashboard - statusoverzicht|Dashboard]].)*
- **Gebruikerschip** — een rond plaatje met je **initialen** plus je gebruikersnaam.
- **Afmelden** — beëindigt je sessie.

> [!note] De AI-modelkiezer zit niet meer in de balk
> De pill waarmee je tussen **Ollama** / **Mistral** wisselde (of AI uit zette) is
> uit de menubalk **verwijderd**. Het model is nu één globale, admin-only instelling
> onder **Beheer → Instellingen → 🤖 AI-assistent** (zie [[LLM providers]]). Niet-
> beheerders zien dus het **resultaat** (welk model actief is), maar geen wisselknop.

## Een echt voorbeeld

De beheerder `anton.partono@koop.overheid.nl` logt in en ziet in de balk:
**Chat · Dashboard · Documents · Beheer**, rechts *Verbonden* (groen), en het chip
**AP · anton.partono@…**.

1. Hij klikt **Dashboard** → die knop licht op; hij ziet het [[Dashboard - statusoverzicht|statusoverzicht]].
2. Hij klikt **Beheer → Regressietest** → in de balk blijft **Beheer** opgelicht
   (Regressietest is een onderdeel van Beheer), dus hij weet dat hij "in Beheer" zit.
3. Een collega met alléén het recht `documents` ziet **Chat** en **Documents**, maar
   **geen** Dashboard- of Beheer-knop — precies volgens zijn rechten.

## Smal scherm

Op smalle schermen vouwt de balk samen tot **alleen pictogrammen** (zonder tekst) en
verbergt de lange gebruikersnaam, zodat het overzichtelijk blijft.

## Configuratie & randgevallen

- **Een knop ontbreekt?** Dat is bijna altijd een **rechtenkwestie**, geen fout —
  de super admin kent rechten toe via **Beheer → Autorisatie**.
- **Nieuwe backend-route achter het menu?** Vergeet niet die in `frontend/nginx.conf`
  te proxyen (zie RULES.md), anders geeft de knop in de browser een 404/405.

## Gerelateerd

- [[Dashboard - statusoverzicht]] · [[LLM providers]] · [[Architecture]]
