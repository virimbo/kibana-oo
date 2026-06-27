"""Approval gate: /me/permissions exposes an `approved` flag. A super-admin is
always approved. DB isolated per test; auth mirrors test_monitor_api.py."""
import pytest
from fastapi.testclient import TestClient

import main
from config import settings
from session import _sessions


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Auth model (mirrors test_monitor_api): a SUPER admin holds every feature.
    monkeypatch.setattr(settings, "super_admins", "boss@koop.nl")
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "t.db"))
    _sessions.clear()
    _sessions["admin-tok"] = {"username": "boss@koop.nl", "sid": "sid1"}
    yield TestClient(main.app)
    _sessions.clear()


SUPER = {"Authorization": "Bearer admin-tok"}


def test_me_permissions_has_approved_flag(client):
    r = client.get("/me/permissions", headers=SUPER)
    assert r.status_code == 200
    body = r.json()
    assert "approved" in body and body["approved"] is True   # super-admin -> approved
