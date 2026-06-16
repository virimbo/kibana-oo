"""Admin authorization for dashboard endpoints.

v1 gates on an env allowlist (DASHBOARD_ADMINS). Extension point: when the
Keycloak OIDC claims (groups/roles) are captured at login, add a group check
here (e.g. session.get("groups")) before the allowlist fallback.
"""
from fastapi import Depends, HTTPException

import permissions
from config import settings
from session import require_session


def require_admin(session: dict = Depends(require_session)) -> dict:
    """FastAPI dependency: 401 if not logged in, 403 if not an admin (or super)."""
    username = (session.get("username") or "").strip()
    if username and (username in settings.admin_list or permissions.is_super(username)):
        return session
    raise HTTPException(status_code=403, detail="Administrator access required")


def require_feature(feature: str):
    """Dependency factory: allow only if the session is granted `feature`
    (super admin → all; chat → baseline; otherwise an explicit grant)."""
    def dep(session: dict = Depends(require_session)) -> dict:
        if permissions.has_feature(session, feature):
            return session
        raise HTTPException(status_code=403, detail=f"Access to '{feature}' is not granted")
    return dep


def require_super(session: dict = Depends(require_session)) -> dict:
    """Dependency: super administrators only (manages the authorisation matrix)."""
    if permissions.is_super(session.get("username")):
        return session
    raise HTTPException(status_code=403, detail="Super administrator access required")
