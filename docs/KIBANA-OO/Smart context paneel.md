---
title: Smart context paneel (hover-intelligentie)
tags: [dashboard, beheer, ai, obsidian, nl]
aliases: [SmartContextPanel, Contextpaneel, Hover-paneel]
component: smart-context
purpose-business: Geeft de beheerder direct uitleg, status en openstaande taken bij elke dashboardkaart.
purpose-technical: Hover/focus op een kaart → rechts paneel met vault-context, TODO's en optionele AI-analyse.
dependencies: [Monitoring dashboard, Obsidian vault, LLM providers]
related: [Monitoring dashboard, Verwerkingsstraat queues, Aanleverfouten, Certificaten en TLS]
risk: low
owner: KOOP Beheer
category: "Beheer & configuratie"
created: 2026-06-17
updated: 2026-06-17
---

# Smart context paneel 🧠

Terug naar [[Home]] · zie ook [[Monitoring dashboard]] en [[Navigatie]].

> [!info] Voor wie is dit?
> Voor de **beheerder** die bij een dashboardkaart meteen wil weten: *wat is dit,
> hoe gezond is het, en wat staat er nog open* — zonder de pagina te verlaten.

## Wat & waarom

Het **Smart context paneel** verschijnt **rechts in beeld** zodra je met de muis
boven een kaart hangt (of er met het toetsenbord naartoe navigeert). Het toont in
één oogopslag:

- **Kaartinformatie** — componentnaam, doel (business + technisch),
  afhankelijkheden, gerelateerde onderdelen, status, risico en eigenaar.
- **AI-analyse** *(optioneel)* — een korte, in het Nederlands geschreven duiding:
  huidige toestand, trend, risico, mogelijke impact en aanbevolen acties.
- **TO DO** — openstaande taken die **live uit de Obsidian-vault** (`docs/KIBANA-OO/`)
  worden gelezen: technische schuld, bekende problemen, verbeteringen, security.
- **Documentatie** — een directe link naar de bron-note in Obsidian.

Het probleem dat het oplost: kennis over een component zat verspreid in runbooks en
notities. Nu staat die context **precies daar waar je kijkt** — bij de kaart zelf.

## Hoe te gebruiken (stap voor stap)

1. Ga naar **Dashboard**.
2. **Beweeg de muis** boven een kaart (bijv. een queue-tegel zoals
   *Document-Harvester*, een hero-tegel zoals *Criticals*, of de
   *Aanleverfouten*-kaart). Na een korte vertraging (~150 ms) schuift het paneel
   rechts in beeld.
3. Wil je het paneel **vastzetten** om rustig te lezen? **Klik** op de kaart (of
   druk **Enter** als de kaart focus heeft). Het paneel blijft dan open.
4. **Sluiten:** druk **Esc**, of klik op het kruisje **×** rechtsboven in het paneel.
5. Klik op de **documentatielink** onderaan om de volledige note in Obsidian te
   openen en daar taken af te vinken of bij te werken.

> [!tip] Toetsenbord & toegankelijkheid (WCAG 2.2 AA)
> Het paneel is volledig met het toetsenbord te bedienen (Tab naar de kaart →
> opent; Esc sluit en zet de focus terug). Kleur is nooit het enige signaal —
> er staan altijd iconen en tekst bij. Op smalle schermen wordt het een
> uitschuifbaar paneel over de volledige hoogte.

## Een echt voorbeeld

Je hangt boven de tegel **Document-Harvester** in *Dead-letter queues*. Rechts
verschijnt:

> **Document-Harvester** · status: *healthy* · risico: *low*
> **Doel (business):** Verwerkt binnenkomende publicatiedocumenten.
> **Afhankelijkheden:** RabbitMQ · Documentopslag · Indexatie
> **🧠 AI-analyse:** *Huidige toestand: gezond, queue leeg…*
> **✓ TO DO:**
> ☐ Verbeter retry-afhandeling
> ☐ Voeg queue-lag monitoring toe
> ☐ Review dead-letter routing
> **📄 Documentatie:** [[Verwerkingsstraat queues]] ↗

De naam en de live status (*healthy*) komen van de **kaart zelf**; doel, taken en de
AI-analyse komen uit de **vault** en de **LLM**.

## Betekenis van de cijfers, kleuren en statussen

- **Status-badge** — groen *ok/healthy*, oranje *warn/degraded*, rood *crit/critical*.
  Deze komt 1-op-1 van wat de kaart al toont (de live waarde).
- **Risico-badge** — uit de vault-frontmatter (`risk: low|medium|high`).
- **TO DO** — ☐ = open, ☑ = afgerond. De lijst is een **live spiegel** van de
  `- [ ]`/`- [x]` regels in de bron-note; afvinken doe je in Obsidian.
- **"Nog niet gedocumenteerd in de vault."** — er is (nog) geen note met de juiste
  `component:` voor deze kaart. Het paneel werkt dan nog steeds, maar zonder
  vault-inhoud.

## Hoe een kaart "slim" wordt

Een kaart krijgt context via twee dingen:

1. **Registry** — in `backend/context_engine.py` koppelt `REGISTRY` een kaart-id
   (bijv. `queue:document-harvester`) aan een **component-id** (bijv.
   `rabbitmq-queues`).
2. **Vault-frontmatter** — een note wordt dat component door in de frontmatter
   `component:` op te nemen, plus optioneel `purpose-business`, `purpose-technical`,
   `dependencies`, `related`, `risk`, `owner`, `last-incident`. **TO DO's** zijn
   gewone Obsidian-taken (`- [ ]`) in de tekst.

```yaml
---
component: document-harvester
purpose-business: Verwerkt binnenkomende publicatiedocumenten.
dependencies: [RabbitMQ, Documentopslag, Indexatie]
risk: low
---
- [ ] Verbeter retry-afhandeling
```

Een note mag meerdere componenten dekken (`component: [a, b, c]`). Ontbrekende
velden worden netjes overgeslagen.

## Configuratie & randgevallen

- **Aanzetten:** zet `SMART_CONTEXT_ENABLED=true` in `.env` en herstart de backend.
- **Snel aan/uit per gebruiker:** in **Beheer → Instellingen → Dashboard experience**
  staat de schakelaar **"Show card detail panel (hover)"**. Uit = geen hover-paneel
  meer (handig als je even rustig wilt lezen); de keuze wordt per sessie onthouden.
  Dit staat los van de `SMART_CONTEXT_ENABLED`-vlag (die bepaalt of de functie
  überhaupt beschikbaar is).
- **Vault-locatie:** leeg laten = automatisch `docs/KIBANA-OO` naast de code
  (lokaal). In een container: mount de vault en zet `SMART_CONTEXT_VAULT_PATH`.
- **Autorisatie:** ook als de vlag aanstaat, ziet een gebruiker het paneel alleen
  met het recht **`smart_context`** (Beheer → Autorisatie). Super admins hebben het
  altijd. Zie [[Navigatie]].
- **AI uit?** Staat het AI-model op *uit* (of is het onbereikbaar), dan verbergt het
  paneel simpelweg de AI-sectie — de rest blijft werken. Zie [[LLM providers]].
- **Niets zichtbaar?** Controleer in volgorde: (1) staat `SMART_CONTEXT_ENABLED` op
  `true`, (2) heeft de gebruiker het recht `smart_context`, (3) heeft de note de
  juiste `component:`.

> [!warning] Veiligheid
> Het paneel **leest alleen**. Vault-bestanden worden uitsluitend binnen één
> vault-map gelezen (geen path traversal), kaart-id's worden tegen de registry
> gevalideerd, en vault-tekst wordt veilig (gesanitiseerd) weergegeven. De
> certificaat-/TLS-code blijft **bevroren** en wordt nergens gewijzigd.

## Uitschakelen / rollback

Zet `SMART_CONTEXT_ENABLED=false` (of laat de standaard staan) en herstart de
backend. Het paneel verdwijnt direct; er is geen datamigratie en niets anders
verandert. Rollback is dus een kwestie van seconden.

## Onder de motorkap (voor ontwikkelaars)

- Backend: `backend/context_engine.py` (vault-index, registry, assembler, AI) en
  `backend/context_api.py` (endpoints onder `/dashboard/context`, dus al door nginx
  geproxyd). Tests: `backend/tests/test_context.py`.
- Frontend: `frontend/src/SmartContextPanel.jsx` + `useCardContext.js` (hover-intent,
  pin, toetsenbord) + stijlen in `styles.css` (`.scp`).
- Kaarten dragen inerte `data-smartcard`/`data-smartlabel`/`data-smartstatus`
  attributen; verder is alles additief — bestaand gedrag verandert niet.
