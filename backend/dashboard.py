"""Admin-gated dashboard endpoints. Numbers come from monitoring.build_snapshot;
the briefing narrates the same snapshot. Both are cached."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

import asyncio

import notify
from auth import require_admin
from briefing import explain_trace, generate_briefing
from cache import TTLCache
from digest import build_digest
from certificates import fetch_certificates
from config import settings
from documents import build_document_activity, build_pipeline_health, build_pipeline_outcomes, trace_document
from llm import provider_model
from monitoring import build_snapshot, resolve_data_view
import aanlever
import regression

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard")

_summary_cache = TTLCache(ttl=settings.dashboard_cache_ttl)
_briefing_cache = TTLCache(ttl=settings.dashboard_cache_ttl)
_cert_cache = TTLCache(ttl=3600)  # certificates change slowly
_documents_cache = TTLCache(ttl=settings.dashboard_cache_ttl)
_trace_cache = TTLCache(ttl=settings.dashboard_cache_ttl)
_health_cache = TTLCache(ttl=settings.dashboard_cache_ttl)
_outcomes_cache = TTLCache(ttl=settings.dashboard_cache_ttl)
_aanlever_cache = TTLCache(ttl=settings.dashboard_cache_ttl)

# Allowed rolling periods (minutes). FastAPI returns 422 for anything else.
ALLOWED_PERIODS = {15, 30, 60, 360, 1440}


def _period(value: int) -> int:
    return value if value in ALLOWED_PERIODS else 15


async def get_cached_snapshot(sid: str, period: int, data_view: str | None) -> dict:
    """Cluster snapshot as a dict, served from the shared dashboard cache. Used by
    BOTH the /summary endpoint and the chat health path, so a health question
    reuses the dashboard's already-computed facts instead of re-running dozens of
    Elasticsearch queries on every message (which made chat slow / time out)."""
    period = _period(period)
    dv = resolve_data_view(data_view)
    key = f"summary:{dv}:{period}"
    cached = _summary_cache.get(key)
    if cached is not None:
        return cached
    payload = (await build_snapshot(sid, period, dv)).model_dump()
    _summary_cache.set(key, payload)
    return payload


async def get_cached_health(sid: str, data_view: str | None) -> dict:
    """Pipeline health, served from the shared dashboard cache (see above). The
    expensive scan + portal verification runs at most once per cache TTL,
    regardless of whether the dashboard or the chat asked for it."""
    dv = resolve_data_view(data_view)
    cached = _health_cache.get("health")
    if cached is not None:
        return cached
    result = await build_pipeline_health(sid, dv)
    _health_cache.set("health", result)
    return result


@router.get("/summary")
async def summary(
    period: int = Query(default=15),
    data_view: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    try:
        return await get_cached_snapshot(session["sid"], period, data_view)
    except Exception as e:
        logger.error(f"Dashboard summary failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load dashboard: {e}")


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
        text = await generate_briefing(snap, session=session)
    except Exception as e:
        logger.error(f"Dashboard briefing failed: {e}")
        raise HTTPException(status_code=502, detail=f"AI briefing unavailable: {e}")
    payload = {"briefing": text, "period_minutes": snap.period_minutes, "data_view": snap.data_view}
    _briefing_cache.set(key, payload)
    return payload


@router.get("/certificates")
async def certificates(session: dict = Depends(require_admin)):
    """TLS certificate expiry countdowns, read from Kibana monitoring data."""
    cached = _cert_cache.get("certs")
    if cached is not None:
        return cached
    try:
        certs = await fetch_certificates(session["sid"])
    except Exception as e:
        logger.error(f"Certificate lookup failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load certificates: {e}")
    payload = {"certificates": [c.model_dump() for c in certs]}
    _cert_cache.set("certs", payload)
    return payload


@router.get("/documents")
async def documents(
    period: int = Query(default=60),
    data_view: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    """Document-flow activity: lifecycle events, types, errors, and a live feed."""
    period = _period(period)
    dv = resolve_data_view(data_view)
    key = f"documents:{dv}:{period}"
    cached = _documents_cache.get(key)
    if cached is not None:
        return cached
    try:
        activity = await build_document_activity(session["sid"], period, dv)
    except Exception as e:
        logger.error(f"Document activity failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load document activity: {e}")
    payload = activity.model_dump()
    _documents_cache.set(key, payload)
    return payload


async def _get_trace(sid: str, doc_id: str, dv: str) -> dict:
    """Trace one document, cached briefly so the AI-explain call reuses it."""
    key = f"trace:{dv}:{doc_id}"
    cached = _trace_cache.get(key)
    if cached is not None:
        return cached
    result = await trace_document(sid, doc_id, dv)
    _trace_cache.set(key, result)
    return result


@router.get("/pipeline-health")
async def pipeline_health(
    data_view: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    """Proactive: documents stuck in the pipeline + where problems cluster by
    stage, so admins catch issues without tracing each document."""
    try:
        return await get_cached_health(session["sid"], data_view)
    except Exception as e:
        logger.error(f"Pipeline health failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load pipeline health: {e}")


@router.get("/outcomes")
async def outcomes(
    period: int = Query(default=60),
    data_view: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    """Document outcomes for the window, split by pipeline (OVS/NVS): published,
    updated, withdrawn, failed-to-publish, plus success rate, backlog, latency and
    trend. Cached per (data view, period)."""
    period = _period(period)
    dv = resolve_data_view(data_view)
    key = f"outcomes:{dv}:{period}"
    cached = _outcomes_cache.get(key)
    if cached is not None:
        return cached
    try:
        result = await build_pipeline_outcomes(session["sid"], period, dv)
    except Exception as e:
        logger.error(f"Pipeline outcomes failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load pipeline outcomes: {e}")
    _outcomes_cache.set(key, result)
    return result


@router.post("/digest/send")
async def digest_send(
    data_view: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    """Build the 'documents needing attention' digest and send it now via the
    configured channels (email and/or webhook). Uses the caller's session."""
    dv = resolve_data_view(data_view)
    try:
        health = await build_pipeline_health(session["sid"], dv)
    except Exception as e:
        logger.error(f"Digest health failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to build digest: {e}")

    digest = build_digest(health)
    email_ok = (
        await asyncio.to_thread(notify.send_email, digest["subject"], digest["html"], digest["text"])
        if notify.email_configured() else False
    )
    webhook_ok = await notify.send_webhook(digest["text"]) if notify.webhook_configured() else False
    return {
        "configured": notify.email_configured() or notify.webhook_configured(),
        "sent": email_ok or webhook_ok,
        "email": email_ok,
        "webhook": webhook_ok,
        "count": digest["count"],
        "critical": digest["critical"],
    }


# ── Regression test (post-release health gate for open.overheid.nl) ──────────
@router.post("/regression/run")
async def regression_run(session: dict = Depends(require_admin)):
    """Start a regression run in the background; returns its id to poll."""
    run_id = await regression.start_run(trigger="manual")
    return {"run_id": run_id, "running": True}


@router.get("/regression/latest")
async def regression_latest(session: dict = Depends(require_admin)):
    """The most recent run (live while in progress), or null if none yet."""
    run = await regression.latest_run()
    return run.model_dump() if run else {"run": None}


@router.get("/regression/runs")
async def regression_runs(limit: int = Query(default=20, ge=1, le=100),
                          session: dict = Depends(require_admin)):
    return {"runs": await regression.list_runs(limit)}


@router.get("/regression/reliability")
async def regression_reliability(limit: int = Query(default=50, ge=1, le=500),
                                 session: dict = Depends(require_admin)):
    """Per-check pass/warn/fail counts over the last `limit` runs — flaky-check radar."""
    return {"checks": await regression.reliability(limit), "window": limit}


@router.get("/regression/runs/{run_id}")
async def regression_run_detail(run_id: str, session: dict = Depends(require_admin)):
    run = await regression.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.model_dump()


# ── Aanleverfouten (documents rejected at delivery/intake) ───────────────────
@router.get("/aanleverfouten")
async def aanleverfouten(
    data_view: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    """Documents rejected at the doculoket/aanlever stage, grouped by publisher +
    error type. Durable (open until published or acknowledged), reconciled against
    open.overheid.nl. Cached so the badge poll is cheap."""
    cached = _aanlever_cache.get("view")
    if cached is not None:
        return cached
    try:
        view = await aanlever.scan(session["sid"], data_view)
    except Exception as e:
        logger.error(f"Aanleverfouten scan failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to load aanleverfouten: {e}")
    _aanlever_cache.set("view", view)
    return view


@router.post("/aanleverfouten/{doc_id}/ack")
async def aanleverfouten_ack(doc_id: str, session: dict = Depends(require_admin)):
    """Acknowledge (dismiss) an aanleverfout so it stops showing in the list/badge."""
    ok = await aanlever.acknowledge(doc_id)
    _aanlever_cache.clear()  # reflect immediately
    return {"acknowledged": ok}


@router.get("/document-trace")
async def document_trace(
    id: str = Query(..., min_length=2, max_length=200),
    data_view: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    """Trace one document's full lifecycle across services by its Plooi/ronl id."""
    dv = resolve_data_view(data_view)
    try:
        return await _get_trace(session["sid"], id, dv)
    except Exception as e:
        logger.error(f"Document trace failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to trace document: {e}")


@router.get("/document-trace/explain")
async def document_trace_explain(
    id: str = Query(..., min_length=2, max_length=200),
    data_view: str | None = Query(default=None),
    session: dict = Depends(require_admin),
):
    """Grounded, plain-language AI summary of one document's journey. Reports the
    provider/model used. Never fails the request on an LLM error — the error is
    returned inline so the UI can show it without losing the deterministic trace."""
    dv = resolve_data_view(data_view)
    provider, model = provider_model(session)
    try:
        trace = await _get_trace(session["sid"], id, dv)
    except Exception as e:
        logger.error(f"Document trace (for explain) failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to trace document: {e}")

    if not trace.get("found"):
        return {"summary": "No log events for this id in this data view, so there is nothing to analyze.",
                "provider": provider, "model": model, "error": False}
    try:
        summary = await explain_trace(trace, session=session)
        return {"summary": summary, "provider": provider, "model": model, "error": False}
    except Exception as e:
        logger.error(f"Trace AI explain failed: {e}")
        return {"summary": str(e), "provider": provider, "model": model, "error": True}
