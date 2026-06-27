import pytest
from config import settings
import permissions as p

@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings, "super_admins", "boss@koop.nl")
    yield

def test_record_login_registers_unknown_as_pending():
    assert p.record_login("new.user@koop.nl") == "pending"
    assert p.user_status("new.user@koop.nl") == "pending"

def test_super_admin_always_approved():
    assert p.record_login("boss@koop.nl") == "approved"
    assert p.user_status("boss@koop.nl") == "approved"
    assert p.is_approved("boss@koop.nl") is True

def test_approve_and_suspend_transitions():
    p.record_login("u@koop.nl")
    p.approve("u@koop.nl", actor="boss@koop.nl")
    assert p.user_status("u@koop.nl") == "approved" and p.is_approved("u@koop.nl") is True
    p.suspend("u@koop.nl", actor="boss@koop.nl")
    assert p.user_status("u@koop.nl") == "suspended" and p.is_approved("u@koop.nl") is False

def test_list_users_includes_status():
    p.record_login("a@koop.nl")
    rows = {r["username"]: r for r in p.list_users()}
    assert rows["a@koop.nl"]["status"] == "pending"

def test_is_approved_failsafe_when_table_empty():
    assert p.is_approved("boss@koop.nl") is True

def test_pending_user_has_no_features():
    p.record_login("u@koop.nl")
    p.grant("u@koop.nl", "dashboard", actor="boss@koop.nl")   # granted but NOT approved
    assert p.user_features("u@koop.nl") == []                 # gate: nothing until approved
    assert p.has_feature({"username": "u@koop.nl"}, "dashboard") is False
    assert p.has_feature({"username": "u@koop.nl"}, "chat") is False   # baseline gated too

def test_approved_user_gets_features_and_baseline():
    p.record_login("u2@koop.nl")
    p.approve("u2@koop.nl", actor="boss@koop.nl")
    p.grant("u2@koop.nl", "dashboard", actor="boss@koop.nl")
    assert "dashboard" in p.user_features("u2@koop.nl")
    assert p.has_feature({"username": "u2@koop.nl"}, "chat") is True
    assert p.has_feature({"username": "u2@koop.nl"}, "dashboard") is True

def test_super_admin_unaffected_by_gate():
    assert p.has_feature({"username": "boss@koop.nl"}, "chat") is True
    assert "dashboard" in p.user_features("boss@koop.nl")
