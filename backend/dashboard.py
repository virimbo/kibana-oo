"""Admin-gated dashboard endpoints. Numbers come from monitoring.build_snapshot;
the briefing narrates the same snapshot. Both are cached."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_admin
from briefing import generate_briefing
from cache import TTLCache
from config import settings
from monitoring import build_snapshot, resolve_data_view

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard")

_summary_cache = TTLCache(ttl=settings.dashboard_cache_ttl)
_briefing_cache = TTLCache(ttl=settings.dashboard_cache_ttl)

# Allowed rolling periods (minutes). FastAPI returns 422 for anything else.
ALLOWED_PERIODS = {15, 30, 60, 360, 1440}


def _period(value: int) -> int:
    return value if value in ALLOWED_PERIODS else 15


@router.get("/summary")
async def summary(
    period: int = Query(default=15),
    data_view: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    period = _period(period)
    dv = resolve_data_view(data_view)
    key = f"summary:{dv}:{period}"
    cached = _summary_cache.get(key)
    if cached is not None:
        return cached
    try:
        snap = await build_snapshot(session["sid"], period, dv)
    except Exception as e:
        logger.error(f"Dashboard summary failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load dashboard: {e}")
    payload = snap.model_dump()
    _summary_cache.set(key, payload)
    return payload


@router.get("/briefing")
async def briefing(
    period: int = Query(default=15),
    data_view: str | None = Query(default=None),
    regenerate: bool = Query(default=False),
    session: dict = Depends(require_admin),
):
    period = _period(period)
    dv = resolve_data_view(data_view)
    key = f"briefing:{dv}:{period}"
    if not regenerate:
        cached = _briefing_cache.get(key)
        if cached is not None:
            return cached
    try:
        snap = await build_snapshot(session["sid"], period, dv)
        text = await generate_briefing(snap)
    except Exception as e:
        logger.error(f"Dashboard briefing failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI briefing unavailable: {e}")
    payload = {"briefing": text, "date": snap.date}
    _briefing_cache.set(key, payload)
    return payload
