"""Feature authorisation: super-admin root of trust, deny-by-default, chat
baseline, grant/revoke, super-only matrix manager, and one-time admin seeding."""
import pytest

import permissions as P
from config import settings

SUPER = "boss@koop.overheid.nl"
ADMIN = "admin@koop.overheid.nl"
USER = "user@koop.overheid.nl"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "app.db"))
    monkeypatch.setattr(settings, "super_admins", SUPER)
    monkeypatch.setattr(settings, "dashboard_admins", ADMIN)
    yield


def sess(u):
    return {"username": u}


def test_is_super_from_config_case_insensitive():
    assert P.is_super(SUPER) and P.is_super(SUPER.upper())
    assert not P.is_super(USER)


def test_super_has_every_feature():
    for f in P.GRANTABLE + ["authorization"]:
        assert P.has_feature(sess(SUPER), f)


def test_chat_is_open_baseline():
    P.approve(USER, actor=SUPER)                       # baseline requires approval (gate)
    assert P.has_feature(sess(USER), "chat")          # anyone authenticated
    assert P.has_feature(sess(SUPER), "chat")


def test_deny_by_default():
    for f in P.GRANTABLE:
        assert P.has_feature(sess(USER), f) is False


def test_grant_then_revoke():
    P.approve(USER, actor=SUPER)                        # grants only apply once approved (gate)
    assert P.grant(USER, "regression", actor=SUPER) is True
    assert P.has_feature(sess(USER), "regression") is True
    assert "regression" in P.user_features(USER)
    P.revoke(USER, "regression", actor=SUPER)
    assert P.has_feature(sess(USER), "regression") is False


def test_grant_unknown_feature_rejected():
    assert P.grant(USER, "not_a_feature", actor=SUPER) is False
    assert P.has_feature(sess(USER), "not_a_feature") is False


def test_authorization_is_super_only():
    P.grant(USER, "authorization", actor=SUPER)        # not grantable → no-op
    assert P.has_feature(sess(USER), "authorization") is False
    assert P.has_feature(sess(SUPER), "authorization") is True


def test_seeding_grants_existing_admins_all_and_is_idempotent():
    P.approve(ADMIN, actor=SUPER)                       # seeded grants surface once approved (gate)
    P.ensure_seeded()
    assert set(P.user_features(ADMIN)) == set(P.GRANTABLE)
    audit_after_first = len(P.audit_log(1000))
    P.ensure_seeded()                                   # idempotent
    assert len(P.audit_log(1000)) == audit_after_first
    # a non-admin user is still deny-by-default after seeding
    assert P.has_feature(sess(USER), "dashboard") is False


def test_matrix_shape():
    P.grant(USER, "dashboard", actor=SUPER)
    m = P.matrix()
    assert {f["key"] for f in m["catalog"]} == set(P.GRANTABLE)
    row = next(u for u in m["users"] if u["username"] == USER)
    assert row["features"] == ["dashboard"]
    assert SUPER.lower() in m["super_admins"]
