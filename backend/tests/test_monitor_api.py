"""Monitor API: config endpoints are super-admin only; the results card is
feature-gated. DB isolated per test; secret VALUES never enter the API surface."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import monitor_api
import monitor_registry as reg
from config import settings
from session import _sessions


@pytest.fixture
def client(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(monitor_api.router)
    app.include_router(monitor_api.results_router)
    # Auth model (mirrors test_dashboard): a SUPER admin holds every feature.
    monkeypatch.setattr(settings, "super_admins", "boss@koop.nl")
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "app.db"))
    # The registry caches a "schema created" flag at module level — reset it so the
    # schema is (re)applied to this test's fresh DB.
    monkeypatch.setattr(reg, "_schema_ready", False)
    _sessions.clear()
    _sessions["admin-tok"] = {"username": "boss@koop.nl", "sid": "sid1"}
    yield TestClient(app)
    _sessions.clear()


SUPER = {"Authorization": "Bearer admin-tok"}


def test_types_lists_http(client):
    r = client.get("/monitor/types", headers=SUPER)
    assert r.status_code == 200
    assert "http" in r.json()


def test_connection_never_echoes_secret_value(client, monkeypatch):
    # If a token value were ever read/returned, it would be this — assert it isn't.
    monkeypatch.setenv("MONITOR_TEST_TOKEN", "s3cr3t-value")
    r = client.post(
        "/monitor/connections",
        headers=SUPER,
        json={"kind": "prometheus", "name": "prom", "base_url": "https://prom.x",
              "secret_ref": "MONITOR_TEST_TOKEN"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["secret_ref"] == "MONITOR_TEST_TOKEN"   # the NAME is fine
    assert "s3cr3t-value" not in r.text                  # the VALUE never leaks
    # no field carries a raw secret value
    assert "secret" not in {k for k in body if k != "secret_ref"}


def test_target_create_then_list(client):
    created = client.post(
        "/monitor/targets",
        headers=SUPER,
        json={"name": "homepage", "type": "http", "environment": "prod",
              "config": {"url": "https://example.x/"}},
    )
    assert created.status_code == 200
    tid = created.json()["id"]
    listed = client.get("/monitor/targets", headers=SUPER)
    assert listed.status_code == 200
    assert any(t["id"] == tid and t["name"] == "homepage" for t in listed.json())


def test_results_card_disabled_flag(client, monkeypatch):
    monkeypatch.setattr(settings, "monitor_enabled", False)
    r = client.get("/dashboard/monitoring", headers=SUPER)
    assert r.status_code == 200
    assert r.json() == {"enabled": False}
