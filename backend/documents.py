"""Document-flow activity from logs: lifecycle events (created / updated /
deleted / retrieved), document types, errors, a timeline, and a live feed.
Read-only via the Kibana proxy. Action classification is best-effort keyword
matching and is meant to be tuned against the real logs."""
import asyncio
import re
from collections import Counter
from datetime import datetime, timezone

from pydantic import BaseModel

import incidents
import pipeline
from elastic import _es_search, extract_doc_ids
from config import settings
from monitoring import _flatten, _first_field, period_bounds, timeseries_interval, summarize_doc, resolve_data_view
from portal import fetch_document_meta

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
    # Honest severity: looks at the MESSAGE too (404 / connection reset / broken
    # pipe …), not just the log level — see backend/pipeline.py.
    severity = pipeline.event_severity(level, message)
    problem = pipeline.classify_message(message)
    pipeline_raw = (
        _first_field(src, settings.pipeline_field) if settings.pipeline_field else None
    )
    return {
        "timestamp": src.get("@timestamp"),
        "action": classify_action(message),
        "severity": severity,                       # ok | warning | error
        "status": "error" if severity == "error" else "ok",  # back-compat
        "problem": problem,                         # {key, severity, explanation} or None
        "doc_id": base.get("code"),
        "link": base.get("link"),
        "filename": filename,
        "type": ftype,
        "org": org if isinstance(org, str) else None,
        "service": _service(flat),
        "index": hit.get("_index"),                 # data-stream — a reliable pipeline signal
        "pipeline_raw": pipeline_raw if isinstance(pipeline_raw, str) else None,
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


def _is_system_file(filename: str) -> bool:
    low = filename.lower()
    return low.endswith(".json") or low.startswith(("manifest", "metadata"))


async def trace_document(sid: str, plooi_id: str, data_view: str | None) -> dict:
    """Fetch the full lifecycle of one document (all log events mentioning its id),
    oldest first, so an admin can trace where its flow succeeded or failed — with the
    document title, the services it passed through, and management/portal links."""
    dv = resolve_data_view(data_view)
    needle = plooi_id.strip()
    body = {
        "size": 300,
        "sort": [{"@timestamp": {"order": "asc"}}],
        "query": {"query_string": {"query": f"\"{needle}\"", "default_field": "*", "lenient": True}},
    }
    # Search EVERY data view (tolerating per-view failures), not just the selected
    # one — a document's pipeline logs may live in a different index, so this is
    # what makes the journey line up with the architecture instead of being partial.
    views = settings.data_view_list
    results = await asyncio.gather(
        *[_es_search(sid, v, body) for v in views], return_exceptions=True
    )
    hits = []
    for res in results:
        if not isinstance(res, Exception):
            hits.extend(res.get("hits", {}).get("hits", []))
    events = [summarize_event(h) for h in hits]
    # De-duplicate (same event can appear across overlapping views) and order.
    seen: set = set()
    unique: list[dict] = []
    for e in sorted(events, key=lambda x: x.get("timestamp") or ""):
        key = (e.get("timestamp"), (e.get("message") or "")[:80], e.get("service"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    events = unique
    errors = sum(1 for e in events if e.get("severity") == "error")
    warnings = sum(1 for e in events if e.get("severity") == "warning")

    # Title: prefer the authoritative official title from the public portal API;
    # fall back to the first real document filename seen in the logs.
    log_title = None
    for e in events:
        fn = e.get("filename")
        if fn and not _is_system_file(fn):
            log_title = fn.rsplit(".", 1)[0]
            break

    portal_uuid = _portal_id(needle)  # UUID directly, or extracted from ronl-<uuid>
    meta = await fetch_document_meta(portal_uuid)
    title = (meta.get("title") if meta else None) or log_title

    # A direct, always-clickable open.overheid.nl/details/<uuid> page. It needs no
    # API call — it works even when portal enrichment is blocked (e.g. a VPN that
    # intercepts TLS) — so the admin can always jump straight to the live document.
    details_link = (
        settings.portal_details_template.format(id=portal_uuid)
        if _UUID_RE.fullmatch(portal_uuid)
        else None
    )

    ronl = next((e["doc_id"] for e in events if e.get("doc_id") and e["doc_id"].lower().startswith("ronl")), None)
    # Public link: the portal's canonical link wins; else the details page; else a
    # ronl document link.
    portal_link = (meta.get("link") if meta else None) or details_link or (
        settings.doc_link_template.format(id=ronl) if ronl else None
    )

    # Per-service "stages": the document's journey, in the order it reached each
    # service, with counts, time span, errors, and the first meaningful message.
    stage_map: dict[str, dict] = {}
    for e in events:
        svc = e.get("service") or "(unknown)"
        st = stage_map.get(svc)
        if st is None:
            st = stage_map[svc] = {
                "service": svc, "events": 0, "errors": 0,
                "first_seen": e["timestamp"], "last_seen": e["timestamp"], "message": None,
            }
        st["events"] += 1
        if e["status"] == "error":
            st["errors"] += 1
        st["last_seen"] = e["timestamp"]
        if not st["message"] and e.get("message"):
            st["message"] = e["message"]
    stages = sorted(stage_map.values(), key=lambda x: x["first_seen"] or "")

    # The canonical lifecycle: where the document got to, honest health, and a
    # plain-language verdict — the single source of truth (backend/pipeline.py).
    # Publication status from open.overheid.nl is authoritative: a live document
    # is never "stuck", even if the scanned logs are incomplete.
    published = pipeline.is_published(meta.get("status")) if meta else False
    lifecycle = pipeline.build_pipeline_view(events, published=published)

    return {
        "id": needle,
        "data_view": dv,
        "data_views_searched": views,
        "title": title,
        "portal_meta": meta,  # official metadata dict, or None if unresolved
        "found": len(events) > 0,
        "errors": errors,
        "warnings": warnings,
        "lifecycle": lifecycle,   # { stages[], verdict, headline, … }
        "stages": stages,         # raw per-service detail (kept for the detail view)
        "first_seen": events[0]["timestamp"] if events else None,
        "last_seen": events[-1]["timestamp"] if events else None,
        "doculoket_link": settings.doculoket_link_template.format(id=needle),
        "portal_link": portal_link,
        "details_link": details_link,  # direct open.overheid.nl/details/<uuid>, API-free
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


def _event_doc_id(e: dict) -> str | None:
    """The document id an event belongs to: the ronl id if present, else a UUID
    found in the message."""
    did = e.get("doc_id")
    if did:
        return did
    ids = extract_doc_ids(e.get("message") or "")
    return ids[0] if ids else None


# Problem types that genuinely indicate a document is in trouble. The routine
# 'not_found' (404 probe to the public API) is deliberately excluded — on its
# own it does not mean a document is at risk.
_ALERTING_PROBLEMS = {"connection_reset", "broken_pipe", "timeout", "refused", "server_error", "failure"}
# A stall at one of these late stages is meaningful even without an error — the
# document got most of the way through and then stopped.
_LATE_STAGES = {"publication", "indexing", "export"}


def _has_alerting(events: list[dict]) -> bool:
    """Does this document show a real trouble signal (error, or a reset/timeout/
    failure)? Routine 404 probes do not count."""
    for e in events:
        if e.get("severity") == "error":
            return True
        prob = e.get("problem")
        if prob and prob.get("key") in _ALERTING_PROBLEMS:
            return True
    return False


_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


def _portal_id(doc_id: str) -> str:
    """The id to look up on the public portal. ronl- ids embed a UUID
    (ronl-archief-<uuid>) — extract it so the portal (UUID-only) can resolve the
    title and publication status."""
    m = _UUID_RE.search(doc_id or "")
    return m.group(0) if m else doc_id


def _log_title(events: list[dict]) -> str | None:
    """Best-effort title from the logs: the first real document filename (skip
    system files like manifest.json). Lets ronl- documents — which the portal API
    can't resolve — still show a human name."""
    for e in events:
        fn = e.get("filename")
        if fn and not _is_system_file(fn):
            return fn.rsplit(".", 1)[0]
    return None


def _stage_index(stage_name: str | None) -> int:
    """Position of a stage (by display name) in the canonical pipeline, or -1."""
    for i, s in enumerate(pipeline.PIPELINE):
        if s["name"] == stage_name:
            return i
    return -1


def _incident_service(events: list[dict]) -> str | None:
    """The raw log service where the document currently sits — taken from the most
    recent event, since that is where it stalled or failed."""
    latest = max(events, key=lambda e: e.get("timestamp") or "", default=None)
    return (latest or {}).get("service") if latest else None


_OVS_RE = re.compile(r"\bovs\b|oude.?verwerkingsstraat", re.IGNORECASE)
_NVS_RE = re.compile(r"\bnvs\b|nieuwe.?verwerkingsstraat", re.IGNORECASE)


def _match_pipeline_value(value: str | None, nvs_terms: list[str], ovs_terms: list[str]) -> str | None:
    """Map a single field/index value to NVS/OVS by substring, or None."""
    v = (value or "").lower()
    if not v:
        return None
    if any(t in v for t in nvs_terms):
        return "NVS"
    if any(t in v for t in ovs_terms):
        return "OVS"
    return None


def _detect_pipeline(events: list[dict]) -> str:
    """Classify a document as OVS (oude) vs NVS (nieuwe verwerkingsstraat) in
    order of TRUST:
      1. a dedicated log field (settings.pipeline_field) — most reliable;
      2. the index / data-stream the events live in — structural, reliable;
      3. the publication-date cutoff (the pipeline switchover) — the KOOP rule;
      4. explicit free-text markers in service/message;
      5. mapping onto the canonical NVS lifecycle → NVS.
    When a trusted signal (1-3) is configured, it is AUTHORITATIVE: a document
    that matches none is reported as '—' rather than guessed. When no trusted
    signal is configured, layers 4-5 provide a best-effort label."""
    nvs_vals, ovs_vals = settings.pipeline_nvs_value_list, settings.pipeline_ovs_value_list
    nvs_idx, ovs_idx = settings.pipeline_nvs_index_list, settings.pipeline_ovs_index_list

    # 1) Dedicated field (authoritative).
    if settings.pipeline_field:
        for e in events:
            got = _match_pipeline_value(e.get("pipeline_raw"), nvs_vals, ovs_vals)
            if got:
                return got

    # 2) Index / data-stream (authoritative).
    if nvs_idx or ovs_idx:
        for e in events:
            got = _match_pipeline_value(e.get("index"), nvs_idx, ovs_idx)
            if got:
                return got

    # 3) Publication-date cutoff — the pipeline switchover (authoritative business
    # rule). A document active on/after the cutoff went through NVS; before, OVS.
    cutoff = settings.pipeline_nvs_cutoff_date
    if cutoff:
        ref = max(
            (pipeline.parse_ts(e.get("timestamp")) for e in events if e.get("timestamp")),
            default=None,
        )
        if ref:
            return "NVS" if ref.date() >= cutoff else "OVS"

    # A trusted signal was configured but nothing matched → honest unknown.
    if settings.pipeline_reliable_configured:
        return "—"

    # 4-5) Best-effort fallback (only when no trusted signal is configured).
    text = " ".join(f"{e.get('service') or ''} {e.get('message') or ''}" for e in events)
    if _OVS_RE.search(text):
        return "OVS"
    if _NVS_RE.search(text):
        return "NVS"
    if any(pipeline.stage_for_service(e.get("service")) for e in events):
        return "NVS"
    return "—"


def _age_label(first_detected: str | None, now: datetime) -> str:
    """Plain-language age of an open incident, e.g. '3d 4h' or '12 min'."""
    started = pipeline.parse_ts(first_detected)
    if not started:
        return ""
    secs = int((now - started).total_seconds())
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins} min"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h {mins % 60}m"
    return f"{hours // 24}d {hours % 24}h"


# Human-readable status, by verdict. Only 'stuck' and 'problem' ever reach here.
_STATUS_LABELS = {
    "problem": "Error — stopped",
    "stuck": "Stuck — no progress",
}


def _fmt_when(ts: str | None) -> str:
    """A compact, sortable 'YYYY-MM-DD HH:MM' for the row, or '' if unknown."""
    dt = pipeline.parse_ts(ts)
    return dt.strftime("%Y-%m-%d %H:%M") if dt else ""


def _incident_to_row(rec: dict, now: datetime) -> dict:
    """Shape a stored incident the way the Documents UI expects: identity, where
    it stalled (stage + raw service), which pipeline, a plain-language status, the
    last-activity date/time, and how long it has been open."""
    verdict = rec.get("verdict")
    return {
        "id": rec["doc_id"],
        "verdict": verdict,
        "status_label": _STATUS_LABELS.get(verdict, "Needs attention"),
        "headline": rec.get("headline"),
        "stuck_stage": rec.get("stage"),
        "service": rec.get("service"),
        "pipeline": rec.get("pipeline") or "—",
        "title": rec.get("title"),
        "link": rec.get("link"),
        "events": rec.get("events", 0),
        "last_seen": rec.get("last_activity"),
        "last_seen_label": _fmt_when(rec.get("last_activity")),
        "first_detected": rec.get("first_detected"),
        "open_since": _age_label(rec.get("first_detected"), now),
    }


async def build_pipeline_health(
    sid: str, data_view: str | None = None, now: datetime | None = None
) -> dict:
    """Proactive, dashboard-level view of the whole pipeline: which documents are
    STUCK (entered but never finished, and went quiet), and where problems cluster
    by stage — so an admin spots issues without tracing each document by hand.
    Scans recent document events across ALL data views and runs each document
    through the canonical lifecycle (see backend/pipeline.py)."""
    lookback = settings.pipeline_health_lookback_minutes
    start, end = period_bounds(lookback)
    body = {
        "size": settings.pipeline_health_scan_size,
        "sort": [{"@timestamp": {"order": "asc"}}],
        "query": _event_query(start, end),
    }
    views = settings.data_view_list
    results = await asyncio.gather(
        *[_es_search(sid, v, body) for v in views], return_exceptions=True
    )
    hits = []
    for res in results:
        if not isinstance(res, Exception):
            hits.extend(res.get("hits", {}).get("hits", []))
    events = [summarize_event(h) for h in hits]
    now = now or datetime.now(timezone.utc)

    # ── where problems cluster: per-stage event / warning / error counts ──
    stage_health = []
    counters: dict[str, dict] = {}
    for s in pipeline.PIPELINE:
        counters[s["key"]] = {"key": s["key"], "name": s["name"], "icon": s["icon"],
                              "events": 0, "warnings": 0, "errors": 0}
    for e in events:
        key = pipeline.stage_for_service(e.get("service"))
        if not key:
            continue
        c = counters[key]
        c["events"] += 1
        if e.get("severity") == "warning":
            c["warnings"] += 1
        elif e.get("severity") == "error":
            c["errors"] += 1
    stage_health = [counters[s["key"]] for s in pipeline.PIPELINE]

    # ── group events per document and find the stuck ones ──
    groups: dict[str, list[dict]] = {}
    for e in events:
        did = _event_doc_id(e)
        if did:
            groups.setdefault(did, []).append(e)

    settle_seconds = settings.incident_settle_minutes * 60
    candidates = []
    progressed_ids: set[str] = set()  # scanned docs that are NOT (any longer) at risk
    for did, evs in groups.items():
        view = pipeline.build_pipeline_view(evs, now=now)
        if view["verdict"] not in ("stuck", "problem"):
            progressed_ids.add(did)  # healthy / in-progress / published → recovered
            continue
        # SETTLE TIME — the core false-positive fix. A document still emitting
        # events is in motion, not an incident: a transient error at Intake that
        # the pipeline retries past would otherwise be flagged for the minute or
        # two before it moves on. Only flag once the document has gone SILENT for
        # the settle period (and, below, is confirmed not live). A document with
        # no parseable timestamp is treated as not-yet-settled (skip).
        last_seen = max((e.get("timestamp") or "" for e in evs), default="")
        last_dt = pipeline.parse_ts(last_seen)
        quiet = (now - last_dt).total_seconds() if last_dt else None
        if quiet is None or quiet < settle_seconds:
            continue
        # Only flag a document as genuinely at-risk — NOT every document whose
        # later-stage events just fell outside the scanned window. It must have a
        # real trouble signal (an error, or a reset/timeout/failure — the routine
        # 404 probe doesn't count) OR have stalled LATE in the pipeline.
        reached = [s["key"] for s in view["stages"] if s["reached"]]
        furthest_key = reached[-1] if reached else None
        if view["verdict"] == "problem" or _has_alerting(evs) or furthest_key in _LATE_STAGES:
            candidates.append({
                "id": did,
                "verdict": view["verdict"],
                "headline": view["headline"],
                "stuck_stage": view["furthest_stage"],
                "next_stage": view["next_stage"],
                "events": len(evs),
                "last_seen": last_seen,
                "service": _incident_service(evs),     # raw service where it stalled
                "pipeline": _detect_pipeline(evs),      # NVS / OVS / — (best-effort)
                "log_title": _log_title(evs),   # filename from logs (works for ronl- ids)
            })

    # ── Reconcile with GROUND TRUTH: a candidate that is actually published on
    # open.overheid.nl is NOT stuck (the logs we scanned were just incomplete).
    # Only verify the flagged candidates (few) — cached + best-effort. ──
    verify = candidates[:settings.pipeline_health_verify_max]
    metas = await asyncio.gather(
        *[fetch_document_meta(_portal_id(d["id"])) for d in verify], return_exceptions=True
    )
    meta_by_id = {
        d["id"]: (m if isinstance(m, dict) else None) for d, m in zip(verify, metas)
    }

    confirmed = []          # genuine, not-published at-risk documents this scan
    confirmed_published = 0
    for d in candidates:
        meta = meta_by_id.get(d["id"])
        if meta and pipeline.is_published(meta.get("status")):
            confirmed_published += 1     # false alarm — it's live & readable
            progressed_ids.add(d["id"])  # so any open incident for it auto-resolves
            continue
        # Title: official (portal, UUID only) → else the filename from the logs
        # (so ronl- documents show a real name, not just their id).
        log_title = d.pop("log_title", None)
        d["title"] = (meta.get("title") if meta else None) or log_title
        # Prefer the API-free open.overheid.nl/details/<uuid> page so the link
        # is clickable even when portal enrichment is blocked (VPN/TLS); fall
        # back to the canonical portal link, then a ronl document link.
        portal_uuid = _portal_id(d["id"])
        details_link = (
            settings.portal_details_template.format(id=portal_uuid)
            if _UUID_RE.fullmatch(portal_uuid)
            else None
        )
        d["link"] = (meta.get("link") if meta else None) or details_link \
            or settings.doc_link_template.format(id=d["id"])
        d["stage_index"] = _stage_index(d["stuck_stage"])
        d["data_view"] = data_view or "all"
        confirmed.append(d)

    # ── DURABLE INCIDENT STATE ─────────────────────────────────────────────────
    # The displayed list is driven by the persistent store, not this single scan,
    # so genuine problems stay visible for days (across restarts and beyond the
    # scan window) until they are actually solved.
    #   1. Open / refresh an incident for every confirmed at-risk document.
    #   2. Auto-resolve incidents whose document has recovered THIS scan
    #      (progressed to a later stage, became healthy, or is now published).
    #   3. Auto-resolve out-of-window incidents that the portal now reports live.
    for d in confirmed:
        await incidents.upsert_open(d, now)

    open_recs = await incidents.open_incidents()
    confirmed_ids = {d["id"] for d in confirmed}

    # (2) recovered within the window: previously open, scanned now, no longer at risk
    for r in open_recs:
        if r["doc_id"] in progressed_ids and r["doc_id"] not in confirmed_ids:
            await incidents.resolve(r["doc_id"], "progressed", now)

    # (3) out-of-window incidents: re-check the portal (bounded) — published ⇒ solved
    stale = [r for r in open_recs
             if r["doc_id"] not in groups and r["doc_id"] not in confirmed_ids]
    stale = stale[:settings.incident_reverify_max]
    stale_metas = await asyncio.gather(
        *[fetch_document_meta(_portal_id(r["doc_id"])) for r in stale],
        return_exceptions=True,
    )
    for r, m in zip(stale, stale_metas):
        meta = m if isinstance(m, dict) else None
        if meta and pipeline.is_published(meta.get("status")):
            await incidents.resolve(r["doc_id"], "published", now)

    # Final list = whatever is still OPEN, oldest (longest-unsolved) first.
    final_open = await incidents.open_incidents()
    stuck = [_incident_to_row(r, now) for r in final_open]
    stuck.sort(key=lambda d: (d["verdict"] != "problem", d.get("first_detected") or ""))

    return {
        "lookback_minutes": lookback,
        "documents_scanned": len(groups),
        "stuck_count": len(stuck),
        "stuck": stuck[:50],
        "confirmed_published": confirmed_published,  # candidates that were actually live
        "stage_health": stage_health,
        "total_warnings": sum(c["warnings"] for c in stage_health),
        "total_errors": sum(c["errors"] for c in stage_health),
    }


# ════════════════════════════════════════════════════════════════════════════
# Pipeline Outcomes — throughput & failures by outcome and pipeline (OVS/NVS)
# ════════════════════════════════════════════════════════════════════════════

# Outcome buckets, in display order. Only ONE applies to a document per window.
OUTCOMES = ["published", "updated", "withdrawn", "failed", "in_progress"]
PIPELINES = ["NVS", "OVS", "—"]
# Lifecycle verdicts that mean the document reached the public portal.
_LIVE_VERDICTS = {"published", "healthy", "warnings"}


def _doc_outcome(events: list[dict], view: dict, settle_seconds: float, now: datetime) -> str:
    """The single outcome for a document this window, by precedence:
    withdrawn (intrekking) → published/updated (reached live) → failed (a settled
    system error, i.e. quiet past the settle window and not live) → in_progress.
    The settle gate is what keeps 'failed' honest — a transient error that the
    pipeline is still retrying is 'in_progress', not a failure."""
    actions = {e.get("action") for e in events}
    if "deleted" in actions:
        return "withdrawn"
    if view["stages"][-1]["reached"] or view["verdict"] in _LIVE_VERDICTS:
        # An update to an already-live document vs. a first publication.
        if "updated" in actions and "created" not in actions:
            return "updated"
        return "published"
    last_dt = pipeline.parse_ts(max((e.get("timestamp") or "" for e in events), default=""))
    quiet = (now - last_dt).total_seconds() if last_dt else None
    settled = quiet is not None and quiet >= settle_seconds
    if settled and (view["verdict"] == "problem" or _has_alerting(events)):
        return "failed"
    return "in_progress"


def _doc_link(did: str, meta: dict | None = None) -> str:
    """Best, click-through link for a document: portal link → API-free details
    page (UUIDs) → canonical document link."""
    portal_uuid = _portal_id(did)
    details = (
        settings.portal_details_template.format(id=portal_uuid)
        if _UUID_RE.fullmatch(portal_uuid) else None
    )
    return (meta.get("link") if meta else None) or details \
        or settings.doc_link_template.format(id=did)


def _publish_seconds(events: list[dict]) -> float | None:
    """Intake→live wall-clock for a completed document, if we have both ends."""
    times = sorted(t for t in (pipeline.parse_ts(e.get("timestamp")) for e in events) if t)
    if len(times) < 2:
        return None
    return (times[-1] - times[0]).total_seconds()


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round((p / 100.0) * (len(ordered) - 1)))))
    return round(ordered[k], 1)


def _pct_change(curr: int, prev: int) -> float | None:
    if not prev:
        return None
    return round((curr - prev) / prev * 100.0, 1)


async def _scan_doc_events(sid: str, start: datetime, end: datetime,
                           views: list[str], size: int) -> list[dict]:
    """Document events in [start, end) across all views, tolerant of per-view
    failures so one unavailable index never empties the whole window."""
    body = {"size": size, "sort": [{"@timestamp": {"order": "asc"}}],
            "query": _event_query(start, end)}
    results = await asyncio.gather(
        *[_es_search(sid, v, body) for v in views], return_exceptions=True
    )
    hits: list[dict] = []
    for res in results:
        if not isinstance(res, Exception):
            hits.extend(res.get("hits", {}).get("hits", []))
    return [summarize_event(h) for h in hits]


def _group_by_doc(events: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for e in events:
        did = _event_doc_id(e)
        if did:
            groups.setdefault(did, []).append(e)
    return groups


def _empty_counts() -> dict[str, dict[str, int]]:
    return {p: {o: 0 for o in OUTCOMES} for p in PIPELINES}


def _classify_window(groups: dict[str, list[dict]], settle_seconds: float, now: datetime):
    """Classify every document in a window → (counts[pipeline][outcome], records,
    publish-latencies). One pass; no network."""
    counts = _empty_counts()
    records: list[dict] = []
    latencies: list[float] = []
    for did, evs in groups.items():
        view = pipeline.build_pipeline_view(evs, now=now)
        outcome = _doc_outcome(evs, view, settle_seconds, now)
        pl = _detect_pipeline(evs)
        counts.setdefault(pl, {o: 0 for o in OUTCOMES})[outcome] += 1
        records.append({
            "id": did, "outcome": outcome, "pipeline": pl,
            "stage": view["furthest_stage"], "service": _incident_service(evs),
            "last_seen": max((e.get("timestamp") or "" for e in evs), default=""),
            "events": len(evs), "title": _log_title(evs), "verdict": view["verdict"],
        })
        if outcome in ("published", "updated"):
            secs = _publish_seconds(evs)
            if secs is not None:
                latencies.append(secs)
    return counts, records, latencies


async def build_pipeline_outcomes(
    sid: str, period_minutes: int, data_view: str | None = None, now: datetime | None = None
) -> dict:
    """Document OUTCOMES for the selected window, split by pipeline (OVS/NVS):
    how many were published / updated / withdrawn, how many FAILED to publish from
    a system error, plus the publish success rate, backlog (work in progress),
    time-to-publish (p50/p95), and a trend vs the previous equal window. The
    'failed' set is reconciled against the public portal so a document that is in
    fact live is never reported as a failure."""
    now = now or datetime.now(timezone.utc)
    views = settings.data_view_list
    settle_seconds = settings.incident_settle_minutes * 60
    size = settings.pipeline_health_scan_size
    start, end = period_bounds(period_minutes, now)
    prev_start = start - (end - start)

    cur_events, prev_events = await asyncio.gather(
        _scan_doc_events(sid, start, end, views, size),
        _scan_doc_events(sid, prev_start, start, views, size),
    )
    counts, records, latencies = _classify_window(_group_by_doc(cur_events), settle_seconds, now)
    prev_counts, _, _ = _classify_window(_group_by_doc(prev_events), settle_seconds, now)

    # ── GROUND TRUTH: a 'failed' document that is actually live on the portal is
    # not a failure. Reconcile the failed set (bounded, cached) and move confirmed
    # live ones to 'published'. ──
    failed = [r for r in records if r["outcome"] == "failed"]
    verify = failed[:settings.pipeline_health_verify_max]
    metas = await asyncio.gather(
        *[fetch_document_meta(_portal_id(r["id"])) for r in verify], return_exceptions=True
    )
    reconciled_live = 0
    for r, m in zip(verify, metas):
        meta = m if isinstance(m, dict) else None
        if meta and pipeline.is_published(meta.get("status")):
            counts[r["pipeline"]]["failed"] -= 1
            counts[r["pipeline"]]["published"] += 1
            r["outcome"] = "published"
            r["title"] = r["title"] or meta.get("title")
            r["_meta"] = meta
            reconciled_live += 1
        elif meta:
            r["title"] = r["title"] or meta.get("title")
            r["_meta"] = meta

    # ── roll up ──
    totals = {o: sum(counts[p][o] for p in counts) for o in OUTCOMES}
    prev_totals = {o: sum(prev_counts[p][o] for p in prev_counts) for o in OUTCOMES}
    throughput = totals["published"] + totals["updated"]
    prev_throughput = prev_totals["published"] + prev_totals["updated"]
    decided = throughput + totals["failed"]
    success_rate = round(throughput / decided * 100.0, 1) if decided else None

    # ── drill-downs: top documents per outcome (most recent first), click-through ──
    drill: dict[str, list[dict]] = {}
    for o in OUTCOMES:
        rows = [r for r in records if r["outcome"] == o]
        rows.sort(key=lambda r: r["last_seen"], reverse=True)
        drill[o] = [{
            "id": r["id"],
            "title": r["title"] or r["id"],
            "link": _doc_link(r["id"], r.get("_meta")),
            "pipeline": r["pipeline"],
            "service": r["service"],
            "stage": r["stage"],
            "last_seen": r["last_seen"],
            "when": _fmt_when(r["last_seen"]),
        } for r in rows[:25]]

    return {
        "period_minutes": period_minutes,
        "data_view": data_view or "all",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "documents": len(records),
        "by_pipeline": counts,
        "totals": totals,
        "throughput": throughput,             # published + updated
        "publish_failures": totals["failed"],
        "backlog": totals["in_progress"],     # entered but not live, not failed
        "success_rate": success_rate,         # %, or None when nothing was decided
        "reconciled_live": reconciled_live,    # 'failed' docs found live on the portal
        "latency": {
            "p50_seconds": _percentile(latencies, 50),
            "p95_seconds": _percentile(latencies, 95),
            "samples": len(latencies),
        },
        "trend": {
            "throughput_pct": _pct_change(throughput, prev_throughput),
            "failed_pct": _pct_change(totals["failed"], prev_totals["failed"]),
            "prev_throughput": prev_throughput,
            "prev_failed": prev_totals["failed"],
        },
        "drill": drill,
    }
