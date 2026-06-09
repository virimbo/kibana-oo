"""Dashboard fact layer: deterministic Elasticsearch aggregations via the
Kibana console proxy. Every number the dashboard shows is computed here.

The dashboard queries a rolling window ([now - period, now]) over a single
selected data view, and compares it to the immediately preceding equal period."""
import asyncio
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel

from elastic import _es_search
from config import settings

# Thresholds for the headline status banner (count of criticals in the window).
DEGRADED_AT = 1
CRITICAL_AT = 100

DATA_VIEW_LABELS = {
    "logs-*": "All logs",
    "ds-prod5-koop-plooi*": "KOOP Plooi (prod5)",
    "ds-prod5-koop-sp": "KOOP SP (prod5)",
}

# Histogram bucket size per period (minutes) so every period yields a readable
# number of bars. Falls back to "5m" for unknown periods.
_INTERVALS = {15: "1m", 30: "2m", 60: "5m", 360: "30m", 1440: "1h"}


def resolve_data_view(requested: str | None) -> str:
    """Validate a requested data view against the whitelist, else use the default."""
    allowed = settings.data_view_list
    if requested and requested in allowed:
        return requested
    if settings.default_data_view in allowed:
        return settings.default_data_view
    return allowed[0]


def period_bounds(period_minutes: int, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the rolling [start, end) UTC window for the last `period_minutes`."""
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(minutes=period_minutes)
    return start, end


def timeseries_interval(period_minutes: int) -> str:
    return _INTERVALS.get(period_minutes, "5m")


def critical_query(start: datetime, end: datetime) -> dict:
    """ES query: documents in [start, end) that are 'critical' — error-level
    logs, documents with an error.message, HTTP 5xx, or APM error events."""
    return {
        "bool": {
            "filter": [
                {"range": {"@timestamp": {"gte": start.isoformat(), "lt": end.isoformat()}}},
                {
                    "bool": {
                        "minimum_should_match": 1,
                        "should": [
                            {"terms": {"log.level": ["error", "ERROR", "fatal", "FATAL", "critical", "CRITICAL"]}},
                            # top-level `level` (logback/Logstash JSON, e.g. KOOP Plooi services)
                            {"terms": {"level": ["error", "ERROR", "fatal", "FATAL", "critical", "CRITICAL"]}},
                            {"exists": {"field": "error.message"}},
                            {"range": {"http.response.status_code": {"gte": 500}}},
                            {"term": {"processor.event": "error"}},
                        ],
                    }
                },
            ]
        }
    }


def snapshot_body(start: datetime, end: datetime, interval: str, tz_name: str) -> dict:
    """size:0 aggregation body for the selected data view's window."""
    return {
        "size": 0,
        "track_total_hits": True,
        "query": critical_query(start, end),
        "aggs": {
            "over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": interval,
                    "time_zone": tz_name,
                    "min_doc_count": 0,
                }
            },
            "signatures": {
                "terms": {"field": "error.type", "size": 10, "missing": "(untyped)"},
                "aggs": {
                    "first": {"min": {"field": "@timestamp"}},
                    "last": {"max": {"field": "@timestamp"}},
                },
            },
            "services": {"terms": {"field": "service.name", "size": 10}},
            "status_codes": {
                "filter": {"range": {"http.response.status_code": {"gte": 500}}},
                "aggs": {
                    "codes": {"terms": {"field": "http.response.status_code", "size": 10}},
                    "urls": {"terms": {"field": "url.path", "size": 10}},
                },
            },
        },
    }


def not_found_body(start: datetime, end: datetime) -> dict:
    """size:0 query for HTTP 404s in the window — documents users requested but
    that were not found. Separate from criticals (404 is a client, not server, error)."""
    return {
        "size": 0,
        "track_total_hits": True,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": start.isoformat(), "lt": end.isoformat()}}},
                    {"term": {"http.response.status_code": 404}},
                ]
            }
        },
        "aggs": {"urls": {"terms": {"field": "url.path", "size": 10}}},
    }


def parse_not_found(resp: dict) -> tuple[int, list[dict]]:
    total = resp.get("hits", {}).get("total", {}).get("value", 0)
    urls = [
        {"url": b["key"], "count": b["doc_count"]}
        for b in resp.get("aggregations", {}).get("urls", {}).get("buckets", [])
    ]
    return total, urls


def _dig_path(src: object, dotted: str):
    cur = src
    for key in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _first_field(src: dict, fields_csv: str):
    for field in (f.strip() for f in fields_csv.split(",") if f.strip()):
        val = _dig_path(src, field)
        if val not in (None, "", []):
            return val
    return None


# A document's action counts as "new" (a brand-new publication) vs an update of
# an existing/"mother" document. New documents must NOT use the old pipeline.
_NEW_ACTION_RE = re.compile(r"new|create|aanmaak|nieuw|insert|add", re.IGNORECASE)


def is_new_action(action: str | None) -> bool:
    return bool(action and _NEW_ACTION_RE.search(action))


def _flatten(src, prefix: str = "", out: dict | None = None) -> dict:
    """Flatten a nested _source into dotted-key -> scalar pairs."""
    if out is None:
        out = {}
    if isinstance(src, dict):
        for k, v in src.items():
            _flatten(v, f"{prefix}{k}.", out)
    elif isinstance(src, (str, int, float, bool)) and str(src).strip() != "":
        out[prefix[:-1]] = src
    return out


# Infrastructure / ECS metadata fields — never a document's own identity. Excluded
# from auto-discovery so we don't pick the cluster/namespace name as a "document".
_INFRA_PREFIX = re.compile(
    r"^(agent|cloud|host|observer|ecs|orchestrator|container|process|input|stream|"
    r"data_stream|service|kibana|cluster|elastic_agent|fields|tags|kubernetes|"
    r"kubernetes_namespace|platform_cluster|thread_name|level_value|@version|_p|time|"
    r"log\.file|log\.offset|event\.(dataset|module|ingested|created|kind|category|outcome))($|\.)",
    re.IGNORECASE,
)

# When the configured fields don't match, auto-discover by field-name hint.
_URL_HINT = re.compile(r"(^|\.)(url|uri|link|href|permalink|locatie|location)($|\.)|path", re.IGNORECASE)
_ID_HINT = re.compile(r"identifier|documentid|document\.id|dossier|kenmerk|(^|\.)id$|productid|\bcode\b", re.IGNORECASE)
_TITLE_HINT = re.compile(r"titel|title|onderwerp|(^|\.)naam$|(^|\.)name$|omschrijv|subject", re.IGNORECASE)
_ACTION_HINT = re.compile(r"action|operation|operatie|mutatie|(^|\.)type$|soort|verb|(^|\.)kind$|status", re.IGNORECASE)


def _scan(flat: dict, hint: re.Pattern, url_like: bool = False):
    cands = [
        (k, v) for k, v in flat.items()
        if isinstance(v, str) and v.strip() and hint.search(k) and not _INFRA_PREFIX.match(k)
    ]
    if url_like:  # only accept values that are genuinely a URL or a path
        cands = [kv for kv in cands if kv[1].startswith(("http://", "https://", "/"))]
    return cands[0][1] if cands else None


def _looks_like_doc_path(value: str) -> bool:
    return value.startswith("/") and len(value) > 1


def summarize_doc(hit: dict) -> dict:
    """Turn a raw document hit into a compact list item: a label, an open.overheid.nl
    link (ONLY when a real URL/path exists), the action (new/update), and a preview of
    the document's own fields. Prefers configured DOC_* fields, then auto-discovers."""
    src = hit.get("_source", {})
    flat = _flatten(src)
    url_cfg = _first_field(src, settings.doc_url_fields)          # from explicit config
    url_auto = _scan(flat, _URL_HINT, url_like=True)              # auto-discovered
    code = _first_field(src, settings.doc_id_fields) or _scan(flat, _ID_HINT)
    title = _first_field(src, settings.doc_title_fields) or _scan(flat, _TITLE_HINT)
    action = _first_field(src, settings.doc_action_fields) or _scan(flat, _ACTION_HINT)

    # Extract a document identifier (e.g. KOOP "ronl-...") from the log text.
    message = flat.get("message")
    doc_id = None
    if settings.doc_id_regex:
        haystack = str(message) if message else " ".join(str(v) for v in flat.values())
        m = re.search(settings.doc_id_regex, haystack)
        doc_id = m.group(0) if m else None

    base = settings.portal_base_url.rstrip("/")
    link = None
    if isinstance(url_cfg, str) and url_cfg.startswith(("http://", "https://")):
        link = url_cfg                                            # explicit absolute URL
    elif isinstance(url_cfg, str) and _looks_like_doc_path(url_cfg):
        link = f"{base}/{url_cfg.lstrip('/')}"                    # trust explicitly-configured path
    elif isinstance(url_auto, str) and url_auto.startswith(("http://", "https://")):
        link = url_auto                                          # auto: only full URLs, never guessed paths
    elif doc_id and settings.doc_link_template:
        link = settings.doc_link_template.format(id=doc_id)       # build portal link from extracted id

    url = url_cfg or url_auto
    code = code or doc_id
    # For log-shaped data the message IS the meaningful content; prefer an explicitly
    # configured title, then the log message, then any auto-discovered title/id.
    label = (
        _first_field(src, settings.doc_title_fields)
        or (str(message)[:140] if isinstance(message, str) and message.strip() else None)
        or title
        or code
        or url
        or "(document)"
    )
    # Preview the document's OWN fields (infra/metadata excluded) so the admin sees
    # real content and the correct DOC_* fields can be configured from one look.
    own = [
        (k, v) for k, v in flat.items()
        if k not in ("@timestamp", "message") and not _INFRA_PREFIX.match(k)
    ]
    preview = " · ".join(f"{k}={str(v)[:48]}" for k, v in own[:5])
    return {
        "timestamp": src.get("@timestamp"),
        "label": str(label),
        "code": code if isinstance(code, str) else None,
        "link": link,
        "action": action if isinstance(action, str) else None,
        "preview": preview,
    }


async def fetch_pipeline_docs(
    sid: str, index: str, start: datetime, end: datetime, query_string: str, size: int | None = None
) -> list[dict]:
    """Fetch the actual documents matching a pipeline query, newest first, as
    clickable drill-down items."""
    size = size or settings.pipeline_doc_size
    body = {
        "size": size,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": start.isoformat(), "lt": end.isoformat()}}},
                    {"query_string": {"query": query_string, "default_field": "*", "lenient": True}},
                ]
            }
        },
    }
    resp = await _es_search(sid, index, body)
    # De-duplicate: many log lines often refer to the same document.
    seen: set[str] = set()
    unique: list[dict] = []
    for doc in (summarize_doc(h) for h in resp.get("hits", {}).get("hits", [])):
        key = doc.get("code") or doc.get("link") or doc.get("label") or ""
        if key in seen:
            continue
        seen.add(key)
        unique.append(doc)
    return unique


def parse_aggs(resp: dict) -> dict:
    aggs = resp.get("aggregations", {})
    timeseries = [
        {"timestamp": b["key_as_string"], "count": b["doc_count"]}
        for b in aggs.get("over_time", {}).get("buckets", [])
    ]
    signatures = [
        {
            "signature": b["key"],
            "count": b["doc_count"],
            "first_seen": b.get("first", {}).get("value_as_string"),
            "last_seen": b.get("last", {}).get("value_as_string"),
        }
        for b in aggs.get("signatures", {}).get("buckets", [])
    ]
    services = [
        {"name": b["key"], "count": b["doc_count"]}
        for b in aggs.get("services", {}).get("buckets", [])
    ]
    sc = aggs.get("status_codes", {})
    status_codes = [
        {"code": b["key"], "count": b["doc_count"]}
        for b in sc.get("codes", {}).get("buckets", [])
    ]
    failing_urls = [
        {"url": b["key"], "count": b["doc_count"]}
        for b in sc.get("urls", {}).get("buckets", [])
    ]
    return {
        "total": resp.get("hits", {}).get("total", {}).get("value", 0),
        "timeseries": timeseries,
        "signatures": signatures,
        "services": services,
        "status_codes": status_codes,
        "failing_urls": failing_urls,
    }


def status_level(total: int) -> str:
    if total >= CRITICAL_AT:
        return "critical"
    if total >= DEGRADED_AT:
        return "degraded"
    return "ok"


class Delta(BaseModel):
    previous: int                      # criticals in the prior equal-length period
    pct_vs_previous: float | None = None


class SystemBreakdown(BaseModel):
    data_view: str
    label: str
    count: int = 0
    available: bool = True


class DashboardSnapshot(BaseModel):
    period_minutes: int
    data_view: str
    window_start: str
    window_end: str
    total: int
    delta: Delta
    status_level: str
    systems: list[SystemBreakdown]
    timeseries: list[dict]
    top_signatures: list[dict]
    affected_services: list[dict]
    status_codes: list[dict]
    failing_urls: list[dict]
    not_found_total: int = 0
    not_found_urls: list[dict] = []
    nvs_count: int = 0   # documents processed via the new pipeline (nieuwe verwerkingsstraat)
    nvs_docs: list[dict] = []   # the actual NVS documents (drill-down, clickable)
    portal_base: str = ""       # base URL for building document links
    partial: bool


async def _count(sid: str, index: str, start: datetime, end: datetime) -> int:
    body = {"size": 0, "track_total_hits": True, "query": critical_query(start, end)}
    resp = await _es_search(sid, index, body)
    return resp.get("hits", {}).get("total", {}).get("value", 0)


def _pct(curr: int, base: float) -> float | None:
    if not base:
        return None
    return round((curr - base) / base * 100, 1)


async def build_snapshot(
    sid: str,
    period_minutes: int,
    data_view: str | None,
    now: datetime | None = None,
) -> DashboardSnapshot:
    """Resolve the window once, fan out concurrent queries, assemble one
    consistent snapshot for the selected data view. Headline numbers come from
    that view; per-system tiles show every whitelisted view for the same window;
    the delta compares to the immediately preceding equal-length period."""
    tz = settings.dashboard_timezone
    dv = resolve_data_view(data_view)
    start, end = period_bounds(period_minutes, now)
    prev_start = start - (end - start)
    interval = timeseries_interval(period_minutes)
    views = settings.data_view_list

    agg_task = _es_search(sid, dv, snapshot_body(start, end, interval, tz))
    prev_task = _count(sid, dv, prev_start, start)
    nf_task = _es_search(sid, dv, not_found_body(start, end))
    # Count UNIQUE documents per pipeline (de-duplicated), so the tile number always
    # matches the list — many log lines often refer to the same document.
    nvs_docs_task = fetch_pipeline_docs(sid, dv, start, end, settings.pipeline_nvs_query)
    view_tasks = [_count(sid, v, start, end) for v in views]

    results = await asyncio.gather(
        agg_task, prev_task, nf_task, nvs_docs_task,
        *view_tasks, return_exceptions=True
    )
    agg_res, prev_res, nf_res = results[0], results[1], results[2]
    nvs_docs_res = results[3]
    view_counts = results[4:]

    if isinstance(agg_res, Exception):
        raise agg_res  # core query failed — surfaced as 502 by the router

    parsed = parse_aggs(agg_res)
    partial = isinstance(prev_res, Exception)
    previous = 0 if partial else prev_res
    if isinstance(nf_res, Exception):
        not_found_total, not_found_urls = 0, []
    else:
        not_found_total, not_found_urls = parse_not_found(nf_res)
    nvs_docs = [] if isinstance(nvs_docs_res, Exception) else nvs_docs_res
    nvs_count = len(nvs_docs)   # unique NVS documents — matches the list

    systems: list[SystemBreakdown] = []
    for view, count in zip(views, view_counts):
        label = DATA_VIEW_LABELS.get(view, view)
        if isinstance(count, Exception):
            partial = True
            systems.append(SystemBreakdown(data_view=view, label=label, available=False))
        else:
            systems.append(SystemBreakdown(data_view=view, label=label, count=count))

    total = parsed["total"]
    return DashboardSnapshot(
        period_minutes=period_minutes,
        data_view=dv,
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        total=total,
        delta=Delta(previous=previous, pct_vs_previous=_pct(total, previous)),
        status_level=status_level(total),
        systems=systems,
        timeseries=parsed["timeseries"],
        top_signatures=parsed["signatures"],
        affected_services=parsed["services"],
        status_codes=parsed["status_codes"],
        failing_urls=parsed["failing_urls"],
        not_found_total=not_found_total,
        not_found_urls=not_found_urls,
        nvs_count=nvs_count,
        nvs_docs=nvs_docs,
        portal_base=settings.portal_base_url,
        partial=partial,
    )
