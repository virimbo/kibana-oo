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
