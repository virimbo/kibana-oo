---
title: Documentgezondheid
tags: [documents, monitoring, intelligence, beheer, nl]
aliases: [Documentgezondheid, Document health, Documenten-verdict]
component: documents
purpose-business: Vertaalt de ruwe document-tellingen op de Documenten-pagina naar een begrijpelijk oordeel + pro-actieve signalen, zodat een beheerder direct ziet of er actie nodig is.
purpose-technical: Een pure helper `_build_health()` in documents.py bouwt een `health`-object (level/headline/signals) uit de tellingen vs. het vorige venster; de frontend toont een verdict-banner + signalen.
related: [Document lifecycle (pipeline), Document tracer, Runbook - wat te doen, AI-architectuur]
owner: KOOP Beheer
---

# Documentgezondheid

> 🇳🇱 De Documenten-pagina toonde ruwe tellingen (events / unique / errors / op actie /
> op type / activiteit) zonder uitleg. Deze **intelligence-laag** zet dat om in een
> **plain-Dutch verdict** + **pro-actieve signalen** met aanbevolen acties, zodat een
> beheerder in één oogopslag ziet of er iets aan de hand is.

Gerelateerd: [[Document lifecycle (pipeline)]] · [[Document tracer]] ·
[[Runbook - wat te doen]]

---

## Wat je ziet

Boven de panelen staat een **gezondheids-banner**:

- ✅ **Gezond** — *"19 documenten verwerkt, 0 fouten (dit venster)."*
- ⚠️ **Aandacht** — een waarschuwing (bv. ongewoon volume).
- ⛔ **Kritiek** — een ernstig signaal (verwerking gestopt of foutpiek).

Daaronder, indien van toepassing, de **signalen** — elk met een **aanbevolen actie**.

## De drie signalen

Vergeleken met het **vorige venster** (zelfde lengte, direct ervoor):

| Signaal | Wanneer | Boodschap |
|---------|---------|-----------|
| **Verwerking gestopt** (`stalled`) | nu 0 events, maar vorig venster had activiteit (`≥ doc_stall_min_prior`) | "Geen documentactiviteit (was N) — verwerking mogelijk gestopt." |
| **Foutpiek** (`error_spike`) | `errors ≥ doc_error_threshold` óf `errors > 0` en `+100%` t.o.v. vorig venster | "X fouten (+Y%)." |
| **Ongewoon volume** (`volume`) | events én vorig venster > 0, en `|Δ%| ≥ doc_volume_swing_pct` | "Volume ongewoon hoog/laag: N vs M (vorig venster)." |

De **KPI-kaarten** (events, errors) tonen nu ook de delta t.o.v. het vorige venster
(bv. *"+5% vs vorig venster"*), zodat een getal context heeft.

## "Op actie" — niet-geclassificeerd

Het actietype wordt afgeleid uit een **structured veld** (`event.action`/`action`) of
anders uit keywords in de logtekst. Wat niet te herleiden is heet eerlijk
**"niet-geclassificeerd"** (voorheen het verwarrende "other"). Staat *alleen*
"niet-geclassificeerd" in het paneel, dan staat het actietype simpelweg niet in de log
— alleen het aantal events is dan bekend, en het verdict leunt er niet op.

## Pro-actief handelen (runbook)

Een kritiek signaal verwijst naar de runbook-sectie **"Bij document-verwerking
gestopt"** ([[Runbook - wat te doen]]): controleer de harvester/ingest-pods en de logs,
herstart zo nodig, escaleer. De Smart-Context-koppeling (`card:documents`) levert die
stap.

## Configuratie

`.env` (server) — drempels met verstandige defaults:
```ini
DOC_ERROR_THRESHOLD=10     # errors ≥ dit = kritieke foutpiek
DOC_STALL_MIN_PRIOR=1      # vorig-venster events nodig om "0 nu" een stall te noemen
DOC_VOLUME_SWING_PCT=60    # |Δ%| events ≥ dit = volume-signaal
```

## Architectuur (read-only, additief)

- `backend/documents.py` — `_build_health(events, events_prior, errors, error_pct_change,
  events_pct_change)` (pure) + een extra prior-window event-count; `health` in de
  summary-payload. Bestaande panelen/feed/data-keys ongewijzigd.
- `frontend/src/Documents.jsx` — verdict-banner + signalen + KPI-delta's + eerlijke label.
- `backend/context_engine.py` + runbook — de `card:documents`-conditie.

## Later (roadmap)

**Phase B — push-alerts:** het `health`-object *is* al een alert-payload, dus bij
`level ≥ warning` kan het via de bestaande [[Alerting (meldingen)]]-engine (categorie
*Documents*, e-mail → Mattermost) gepusht worden — "stuur wat je al berekent". Verder:
een **lerende baseline** (i.p.v. alleen het vorige venster) en per-bron gezondheid.
