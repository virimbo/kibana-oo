"""Document-flow activity from logs: lifecycle events (created / updated /
deleted / retrieved), document types, errors, a timeline, and a live feed.
Read-only via the Kibana proxy. Action classification is best-effort keyword
matching and is meant to be tuned against the real logs."""
import asyncio
import re
from collections import Counter
from datetime import datetime

from pydantic import BaseModel

from elastic import _es_search
from config import settings
from monitoring import _flatten, period_bounds, timeseries_interval, summarize_doc, resolve_data_view

# Ordered: the first rule that matches the log message wins.
_ACTION_RULES = [
    ("deleted", re.compile(r"delet|verwijder|remov|ingetrokken|intrekking|purge", re.IGNORECASE)),
    ("created", re.compile(r"\b(store[sd]?|upload|created?|aangemaakt|ingest|indexed|publish|gepubliceerd|nieuw|added)\b", re.IGNORECASE)),
    ("updated", re.compile(r"update|gewijzigd|wijzig|mutatie|herpubli|version|versie", re.IGNORECASE)),
    ("retrieved", re.compile(r"retriev|ophalen|download|\bget\b|\bread\b|opgehaald", re.IGNORECASE)),
]

_FILE_RE = re.compile(
    r"([\w%.\-]+\.(pdf|xml|html?|json|csv|docx?|xlsx?|zip|txt|odt|jpe?g|png|tiff?))",
    re.IGNORECASE,
)


def classify_action(message: str | None) -> str:
    for name, rx in _ACTION_RULES:
        if rx.search(message or ""):
            return name
    return "other"


def extract_file(message: str | None) -> tuple[str | None, str | None]:
    m = _FILE_RE.search(message or "")
    if not m:
        return None, None
    return m.group(1), m.group(2).lower()


def _service(flat: dict) -> str | None:
    logger_name = flat.get("logger_name")
    if isinstance(logger_name, str) and logger_name:
        return ".".join(logger_name.split(".")[-2:])
    return flat.get("service.name") or flat.get("kubernetes.container_name") or None


def summarize_event(hit: dict) -> dict:
    src = hit.get("_source", {})
    flat = _flatten(src)
    base = summarize_doc(hit)  # reuse: label, code (doc id), link, preview
    message = str(flat.get("message", "") or "")
    level = str(flat.get("level") or flat.get("log.level") or "")
    filename, ftype = extract_file(message)
    return {
        "timestamp": src.get("@timestamp"),
        "action": classify_action(message),
        "status": "error" if level.upper() in ("ERROR", "FATAL", "CRITICAL") else "ok",
        "doc_id": base.get("code"),
        "link": base.get("link"),
        "filename": filename,
        "type": ftype,
        "service": _service(flat),
        "message": message[:200],
    }


def _event_query(start: datetime, end: datetime) -> dict:
    return {
        "bool": {
            "filter": [
                {"range": {"@timestamp": {"gte": start.isoformat(), "lt": end.isoformat()}}},
                {"query_string": {"query": settings.document_event_query, "default_field": "*", "lenient": True}},
            ]
        }
    }


def _timeseries_body(start: datetime, end: datetime, interval: str) -> dict:
    return {
        "size": 0,
        "track_total_hits": True,
        "query": _event_query(start, end),
        "aggs": {
            "over_time": {
                "date_histogram": {"field": "@timestamp", "fixed_interval": interval, "min_doc_count": 0}
            }
        },
    }


def _feed_body(start: datetime, end: datetime) -> dict:
    return {
        "size": settings.document_event_size,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": _event_query(start, end),
    }


class DocumentActivity(BaseModel):
    period_minutes: int
    data_view: str
    window_start: str
    window_end: str
    portal_base: str
    total: int
    unique_documents: int
    errors: int
    by_action: list[dict]
    by_type: list[dict]
    timeseries: list[dict]
    events: list[dict]


async def build_document_activity(sid: str, period_minutes: int, data_view: str | None) -> DocumentActivity:
    dv = resolve_data_view(data_view)
    start, end = period_bounds(period_minutes)
    interval = timeseries_interval(period_minutes)

    ts_res, feed_res = await asyncio.gather(
        _es_search(sid, dv, _timeseries_body(start, end, interval)),
        _es_search(sid, dv, _feed_body(start, end)),
        return_exceptions=True,
    )
    if isinstance(feed_res, Exception):
        raise feed_res  # the feed is the core — surfaced as 502 by the router

    events = [summarize_event(h) for h in feed_res.get("hits", {}).get("hits", [])]

    if isinstance(ts_res, Exception):
        total, timeseries = len(events), []
    else:
        total = ts_res.get("hits", {}).get("total", {}).get("value", len(events))
        timeseries = [
            {"timestamp": b["key_as_string"], "count": b["doc_count"]}
            for b in ts_res.get("aggregations", {}).get("over_time", {}).get("buckets", [])
        ]

    by_action = [{"action": a, "count": c} for a, c in Counter(e["action"] for e in events).most_common()]
    by_type = [{"type": t, "count": c} for t, c in Counter(e["type"] for e in events if e["type"]).most_common()]
    errors = sum(1 for e in events if e["status"] == "error")
    unique = len({(e["doc_id"] or e["filename"] or e["message"]) for e in events})

    return DocumentActivity(
        period_minutes=period_minutes,
        data_view=dv,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        portal_base=settings.portal_base_url,
        total=total,
        unique_documents=unique,
        errors=errors,
        by_action=by_action,
        by_type=by_type,
        timeseries=timeseries,
        events=events,
    )
