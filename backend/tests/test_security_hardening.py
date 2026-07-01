"""Security-hardening tests: sliding-window login limiter, session TTL/idle
expiry, hardened config defaults, and the security-headers middleware."""
import importlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import ratelimit
import session as session_mod
from config import Settings


# ── ratelimit ────────────────────────────────────────────────────────────────
def test_ratelimit_allows_up_to_max_then_blocks():
    ratelimit.reset("k")
    # 3 allowed within the window, the 4th is blocked.
    assert ratelimit.allow("k", 3, 60, now=1000.0) is True
    assert ratelimit.allow("k", 3, 60, now=1001.0) is True
    assert ratelimit.allow("k", 3, 60, now=1002.0) is True
    assert ratelimit.allow("k", 3, 60, now=1003.0) is False


def test_ratelimit_window_resets():
    ratelimit.reset("w")
    assert ratelimit.allow("w", 2, 60, now=1000.0) is True
    assert ratelimit.allow("w", 2, 60, now=1001.0) is True
    assert ratelimit.allow("w", 2, 60, now=1002.0) is False
    # Once the window has fully elapsed, old hits are pruned and calls flow again.
    assert ratelimit.allow("w", 2, 60, now=1062.0) is True


def test_ratelimit_keys_are_independent():
    ratelimit.reset()
    assert ratelimit.allow("a", 1, 60, now=1.0) is True
    assert ratelimit.allow("a", 1, 60, now=2.0) is False
    assert ratelimit.allow("b", 1, 60, now=2.0) is True  # different key unaffected


# ── session TTL / idle ───────────────────────────────────────────────────────
@pytest.fixture
def frozen_clock(monkeypatch):
    """A mutable module-level clock: set `holder['now']`, patched into session._now."""
    holder = {"now": 1_000_000.0}
    monkeypatch.setattr(session_mod, "_now", lambda: holder["now"])
    # keep the store clean for each test
    session_mod._sessions.clear()
    yield holder


def test_session_valid_immediately(frozen_clock):
    token = session_mod.create_session("u@x.nl", "sid-1")
    assert session_mod.get_session(token) is not None
    assert session_mod.get_session(token)["username"] == "u@x.nl"


def test_session_expires_after_ttl(frozen_clock, monkeypatch):
    monkeypatch.setattr(session_mod.settings, "session_ttl_minutes", 10)
    monkeypatch.setattr(session_mod.settings, "session_idle_minutes", 10_000)
    token = session_mod.create_session("u@x.nl", "sid-1")
    frozen_clock["now"] += 11 * 60  # past the absolute TTL
    assert session_mod.get_session(token) is None
    assert token not in session_mod._sessions  # evicted


def test_session_expires_after_idle(frozen_clock, monkeypatch):
    monkeypatch.setattr(session_mod.settings, "session_ttl_minutes", 10_000)
    monkeypatch.setattr(session_mod.settings, "session_idle_minutes", 5)
    token = session_mod.create_session("u@x.nl", "sid-1")
    frozen_clock["now"] += 6 * 60  # idle beyond the idle window
    assert session_mod.get_session(token) is None


def test_session_last_seen_refresh_keeps_it_alive(frozen_clock, monkeypatch):
    monkeypatch.setattr(session_mod.settings, "session_ttl_minutes", 10_000)
    monkeypatch.setattr(session_mod.settings, "session_idle_minutes", 5)
    token = session_mod.create_session("u@x.nl", "sid-1")
    # Touch it every 4 min (< idle window) many times → stays alive.
    for _ in range(10):
        frozen_clock["now"] += 4 * 60
        assert session_mod.get_session(token) is not None
    # Then go idle past the window → expires.
    frozen_clock["now"] += 6 * 60
    assert session_mod.get_session(token) is None


def test_expired_token_behaves_like_unknown(frozen_clock, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(session_mod.settings, "session_ttl_minutes", 1)
    monkeypatch.setattr(session_mod.settings, "session_idle_minutes", 1)
    token = session_mod.create_session("u@x.nl", "sid-1")
    frozen_clock["now"] += 5 * 60
    with pytest.raises(HTTPException) as exc:
        session_mod.require_session(f"Bearer {token}")
    assert exc.value.status_code == 401


# ── config defaults ──────────────────────────────────────────────────────────
def test_super_admins_default_is_empty(monkeypatch):
    monkeypatch.delenv("SUPER_ADMINS", raising=False)
    s = Settings(_env_file=None)
    assert s.super_admins == ""
    assert s.super_admin_list == []


def test_super_admin_list_still_parses():
    s = Settings(super_admins="A@X.nl, b@y.NL ")
    assert s.super_admin_list == ["a@x.nl", "b@y.nl"]  # trimmed + lowercased


def test_security_settings_defaults():
    s = Settings(_env_file=None)
    assert s.session_ttl_minutes == 720
    assert s.session_idle_minutes == 240
    assert s.login_rate_max == 12
    assert s.login_rate_window_seconds == 60
    assert s.expose_api_docs is False


# ── security-headers middleware ──────────────────────────────────────────────
def test_security_headers_middleware_sets_headers():
    import main

    client = TestClient(main.app)
    resp = client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert resp.headers["X-Permitted-Cross-Domain-Policies"] == "none"
