"""Dashboard fact layer: deterministic Elasticsearch aggregations via the
Kibana console proxy. Every number the dashboard shows is computed here."""
import asyncio
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

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


def day_bounds(date_str: str | None, tz_name: str) -> tuple[datetime, datetime]:
    """Return the [start, end) UTC datetimes for the calendar day `date_str`
    (YYYY-MM-DD) in timezone `tz_name`. If date_str is None, use today in tz."""
    tz = ZoneInfo(tz_name)
    if date_str:
        day = datetime.strptime(date_str, "%Y-%m-%d").date()
    else:
        day = datetime.now(tz).date()
    local_start = datetime.combine(day, time.min, tzinfo=tz)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def critical_query(start: datetime, end: datetime) -> dict:
    """ES query: documents in [start, end) that are 'critical' — error-level
    logs, documents with an error.message, HTTP 5xx, or APM error events."""
    return {
        "bool": {
            "filter": [
                {"range": {"@timestamp": {"gte": start.isoformat(), "lte": end.isoformat()}}},
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


def snapshot_body(start: datetime, end: datetime, tz_name: str) -> dict:
    """size:0 aggregation body for one data view's day snapshot."""
    return {
        "size": 0,
        "track_total_hits": True,
        "query": critical_query(start, end),
        "aggs": {
            "over_time": {
                "date_histogram": {
                    "field": "@timestamp",
                    "fixed_interval": "1h",
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


def baseline_body(start: datetime, end: datetime, tz_name: str) -> dict:
    """size:0 daily histogram of criticals over the 7 days before `start`
    through `end`, for computing deltas."""
    base_start = start - timedelta(days=7)
    return {
        "size": 0,
        "query": critical_query(base_start, end),
        "aggs": {
            "per_day": {
                "date_histogram": {
                    "field": "@timestamp",
                    "calendar_interval": "1d",
                    "time_zone": tz_name,
                    "min_doc_count": 0,
                }
            }
        },
    }


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


def parse_baseline(resp: dict) -> tuple[int, float]:
    """Return (previous_day_count, avg_of_7_history_days) from the daily histogram.
    The last bucket is the current day and is excluded from both."""
    buckets = resp.get("aggregations", {}).get("per_day", {}).get("buckets", [])
    history = [b["doc_count"] for b in buckets[:-1]]  # drop current day
    previous = history[-1] if history else 0
    last7 = history[-7:]
    avg_7d = round(sum(last7) / len(last7), 2) if last7 else 0.0
    return previous, avg_7d


def status_level(total: int) -> str:
    if total >= CRITICAL_AT:
        return "critical"
    if total >= DEGRADED_AT:
        return "degraded"
    return "ok"


class Delta(BaseModel):
    previous: int
    avg_7d: float
    pct_vs_previous: float | None = None
    pct_vs_avg: float | None = None


class SystemBreakdown(BaseModel):
    data_view: str
    label: str
    count: int = 0
    available: bool = True


class DashboardSnapshot(BaseModel):
    date: str
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
    partial: bool


async def _count(sid: str, index: str, start: datetime, end: datetime) -> int:
    body = {"size": 0, "track_total_hits": True, "query": critical_query(start, end)}
    resp = await _es_search(sid, index, body)
    return resp.get("hits", {}).get("total", {}).get("value", 0)


def _pct(curr: int, base: float) -> float | None:
    if not base:
        return None
    return round((curr - base) / base * 100, 1)


async def build_snapshot(sid: str, date_str: str | None) -> DashboardSnapshot:
    """Resolve the window once, fan out concurrent queries, assemble one
    consistent snapshot. Rollup numbers come from a single query over the
    non-superset views; per-system tiles are isolated counts."""
    tz = settings.dashboard_timezone
    start, end = day_bounds(date_str, tz)
    rollup_index = settings.rollup_index
    views = settings.data_view_list

    agg_task = _es_search(sid, rollup_index, snapshot_body(start, end, tz))
    base_task = _es_search(sid, rollup_index, baseline_body(start, end, tz))
    view_tasks = [_count(sid, v, start, end) for v in views]

    results = await asyncio.gather(agg_task, base_task, *view_tasks, return_exceptions=True)
    agg_res, base_res = results[0], results[1]
    view_counts = results[2:]

    if isinstance(agg_res, Exception):
        raise agg_res  # core rollup failed — surfaced as 502 by the router

    parsed = parse_aggs(agg_res)
    if isinstance(base_res, Exception):
        previous, avg_7d = 0, 0.0
    else:
        previous, avg_7d = parse_baseline(base_res)

    systems: list[SystemBreakdown] = []
    partial = isinstance(base_res, Exception)
    for view, count in zip(views, view_counts):
        label = DATA_VIEW_LABELS.get(view, view)
        if isinstance(count, Exception):
            partial = True
            systems.append(SystemBreakdown(data_view=view, label=label, available=False))
        else:
            systems.append(SystemBreakdown(data_view=view, label=label, count=count))

    total = parsed["total"]
    return DashboardSnapshot(
        date=date_str or start.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d"),
        window_start=start.isoformat(),
        window_end=end.isoformat(),
        total=total,
        delta=Delta(
            previous=previous,
            avg_7d=avg_7d,
            pct_vs_previous=_pct(total, previous),
            pct_vs_avg=_pct(total, avg_7d),
        ),
        status_level=status_level(total),
        systems=systems,
        timeseries=parsed["timeseries"],
        top_signatures=parsed["signatures"],
        affected_services=parsed["services"],
        status_codes=parsed["status_codes"],
        failing_urls=parsed["failing_urls"],
        partial=partial,
    )
