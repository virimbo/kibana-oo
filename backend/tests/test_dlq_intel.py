"""DLQ Intelligence: x-death parsing, trend, smart verdict, peek (mocked), scan,
and API gating. No real RabbitMQ — message payloads/headers are passed in directly."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import dlq_intel


def _msg(reason, exchange="orders", rk="order.created", minutes_ago=10):
    t = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    return {"properties": {"headers": {"x-death": [
        {"reason": reason, "exchange": exchange, "routing-keys": [rk],
         "queue": "q", "count": 3, "time": t},
    ]}}}


def test_parse_failure_extracts_reason_source_age():
    rec = dlq_intel._parse_failure(_msg("rejected", "orders", "order.created", 10))
    assert rec["reason"] == "rejected"
    assert rec["source"] == "orders"
    assert rec["routing"] == "order.created"
    assert 540 <= rec["age_seconds"] <= 660  # ~10 min


def test_parse_failure_maps_delivery_limit_to_max_retries():
    rec = dlq_intel._parse_failure(_msg("delivery_limit"))
    assert rec["reason"] == "max-retries"


def test_parse_failure_missing_xdeath_is_unknown():
    rec = dlq_intel._parse_failure({"properties": {"headers": {}}})
    assert rec["reason"] == "onbekend" and rec["age_seconds"] is None


@pytest.fixture()
def store(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings, "dlq_intel_history", 50)
    monkeypatch.setattr(settings, "dlq_intel_grow_delta", 5)
    return settings


def test_trend_growing_stable_draining(store):
    q = "export.dlq"
    # base = the most recent recorded sample (20)
    for d in (10, 12, 20):
        dlq_intel._record_depth(q, d)
    assert dlq_intel._trend(q, current=40) == "growing"    # 40 >= 20 + delta(5)
    assert dlq_intel._trend(q, current=20) == "stable"     # unchanged
    assert dlq_intel._trend(q, current=10) == "draining"   # 10 <= 20 - delta(5)


def test_trend_unknown_without_history(store):
    assert dlq_intel._trend("brand-new.dlq", current=3) == "unknown"


def test_verdict_growing_is_critical(store):
    v = dlq_intel._verdict(depth=240, source_consumers=2, trend="growing",
                           oldest_age=3 * 3600,
                           reasons=[{"reason": "max-retries", "count": 200},
                                    {"reason": "rejected", "count": 40}],
                           source="order-service")
    assert v["severity"] == "critical"
    assert "groeit" in v["headline"]
    assert "max-retries" in v["headline"]
    assert v["action"]


def test_verdict_no_consumer_is_critical(store):
    v = dlq_intel._verdict(depth=12, source_consumers=0, trend="stable",
                           oldest_age=600, reasons=[{"reason": "expired", "count": 12}],
                           source="x")
    assert v["severity"] == "critical"


def test_verdict_parked_long_is_warn(store):
    old = int(6 * 86400)
    v = dlq_intel._verdict(depth=12, source_consumers=2, trend="stable",
                           oldest_age=old, reasons=[{"reason": "rejected", "count": 12}],
                           source="x")
    assert v["severity"] == "warn"
    assert "geparkeerd" in v["headline"].lower()


def test_verdict_empty_is_ok(store):
    v = dlq_intel._verdict(depth=0, source_consumers=2, trend="stable",
                           oldest_age=None, reasons=[], source="x")
    assert v["severity"] == "ok"


import httpx


def test_peek_uses_reject_requeue_true_and_groups(monkeypatch, store):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return [_msg("rejected"), _msg("delivery_limit"), _msg("delivery_limit")]

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, auth=None, headers=None):
            captured["url"] = url
            captured["body"] = json
            return FakeResp()

    monkeypatch.setattr(dlq_intel.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(store, "rabbitmq_api_url", "https://rmq.example")
    monkeypatch.setattr(store, "rabbitmq_user", "u")
    monkeypatch.setattr(store, "rabbitmq_password", "p")

    import asyncio
    sample, reasons = asyncio.run(dlq_intel._peek("/", "export.dlq"))
    assert captured["body"]["ackmode"] == "reject_requeue_true"
    assert captured["body"]["count"] == store.dlq_intel_peek_max
    assert "/api/queues/%2F/export.dlq/get" in captured["url"]
    assert reasons[0] == {"reason": "max-retries", "count": 2}
    assert len(sample) == 3


def test_peek_failure_returns_empty(monkeypatch, store):
    class BoomClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *a, **k): raise httpx.HTTPError("boom")
    monkeypatch.setattr(dlq_intel.httpx, "AsyncClient", BoomClient)
    monkeypatch.setattr(store, "rabbitmq_api_url", "https://rmq.example")
    monkeypatch.setattr(store, "rabbitmq_user", "u")
    monkeypatch.setattr(store, "rabbitmq_password", "p")
    import asyncio
    sample, reasons = asyncio.run(dlq_intel._peek("/", "export.dlq"))
    assert sample == [] and reasons == []


def test_scan_builds_enriched_view(monkeypatch, store):
    monkeypatch.setattr(store, "dlq_intel_enabled", True)
    monkeypatch.setattr(store, "rabbitmq_api_url", "https://rmq.example")
    monkeypatch.setattr(store, "rabbitmq_user", "u")
    monkeypatch.setattr(store, "rabbitmq_password", "p")

    async def fake_base():
        return {"configured": True, "dlqs": [
            {"name": "export.dlq", "vhost": "/", "depth": 240, "source": "export",
             "source_consumers": 2, "severity": "warn", "first_seen": None},
            {"name": "antivirus.dlq", "vhost": "/", "depth": 0, "source": "antivirus",
             "source_consumers": 1, "severity": "ok", "first_seen": None},
        ]}
    monkeypatch.setattr(dlq_intel.rabbitmq_dlq, "latest", fake_base)

    async def fake_peek(vhost, name):
        return ([{"reason": "max-retries", "source": "export", "routing": "x",
                  "age_seconds": 3 * 3600}],
                [{"reason": "max-retries", "count": 240}])
    monkeypatch.setattr(dlq_intel, "_peek", fake_peek)

    import asyncio
    view = asyncio.run(dlq_intel.scan())
    assert view["configured"] is True
    q = {x["name"]: x for x in view["queues"]}
    assert q["export.dlq"]["severity"] == "critical"
    assert q["export.dlq"]["reasons"][0]["reason"] == "max-retries"
    assert q["antivirus.dlq"]["severity"] == "ok"
    assert view["verdict"] in ("CRITICAL", "WARN", "OK")
