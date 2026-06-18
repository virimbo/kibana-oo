"""DLQ Intelligence API — read-only, gated by the existing `rabbitmq` grant.
200 {enabled:false} when the flag is off (instant rollback)."""
import logging

from fastapi import APIRouter, Depends, HTTPException

import dlq_intel
from auth import require_feature
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard/dlq")


@router.get("/intel")
async def intel(session: dict = Depends(require_feature("rabbitmq"))):
    if not settings.dlq_intel_enabled:
        return {"enabled": False}
    try:
        view = await dlq_intel.latest()
        return {"enabled": True, **view}
    except Exception as e:  # noqa: BLE001 — degrade, never 500 the dashboard
        logger.error("dlq_intel status failed: %s", e)
        raise HTTPException(status_code=502, detail="DLQ intelligence unavailable") from e
