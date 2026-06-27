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


PENDING = {"Authorization": "Bearer pend-tok"}


def _register_pending():
    """A non-super session whose user is 'pending' (recorded but not approved)."""
    import permissions
    permissions.record_login("pend.user@koop.nl")
    _sessions["pend-tok"] = {"username": "pend.user@koop.nl", "sid": "sid2"}


def test_pending_user_blocked_from_chat(client):
    _register_pending()
    r = client.post("/chat", headers=PENDING, json={"question": "hi", "stream": False})
    assert r.status_code == 403


def test_admin_users_list_approve_suspend(client):
    import permissions
    permissions.record_login("pend@koop.nl")
    r = client.get("/admin/users", headers=SUPER)
    assert any(u["username"] == "pend@koop.nl" and u["status"] == "pending" for u in r.json())
    assert client.post("/admin/users/pend@koop.nl/approve", headers=SUPER).status_code == 200
    assert permissions.user_status("pend@koop.nl") == "approved"
    assert client.post("/admin/users/pend@koop.nl/suspend", headers=SUPER).status_code == 200
    assert permissions.user_status("pend@koop.nl") == "suspended"
