"""Uptime monitor: target parsing, classification (up/degraded/down/unreachable
incl. internal-vs-public), status allowlist, view grouping, and API flag gating.
Network is mocked — no real HTTP."""
import asyncio

import httpx
import pytest
from fastapi import HTTPException

import uptime
import uptime_api as api
from config import settings


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    uptime._state.clear()
    uptime._latest = None
    monkeypatch.setattr(settings, "uptime_enabled", True)
    monkeypatch.setattr(settings, "uptime_degraded_ms", 2000)
    monkeypatch.setattr(settings, "uptime_alert_enabled", False)
    monkeypatch.setattr(settings, "uptime_history", 30)
    yield
    uptime._state.clear()
    uptime._latest = None


# ── parsing ──────────────────────────────────────────────────────────────────
def test_parse_targets_fields_and_internal(monkeypatch):
    monkeypatch.setattr(settings, "uptime_targets",
        "open | PROD | https://open.x | 2xx,3xx\n"
        "# a comment\n"
        "admin | PROD | http://admin.x/login | 2xx | internal\n")
    ts = uptime._parse_targets()
    assert len(ts) == 2
    assert ts[0] == {"name": "open", "env": "PROD", "url": "https://open.x",
                     "expected": ["2xx", "3xx"], "internal": False}
    assert ts[1]["internal"] is True


def test_status_ok_classes_and_explicit():
    assert uptime._status_ok(200, ["2xx", "3xx"]) is True
    assert uptime._status_ok(302, ["2xx", "3xx"]) is True
    assert uptime._status_ok(404, ["2xx", "3xx"]) is False
    assert uptime._status_ok(401, ["200", "401"]) is True


# ── classification via _probe (mocked transport) ─────────────────────────────
def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _probe(target, handler):
    async def run():
        async with _client(handler) as c:
            return await uptime._probe(c, target)
    return asyncio.run(run())


def test_probe_up_on_expected_status():
    t = {"url": "https://x", "expected": ["2xx"], "internal": False}
    r = _probe(t, lambda req: httpx.Response(200))
    assert r["state"] == "up" and r["http_status"] == 200


def test_probe_down_on_unexpected_status():
    t = {"url": "https://x", "expected": ["2xx"], "internal": False}
    r = _probe(t, lambda req: httpx.Response(503))
    assert r["state"] == "down" and r["http_status"] == 503


def test_probe_degraded_when_slow(monkeypatch):
    monkeypatch.setattr(settings, "uptime_degraded_ms", -1)  # force "slow"
    t = {"url": "https://x", "expected": ["2xx"], "internal": False}
    r = _probe(t, lambda req: httpx.Response(200))
    assert r["state"] == "degraded"


def test_probe_internal_failure_is_unreachable():
    t = {"url": "https://vpn-only", "expected": ["2xx"], "internal": True}
    def boom(req): raise httpx.ConnectError("no route", request=req)
    r = _probe(t, boom)
    assert r["state"] == "unreachable" and r["http_status"] is None


def test_probe_public_failure_is_down():
    t = {"url": "https://public", "expected": ["2xx"], "internal": False}
    def boom(req): raise httpx.ConnectError("refused", request=req)
    r = _probe(t, boom)
    assert r["state"] == "down"


# ── scan view: grouping, summary, history/uptime% ────────────────────────────
def test_scan_builds_grouped_view(monkeypatch):
    monkeypatch.setattr(settings, "uptime_targets",
        "open | PROD | https://open.x | 2xx\n"
        "gw | TEST | https://gw.x | 2xx | internal\n")
    def handler(req):
        return httpx.Response(200) if "open.x" in str(req.url) else httpx.Response(500)
    monkeypatch.setattr(uptime, "httpx", httpx)  # ensure same module
    async def run():
        # Patch AsyncClient to use the mock transport.
        orig = httpx.AsyncClient
        def factory(*a, **k):
            k.pop("timeout", None); k.pop("headers", None)
            return orig(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return await uptime.scan()
    view = asyncio.run(run())
    assert view["enabled"] is True
    envs = {g["env"] for g in view["groups"]}
    assert envs == {"PROD", "TEST"}
    # gw is internal but returned 500 (reached) → down, not unreachable.
    gw = next(s for g in view["groups"] for s in g["sites"] if s["name"] == "gw")
    assert gw["state"] == "down"
    assert gw["uptime_pct"] == 0
    assert view["summary"]["down"] == 1 and view["summary"]["verdict"] == "down"


# ── API gating ───────────────────────────────────────────────────────────────
def test_status_endpoint_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "uptime_enabled", False)
    assert asyncio.run(api.status(session={})) == {"enabled": False}


def test_status_endpoint_enabled_returns_view(monkeypatch):
    monkeypatch.setattr(settings, "uptime_targets", "open | PROD | https://open.x | 2xx")
    orig = httpx.AsyncClient
    def factory(*a, **k):
        k.pop("timeout", None); k.pop("headers", None)
        return orig(transport=httpx.MockTransport(lambda req: httpx.Response(200)))
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    out = asyncio.run(api.status(session={}))
    assert out["enabled"] is True and out["summary"]["up"] == 1
