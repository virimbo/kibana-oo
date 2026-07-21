"""SQLite persistence for admin-managed Mattermost webhook targets (shared
kibana_oo.db via db.py).

Why: the app posts alerts to a single Mattermost incoming webhook. In practice
there are several — one per environment (ACC / TST / PROD). Editing
DIGEST_WEBHOOK_URL in .env and redeploying every time you switch is slow and
error-prone. This store lets a super admin keep all the webhooks side by side
and flip the ACTIVE one in one click from Beheer.

Fail-safe & additive: active_url() falls back to settings.digest_webhook_url
whenever no managed webhook is active, so alert dispatch behaves exactly as
before until an admin opts in by adding + activating a webhook here. Only one
webhook is active at a time.
"""
from __future__ import annotations

import os
from contextlib import closing
from datetime import datetime, timezone

import db
from config import settings

# A stored value may be a literal URL **or** an `env:VARNAME` reference. The
# reference form keeps the secret OUT of the database — only the env-var NAME is
# stored; the real URL lives in the (encrypted) .env. Recommended for production.
_ENV_PREFIX = "env:"


def resolve_url(value: str | None) -> str:
    """Effective URL for a stored value: resolves `env:VARNAME` from the
    environment, or returns the literal URL. "" when unset/missing."""
    v = (value or "").strip()
    if v.startswith(_ENV_PREFIX):
        return os.environ.get(v[len(_ENV_PREFIX):].strip(), "").strip()
    return v

_SCHEMA = """
CREATE TABLE IF NOT EXISTS mattermost_webhooks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    label      TEXT NOT NULL,
    url        TEXT NOT NULL,
    active     INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn():
    conn = db.connect()
    conn.executescript(_SCHEMA)
    return conn


def mask_url(url: str) -> str:
    """A recognisable-but-safe rendering of a webhook URL for the UI. Mattermost
    incoming-webhook URLs look like ``https://host/hooks/<secret-code>``; we show
    the host + ``/hooks/`` and only the last 4 characters of the secret so an
    admin can tell webhooks apart without the full token being exposed."""
    if not url:
        return ""
    if url.strip().startswith(_ENV_PREFIX):
        return url.strip()          # a variable NAME, not a secret — safe to show
    if "/hooks/" in url:
        head, code = url.split("/hooks/", 1)
        tail = code[-4:] if len(code) > 4 else code
        return f"{head}/hooks/…{tail}"
    # Non-standard URL: reveal only the scheme+host and a short tail.
    tail = url[-4:] if len(url) > 4 else url
    return f"{url[:24]}…{tail}"


def _row(r, *, reveal: bool = False) -> dict:
    return {
        "id": r["id"],
        "label": r["label"],
        "url": r["url"] if reveal else mask_url(r["url"]),
        "active": bool(r["active"]),
        "updated_at": r["updated_at"],
        "updated_by": r["updated_by"],
    }


def list_webhooks(*, reveal: bool = False) -> list[dict]:
    """All configured webhooks, active first then by label. URLs are masked
    unless ``reveal`` is set (never reveal in an API response)."""
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM mattermost_webhooks ORDER BY active DESC, label COLLATE NOCASE, id"
        ).fetchall()
    return [_row(r, reveal=reveal) for r in rows]


def get_webhook(wid: int, *, reveal: bool = False) -> dict | None:
    with closing(_conn()) as conn:
        r = conn.execute("SELECT * FROM mattermost_webhooks WHERE id=?", (wid,)).fetchone()
    return _row(r, reveal=reveal) if r else None


def add_webhook(label: str, url: str, actor: str | None) -> dict:
    """Insert a webhook. If it is the first one configured, it becomes active
    automatically so the feature works with a single action."""
    with closing(_conn()) as conn:
        has_any = conn.execute("SELECT 1 FROM mattermost_webhooks LIMIT 1").fetchone() is not None
        active = 0 if has_any else 1
        cur = conn.execute(
            "INSERT INTO mattermost_webhooks (label, url, active, updated_at, updated_by) "
            "VALUES (?,?,?,?,?)", (label, url, active, _now(), actor))
        conn.commit()
        wid = cur.lastrowid
    return get_webhook(wid)  # type: ignore[return-value]


def update_webhook(wid: int, *, label: str | None, url: str | None, actor: str | None) -> dict | None:
    sets, params = [], []
    if label is not None:
        sets.append("label=?"); params.append(label)
    if url is not None:
        sets.append("url=?"); params.append(url)
    if not sets:
        return get_webhook(wid)
    sets.append("updated_at=?"); params.append(_now())
    sets.append("updated_by=?"); params.append(actor)
    params.append(wid)
    with closing(_conn()) as conn:
        cur = conn.execute(
            f"UPDATE mattermost_webhooks SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
        if cur.rowcount == 0:
            return None
    return get_webhook(wid)


def delete_webhook(wid: int) -> bool:
    with closing(_conn()) as conn:
        cur = conn.execute("DELETE FROM mattermost_webhooks WHERE id=?", (wid,))
        conn.commit()
        return cur.rowcount > 0


def set_active(wid: int, actor: str | None) -> dict | None:
    """Make ``wid`` the single active webhook (clears the flag on all others).
    Returns the now-active row, or None if the id does not exist."""
    with closing(_conn()) as conn:
        if conn.execute("SELECT 1 FROM mattermost_webhooks WHERE id=?", (wid,)).fetchone() is None:
            return None
        conn.execute("UPDATE mattermost_webhooks SET active=0 WHERE active=1")
        conn.execute("UPDATE mattermost_webhooks SET active=1, updated_at=?, updated_by=? WHERE id=?",
                     (_now(), actor, wid))
        conn.commit()
    return get_webhook(wid)


def get_active(*, reveal: bool = False) -> dict | None:
    with closing(_conn()) as conn:
        r = conn.execute(
            "SELECT * FROM mattermost_webhooks WHERE active=1 ORDER BY id LIMIT 1").fetchone()
    return _row(r, reveal=reveal) if r else None


def active_url() -> str:
    """The webhook URL alert dispatch should post to: the admin-selected active
    webhook, or settings.digest_webhook_url as a fail-safe fallback (so behaviour
    is unchanged until an admin activates a managed webhook)."""
    with closing(_conn()) as conn:
        r = conn.execute(
            "SELECT url FROM mattermost_webhooks WHERE active=1 ORDER BY id LIMIT 1").fetchone()
    if r and r["url"]:
        return resolve_url(r["url"])     # resolves an env:VARNAME reference
    return settings.digest_webhook_url


def fallback_configured() -> bool:
    """Whether the static .env DIGEST_WEBHOOK_URL is set (used by the UI to
    explain what happens when no managed webhook is active)."""
    return bool(settings.digest_webhook_url)
