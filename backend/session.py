"""In-memory session store: token -> {username, sid, llm_provider}.

Single source of truth for sessions, shared by the auth endpoints and the
dashboard router. In-memory by design (sessions reset on restart).
"""
import secrets

from fastapi import Header, HTTPException

# token -> {"username": str, "sid": str, "llm_provider": str}
_sessions: dict[str, dict] = {}

# Valid LLM providers
VALID_PROVIDERS = ["ollama", "mistral"]


def create_session(username: str, sid: str, llm_provider: str | None = None) -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "username": username,
        "sid": sid,
        "llm_provider": llm_provider if llm_provider in VALID_PROVIDERS else None,
    }
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


def set_llm_provider(token: str, provider: str) -> None:
    """Update the LLM provider preference for a session."""
    if provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Invalid provider. Must be one of: {VALID_PROVIDERS}")
    if token in _sessions:
        _sessions[token]["llm_provider"] = provider
