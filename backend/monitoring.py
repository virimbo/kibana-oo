"""Dashboard fact layer: deterministic Elasticsearch aggregations via the
Kibana console proxy. Every number the dashboard shows is computed here.

The dashboard queries a rolling window ([now - period, now]) over a single
selected data view, and compares it to the immediately preceding equal period."""
import asyncio
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


def pipeline_body(start: datetime, end: datetime, query_string: str) -> dict:
    """size:0 count of documents in the window matching a pipeline (OVS/NVS)
    query string. The query string is configurable to match how logs label them."""
    return {
        "size": 0,
        "track_total_hits": True,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": start.isoformat(), "lt": end.isoformat()}}},
                    {"query_string": {"query": query_string, "default_field": "*", "lenient": True}},
                ]
            }
        },
    }


async def _pipeline_count(sid: str, index: str, start: datetime, end: datetime, query_string: str) -> int:
    resp = await _es_search(sid, index, pipeline_body(start, end, query_string))
    return resp.get("hits", {}).get("total", {}).get("value", 0)


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


def summarize_doc(hit: dict) -> dict:
    """Turn a raw document hit into a compact, clickable list item:
    a label, an open.overheid.nl link (best-effort), and the action (new/update)."""
    src = hit.get("_source", {})
    url = _first_field(src, settings.doc_url_fields)
    code = _first_field(src, settings.doc_id_fields)
    title = _first_field(src, settings.doc_title_fields)
    action = _first_field(src, settings.doc_action_fields)
    base = settings.portal_base_url.rstrip("/")
    link = None
    if isinstance(url, str) and url:
        link = url if url.startswith("http") else f"{base}/{url.lstrip('/')}"
    elif isinstance(code, str) and code.startswith("/"):
        link = f"{base}{code}"
    label = title or code or url or "(document)"
    return {
        "timestamp": src.get("@timestamp"),
        "label": str(label),
        "code": code if isinstance(code, str) else None,
        "link": link,
        "action": action if isinstance(action, str) else None,
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
    return [summarize_doc(h) for h in resp.get("hits", {}).get("hits", [])]


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
    ovs_count: int = 0   # documents via the old pipeline (oude verwerkingsstraat)
    nvs_count: int = 0   # documents via the new pipeline (nieuwe verwerkingsstraat)
    ovs_docs: list[dict] = []   # the actual OVS documents (drill-down, clickable)
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
    ovs_task = _pipeline_count(sid, dv, start, end, settings.pipeline_ovs_query)
    nvs_task = _pipeline_count(sid, dv, start, end, settings.pipeline_nvs_query)
    ovs_docs_task = fetch_pipeline_docs(sid, dv, start, end, settings.pipeline_ovs_query)
    view_tasks = [_count(sid, v, start, end) for v in views]

    results = await asyncio.gather(
        agg_task, prev_task, nf_task, ovs_task, nvs_task, ovs_docs_task,
        *view_tasks, return_exceptions=True
    )
    agg_res, prev_res, nf_res = results[0], results[1], results[2]
    ovs_res, nvs_res, ovs_docs_res = results[3], results[4], results[5]
    view_counts = results[6:]

    if isinstance(agg_res, Exception):
        raise agg_res  # core query failed — surfaced as 502 by the router

    parsed = parse_aggs(agg_res)
    partial = isinstance(prev_res, Exception)
    previous = 0 if partial else prev_res
    if isinstance(nf_res, Exception):
        not_found_total, not_found_urls = 0, []
    else:
        not_found_total, not_found_urls = parse_not_found(nf_res)
    ovs_count = 0 if isinstance(ovs_res, Exception) else ovs_res
    nvs_count = 0 if isinstance(nvs_res, Exception) else nvs_res
    ovs_docs = [] if isinstance(ovs_docs_res, Exception) else ovs_docs_res

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
        ovs_count=ovs_count,
        nvs_count=nvs_count,
        ovs_docs=ovs_docs,
        portal_base=settings.portal_base_url,
        partial=partial,
    )
