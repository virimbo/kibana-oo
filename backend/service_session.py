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
  * CIRCUIT-BROKEN — a persistently failing login (stale/expired password) is NOT
    retried every cycle. After `service_sid_quick_retries` consecutive failures we
    back off exponentially (60s, 120s, 240s, …) up to `service_sid_backoff_cap_minutes`.
    This is deliberate: without it, one expired service password hammered Keycloak
    once a minute and tripped its brute-force lockout — which then blocked the human
    admin too, because the service account was a personal account. A success resets
    the counter.

Use a READ-ONLY Keycloak/SP service account.
"""
import logging
import time

import elastic
from config import settings

logger = logging.getLogger(__name__)

# Base cooldown for the first backoff step; each further failure doubles it,
# capped at settings.service_sid_backoff_cap_minutes.
_BACKOFF_BASE_SECONDS = 60

# Module-level cache: the last good sid and the epoch second it was acquired.
_sid: str | None = None
_acquired_at: float | None = None
# Circuit-breaker state: how many logins have failed in a row, and the earliest
# epoch second at which we're allowed to try again (0.0 = try now).
_consecutive_failures: int = 0
_next_attempt_at: float = 0.0


def _now() -> float:
    """Current epoch seconds. Indirected so tests can freeze/advance the clock
    (patch `service_session._now`) to exercise TTL expiry without sleeping."""
    return time.time()


def is_configured() -> bool:
    """True only when BOTH the service user and password are set."""
    return bool(settings.monitor_service_user and settings.monitor_service_password)


def _reset() -> None:
    """Clear the cached sid AND the circuit-breaker state. For tests."""
    global _sid, _acquired_at, _consecutive_failures, _next_attempt_at
    _sid = None
    _acquired_at = None
    _consecutive_failures = 0
    _next_attempt_at = 0.0


def _record_failure(now: float) -> None:
    """Register a failed login: drop any cached sid and, once we've exhausted the
    free quick retries, open the breaker for an exponentially growing cooldown."""
    global _sid, _acquired_at, _consecutive_failures, _next_attempt_at
    _sid = None
    _acquired_at = None
    _consecutive_failures += 1
    over = _consecutive_failures - settings.service_sid_quick_retries
    if over > 0:
        cap = settings.service_sid_backoff_cap_minutes * 60
        cooldown = min(_BACKOFF_BASE_SECONDS * (2 ** (over - 1)), cap)
        _next_attempt_at = now + cooldown
        logger.warning(
            "monitor service-session: %d consecutive failures — backing off %ds "
            "before the next Keycloak login attempt (avoids account lockout)",
            _consecutive_failures, int(cooldown),
        )


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
    global _sid, _acquired_at, _consecutive_failures, _next_attempt_at

    if not is_configured():
        return None

    now = _now()
    if _is_fresh(now):
        return _sid

    # Circuit open: a recent run of failures means we're in a cooldown window.
    # Return None WITHOUT touching Keycloak, so a bad password can't be hammered.
    if now < _next_attempt_at:
        return None

    try:
        sid = await elastic.keycloak_login(
            settings.monitor_service_user,
            settings.monitor_service_password,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort; never break the loop
        logger.warning(
            "monitor service-session login failed (attempt %d): %s",
            _consecutive_failures + 1, exc,
        )
        _record_failure(now)
        return None

    if not sid:
        # A falsy sid is not a usable session — treat it as a failure so repeated
        # empty results also back off instead of retrying every cycle.
        _record_failure(now)
        return None

    _sid = sid
    _acquired_at = now
    _consecutive_failures = 0
    _next_attempt_at = 0.0
    return sid
