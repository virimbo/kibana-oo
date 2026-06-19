# Aanleverfouten monitor

Toont documenten die **geweigerd zijn bij aanlevering** (de doculoket
"Aanleverfouten") zodat admins in één oogopslag zien welke publishers documenten hebben
die faalden en gecorrigeerd en opnieuw aangeleverd moeten worden. Te vinden als card op
het **Dashboard** plus een globale header-badge.

## Waarom het niet in de publieke API staat

Wanneer een publisher een *set* aanlevert, verwerken sommige documenten prima (en worden
gepubliceerd) terwijl andere de validatie niet halen. **De gefaalde worden nooit
gepubliceerd**, dus de publieke openbaarmakingen-API kan ze niet zien — alleen de
geslaagde. Daarom gebeurt detectie in de logs, verzoend tegen het portaal.

## Hoe het werkt (detect → reconcile → persist → group)

1. **Detect** in `ds-prod5-koop-plooi` (instelbare data view). Een document is een
   aanleverfout-kandidaat wanneer een log-event matcht met het detectiesignaal:
   - een **structured status field** (`AANLEVER_STATUS_FIELD`) gelijk aan één van
     `AANLEVER_STATUS_VALUES`, als zo'n veld bestaat (meest precies), **of**
   - een fallback: een **error bij een intake/aanlever-service**
     (`AANLEVER_SERVICES`) of een **message die matcht** met `AANLEVER_PATTERNS`
     (`aanleverfout`, `afgekeurd`, `geweigerd`, `validatie`, `schema`, …).

   Het document-id is het `ronl-`-id indien aanwezig, anders de **UUID** in de message
   (aanleverfouten gebruiken de doculoket-UUID).

2. **Reconcile** elke kandidaat tegen open.overheid.nl. Als het document nu
   `gepubliceerd`/live is, was de error **fixed & opnieuw aangeleverd → auto-resolved**.
   Dit houdt de lijst vrij van false positives.

3. **Persist** als een duurzaam incident (`aanlever_incidents` in `kibana_oo.db`):
   - OPEN vanaf eerste detectie, overlevend over restarts en het scan-venster heen;
   - pas geopend na een **settle delay** (`AANLEVER_SETTLE_MINUTES`) zodat een
     transient error die meteen retry-slaagt nooit getoond wordt;
   - **auto-resolved** bij publicatie; **handmatig acknowledged** (dismissed) door een
     admin via de ✓-knop.

4. **Group** de open incidents **per publisher + error-type**, met een summary-headline
   en een **nieuw (laatste 24 u) vs. persisting**-split.

## Op het dashboard

- Een summary-headline ("⚠ N aanleverfouten bij M organisaties — K nieuw").
- Error-type-tags (Schema, Validatie, Afgekeurd, …).
- Per-publisher-groepen; elke row toont het document, de error, en:
  - de **titel** → klik om het document te **tracen**,
  - **↗** → open het in **doculoket** om te fixen & opnieuw aan te leveren,
  - **✓** → acknowledge/dismiss.
- Een **header-badge** op elke admin-pagina (open count), elke 60 s gepolld.

## Alerts & digest

Bij **nieuwe** aanleverfouten (deduped — eenmalig gealert wanneer het incident opent),
gaat een alert uit via de digest-webhook + email (`AANLEVER_ALERT_ENABLED`). Zet
`DIGEST_WEBHOOK_URL` / SMTP voor de bezorging.

## Configuratie (`.env`)

| Var | Default | Doel |
|---|---|---|
| `AANLEVER_ENABLED` | `true` | Hoofdschakelaar |
| `AANLEVER_DATA_VIEW` | `ds-prod5-koop-plooi*` | Index om te scannen |
| `AANLEVER_LOOKBACK_HOURS` | `48` | Detectie-venster |
| `AANLEVER_STATUS_FIELD` | _(leeg)_ | Structured status field, indien aanwezig (meest precies) |
| `AANLEVER_STATUS_VALUES` | `aanleverfout,afgekeurd,…` | Waarden die "rejected" betekenen |
| `AANLEVER_SERVICES` | `doculoket,aanlever,…` | Intake-services voor het fallback-signaal |
| `AANLEVER_PATTERNS` | `aanleverfout,afgekeurd,…` | Message-frasen voor het fallback-signaal |
| `AANLEVER_SETTLE_MINUTES` | `10` | Zo lang persisten voordat het een incident is |
| `AANLEVER_ALERT_ENABLED` | `true` | Alert op nieuw |

## ⚠️ Kalibratie

De detectiepatronen worden met zinnige defaults geleverd maar moeten **afgestemd worden
op de echte `ds-prod5-koop-plooi`-logs** — bevestig of er een structured status field
bestaat (zet `AANLEVER_STATUS_FIELD` zo ja; het is het meest precieze signaal) en dat de
keyword/service-lijsten matchen met hoe weigeringen daadwerkelijk gelogd worden. De
reconciliatie-stap betekent dat een verkeerd afgestemd patroon *geen* false positives
oplevert (een gepubliceerd doc wordt altijd uitgefilterd), alleen potentiële misses.

## API

| Method | Path | Doel |
|---|---|---|
| GET | `/dashboard/aanleverfouten` | Gegroepeerde open lijst + summary + count (cached) |
| POST | `/dashboard/aanleverfouten/{doc_id}/ack` | Acknowledge / dismiss |
