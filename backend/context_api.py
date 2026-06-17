"""SmartContextPanel API — additive, read-only endpoints under /dashboard/context.

Gated by both the feature flag (settings.smart_context_enabled) and the
authorisation matrix (require_feature("smart_context")). When the flag is off
every endpoint answers 200 {"enabled": false} so the frontend simply renders
nothing — no errors, instant rollback.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

import context_engine as engine
from auth import require_feature
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard/context")

# Display-only echo values are length-capped and stripped of control characters
# before they are ever returned, so a card can never inject markup via them.
_MAX_LABEL = 80


def _sanitize(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = "".join(ch for ch in value if ch.isprintable()).strip()
    return cleaned[:_MAX_LABEL] or None


@router.get("/registry")
def registry(session: dict = Depends(require_feature("smart_context"))):
    if not settings.smart_context_enabled:
        return {"enabled": False, "cards": {}}
    return {"enabled": True, "cards": engine.registry_map()}


@router.get("/card/{card_id}")
def card(
    card_id: str,
    label: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: dict = Depends(require_feature("smart_context")),
):
    if not settings.smart_context_enabled:
        return {"enabled": False}
    if not engine.is_known_card(card_id):
        raise HTTPException(status_code=404, detail="Unknown card")
    try:
        return engine.assemble(card_id, label=_sanitize(label), status=_sanitize(status))
    except Exception as e:  # noqa: BLE001 — degrade rather than 500 the panel
        logger.warning("SmartContext card assembly failed for %s: %s", card_id, e)
        raise HTTPException(status_code=502, detail="Context unavailable") from e


@router.get("/card/{card_id}/ai")
async def card_ai(
    card_id: str,
    label: str | None = Query(default=None),
    status: str | None = Query(default=None),
    session: dict = Depends(require_feature("smart_context")),
):
    if not settings.smart_context_enabled:
        return {"enabled": False}
    if not engine.is_known_card(card_id):
        raise HTTPException(status_code=404, detail="Unknown card")
    info = engine.assemble(card_id, label=_sanitize(label), status=_sanitize(status))
    return await engine.analyze(info, session=session)
