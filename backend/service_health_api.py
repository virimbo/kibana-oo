"""Service health API — additive, read-only endpoint under /dashboard/service-health.

Gated by the feature flag (settings.service_health_enabled) and the authorisation
matrix (require_feature("service_health")). 200 {"enabled": false} when off so the
frontend renders nothing — instant rollback. Routed under /dashboard/ so the existing
nginx proxy already covers it.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

import service_health
from auth import require_feature
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard/service-health")


@router.get("")
async def status(session: dict = Depends(require_feature("service_health"))):
    if not settings.service_health_enabled:
        return {"enabled": False}
    try:
        return await service_health.latest()
    except Exception as e:  # noqa: BLE001 — degrade rather than 500 the dashboard
        logger.error("service_health status failed: %s", e)
        raise HTTPException(status_code=502, detail="Service health unavailable") from e
