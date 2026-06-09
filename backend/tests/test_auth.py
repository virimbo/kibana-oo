import pytest
from fastapi import HTTPException

import auth


def test_admin_allowed(monkeypatch):
    monkeypatch.setattr(auth.settings, "dashboard_admins", "boss@koop.nl")
    session = {"username": "boss@koop.nl", "sid": "x"}
    assert auth.require_admin(session) is session


def test_non_admin_forbidden(monkeypatch):
    monkeypatch.setattr(auth.settings, "dashboard_admins", "boss@koop.nl")
    session = {"username": "intern@koop.nl", "sid": "x"}
    with pytest.raises(HTTPException) as exc:
        auth.require_admin(session)
    assert exc.value.status_code == 403


def test_empty_allowlist_forbids_everyone(monkeypatch):
    monkeypatch.setattr(auth.settings, "dashboard_admins", "")
    session = {"username": "anyone@koop.nl", "sid": "x"}
    with pytest.raises(HTTPException) as exc:
        auth.require_admin(session)
    assert exc.value.status_code == 403
