"""Shared SQLite database for feature run/audit logs.

One file (settings.app_db_path), a table per feature, behind a single connection
helper. Each feature module owns its own schema (CREATE TABLE IF NOT EXISTS) but
shares this connection so there is one thing to mount, persist and back up.

The durable incident store (incidents.py) intentionally keeps its OWN file: it
holds live prod incident state and is a different concern, so it is not merged
here to avoid migration risk. See docs/database.md.
"""
import sqlite3
from contextlib import closing, contextmanager

from config import settings


def connect() -> sqlite3.Connection:
    """A configured connection to the shared app database. WAL for safe concurrent
    reads/writes; foreign keys ON so ON DELETE CASCADE works for child rows."""
    conn = sqlite3.connect(settings.app_db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")  # wait, don't error, if briefly locked
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def cursor():
    """Connection context that commits on success and always closes."""
    with closing(connect()) as conn:
        yield conn
        conn.commit()
