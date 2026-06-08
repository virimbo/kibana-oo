"""Admin-gated dashboard endpoints. Numbers come from monitoring.build_snapshot;
the briefing narrates the same snapshot. Both are cached."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import require_admin
from briefing import generate_briefing
from cache import TTLCache
from config import settings
from monitoring import build_snapshot

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard")

_summary_cache = TTLCache(ttl=settings.dashboard_cache_ttl)
_briefing_cache = TTLCache(ttl=24 * 3600)  # per day


@router.get("/summary")
async def summary(
    date: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    key = f"summary:{date or 'today'}"
    cached = _summary_cache.get(key)
    if cached is not None:
        return cached
    try:
        snap = await build_snapshot(session["sid"], date)
    except Exception as e:
        logger.error(f"Dashboard summary failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load dashboard: {e}")
    payload = snap.model_dump()
    _summary_cache.set(key, payload)
    return payload


@router.get("/briefing")
async def briefing(
    date: str | None = Query(default=None),
    regenerate: bool = Query(default=False),
    session: dict = Depends(require_admin),
):
    key = f"briefing:{date or 'today'}"
    if not regenerate:
        cached = _briefing_cache.get(key)
        if cached is not None:
            return cached
    try:
        snap = await build_snapshot(session["sid"], date)
        text = await generate_briefing(snap)
    except Exception as e:
        logger.error(f"Dashboard briefing failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI briefing unavailable: {e}")
    payload = {"briefing": text, "date": snap.date}
    _briefing_cache.set(key, payload)
    return payload
