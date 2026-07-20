---
title: "FG-DPO checklist (AVG, EU AI Act, BIO)"
category: "Project & communicatie"
created: 2026-07-16
updated: 2026-07-16
tags: [kibana-oo, compliance, avg, gdpr, eu-ai-act, bio, dpia, fg, dpo, beheer, nl]
aliases: [FG checklist, DPO checklist, Compliance checklist, AVG checklist, EU AI Act checklist, DPIA-intake]
---

# FG/DPO-checklist — AVG · EU AI Act · BIO

> **Wat is dit?** Een **concept-checklist ter validatie door de FG** (Functionaris
> Gegevensbescherming) en security/CISO, om **Open Overheid – Monitoring** naar
> **productie** te brengen binnen de Nederlandse overheid. Het is een
> **hulpmiddel + DPIA-intake**, géén juridisch advies. De FG/CISO zet de
> definitieve vinkjes.
>
> **Legenda:** ✅ = ingebouwd/aanwezig · ⚠️ = nog te doen (formele stap) ·
> ❓ = **beslissing van de FG/CISO nodig**.
>
> Verwant: [[Presentatie - Management]], [[AI-architectuur]], [[Autorisatie]],
> [[Certificaten en TLS]].

## 0. Systeem in één alinea (voor de FG)

Open Overheid – Monitoring bewaakt of het Woo-publicatieplatform
(open.overheid.nl) gezond is. Het is **alleen-lezen**: het leest logs/metrics uit
Elasticsearch via Kibana en toont status + uitleg. De AI is **RAG** (haalt logs
op → vat samen met een taalmodel); hij **beslist niets** en handelt niet
autonoom — een mens beslist. Het systeem raakt de publicatieketen niet aan en
neemt geen besluiten over personen. Zie [[AI-architectuur]].

---

## A. AVG / UAVG — verwerking van persoonsgegevens

- [ ] **Worden er persoonsgegevens verwerkt?** ⚠️ *Waarschijnlijk indirect.* De app
  verwerkt **logs** die incidenteel identifiers kunnen bevatten (bv. een
  gebruikersnaam, IP, of een persoon genoemd in een document-titel). De app
  verwerkt géén burgerpersoonsgegevens als *doel*.
- [ ] **Categorieën betrokkenen** benoemen: (1) **beheerders/gebruikers** van de app
  (login, activiteit); (2) mogelijk **personen genoemd in logs/documenten**.
- [ ] **Bijzondere/gevoelige gegevens?** ⚠️ Bepalen of Woo-documenten bijzondere
  categorieën (art. 9) kunnen bevatten; zo ja, extra waarborgen.
- [ ] **Grondslag (art. 6 AVG)** ✅ voorstel: **taak van algemeen belang / wettelijke
  taak** (art. 6(1)(e)) — het systeem ondersteunt de **Woo**-publicatieplicht. FG
  bevestigt de grondslag.
- [ ] **Doelbinding & doelomschrijving (art. 5)** ✅ doel = *operationeel bewaken van
  de publicatieketen*. Vastleggen dat data niet voor andere doelen wordt gebruikt.
- [ ] **Data-minimalisatie (art. 5(1)(c))** ✅ **PII-redactie ingebouwd**
  (`LLM_REDACT_PII=true`) vóórdat tekst naar het taalmodel gaat; alleen-lezen;
  geen kopie van documentinhoud.
- [ ] **Bewaartermijn (art. 5(1)(e))** ⚠️ **vaststellen** per gegevenssoort
  (feature-run-logs in `kibana_oo.db`, incidenten in `incidents.db`,
  sessie-/auditlogs). Bron-logs zelf staan in Elasticsearch (ander beheer).
- [ ] **Rechten van betrokkenen (art. 15–22)** ⚠️ proces beschrijven voor inzage/
  correctie/verwijdering — voor **gebruikers** haalbaar; voor incidentele PII in
  bron-logs verwijzen naar de bronsystemen.
- [ ] **Beveiliging (art. 32)** ✅ zie **sectie C (BIO)**.
- [ ] **Verwerkingsregister (art. 30)** ⚠️ **opnemen** in het register van
  verwerkingen van de organisatie.
- [ ] **Verwerker(s) & verwerkersovereenkomst (art. 28)** ❓ **hangt af van de
  LLM-keuze** (zie sectie B/§model): bij een **gehost** model (bv. Mistral, EU) is
  een **verwerkersovereenkomst** nodig; bij het **lokale** model (Ollama, on-prem)
  verlaat data het pand niet → **geen externe verwerker** voor de AI.
- [ ] **Doorgifte buiten de EER (art. 44+)** ❓ alleen relevant bij een gehost model
  buiten de EER — dan een transfermechanisme. Met **lokaal model: n.v.t.**
- [ ] **Datalek-procedure (art. 33/34)** ⚠️ aansluiten op de bestaande meldprocedure
  van de organisatie.

---

## B. EU AI Act (Verordening (EU) 2024/1689)

- [ ] **Rol** ✅ de organisatie is **deployer/gebruiker** van een AI-systeem, **niet
  de provider** van het onderliggende model.
- [ ] **Risicoklasse** ✅ voorstel: **beperkt risico**. Onderbouwing: geen
  hoog-risico use case (geen biometrie, geen besluit over rechten/toegang van
  personen, geen kritieke veiligheidsfunctie); AI **ondersteunt/legt uit**,
  **mens-in-de-lus** beslist. FG/jurist bevestigt de klasse.
- [ ] **Transparantieplicht (art. 50)** ✅ de app maakt kenbaar dat antwoorden door
  AI zijn gegenereerd; documentatie is openbaar in de vault.
- [ ] **Menselijk toezicht** ✅ ingebouwd — de AI voert geen acties uit; alle
  beslissingen liggen bij de beheerder.
- [ ] **GPAI-model** ✅ het onderliggende taalmodel is *general-purpose*; de
  GPAI-verplichtingen liggen primair bij de modelaanbieder, niet bij de deployer.
- [ ] **AI-geletterdheid (art. 4)** ⚠️ korte instructie/awareness voor gebruikers
  vastleggen (wat de AI wel/niet doet).
- [ ] **Geen verboden praktijken (art. 5)** ✅ niet van toepassing (geen social
  scoring, geen manipulatieve/biometrische toepassing).

---

## C. BIO — informatiebeveiliging (Baseline Informatiebeveiliging Overheid)

- [ ] **Transport-encryptie (TLS)** ✅ + **actieve certificaat-/TLS-bewaking**
  ([[Certificaten en TLS]]).
- [ ] **Authenticatie** ✅ **Keycloak OIDC-SSO** (geen eigen wachtwoordopslag).
- [ ] **Autorisatie / least privilege** ✅ rechten-matrix **per gebruiker × per
  functie** + **goedkeuringsgate** voor nieuwe gebruikers ([[Autorisatie]]).
- [ ] **Secrets-beheer** ✅ geheimen in `.env` (**niet** in de code/git); in het
  scherm/DB alleen de *naam* van een geheim, nooit de waarde.
- [ ] **Applicatie-hardening** ✅ security-headers, rate-limiting op login,
  read-only data-toegang.
- [ ] **Logging & auditing** ✅ audit-trail van config-/rechtenwijzigingen; ⚠️
  bewaartermijn logs vaststellen.
- [ ] **Pentest / beveiligingstest** ⚠️ **uitvoeren door een bevoegde partij** vóór
  productie.
- [ ] **BIO-toetsing** ⚠️ formele toetsing tegen de BIO-maatregelen (o.b.v. ISO
  27001/NEN) door security/CISO.
- [ ] **Hosting/omgeving** ⚠️ productie-waardige, beheerde omgeving vaststellen
  (nu: ontwikkel-/pilotopstelling).

---

## D. DPIA — Gegevensbeschermings­effectbeoordeling (art. 35 AVG)

- [ ] **Is een DPIA verplicht?** ⚠️ **Waarschijnlijk ja / aan te raden** — nieuwe
  technologie (AI) + overheidscontext. FG beslist definitief.
- [ ] **DPIA uitvoeren** met minimaal: systeembeschrijving, doel & grondslag,
  categorieën gegevens/betrokkenen, **risico's voor betrokkenen**, genomen
  maatregelen (PII-redactie, alleen-lezen, toegangsbeheer), **restrisico** en
  besluit.
- [ ] **FG-advies & akkoord** ⚠️ vastleggen.
- [ ] **Herbeoordeling** ⚠️ moment/aanleiding voor herziening bepalen (bv. bij
  wijziging van model of scope).

---

## E. Algoritmeregister (`algoritmes.overheid.nl`)

- [ ] **Registreren** ⚠️ het AI-/algoritme-gebruik opnemen in het landelijke
  **Algoritmeregister** — past bij "open overheid", vergroot **publiek
  vertrouwen** en transparantie. FG/comms bepalen de inhoud van de registratie.

---

## F. Governance, documentatie & overdracht

- [ ] **Eigenaarschap** ⚠️ formeel proces-/systeemeigenaar en beheerteam benoemen.
- [ ] **Documentatie** ✅ volledige, actuele documentatie in de Obsidian-vault
  (architectuur, features, runbooks, RCA's).
- [ ] **Bus-factor / overdracht** ⚠️ kennisoverdracht + training team (nu bij één
  bouwer) — zie roadmap in [[Presentatie - Management]].
- [ ] **Wijzigingsbeheer** ✅ conventionele commits, feature-branch → PR → merge;
  ⚠️ formeel change-/release-proces vastleggen voor productie.

---

## G. Samenvattende status

| Domein | Ingebouwd ✅ | Nog te borgen ⚠️ / beslissen ❓ |
|---|---|---|
| **AVG/UAVG** | PII-redactie, alleen-lezen, minimalisatie, OIDC, autorisatie | Grondslag bevestigen, bewaartermijnen, verwerkingsregister, **VWO** (bij hosted), datalekproces |
| **EU AI Act** | Beperkt risico, transparantie, mens-in-de-lus | Risicoklasse formeel bevestigen, AI-geletterdheid |
| **BIO** | TLS, SSO, autorisatie, secrets, headers, audit | **Pentest**, BIO-toetsing, productie-hosting |
| **DPIA** | Bouwstenen aanwezig | **DPIA uitvoeren + FG-akkoord** |
| **Transparantie** | Documentatie openbaar | **Algoritmeregister** |
| **Governance** | Documentatie compleet | Eigenaarschap, overdracht/training |

---

## H. Openstaande beslissingen voor de FG/CISO

1. **Lokaal (Ollama) of gehost (Mistral) taalmodel?** → bepaalt of er een
   **verwerkersovereenkomst** en een **doorgifte-toets** nodig zijn. *Advies voor
   maximale privacy:* **lokaal model** → data verlaat het pand niet.
2. **Grondslag** (art. 6) definitief vaststellen (voorstel: wettelijke taak/algemeen
   belang, Woo).
3. **Is de DPIA verplicht** — en zo ja, wie voert hem uit en op welke termijn?
4. **Bewaartermijnen** per gegevenssoort.
5. **Risicoklasse EU AI Act** formeel bevestigen (voorstel: beperkt risico).

## I. Aanbevolen volgorde naar productie

1. **Model-keuze + grondslag** vastleggen (FG-beslissing 1 & 2).
2. **DPIA** uitvoeren → **FG-akkoord**.
3. **Pentest + BIO-toetsing** door bevoegde partij.
4. **Verwerkingsregister** bijwerken + (indien hosted) **verwerkersovereenkomst**.
5. **Algoritmeregister**-registratie.
6. **Productie-hosting + change-/release-proces** + **overdracht/training**.

> **Eerlijke samenvatting voor het management:** de **techniek werkt en is
> transparant en alleen-lezen**; wat rest is **formele borging** (DPIA, pentest,
> FG-akkoord). Dat is precies waar tijd + mandaat voor wordt gevraagd — zie
> [[Presentatie - Management]].
