"""Service health: target parsing, endpoint classification (incl. actuator JSON),
per-service verdict, scan view, and API flag gating. Network is mocked."""
import asyncio

import pytest

import service_health as sh
import service_health_api as api
from config import settings


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(settings, "service_health_enabled", True)
    monkeypatch.setattr(settings, "service_health_degraded_ms", 2500)
    monkeypatch.setattr(settings, "service_health_timeout", 8.0)
    sh._latest = None
    yield
    sh._latest = None


def test_parse_targets_infers_kind(monkeypatch):
    monkeypatch.setattr(settings, "service_health_targets",
        "Repository | https://repo-actuator.x/actuator | https://repo-service.x/\n"
        "# comment\n"
        "Solr | https://solr.x/solr/\n")
    t = sh._parse_targets()
    assert len(t) == 2
    assert t[0]["service"] == "Repository"
    assert t[0]["endpoints"][0]["kind"] == "actuator"
    assert t[0]["endpoints"][1]["kind"] == "service"
    assert t[1]["service"] == "Solr" and t[1]["endpoints"][0]["kind"] == "service"


class _Resp:
    def __init__(self, status, json=None, ctype="application/json"):
        self.status_code = status
        self._json = json
        self.headers = {"content-type": ctype}
    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def test_actuator_status_parsed():
    assert sh._actuator_status(_Resp(200, {"status": "UP"}), "actuator") == "UP"
    assert sh._actuator_status(_Resp(200, {"status": "DOWN"}), "actuator") == "DOWN"
    # non-actuator → ignored; non-json → None
    assert sh._actuator_status(_Resp(200, {"status": "UP"}), "service") is None
    assert sh._actuator_status(_Resp(200, ctype="text/html"), "actuator") is None


def _client_returning(mapping):
    """Fake httpx.AsyncClient whose .get(url) returns mapping[url] (a _Resp) or raises."""
    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, follow_redirects=True):
            v = mapping.get(url)
            if isinstance(v, Exception):
                raise v
            return v
    return FakeClient


def test_probe_states(monkeypatch):
    import httpx
    mapping = {
        "https://a/actuator": _Resp(200, {"status": "UP"}),
        "https://b/down": _Resp(503),
        "https://c/auth": _Resp(401, ctype="text/html"),       # secured UI → up
        "https://d/unhealthy": _Resp(200, {"status": "DOWN"}),  # reached but DOWN
        "https://e/refused": httpx.ConnectError("refused"),     # → unreachable
    }
    monkeypatch.setattr(sh.httpx, "AsyncClient", _client_returning(mapping))

    async def probe(url, kind="service"):
        async with sh.httpx.AsyncClient() as c:
            return await sh._probe(c, {"url": url, "kind": kind})
    assert asyncio.run(probe("https://a/actuator", "actuator"))["state"] == sh.UP
    assert asyncio.run(probe("https://b/down"))["state"] == sh.DOWN
    assert asyncio.run(probe("https://c/auth"))["state"] == sh.UP
    assert asyncio.run(probe("https://d/unhealthy", "actuator"))["state"] == sh.DOWN
    assert asyncio.run(probe("https://e/refused"))["state"] == sh.UNREACHABLE


def test_service_verdict_worst_wins():
    assert sh._service_verdict([{"state": sh.UP}, {"state": sh.DOWN}]) == sh.DOWN
    assert sh._service_verdict([{"state": sh.UP}, {"state": sh.UNREACHABLE}]) == sh.UNREACHABLE
    assert sh._service_verdict([{"state": sh.UP}, {"state": sh.DEGRADED}]) == sh.DEGRADED
    assert sh._service_verdict([{"state": sh.UP}, {"state": sh.UP}]) == sh.UP


def test_scan_builds_view(monkeypatch):
    monkeypatch.setattr(settings, "service_health_targets",
        "Repo | https://a/actuator | https://b/down\nSolr | https://c/ok")
    mapping = {
        "https://a/actuator": _Resp(200, {"status": "UP"}),
        "https://b/down": _Resp(500),
        "https://c/ok": _Resp(200, ctype="text/html"),
    }
    monkeypatch.setattr(sh.httpx, "AsyncClient", _client_returning(mapping))
    view = asyncio.run(sh.scan())
    by = {s["service"]: s for s in view["services"]}
    assert by["Repo"]["verdict"] == sh.DOWN     # one endpoint 500
    assert by["Solr"]["verdict"] == sh.UP
    assert view["summary"]["down"] == 1
    # Repo (down) sorts before Solr (up)
    assert view["services"][0]["service"] == "Repo"


def test_api_disabled_returns_flag(monkeypatch):
    monkeypatch.setattr(settings, "service_health_enabled", False)
    out = asyncio.run(api.status(session={"username": "x"}))
    assert out == {"enabled": False}
