from datetime import datetime, timedelta, timezone

import pytest

import monitoring


# ── Task 4: day bounds ──────────────────────────────────────

def test_day_bounds_explicit_date_amsterdam_summer():
    # 2026-06-08 is CEST (UTC+2): local midnight = 22:00 UTC the day before.
    start, end = monitoring.day_bounds("2026-06-08", "Europe/Amsterdam")
    assert start == datetime(2026, 6, 7, 22, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 8, 22, 0, tzinfo=timezone.utc)


def test_day_bounds_utc():
    start, end = monitoring.day_bounds("2026-06-08", "UTC")
    assert start == datetime(2026, 6, 8, 0, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 6, 9, 0, 0, tzinfo=timezone.utc)


# ── Task 5: query + aggregation bodies ──────────────────────

def test_critical_query_has_all_three_signals():
    start, end = monitoring.day_bounds("2026-06-08", "UTC")
    q = monitoring.critical_query(start, end)
    shoulds = q["bool"]["filter"][1]["bool"]["should"]
    kinds = {list(s.keys())[0] for s in shoulds}
    assert "terms" in kinds and "exists" in kinds and "range" in kinds and "term" in kinds
    assert q["bool"]["filter"][0]["range"]["@timestamp"]["gte"] == start.isoformat()


def test_snapshot_body_is_size_zero_with_aggs():
    start, end = monitoring.day_bounds("2026-06-08", "UTC")
    body = monitoring.snapshot_body(start, end, "UTC")
    assert body["size"] == 0
    assert set(body["aggs"]) >= {"over_time", "signatures", "services", "status_codes"}


def test_baseline_body_daily_histogram():
    start, end = monitoring.day_bounds("2026-06-08", "UTC")
    body = monitoring.baseline_body(start, end, "UTC")
    assert body["size"] == 0
    agg = body["aggs"]["per_day"]["date_histogram"]
    assert agg["calendar_interval"] == "1d"
    assert body["query"]["bool"]["filter"][0]["range"]["@timestamp"]["gte"] == (
        (start - timedelta(days=7)).isoformat()
    )


# ── Task 6: parsers + status level ──────────────────────────

SAMPLE_AGG_RESPONSE = {
    "hits": {"total": {"value": 42}},
    "aggregations": {
        "over_time": {"buckets": [
            {"key_as_string": "2026-06-08T09:00:00.000+02:00", "doc_count": 30},
            {"key_as_string": "2026-06-08T10:00:00.000+02:00", "doc_count": 12},
        ]},
        "signatures": {"buckets": [
            {"key": "NullPointerException", "doc_count": 30,
             "first": {"value_as_string": "2026-06-08T09:12:00Z"},
             "last": {"value_as_string": "2026-06-08T09:40:00Z"}},
        ]},
        "services": {"buckets": [{"key": "registration-service", "doc_count": 30}]},
        "status_codes": {"codes": {"buckets": [{"key": 500, "doc_count": 8}]},
                         "urls": {"buckets": [{"key": "/api/submit", "doc_count": 8}]}},
    },
}


def test_parse_aggs():
    parsed = monitoring.parse_aggs(SAMPLE_AGG_RESPONSE)
    assert parsed["total"] == 42
    assert parsed["timeseries"][0] == {"timestamp": "2026-06-08T09:00:00.000+02:00", "count": 30}
    assert parsed["signatures"][0]["signature"] == "NullPointerException"
    assert parsed["signatures"][0]["first_seen"] == "2026-06-08T09:12:00Z"
    assert parsed["services"][0] == {"name": "registration-service", "count": 30}
    assert parsed["status_codes"][0] == {"code": 500, "count": 8}
    assert parsed["failing_urls"][0] == {"url": "/api/submit", "count": 8}


def test_parse_baseline_deltas():
    buckets = [{"doc_count": 10} for _ in range(7)] + [{"doc_count": 42}]
    resp = {"aggregations": {"per_day": {"buckets": buckets}}}
    previous, avg_7d = monitoring.parse_baseline(resp)
    assert previous == 10
    assert avg_7d == 10.0


def test_status_level():
    assert monitoring.status_level(0) == "ok"
    assert monitoring.status_level(5) == "degraded"
    assert monitoring.status_level(500) == "critical"


# ── Task 7: snapshot orchestration ──────────────────────────

@pytest.fixture
def patched_es(monkeypatch):
    """Patch _es_search to return canned responses keyed by index string."""
    calls = {}

    async def fake_es(sid, index, body):
        calls.setdefault(index, []).append(body)
        if "per_day" in body.get("aggs", {}):
            return {"aggregations": {"per_day": {"buckets": (
                [{"doc_count": 10} for _ in range(7)] + [{"doc_count": 42}]
            )}}}
        if body.get("aggs"):
            return SAMPLE_AGG_RESPONSE
        return {"hits": {"total": {"value": 7 if "plooi" in index else 0}}}

    monkeypatch.setattr(monitoring, "_es_search", fake_es)
    monkeypatch.setattr(monitoring.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")
    monkeypatch.setattr(monitoring.settings, "dashboard_superset_views", "logs-*")
    return calls


async def test_build_snapshot_assembles_consistent_payload(patched_es):
    snap = await monitoring.build_snapshot("sid-123", "2026-06-08")
    assert snap.date == "2026-06-08"
    assert snap.total == 42
    assert snap.delta.previous == 10
    assert snap.delta.avg_7d == 10.0
    assert snap.status_level == "degraded"
    assert len(snap.systems) == 3
    assert all(s.available for s in snap.systems)
    assert snap.partial is False


async def test_build_snapshot_isolates_view_failure(monkeypatch, patched_es):
    # patched_es already replaced _es_search with the fixture's fake; capture it
    # so flaky_es can delegate to it for the non-failing indices.
    patched_es_original = monitoring._es_search

    async def flaky_es(sid, index, body):
        if index == "ds-prod5-koop-sp" and not body.get("aggs"):
            raise RuntimeError("view down")
        return await patched_es_original(sid, index, body)

    monkeypatch.setattr(monitoring, "_es_search", flaky_es)
    snap = await monitoring.build_snapshot("sid-123", "2026-06-08")
    sp = next(s for s in snap.systems if s.data_view == "ds-prod5-koop-sp")
    assert sp.available is False
    assert snap.partial is True
    assert snap.total == 42
