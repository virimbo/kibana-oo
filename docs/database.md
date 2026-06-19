# Database-architectuur

KIBANA-OO gebruikt **SQLite** voor zijn kleine, duurzame state. Er zijn — bewust —
**twee bestanden**, op het gemounte data-volume.

## 1. `incidents.db` — duurzame incident-store

Eigenaar: `backend/incidents.py`. Bevat live, langlevende **document-incident**-state
(documenten die stuck zitten in de pipeline, OPEN gehouden over restarts heen en
buiten het scan-venster tot ze opgelost zijn). Dit is een apart domein met een eigen
lifecycle, dus het houdt zijn eigen bestand — het is bewust **niet** samengevoegd met
de gedeelde DB om migratierisico op live prod-data te vermijden.

## 2. `kibana_oo.db` — gedeelde app-database (feature run/audit logs)

Eigenaar: `backend/db.py`, met **één tabel per feature**. Hier leeft "run / audit
log"-achtige data, zodat er één bestand is om te mounten, te persisten en te backuppen.
Connection-helper:

```python
import db
with db.cursor() as conn:      # commits on success, always closes
    conn.execute(...)
```

`db.connect()` zet `PRAGMA journal_mode=WAL` (veilige concurrent reads/writes) en
`PRAGMA foreign_keys=ON` (zodat `ON DELETE CASCADE` werkt). Elke feature-module bezit
zijn eigen `CREATE TABLE IF NOT EXISTS`-schema en deelt deze connection.

### Tabellen

**Regression test** (`backend/regression.py`) — hybride schema:

- `regression_runs` — één row per run (summary): `run_id`, `started`, `finished`,
  `verdict`, `trigger`, `target`, `duration_ms`, counts, `changes`. Voedt de
  history-lijst en de verdict-trend zonder join.
- `regression_checks` — één row per check (`run_id` FK → `regression_runs`,
  `ON DELETE CASCADE`): `check_id`, `name`, `severity`, `status`, `detail`,
  `http_status`, `response_ms`, `url`, `method`, `expected`, `actual`,
  `evidence`. Voedt de drill-down en per-check reliability-queries.

Waarom hybride (niet één JSON-blob): checks als rows houden laat ons cross-run vragen
beantwoorden — "hoe vaak is de document-file-check gefaald in de laatste 50 runs?" —
met een `GROUP BY check_id`, in plaats van duizenden JSON-blobs te parsen. De
summary-kolommen op de run-row houden de history-lijst snel.

**RabbitMQ DLQ** (`backend/rabbitmq_dlq.py`) — `dlq_state`: één row per momenteel
niet-lege dead-letter queue (`first_seen` voor age, `alerted` voor dedup). Verwijderd
wanneer de queue draint — de broker is de realtime source of truth voor depth, dus
alleen deze minimale state wordt opgeslagen. Zie [rabbitmq-dlq.md](rabbitmq-dlq.md).

**Authorization** (`backend/permissions.py`) — `feature_grants` (één row per
`username`+`feature`, de access-matrix), `feature_grants_audit` (elke
grant/revoke/seed met actor + timestamp), en `feature_grants_meta` (de run-once
seed-flag). Super admins staan in config, niet hier. Zie
[authorization.md](authorization.md).

**Aanleverfouten** (`backend/aanlever.py`) — `aanlever_incidents`: één row per
geweigerd document (`doc_id` PK), met `publisher`, `error_key`/`error_type`,
`message`, `link` (doculoket), `title`, `first_detected`/`last_detected`,
`status` (open|resolved), en `acknowledged`. Een duurzame incident-store (zoals die
voor stuck docs, maar in de gedeelde DB): OPEN tot het document op open.overheid.nl is
gepubliceerd (auto-resolved) of een admin het acknowledged. Zie
[aanleverfouten.md](aanleverfouten.md).

### Retentie

Per feature. Regression gebruikt een **failure-aware count cap**
(`REGRESSION_HISTORY_CAP`, default 1000): bij overschrijding wordt **oudste PASS
eerst** geprunet zodat WARN/FAIL-records het langst overleven, en de meest recente run
nooit verwijderd. Child `regression_checks`-rows cascade-deleten met hun run.

## Een nieuwe feature-tabel toevoegen

1. Voeg `CREATE TABLE IF NOT EXISTS <feature>_… ` toe aan de feature-module.
2. Gebruik `db.connect()` / `db.cursor()` — open `kibana_oo.db` niet direct ergens
   anders.
3. Bepaal een retentiebeleid en documenteer het hier.

## Operations

Beide bestanden leven onder `/app/data` (mount dit op een volume in
`docker-compose.yml`). Back-up de directory; WAL betekent een `.db`, `.db-wal` en
`.db-shm` per database — kopieer alle drie (of checkpoint eerst).
