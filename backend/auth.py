"""Admin authorization for dashboard endpoints.

v1 gates on an env allowlist (DASHBOARD_ADMINS). Extension point: when the
Keycloak OIDC claims (groups/roles) are captured at login, add a group check
here (e.g. session.get("groups")) before the allowlist fallback.
"""
from fastapi import Depends, HTTPException

from config import settings
from session import require_session


def require_admin(session: dict = Depends(require_session)) -> dict:
    """FastAPI dependency: 401 if not logged in, 403 if not an admin."""
    username = (session.get("username") or "").strip()
    if username and username in settings.admin_list:
        return session
    raise HTTPException(status_code=403, detail="Administrator access required")
