"""In-memory session store: token -> {username, sid, llm_provider, created_at, last_seen}.

Single source of truth for sessions, shared by the auth endpoints and the
dashboard router. In-memory by design (sessions reset on restart).

Sessions expire on two independent clocks (whichever fires first):
  * absolute TTL   — `session_ttl_minutes` since `created_at`
  * idle timeout   — `session_idle_minutes` since `last_seen`
An expired session is deleted on lookup and behaves exactly like an unknown
token (401), so a leaked token can never live indefinitely.
"""
import secrets
import time

from fastapi import Header, HTTPException

from config import settings

# token -> {"username": str, "sid": str, "llm_provider": str,
#           "created_at": float, "last_seen": float}
_sessions: dict[str, dict] = {}


def _now() -> float:
    """Current epoch seconds. A module-level indirection so tests can monkeypatch
    the clock (patch `session._now`) to exercise TTL/idle expiry without sleeping."""
    return time.time()


def _is_expired(session: dict, now: float) -> bool:
    """True when the session has passed its absolute TTL or idle window."""
    created = session.get("created_at", now)
    last = session.get("last_seen", now)
    if now - created > settings.session_ttl_minutes * 60:
        return True
    if now - last > settings.session_idle_minutes * 60:
        return True
    return False


def get_session(token: str, now: float | None = None) -> dict | None:
    """Return the live session for `token`, refreshing `last_seen`. Returns None
    (and evicts the session) when the token is unknown or has expired."""
    ts = _now() if now is None else now
    session = _sessions.get(token)
    if not session:
        return None
    if _is_expired(session, ts):
        _sessions.pop(token, None)
        return None
    session["last_seen"] = ts
    return session

# Valid LLM providers. "none" means the AI is switched off for the session —
# every generation call short-circuits and the deterministic fallbacks take over.
VALID_PROVIDERS = ["ollama", "mistral", "none"]


def create_session(username: str, sid: str, llm_provider: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    now = _now()
    _sessions[token] = {
        "username": username,
        "sid": sid,
        "llm_provider": llm_provider if llm_provider in VALID_PROVIDERS else None,
        "created_at": now,
        "last_seen": now,
    }
    return token


def drop_session(token: str) -> None:
    _sessions.pop(token, None)


def _token_from_header(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not logged in")
    return authorization[7:]


def require_session(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: validate the Bearer token, return the session dict.

    A token that is unknown OR whose session has passed its TTL/idle window is
    treated identically — the same 401, so an expired token leaks nothing."""
    token = _token_from_header(authorization)
    session = get_session(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return session


def set_llm_provider(token: str, provider: str) -> None:
    """Update the LLM provider preference for a session."""
    if provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Must be one of: {VALID_PROVIDERS}")
    if token in _sessions:
        _sessions[token]["llm_provider"] = provider
