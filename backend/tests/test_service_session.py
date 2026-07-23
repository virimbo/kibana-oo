"""Tests for the config-gated background monitor service-session.

The service-session lets the UNATTENDED poll loop obtain a Kibana `sid` so
ES-based checks can run. It must be DORMANT and harmless when no credentials are
configured (return None, no login attempted), cache within its TTL, re-login
after the TTL, and NEVER raise (a failing/unreachable login degrades to None).
"""
import asyncio

import pytest

import service_session
from config import settings


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    # Start every test from empty module state + unconfigured credentials.
    service_session._reset()
    monkeypatch.setattr(settings, "monitor_service_user", "")
    monkeypatch.setattr(settings, "monitor_service_password", "")
    monkeypatch.setattr(settings, "service_sid_ttl_minutes", 30)
    monkeypatch.setattr(settings, "service_sid_quick_retries", 3)
    monkeypatch.setattr(settings, "service_sid_backoff_cap_minutes", 60)
    yield
    service_session._reset()


def _configure(monkeypatch):
    monkeypatch.setattr(settings, "monitor_service_user", "svc")
    monkeypatch.setattr(settings, "monitor_service_password", "pw")


def test_unconfigured_returns_none_without_login(monkeypatch):
    calls = []

    async def fake_login(user, password):
        calls.append((user, password))
        return "sid-should-not-happen"

    monkeypatch.setattr(service_session.elastic, "keycloak_login", fake_login)
    assert asyncio.run(service_session.get_service_sid()) is None
    assert calls == []  # never attempted a login when unconfigured


def test_is_configured_reflects_config(monkeypatch):
    assert service_session.is_configured() is False
    _configure(monkeypatch)
    assert service_session.is_configured() is True
    # Only user set → still not configured (both required).
    monkeypatch.setattr(settings, "monitor_service_password", "")
    assert service_session.is_configured() is False


def test_configured_returns_sid_from_login(monkeypatch):
    _configure(monkeypatch)

    async def fake_login(user, password):
        assert (user, password) == ("svc", "pw")
        return "sid-123"

    monkeypatch.setattr(service_session.elastic, "keycloak_login", fake_login)
    assert asyncio.run(service_session.get_service_sid()) == "sid-123"


def test_caches_within_ttl_logs_in_once(monkeypatch):
    _configure(monkeypatch)
    calls = []

    async def fake_login(user, password):
        calls.append(1)
        return f"sid-{len(calls)}"

    monkeypatch.setattr(service_session.elastic, "keycloak_login", fake_login)
    # Freeze the clock so we stay well within the TTL window.
    monkeypatch.setattr(service_session, "_now", lambda: 1000.0)

    first = asyncio.run(service_session.get_service_sid())
    second = asyncio.run(service_session.get_service_sid())
    assert first == second == "sid-1"
    assert len(calls) == 1  # cached — logged in only once


def test_relogins_after_ttl(monkeypatch):
    _configure(monkeypatch)
    calls = []

    async def fake_login(user, password):
        calls.append(1)
        return f"sid-{len(calls)}"

    monkeypatch.setattr(service_session.elastic, "keycloak_login", fake_login)

    clock = {"t": 1000.0}
    monkeypatch.setattr(service_session, "_now", lambda: clock["t"])

    first = asyncio.run(service_session.get_service_sid())
    assert first == "sid-1"
    # Advance beyond the 30-minute TTL → must re-login.
    clock["t"] += 31 * 60
    second = asyncio.run(service_session.get_service_sid())
    assert second == "sid-2"
    assert len(calls) == 2


def test_login_raising_returns_none_never_raises(monkeypatch):
    _configure(monkeypatch)

    async def boom(user, password):
        raise Exception("Invalid username or password")

    monkeypatch.setattr(service_session.elastic, "keycloak_login", boom)
    # Must swallow the exception and degrade to None.
    assert asyncio.run(service_session.get_service_sid()) is None


def test_none_result_is_not_cached_and_retries(monkeypatch):
    _configure(monkeypatch)
    calls = []

    async def flaky(user, password):
        calls.append(1)
        if len(calls) == 1:
            raise Exception("transient")
        return "sid-ok"

    monkeypatch.setattr(service_session.elastic, "keycloak_login", flaky)
    monkeypatch.setattr(service_session, "_now", lambda: 1000.0)

    # First attempt fails → None, and must NOT be cached as a valid sid.
    assert asyncio.run(service_session.get_service_sid()) is None
    # Next call (same instant, within TTL) retries the login and succeeds.
    assert asyncio.run(service_session.get_service_sid()) == "sid-ok"
    assert len(calls) == 2


def test_sustained_failure_backs_off_and_stops_hammering(monkeypatch):
    """The core lockout fix: a persistently bad/expired password must NOT be
    retried every cycle. After `service_sid_quick_retries` failures the circuit
    opens and further same-instant calls return None WITHOUT touching Keycloak."""
    _configure(monkeypatch)
    calls = []

    async def always_fail(user, password):
        calls.append(1)
        raise Exception("Invalid username or password")

    monkeypatch.setattr(service_session.elastic, "keycloak_login", always_fail)
    monkeypatch.setattr(service_session, "_now", lambda: 1000.0)

    # Hammer it many times at the same instant.
    for _ in range(20):
        assert asyncio.run(service_session.get_service_sid()) is None

    # quick_retries (3) free attempts + 1 that trips the breaker = 4 real logins;
    # everything after is short-circuited while the cooldown window is open.
    assert len(calls) == 4


def test_backoff_expires_then_retries(monkeypatch):
    """Once the cooldown window passes, exactly one new attempt is allowed."""
    _configure(monkeypatch)
    calls = []

    async def always_fail(user, password):
        calls.append(1)
        raise Exception("Invalid username or password")

    monkeypatch.setattr(service_session.elastic, "keycloak_login", always_fail)
    clock = {"t": 1000.0}
    monkeypatch.setattr(service_session, "_now", lambda: clock["t"])

    for _ in range(10):
        asyncio.run(service_session.get_service_sid())
    assert len(calls) == 4  # breaker open after the 4th

    # First cooldown after tripping is 60s. Just before it: still short-circuited.
    clock["t"] = 1000.0 + 59
    asyncio.run(service_session.get_service_sid())
    assert len(calls) == 4
    # At/after the window: exactly one more real attempt.
    clock["t"] = 1000.0 + 60
    asyncio.run(service_session.get_service_sid())
    assert len(calls) == 5


def test_success_resets_the_breaker(monkeypatch):
    """A good login clears the failure state so a later blip gets free retries
    again (the breaker is about *consecutive* failures, not lifetime)."""
    _configure(monkeypatch)
    outcome = {"ok": False}
    calls = []

    async def controllable(user, password):
        calls.append(1)
        if outcome["ok"]:
            return "sid-ok"
        raise Exception("Invalid username or password")

    monkeypatch.setattr(service_session.elastic, "keycloak_login", controllable)
    clock = {"t": 1000.0}
    monkeypatch.setattr(service_session, "_now", lambda: clock["t"])

    # Trip the breaker.
    for _ in range(10):
        asyncio.run(service_session.get_service_sid())
    assert len(calls) == 4

    # Let the window pass and let the next attempt succeed (this resets state).
    clock["t"] += 60
    outcome["ok"] = True
    assert asyncio.run(service_session.get_service_sid()) == "sid-ok"

    # Break the credentials again and expire the cached sid ONCE so a re-login is
    # needed, then hammer at that instant. If the breaker had NOT reset on success,
    # it would still be open and we'd see 0 attempts. Instead we get the full quota
    # of free retries (3) + 1 trip = 4 — proving the counter started from zero.
    outcome["ok"] = False
    calls.clear()
    clock["t"] += 31 * 60  # past the 30-min sid TTL
    for _ in range(20):
        asyncio.run(service_session.get_service_sid())
    assert len(calls) == 4
