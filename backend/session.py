"""In-memory session store: token -> {username, sid}.

Single source of truth for sessions, shared by the auth endpoints and the
dashboard router. In-memory by design (sessions reset on restart).
"""
import secrets

from fastapi import Header, HTTPException

# token -> {"username": str, "sid": str}
_sessions: dict[str, dict] = {}


def create_session(username: str, sid: str) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"username": username, "sid": sid}
    return token


def drop_session(token: str) -> None:
    _sessions.pop(token, None)


def _token_from_header(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not logged in")
    return authorization[7:]


def require_session(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: validate the Bearer token, return the session dict."""
    token = _token_from_header(authorization)
    session = _sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return session
