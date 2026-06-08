from datetime import datetime, timezone

import pytest

import monitoring


# ── period bounds + interval ────────────────────────────────

def test_period_bounds():
    now = datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc)
    start, end = monitoring.period_bounds(15, now=now)
    assert end == now
    assert start == datetime(2026, 6, 8, 11, 45, tzinfo=timezone.utc)


def test_timeseries_interval():
    assert monitoring.timeseries_interval(15) == "1m"
    assert monitoring.timeseries_interval(1440) == "1h"
    assert monitoring.timeseries_interval(999) == "5m"  # fallback


def test_resolve_data_view(monkeypatch):
    monkeypatch.setattr(monitoring.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")
    monkeypatch.setattr(monitoring.settings, "default_data_view", "logs-*")
    assert monitoring.resolve_data_view("ds-prod5-koop-sp") == "ds-prod5-koop-sp"
    assert monitoring.resolve_data_view(None) == "logs-*"
    assert monitoring.resolve_data_view("evil-*") == "logs-*"  # not whitelisted -> default


# ── query + aggregation bodies ──────────────────────────────

def test_critical_query_has_all_signals_and_exclusive_bound():
    start, end = monitoring.period_bounds(60, now=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc))
    q = monitoring.critical_query(start, end)
    shoulds = q["bool"]["filter"][1]["bool"]["should"]
    kinds = {list(s.keys())[0] for s in shoulds}
    assert "terms" in kinds and "exists" in kinds and "range" in kinds and "term" in kinds
    rng = q["bool"]["filter"][0]["range"]["@timestamp"]
    assert rng["gte"] == start.isoformat()
    assert "lt" in rng and "lte" not in rng  # exclusive upper bound


def test_snapshot_body_uses_interval():
    start, end = monitoring.period_bounds(60, now=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc))
    body = monitoring.snapshot_body(start, end, "5m", "UTC")
    assert body["size"] == 0
    assert set(body["aggs"]) >= {"over_time", "signatures", "services", "status_codes"}
    assert body["aggs"]["over_time"]["date_histogram"]["fixed_interval"] == "5m"


def test_not_found_body_and_parse():
    start, end = monitoring.period_bounds(15, now=datetime(2026, 6, 8, 12, 0, tzinfo=timezone.utc))
    body = monitoring.not_found_body(start, end)
    assert body["query"]["bool"]["filter"][1]["term"]["http.response.status_code"] == 404
    resp = {"hits": {"total": {"value": 9}},
            "aggregations": {"urls": {"buckets": [{"key": "/document/missing.pdf", "doc_count": 9}]}}}
    total, urls = monitoring.parse_not_found(resp)
    assert total == 9
    assert urls[0] == {"url": "/document/missing.pdf", "count": 9}


# ── parsers + status level ──────────────────────────────────

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


def test_status_level():
    assert monitoring.status_level(0) == "ok"
    assert monitoring.status_level(5) == "degraded"
    assert monitoring.status_level(500) == "critical"


# ── snapshot orchestration ──────────────────────────────────

@pytest.fixture
def patched_es(monkeypatch):
    """Patch _es_search: aggregation body -> sample; count body -> per-index count."""
    counts = {"logs-*": 5, "ds-prod5-koop-plooi*": 7, "ds-prod5-koop-sp": 0}

    async def fake_es(sid, index, body):
        aggs = body.get("aggs", {})
        if "over_time" in aggs:
            return SAMPLE_AGG_RESPONSE
        if "urls" in aggs:  # the not_found (404) query
            return {"hits": {"total": {"value": 9}}, "aggregations": {"urls": {"buckets": [
                {"key": "/document/missing.pdf", "doc_count": 6},
                {"key": "/zoek/oud", "doc_count": 3}]}}}
        return {"hits": {"total": {"value": counts.get(index, 0)}}}

    monkeypatch.setattr(monitoring, "_es_search", fake_es)
    monkeypatch.setattr(monitoring.settings, "data_views",
                        "logs-*,ds-prod5-koop-plooi*,ds-prod5-koop-sp")
    monkeypatch.setattr(monitoring.settings, "default_data_view", "logs-*")
    return counts


async def test_build_snapshot_assembles_consistent_payload(patched_es):
    snap = await monitoring.build_snapshot("sid-123", 15, "logs-*")
    assert snap.period_minutes == 15
    assert snap.data_view == "logs-*"
    assert snap.total == 42                       # from the aggregation
    assert snap.delta.previous == 5               # prior period count for logs-*
    assert snap.delta.pct_vs_previous == monitoring._pct(42, 5)
    assert snap.status_level == "degraded"
    assert len(snap.systems) == 3
    assert all(s.available for s in snap.systems)
    assert snap.not_found_total == 9
    assert snap.not_found_urls[0] == {"url": "/document/missing.pdf", "count": 6}
    assert snap.partial is False


async def test_build_snapshot_defaults_to_whitelisted_view(patched_es):
    snap = await monitoring.build_snapshot("sid-123", 30, "not-allowed-*")
    assert snap.data_view == "logs-*"             # fell back to default


async def test_build_snapshot_isolates_view_failure(monkeypatch, patched_es):
    # patched_es already replaced _es_search with the fixture's fake; capture it
    # so flaky_es can delegate to it for the non-failing indices.
    fake = monitoring._es_search

    async def flaky_es(sid, index, body):
        if index == "ds-prod5-koop-sp" and not body.get("aggs"):
            raise RuntimeError("view down")
        return await fake(sid, index, body)

    monkeypatch.setattr(monitoring, "_es_search", flaky_es)
    snap = await monitoring.build_snapshot("sid-123", 15, "logs-*")
    sp = next(s for s in snap.systems if s.data_view == "ds-prod5-koop-sp")
    assert sp.available is False
    assert snap.partial is True
    assert snap.total == 42
