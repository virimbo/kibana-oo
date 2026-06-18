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
