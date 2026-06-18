"""Unified alerting: env normalization, monitor→item normalization, toggle filter,
the cooldown/dedup/recovery decision machine, email rendering, and the API guards.
No real network or monitors — snapshots are passed in directly."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import alerts


def test_norm_env_maps_test_variants_to_tst():
    assert alerts._norm_env("TEST") == "TST"
    assert alerts._norm_env("tst") == "TST"
    assert alerts._norm_env("Acceptance") == "ACC"
    assert alerts._norm_env("acc") == "ACC"
    assert alerts._norm_env("PROD") == "PROD"
    assert alerts._norm_env("anything") == "ANYTHING"


def test_env_from_host():
    assert alerts._env_from_host("open-acc.overheid.nl") == "ACC"
    assert alerts._env_from_host("gateway-zoek.koop-plooi-tst.test5.s15m.nl") == "TST"
    assert alerts._env_from_host("open.overheid.nl") == "PROD"


def test_normalize_uptime_snapshot():
    snap = {
        "enabled": True,
        "groups": [
            {"env": "PROD", "sites": [
                {"name": "open.overheid.nl", "env": "PROD", "state": "up",
                 "http_status": 200, "error": None},
            ]},
            {"env": "ACC", "sites": [
                {"name": "open-acc.overheid.nl", "env": "ACC", "state": "down",
                 "http_status": 404, "error": None},
            ]},
        ],
    }
    items = alerts._normalize_uptime(snap)
    by_name = {i["name"]: i for i in items}
    assert by_name["open.overheid.nl"]["severity"] == "ok"
    down = by_name["open-acc.overheid.nl"]
    assert down["severity"] == "critical"
    assert down["category"] == "environment"
    assert down["env"] == "ACC"
    assert down["card_id"] == "environment:ACC:open-acc.overheid.nl"


def test_normalize_dlq_snapshot():
    snap = {"configured": True, "dlqs": [
        {"name": "antivirus.dlq", "depth": 0, "severity": "ok"},
        {"name": "export.dlq", "depth": 250, "severity": "critical",
         "source_consumers": 0},
    ]}
    items = alerts._normalize_dlq(snap)
    by_name = {i["name"]: i for i in items}
    assert by_name["antivirus.dlq"]["severity"] == "ok"
    crit = by_name["export.dlq"]
    assert crit["severity"] == "critical"
    assert crit["category"] == "dlq"
    assert crit["env"] == "PROD"


def test_normalize_cert_list():
    class FakeCert:
        def __init__(self, host, grade, days):
            self.host, self.grade, self.days_remaining = host, grade, days
            self.status = "ok"
    certs = [
        FakeCert("open.overheid.nl", "OK", 50),
        FakeCert("open-acc.overheid.nl", "CRITICAL", 5),
        FakeCert("gateway.koop-plooi-tst.test5.s15m.nl", "WARN", 20),
    ]
    items = alerts._normalize_cert(certs)
    by_name = {i["name"]: i for i in items}
    assert by_name["open.overheid.nl"]["severity"] == "ok"
    assert by_name["open-acc.overheid.nl"]["severity"] == "critical"
    assert by_name["open-acc.overheid.nl"]["env"] == "ACC"
    assert by_name["gateway.koop-plooi-tst.test5.s15m.nl"]["severity"] == "warn"
    assert by_name["gateway.koop-plooi-tst.test5.s15m.nl"]["env"] == "TST"
