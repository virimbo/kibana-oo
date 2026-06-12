"""Durable store of OPEN document incidents.

A single point-in-time log scan cannot tell "stuck forever" from "will move in
two minutes", and the 24-hour scan window silently drops documents that have been
stuck for days. This store closes both gaps: once a document is confirmed a
genuine incident (settled + not live), it is kept OPEN — across restarts and
beyond the scan window — until it is actually resolved (published, or progressed
to a later stage). So the at-risk list shows only real, unresolved problems and
keeps showing them, for days if necessary, until they are solved.

SQLite is used for durability and safe concurrent reads/writes. All blocking
calls are run off the event loop via asyncio.to_thread.
"""
import asyncio
import sqlite3
from contextlib import closing
from datetime import datetime

from config import settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    doc_id         TEXT PRIMARY KEY,
    data_view      TEXT,
    stage          TEXT,
    stage_index    INTEGER DEFAULT -1,
    verdict        TEXT,
    headline       TEXT,
    title          TEXT,
    link           TEXT,
    events         INTEGER DEFAULT 0,
    service        TEXT,
    pipeline       TEXT,
    first_detected TEXT NOT NULL,
    last_detected  TEXT NOT NULL,
    last_activity  TEXT,
    status         TEXT NOT NULL DEFAULT 'open',
    resolved_at    TEXT,
    resolution     TEXT
);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
"""

# Columns added after the first release — applied to existing databases as safe,
# additive migrations so an upgrade never loses or breaks stored incidents.
_ADDED_COLUMNS = {"service": "TEXT", "pipeline": "TEXT"}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.incident_db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(incidents)")}
    for col, col_type in _ADDED_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE incidents ADD COLUMN {col} {col_type}")
    conn.commit()
    return conn


# ── synchronous cores (run in a thread) ─────────────────────────────────────
def _upsert_open_sync(rec: dict, now_iso: str) -> None:
    """Open a new incident, or refresh an existing one. first_detected is set
    once and never moved, so an incident's age reflects when the problem began."""
    with closing(_connect()) as c:
        row = c.execute(
            "SELECT first_detected FROM incidents WHERE doc_id = ?", (rec["id"],)
        ).fetchone()
        first = row["first_detected"] if row else now_iso
        c.execute(
            """
            INSERT INTO incidents (
                doc_id, data_view, stage, stage_index, verdict, headline, title,
                link, events, service, pipeline, first_detected, last_detected,
                last_activity, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'open')
            ON CONFLICT(doc_id) DO UPDATE SET
                data_view     = excluded.data_view,
                stage         = excluded.stage,
                stage_index   = excluded.stage_index,
                verdict       = excluded.verdict,
                headline      = excluded.headline,
                title         = excluded.title,
                link          = excluded.link,
                events        = excluded.events,
                service       = excluded.service,
                pipeline      = excluded.pipeline,
                last_detected = excluded.last_detected,
                last_activity = excluded.last_activity,
                status        = 'open',
                resolved_at   = NULL,
                resolution    = NULL
            """,
            (
                rec["id"], rec.get("data_view"), rec.get("stuck_stage"),
                rec.get("stage_index", -1), rec.get("verdict"), rec.get("headline"),
                rec.get("title"), rec.get("link"), rec.get("events", 0),
                rec.get("service"), rec.get("pipeline"),
                first, now_iso, rec.get("last_seen"),
            ),
        )
        c.commit()


def _resolve_sync(doc_id: str, resolution: str, now_iso: str) -> bool:
    with closing(_connect()) as c:
        cur = c.execute(
            "UPDATE incidents SET status='resolved', resolved_at=?, resolution=? "
            "WHERE doc_id=? AND status='open'",
            (now_iso, resolution, doc_id),
        )
        c.commit()
        return cur.rowcount > 0


def _open_incidents_sync() -> list[dict]:
    with closing(_connect()) as c:
        rows = c.execute(
            "SELECT * FROM incidents WHERE status='open' ORDER BY first_detected ASC"
        ).fetchall()
        return [dict(r) for r in rows]


# ── async API ───────────────────────────────────────────────────────────────
async def upsert_open(rec: dict, now: datetime) -> None:
    await asyncio.to_thread(_upsert_open_sync, rec, now.isoformat())


async def resolve(doc_id: str, resolution: str, now: datetime) -> bool:
    """Mark an open incident resolved ('published' | 'progressed'). Returns True
    if an open incident was actually closed."""
    return await asyncio.to_thread(_resolve_sync, doc_id, resolution, now.isoformat())


async def open_incidents() -> list[dict]:
    """All currently-open incidents, oldest first."""
    return await asyncio.to_thread(_open_incidents_sync)
