# Time range — presets + custom date ranges

De Dashboard- en Documents-pagina's delen een **TimeRange**-control: snelle presets
voor het gangbare geval, plus een **custom absoluut from→to-venster** zodat een admin
**elke datum kan analyseren, inclusief heel oude data**.

## De control

- **Presets** (rollend venster eindigend op nu): 15 min · 30 min · 1 u · 6 u · 24 u ·
  **7 d · 30 d · 90 d · 1 jaar**.
- **Aangepast bereik…** toont twee `datetime-local`-pickers (van / tot) en een
  **Toepassen**-knop. Valideert: begin vóór einde, einde niet in de toekomst.
- Het **resolved venster** wordt altijd getoond (📅 absolute datums bij een custom
  range), en een *"groot bereik (kan trager zijn)"*-hint verschijnt bij vensters van
  meer dan 90 dagen.
- De keuze wordt **gepersisteerd** (`sessionStorage`, key `kibana_oo_timerange`) en
  **gedeeld** over Dashboard ↔ Documents, zodat het venster je volgt.

`TimeRange.jsx` biedt helpers: `timeParams(range)` (het query-fragment),
`rangeLabel(range)`, `loadRange()`, `saveRange()`.

## Backend (additief — het period-pad is onveranderd)

Endpoints (`/summary`, `/briefing`, `/documents`, `/outcomes`) accepteren optionele
`from` / `to` query-params **naast** de bestaande `period`:

- `?period=60` → rollend last-hour-venster (precies als voorheen).
- `?from=<ISO|epoch-ms>&to=<ISO|epoch-ms>` → dat absolute venster.

Eén helper, `monitoring.resolve_window(period, from, to)`, bezit de logica: met een
geldige `from`/`to` geeft hij dat venster terug (gevalideerd — einde geclampt op nu,
begin < einde); anders valt hij terug op `period_bounds(period)`. De builders
(`build_snapshot`, `build_document_activity`, `build_pipeline_outcomes`) kregen een
optionele expliciete `(start, end)` die de period overschrijft; **wanneer weggelaten
is het gedrag byte-voor-byte identiek aan voorheen.**

### Robuustheid voor grote / heel oude ranges

- De dashboard-timeseries gebruikt **`auto_date_histogram`** (target ~60 buckets) voor
  custom vensters, zodat een 2-jaars range de bucket-count nooit laat exploderen; de
  document-activity-chart gebruikt `interval_for_span()` met hetzelfde effect.
- Een out-of-retention / leeg venster rendert de normale empty state (geen crash).
- De AI-briefing krijgt `window_start` / `window_end`, zodat die de echte range vermeldt
  in plaats van "de laatste N minuten".

## Toegestane presets

Preset-minuten worden serverzijde gevalideerd (`ALLOWED_PERIODS`): 15, 30, 60, 360,
1440, 10080, 43200, 129600, 525600. Willekeurige vensters gaan via `from`/`to`, niet
via deze lijst.
