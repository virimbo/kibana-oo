# Database architecture

KIBANA-OO uses **SQLite** for its small, durable state. There are **two files**,
by design, on the mounted data volume.

## 1. `incidents.db` — durable incident store

Owned by `backend/incidents.py`. Holds live, long-lived **document incident**
state (documents stuck in the pipeline, kept OPEN across restarts and beyond the
scan window until resolved). This is a distinct domain with its own lifecycle, so
it keeps its own file — it is intentionally **not** merged into the shared DB to
avoid migration risk to live prod data.

## 2. `kibana_oo.db` — shared app database (feature run/audit logs)

Owned by `backend/db.py`, with **one table per feature**. This is where
"run / audit log" style data lives, so there is a single file to mount, persist
and back up. Connection helper:

```python
import db
with db.cursor() as conn:      # commits on success, always closes
    conn.execute(...)
```

`db.connect()` sets `PRAGMA journal_mode=WAL` (safe concurrent reads/writes) and
`PRAGMA foreign_keys=ON` (so `ON DELETE CASCADE` works). Each feature module owns
its own `CREATE TABLE IF NOT EXISTS` schema and shares this connection.

### Tables

**Regression test** (`backend/regression.py`) — hybrid schema:

- `regression_runs` — one row per run (summary): `run_id`, `started`, `finished`,
  `verdict`, `trigger`, `target`, `duration_ms`, counts, `changes`. Powers the
  history list and verdict trend without a join.
- `regression_checks` — one row per check (`run_id` FK → `regression_runs`,
  `ON DELETE CASCADE`): `check_id`, `name`, `severity`, `status`, `detail`,
  `http_status`, `response_ms`, `url`, `method`, `expected`, `actual`,
  `evidence`. Powers drill-down and per-check reliability queries.

Why hybrid (not a single JSON blob): keeping checks as rows lets us answer
cross-run questions — "how often has the document-file check failed in the last
50 runs?" — with a `GROUP BY check_id`, instead of parsing thousands of JSON
blobs. The summary columns on the run row keep the history list fast.

### Retention

Per feature. Regression uses a **failure-aware count cap**
(`REGRESSION_HISTORY_CAP`, default 1000): when over the cap, prune **oldest PASS
first** so WARN/FAIL records survive longest, and never prune the most recent
run. Child `regression_checks` rows cascade-delete with their run.

## Adding a new feature table

1. Add `CREATE TABLE IF NOT EXISTS <feature>_… ` to the feature module.
2. Use `db.connect()` / `db.cursor()` — do not open `kibana_oo.db` directly
   elsewhere.
3. Decide a retention policy and document it here.

## Operations

Both files live under `/app/data` (mount this on a volume in
`docker-compose.yml`). Back up the directory; WAL means a `.db`, `.db-wal` and
`.db-shm` per database — copy all three (or checkpoint first).
