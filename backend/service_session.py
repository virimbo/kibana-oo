"""Config-gated background service-session for the unattended monitor loop.

The user-facing login flow is session-based (session.py): a human logs in and
their `sid` rides on their session. The BACKGROUND poll loop has no human, so it
historically ran with `sid=None`, leaving every ES-based check dormant.

This module provides a service-account `sid` for that loop ONLY when explicitly
configured (MONITOR_SERVICE_USER + MONITOR_SERVICE_PASSWORD). It is:

  * DORMANT by default — unconfigured → `get_service_sid()` returns None and no
    login is ever attempted, so behaviour is identical to today.
  * BEST-EFFORT — any failure (unreachable Keycloak, bad credentials, anything)
    is logged as a warning and degrades to None. It NEVER raises into the loop.
  * CACHED — a successful login is cached for `service_sid_ttl_minutes`; within
    that window the cached sid is reused, so the loop logs in at most once per
    TTL instead of every cycle. A failed attempt is never cached.

Use a READ-ONLY Keycloak/SP service account.
"""
import logging
import time

import elastic
from config import settings

logger = logging.getLogger(__name__)

# Module-level cache: the last good sid and the epoch second it was acquired.
_sid: str | None = None
_acquired_at: float | None = None


def _now() -> float:
    """Current epoch seconds. Indirected so tests can freeze/advance the clock
    (patch `service_session._now`) to exercise TTL expiry without sleeping."""
    return time.time()


def is_configured() -> bool:
    """True only when BOTH the service user and password are set."""
    return bool(settings.monitor_service_user and settings.monitor_service_password)


def _reset() -> None:
    """Clear the cached sid. For tests."""
    global _sid, _acquired_at
    _sid = None
    _acquired_at = None


def _is_fresh(now: float) -> bool:
    """True when we hold a cached sid younger than the configured TTL."""
    if _sid is None or _acquired_at is None:
        return False
    return (now - _acquired_at) < settings.service_sid_ttl_minutes * 60


async def get_service_sid() -> str | None:
    """Return a service-account Kibana `sid` for the background loop, or None.

    Returns None (never raises) when unconfigured, when a prior attempt failed,
    or when the login fails now. Reuses a cached sid while it is younger than
    `service_sid_ttl_minutes`; otherwise (or when expired) re-logs in.
    """
    global _sid, _acquired_at

    if not is_configured():
        return None

    now = _now()
    if _is_fresh(now):
        return _sid

    try:
        sid = await elastic.keycloak_login(
            settings.monitor_service_user,
            settings.monitor_service_password,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; never break the loop
        logger.warning("monitor service-session login failed: %s", exc)
        _reset()
        return None

    if not sid:
        # A falsy sid is not a usable session — don't cache it, retry next call.
        _reset()
        return None

    _sid = sid
    _acquired_at = now
    return sid
