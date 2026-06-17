"""Uptime/availability API — additive, read-only endpoint under /dashboard/uptime.

Gated by the feature flag (settings.uptime_enabled) and the authorisation matrix
(require_feature("uptime")). When the flag is off it answers 200 {"enabled": false}
so the frontend renders nothing — instant rollback.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

import uptime
from auth import require_feature
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard/uptime")


@router.get("/status")
async def status(session: dict = Depends(require_feature("uptime"))):
    if not settings.uptime_enabled:
        return {"enabled": False}
    try:
        return await uptime.latest()
    except Exception as e:  # noqa: BLE001 — degrade rather than 500 the dashboard
        logger.error("Uptime status failed: %s", e)
        raise HTTPException(status_code=502, detail="Uptime status unavailable") from e
