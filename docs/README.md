# `docs/` — wat staat waar (start hier)

Korte gids zodat je nooit hoeft te twijfelen wélke map de juiste is.

## ⭐ De bron van waarheid: `KIBANA-OO/`

**`docs/KIBANA-OO/` is de enige, actuele Obsidian-vault.** Dit is de map die je
opent in Obsidian én die de applicatie zelf inleest voor het hover-paneel
(read-only gemount als `/app/vault`, zie `docker-compose.yml`). Alle
beheerder-documentatie (in het Nederlands) staat hier — begin bij `Home.md`.

> Gebruik altijd `KIBANA-OO/`. Andere vault-achtige mappen zijn oud of een backup.

## Referentie-documentatie (los, in git)

Technische naslag (Engels), gelinkt vanuit de root-`CLAUDE.md`:

- `ARCHITECTURE.md` — de drie services en hoe een request stroomt
- `database.md` — de databases (`incidents.db`, gedeelde `kibana_oo.db`)
- `authorization.md` — autorisatie (super admin + grant-matrix + approval gate)
- `aanleverfouten.md` — monitoring van afgekeurde aanleveringen
- `regression-test.md` — de post-release health gate
- `rabbitmq-dlq.md` — dead-letter-queue monitor
- `time-range.md` — gedeelde tijdsvenster-presets

## Overige mappen (in git)

- `compliance/` — compliance-notitie(s)
- `superpowers/` — design-specs en implementatieplannen (`specs/`, `plans/`)

## Niet gebruiken (lokaal, buiten git)

Deze stonden hier eerder en zorgden voor verwarring. Ze zitten **niet** in git en
worden door niets in de code gebruikt:

- `KIBANA-OO_BACKUP/` — een oude lokale backup-snapshot (verouderd).
- `fb-monitoring-wiki/` — de vorige vault onder de oude projectnaam (vervangen
  door `KIBANA-OO/`).

Deze mogen naar een `archive/`-map of weg — ze zijn geen bron van waarheid.
