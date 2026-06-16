"""Aanleverfouten monitor — documents rejected at delivery/intake.

The doculoket "Aanleverfouten" concept: a publisher delivers a set, one or more
documents fail validation and are NEVER published; the publisher must fix and
re-deliver. Those errored documents are invisible to the public API (only the
successful ones get published), so we detect them in the ds-prod5-koop-plooi
logs, RECONCILE against open.overheid.nl (a now-published doc means it was fixed
& re-delivered → resolved), and track each as a DURABLE incident: OPEN from first
detection (after a settle delay), surviving restarts and the scan window, until
it is published or manually acknowledged. Grouped by publisher + error type.

Detection is configurable (structured-field-first, else stage + message
patterns) so it can be tuned to the real logs without code changes — see
config.aanlever_* and docs/aanleverfouten.md.
"""
import asyncio
import logging
from contextlib import closing
from datetime import datetime, timedelta, timezone

import db
import notify
from config import settings
from documents import _UUID_RE, _event_doc_id, _portal_id, summarize_event
from elastic import _es_search
from pipeline import is_published
from portal import fetch_document_meta

logger = logging.getLogger(__name__)


# ── Error-type classification (what KIND of aanleverfout) ─────────────────────
_TYPE_LABELS = {
    "schema": "Schema / structuur",
    "validatie": "Validatie",
    "validation": "Validatie",
    "afgekeurd": "Afgekeurd",
    "geweigerd": "Geweigerd",
    "rejected": "Afgewezen",
    "invalid": "Ongeldig",
    "niet geldig": "Ongeldig",
    "herstel": "Herstel vereist",
    "aanleverfout": "Aanleverfout",
}


def _error_type(message: str) -> tuple[str, str]:
    """(key, human label) for the kind of delivery error, from the message."""
    low = (message or "").lower()
    for kw, label in _TYPE_LABELS.items():
        if kw in low:
            return kw.replace(" ", "_"), label
    return "aanleverfout", "Aanleverfout"


def _is_aanlever_event(e: dict) -> bool:
    """Does this parsed log event look like a delivery/intake rejection?
    Structured status field wins; else an error at an intake service, or a
    message matching the configured aanlever phrases."""
    msg = (e.get("message") or "").lower()
    svc = (e.get("service") or "").lower()
    if any(p in msg for p in settings.aanlever_pattern_list):
        return True
    if e.get("severity") == "error" and any(s in svc for s in settings.aanlever_service_list):
        return True
    return False


# ── Elasticsearch query ───────────────────────────────────────────────────────
def _query(start: datetime, end: datetime) -> dict:
    """Best-effort: structured status field (if configured) OR an error/phrase
    signal in the window. Deliberately broad — the parse step + reconciliation
    filter it down, and the patterns are tunable."""
    should = [{"match_phrase": {"message": p}} for p in settings.aanlever_pattern_list]
    for svc in settings.aanlever_service_list:
        should.append({"wildcard": {"logger_name": f"*{svc}*"}})
    error_signal = {
        "bool": {
            "must": [{"terms": {"level": ["ERROR", "FATAL", "WARN"]}}],
            "should": should,
            "minimum_should_match": 1,
        }
    }
    top_should = [error_signal]
    if settings.aanlever_status_field:
        top_should.append(
            {"terms": {settings.aanlever_status_field: settings.aanlever_status_value_list}}
        )
    return {
        "size": 500,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {
            "bool": {
                "must": [{"range": {"@timestamp": {"gte": start.isoformat(), "lte": end.isoformat()}}}],
                "should": top_should,
                "minimum_should_match": 1,
            }
        },
        "_source": True,
    }


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def parse_candidates(hits: list[dict]) -> dict[str, dict]:
    """Group aanlever-error events by document id → one candidate per document
    (latest error wins for the displayed message/type)."""
    by_doc: dict[str, list[dict]] = {}
    for h in hits:
        e = summarize_event(h)
        if not _is_aanlever_event(e):
            continue
        # ronl- id if present, else a UUID in the message (aanleverfouten use the
        # doculoket UUID, which the default ronl- extractor does not catch).
        did = _event_doc_id(e)
        if not did:
            m = _UUID_RE.search(e.get("message") or "")
            did = m.group(0) if m else None
        if not did:
            continue
        by_doc.setdefault(did, []).append(e)

    candidates: dict[str, dict] = {}
    for did, evs in by_doc.items():
        evs.sort(key=lambda e: e.get("timestamp") or "")
        latest = evs[-1]
        times = [t for t in (_parse_ts(e.get("timestamp")) for e in evs) if t]
        key, label = _error_type(latest.get("message") or "")
        candidates[did] = {
            "doc_id": did,
            "portal_uuid": _portal_id(did),
            "publisher": next((e.get("org") for e in reversed(evs) if e.get("org")), None),
            "error_key": key,
            "error_type": label,
            "message": (latest.get("message") or "")[:300],
            "service": latest.get("service"),
            "first_error_at": (min(times).isoformat() if times else None),
            "last_error_at": (max(times).isoformat() if times else None),
            "events": len(evs),
        }
    return candidates


# ── Scan: detect → reconcile → persist → alert ───────────────────────────────
async def scan(sid: str, data_view: str | None = None, now: datetime | None = None) -> dict:
    """Run one detection pass and return the active grouped view. Reconciles each
    candidate against the portal, opens/closes durable incidents, and alerts on
    NEW ones. Never raises into a request."""
    if not settings.aanlever_enabled:
        return _view([], now or datetime.now(timezone.utc))
    now = now or datetime.now(timezone.utc)
    dv = data_view or settings.aanlever_data_view
    start = now - timedelta(hours=settings.aanlever_lookback_hours)

    try:
        res = await _es_search(sid, dv, _query(start, now))
        hits = res.get("hits", {}).get("hits", [])
    except Exception as e:  # noqa: BLE001
        logger.error(f"Aanlever scan query failed: {e}")
        open_now = await asyncio.to_thread(_list_open_sync)
        return _view(open_now, now)

    candidates = parse_candidates(hits)
    settle = timedelta(minutes=settings.aanlever_settle_minutes)
    newly_opened: list[dict] = []
    seen_open_ids: set[str] = set()

    for did, c in candidates.items():
        portal_uuid = c["portal_uuid"]
        meta = await fetch_document_meta(portal_uuid)
        if meta and is_published(meta.get("status")):
            await asyncio.to_thread(_resolve_sync, did, "published on open.overheid.nl", now)
            continue
        first_err = _parse_ts(c["first_error_at"]) or now
        if (now - first_err) < settle:
            continue  # transient — hasn't persisted long enough to be an incident
        c["title"] = (meta or {}).get("title")
        c["link"] = settings.doculoket_link_template.format(id=portal_uuid)
        was_new = await asyncio.to_thread(_upsert_open_sync, c, now)
        seen_open_ids.add(did)
        if was_new:
            newly_opened.append(c)

    # Auto-resolve incidents that are published now even if absent from this scan.
    stale = await asyncio.to_thread(_resolve_published_absent_sync, seen_open_ids, now)
    for did, uuid in stale:
        meta = await fetch_document_meta(uuid)
        if meta and is_published(meta.get("status")):
            await asyncio.to_thread(_resolve_sync, did, "published on open.overheid.nl", now)

    if newly_opened and settings.aanlever_alert_enabled:
        try:
            await _alert(newly_opened)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Aanlever alert failed: {e}")

    open_now = await asyncio.to_thread(_list_open_sync)
    return _view(open_now, now)


def _view(open_incidents: list[dict], now: datetime) -> dict:
    """Group open incidents by publisher + error type, with a summary and a
    new-vs-persisting split (new = first seen in the last 24h)."""
    day_ago = (now - timedelta(hours=24)).isoformat()
    publishers: dict[str, dict] = {}
    by_type: dict[str, int] = {}
    new_count = 0
    for inc in open_incidents:
        pub = inc.get("publisher") or "Onbekende organisatie"
        g = publishers.setdefault(pub, {"publisher": pub, "incidents": [], "count": 0})
        is_new = (inc.get("first_detected") or "") >= day_ago
        if is_new:
            new_count += 1
        row = {**inc, "is_new": is_new}
        g["incidents"].append(row)
        g["count"] += 1
        by_type[inc.get("error_type") or "Aanleverfout"] = by_type.get(inc.get("error_type") or "Aanleverfout", 0) + 1

    groups = sorted(publishers.values(), key=lambda x: -x["count"])
    for g in groups:
        g["incidents"].sort(key=lambda i: i.get("first_detected") or "", reverse=True)
    total = len(open_incidents)
    headline = (
        f"{total} aanleverfout{'en' if total != 1 else ''} bij {len(groups)} "
        f"organisatie{'s' if len(groups) != 1 else ''}"
        + (f" — {new_count} nieuw" if new_count else "")
        if total else "Geen openstaande aanleverfouten."
    )
    return {
        "count": total,
        "new_count": new_count,
        "headline": headline,
        "groups": groups,
        "by_type": [{"type": t, "count": n} for t, n in sorted(by_type.items(), key=lambda x: -x[1])],
    }


async def count_open() -> int:
    return await asyncio.to_thread(_count_open_sync)


async def acknowledge(doc_id: str, now: datetime | None = None) -> bool:
    return await asyncio.to_thread(_ack_sync, doc_id, now or datetime.now(timezone.utc))


async def _alert(newly: list[dict]) -> None:
    lines = [f"⚠ {len(newly)} nieuwe aanleverfout(en) gedetecteerd", ""]
    for c in newly:
        who = c.get("publisher") or "onbekende organisatie"
        lines.append(f"• {who} — {c.get('error_type')} · {c.get('title') or c.get('doc_id')}")
    lines.append("")
    lines.append("Open het dashboard → Aanleverfouten om te herstellen en opnieuw aan te leveren.")
    text = "\n".join(lines)
    await notify.send_webhook(text)
    await asyncio.to_thread(notify.send_email,
                            f"⚠ {len(newly)} nieuwe aanleverfout(en)",
                            "<pre>" + text.replace("<", "&lt;") + "</pre>", text)


# ── SQLite persistence (shared app DB) ────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS aanlever_incidents (
    doc_id         TEXT PRIMARY KEY,
    portal_uuid    TEXT,
    publisher      TEXT,
    error_key      TEXT,
    error_type     TEXT,
    message        TEXT,
    service        TEXT,
    link           TEXT,
    title          TEXT,
    first_detected TEXT NOT NULL,
    last_detected  TEXT NOT NULL,
    last_error_at  TEXT,
    status         TEXT NOT NULL DEFAULT 'open',   -- open | resolved
    acknowledged   INTEGER NOT NULL DEFAULT 0,
    resolved_at    TEXT,
    resolution     TEXT
);
CREATE INDEX IF NOT EXISTS idx_aanlever_status ON aanlever_incidents(status);
"""


def _conn():
    conn = db.connect()
    conn.executescript(_SCHEMA)
    return conn


def _upsert_open_sync(c: dict, now: datetime) -> bool:
    """Open a new incident or refresh an existing one. Returns True if NEW (so the
    caller can alert exactly once). first_detected is set once and never moved."""
    now_iso = now.isoformat()
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT first_detected, status FROM aanlever_incidents WHERE doc_id = ?", (c["doc_id"],)
        ).fetchone()
        is_new = row is None or row["status"] == "resolved"
        first = now_iso if is_new else row["first_detected"]
        conn.execute(
            """INSERT INTO aanlever_incidents
               (doc_id, portal_uuid, publisher, error_key, error_type, message, service,
                link, title, first_detected, last_detected, last_error_at, status, acknowledged,
                resolved_at, resolution)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'open',
                       COALESCE((SELECT acknowledged FROM aanlever_incidents WHERE doc_id=?), 0),
                       NULL, NULL)
               ON CONFLICT(doc_id) DO UPDATE SET
                 publisher=excluded.publisher, error_key=excluded.error_key,
                 error_type=excluded.error_type, message=excluded.message,
                 service=excluded.service, link=excluded.link, title=excluded.title,
                 last_detected=excluded.last_detected, last_error_at=excluded.last_error_at,
                 status='open', resolved_at=NULL, resolution=NULL""",
            (c["doc_id"], c["portal_uuid"], c["publisher"], c["error_key"], c["error_type"],
             c["message"], c["service"], c["link"], c.get("title"), first, now_iso,
             c.get("last_error_at"), c["doc_id"]),
        )
        conn.commit()
    return is_new


def _resolve_sync(doc_id: str, resolution: str, now: datetime) -> bool:
    with closing(_conn()) as conn:
        cur = conn.execute(
            "UPDATE aanlever_incidents SET status='resolved', resolved_at=?, resolution=? "
            "WHERE doc_id=? AND status='open'",
            (now.isoformat(), resolution, doc_id),
        )
        conn.commit()
        return cur.rowcount > 0


def _resolve_published_absent_sync(seen_ids: set[str], now: datetime) -> list[tuple[str, str]]:
    """Open incidents NOT seen in this scan — candidates to verify as published."""
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT doc_id, portal_uuid FROM aanlever_incidents WHERE status='open'"
        ).fetchall()
    return [(r["doc_id"], r["portal_uuid"]) for r in rows if r["doc_id"] not in seen_ids]


def _ack_sync(doc_id: str, now: datetime) -> bool:
    with closing(_conn()) as conn:
        cur = conn.execute(
            "UPDATE aanlever_incidents SET acknowledged=1 WHERE doc_id=? AND status='open'", (doc_id,)
        )
        conn.commit()
        return cur.rowcount > 0


def _list_open_sync() -> list[dict]:
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM aanlever_incidents WHERE status='open' AND acknowledged=0 "
            "ORDER BY first_detected DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def _count_open_sync() -> int:
    with closing(_conn()) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM aanlever_incidents WHERE status='open' AND acknowledged=0"
        ).fetchone()[0]
