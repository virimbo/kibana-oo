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
from monitoring import _flatten, _first_field, period_bounds, timeseries_interval, summarize_doc, resolve_data_view

_ERROR_LEVELS = ["error", "ERROR", "fatal", "FATAL", "critical", "CRITICAL"]

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
    org = _first_field(src, settings.doc_org_fields)
    return {
        "timestamp": src.get("@timestamp"),
        "action": classify_action(message),
        "status": "error" if level.upper() in ("ERROR", "FATAL", "CRITICAL") else "ok",
        "doc_id": base.get("code"),
        "link": base.get("link"),
        "filename": filename,
        "type": ftype,
        "org": org if isinstance(org, str) else None,
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


def _error_query(start: datetime, end: datetime) -> dict:
    """Document events that are errors (top-level `level`, ECS `log.level`, or error.message)."""
    q = _event_query(start, end)
    q["bool"]["filter"].append({
        "bool": {
            "minimum_should_match": 1,
            "should": [
                {"terms": {"level": _ERROR_LEVELS}},
                {"terms": {"log.level": _ERROR_LEVELS}},
                {"exists": {"field": "error.message"}},
            ],
        }
    })
    return q


def _failed_body(start: datetime, end: datetime) -> dict:
    return {
        "size": 20,
        "track_total_hits": True,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": _error_query(start, end),
    }


def _error_count_body(start: datetime, end: datetime) -> dict:
    return {"size": 0, "track_total_hits": True, "query": _error_query(start, end)}


def _alert_level(errors: int, pct_change: float | None) -> str:
    if errors >= 10 or (errors > 0 and pct_change is not None and pct_change >= 100):
        return "critical"
    return "warning" if errors > 0 else "ok"


_WARN_ERROR_LEVELS = ["warn", "WARN", "warning", "WARNING"] + _ERROR_LEVELS


def _issues_query(start: datetime, end: datetime) -> dict:
    """Document events at WARN or ERROR level (covers mapping warnings + errors)."""
    q = _event_query(start, end)
    q["bool"]["filter"].append({
        "bool": {
            "minimum_should_match": 1,
            "should": [
                {"terms": {"level": _WARN_ERROR_LEVELS}},
                {"terms": {"log.level": _WARN_ERROR_LEVELS}},
                {"exists": {"field": "error.message"}},
            ],
        }
    })
    return q


def _issues_body(start: datetime, end: datetime) -> dict:
    return {"size": 300, "sort": [{"@timestamp": {"order": "desc"}}], "query": _issues_query(start, end)}


def detect_source(doc_id: str | None, message: str | None) -> str:
    """Best-effort: the document source (bron), from the id prefix or the message."""
    text = f"{doc_id or ''} {message or ''}".lower()
    for s in settings.processing_source_list:  # longest-first
        sl = s.lower()
        if doc_id and doc_id.lower().startswith(sl + "-"):
            return s
        if re.search(rf"(?<![\w-]){re.escape(sl)}(?![\w-])", text):
            return s
    return "other"


def classify_error_category(message: str | None, level: str | None) -> str:
    low = (message or "").lower()
    lvl = (level or "").upper()
    if "mapping" in low:
        if lvl.startswith("WARN") or "waarschuw" in low or "warn" in low:
            return "mapping_warning"
        return "mapping_error"
    return "processing_error"


def build_source_errors(issues_hits: list[dict]) -> list[dict]:
    """Group WARN/ERROR document events into source x category counts."""
    rows: dict[str, dict] = {}
    for hit in issues_hits:
        src = hit.get("_source", {})
        flat = _flatten(src)
        message = str(flat.get("message", "") or "")
        level = str(flat.get("level") or flat.get("log.level") or "")
        doc_id = summarize_doc(hit).get("code")
        source = detect_source(doc_id, message)
        cat = classify_error_category(message, level)
        row = rows.setdefault(
            source, {"source": source, "processing_error": 0, "mapping_warning": 0, "mapping_error": 0, "total": 0}
        )
        row[cat] += 1
        row["total"] += 1
    return sorted(rows.values(), key=lambda r: r["total"], reverse=True)


async def trace_document(sid: str, plooi_id: str, data_view: str | None) -> dict:
    """Fetch the full lifecycle of one document (all log events mentioning its id),
    oldest first, so an admin can trace where its flow succeeded or failed."""
    dv = resolve_data_view(data_view)
    needle = plooi_id.strip()
    body = {
        "size": 200,
        "sort": [{"@timestamp": {"order": "asc"}}],
        "query": {"query_string": {"query": f"\"{needle}\"", "default_field": "*", "lenient": True}},
    }
    resp = await _es_search(sid, dv, body)
    hits = resp.get("hits", {}).get("hits", [])
    events = [summarize_event(h) for h in hits]
    errors = sum(1 for e in events if e["status"] == "error")
    return {
        "id": needle,
        "data_view": dv,
        "portal_base": settings.portal_base_url,
        "found": len(events) > 0,
        "errors": errors,
        "link": events[-1]["link"] if events and events[-1].get("link") else None,
        "events": events,
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
    errors_prior: int = 0
    error_pct_change: float | None = None
    alert_level: str = "ok"   # ok | warning | critical
    failed: list[dict] = []   # the specific documents that errored
    by_source: list[dict] = []  # errors per source (bron) x category
    by_action: list[dict]
    by_type: list[dict]
    timeseries: list[dict]
    events: list[dict]


async def build_document_activity(sid: str, period_minutes: int, data_view: str | None) -> DocumentActivity:
    dv = resolve_data_view(data_view)
    start, end = period_bounds(period_minutes)
    prev_start = start - (end - start)
    interval = timeseries_interval(period_minutes)

    ts_res, feed_res, failed_res, prior_res, issues_res = await asyncio.gather(
        _es_search(sid, dv, _timeseries_body(start, end, interval)),
        _es_search(sid, dv, _feed_body(start, end)),
        _es_search(sid, dv, _failed_body(start, end)),
        _es_search(sid, dv, _error_count_body(prev_start, start)),
        _es_search(sid, dv, _issues_body(start, end)),
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

    # Proactive: accurate error count + the specific failed documents + spike vs prior period.
    if isinstance(failed_res, Exception):
        errors = sum(1 for e in events if e["status"] == "error")
        failed: list[dict] = []
    else:
        errors = failed_res.get("hits", {}).get("total", {}).get("value", 0)
        seen: set[str] = set()
        failed = []
        for ev in (summarize_event(h) for h in failed_res.get("hits", {}).get("hits", [])):
            key = ev.get("doc_id") or ev.get("filename") or ev.get("message")
            if key in seen:
                continue
            seen.add(key)
            failed.append(ev)
    errors_prior = 0 if isinstance(prior_res, Exception) else prior_res.get("hits", {}).get("total", {}).get("value", 0)
    error_pct_change = round((errors - errors_prior) / errors_prior * 100, 1) if errors_prior else None
    alert_level = _alert_level(errors, error_pct_change)

    by_action = [{"action": a, "count": c} for a, c in Counter(e["action"] for e in events).most_common()]
    by_type = [{"type": t, "count": c} for t, c in Counter(e["type"] for e in events if e["type"]).most_common()]
    unique = len({(e["doc_id"] or e["filename"] or e["message"]) for e in events})
    by_source = [] if isinstance(issues_res, Exception) else build_source_errors(issues_res.get("hits", {}).get("hits", []))

    return DocumentActivity(
        period_minutes=period_minutes,
        data_view=dv,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        portal_base=settings.portal_base_url,
        total=total,
        unique_documents=unique,
        errors=errors,
        errors_prior=errors_prior,
        error_pct_change=error_pct_change,
        alert_level=alert_level,
        failed=failed,
        by_source=by_source,
        by_action=by_action,
        by_type=by_type,
        timeseries=timeseries,
        events=events,
    )
