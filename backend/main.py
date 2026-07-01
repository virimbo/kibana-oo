"""KIBANA-OO Backend — FastAPI app connecting LLAMA to Elasticsearch via Kibana."""

import asyncio
import json
import logging
import re
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import ratelimit

import redact
from config import settings
from elastic import (
    extract_doc_ids,
    get_recent_errors,
    get_recent_logs,
    keycloak_login,
    search_by_document_id,
    search_logs,
)
from llm import generate_answer, generate_answer_stream, polish_text, provider_model, HEALTH_ANALYSIS_SYSTEM
from ocr import image_to_text
from portal import fetch_document_meta
from session import create_session, drop_session, require_session, set_llm_provider, VALID_PROVIDERS
from dashboard import router as dashboard_router, get_cached_snapshot, get_cached_health
from context_api import router as context_router
from cert_monitor import run_cert_monitor_loop
from rabbitmq_dlq import run_dlq_monitor_loop
from uptime import run_uptime_monitor_loop
from uptime_api import router as uptime_router
from infra_api import router as infra_router
from alerts_api import router as alerts_router
from alerts import run_alert_loop
from dlq_intel_api import router as dlq_intel_router
from dlq_intel import run_dlq_intel_loop
from service_health_api import router as service_health_router
from service_health import run_service_health_loop
from monitor_api import router as monitor_router, results_router as monitor_results_router
from monitor_engine import run_monitor_loop
from auth import require_super
import permissions
import regression

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background workers on boot, cancel them on shutdown."""
    try:
        permissions.ensure_seeded()  # one-time: grant existing admins all features
    except Exception as e:  # noqa: BLE001 — must not block startup
        logger.error(f"Feature-grant seeding failed: {e}")
    cert_task = asyncio.create_task(run_cert_monitor_loop())
    dlq_task = asyncio.create_task(run_dlq_monitor_loop())
    uptime_task = asyncio.create_task(run_uptime_monitor_loop())
    alerts_task = asyncio.create_task(run_alert_loop())
    dlq_intel_task = asyncio.create_task(run_dlq_intel_loop())
    service_health_task = asyncio.create_task(run_service_health_loop())
    monitor_task = asyncio.create_task(run_monitor_loop())
    logger.info("Started background monitors (TLS certificates, RabbitMQ DLQ, uptime, alerting, DLQ intelligence, service health, monitoring registry).")
    try:
        yield
    finally:
        for t in (cert_task, dlq_task, uptime_task, alerts_task, dlq_intel_task, service_health_task, monitor_task):
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="KIBANA-OO",
    description="AI-powered chat interface for Elasticsearch logs and metrics",
    version="0.4.0",
    lifespan=lifespan,
    # Gate the interactive API docs / OpenAPI schema off by default so the
    # endpoint surface isn't advertised in production. Flip EXPOSE_API_DOCS=true
    # to bring them back for local development.
    docs_url="/docs" if settings.expose_api_docs else None,
    redoc_url="/redoc" if settings.expose_api_docs else None,
    openapi_url="/openapi.json" if settings.expose_api_docs else None,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Set conservative security headers on every response — cheap defence-in-depth
    against MIME sniffing, clickjacking and referrer/policy leakage."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:3000"],
    allow_methods=["GET", "POST", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(dashboard_router)
app.include_router(context_router)
app.include_router(uptime_router)
app.include_router(infra_router)
app.include_router(alerts_router)
app.include_router(dlq_intel_router)
app.include_router(service_health_router)
app.include_router(monitor_router)
app.include_router(monitor_results_router)

class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    question: str = ""
    time_range_minutes: int = 60
    data_view: str | None = None
    stream: bool = True
    image: str | None = None       # base64 data URL of an uploaded screenshot
    autocorrect: bool = True       # auto spelling/grammar correction of the question


# Friendly labels for the known data views (falls back to the raw id).
DATA_VIEW_LABELS = {
    "logs-*": "All logs",
    "ds-prod5-koop-plooi*": "KOOP Plooi (prod5)",
    "ds-prod5-koop-sp": "KOOP SP (prod5)",
    "apm-*": "APM",
}


def _resolve_data_view(requested: str | None) -> str:
    """Validate a requested data view against the whitelist, else use the default."""
    allowed = settings.data_view_list
    if requested and requested in allowed:
        return requested
    if settings.default_data_view in allowed:
        return settings.default_data_view
    return allowed[0]


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]


@app.get("/health")
async def health():
    """Health check endpoint (no auth required)."""
    model = settings.mistral_model if settings.llm_provider == "mistral" else settings.ollama_model
    return {"status": "ok", "model": model, "provider": settings.llm_provider}


@app.post("/regression/trigger")
async def regression_trigger(x_regression_token: str | None = Header(default=None)):
    """Token-authenticated trigger for CI/CD to run the regression suite on deploy.
    Disabled unless REGRESSION_TRIGGER_TOKEN is set. Not session-based, so a
    pipeline can call it with a static secret header (X-Regression-Token)."""
    token = settings.regression_trigger_token
    if not token:
        raise HTTPException(status_code=404, detail="Regression trigger is not enabled")
    if not x_regression_token or not secrets.compare_digest(x_regression_token, token):
        raise HTTPException(status_code=401, detail="Invalid regression token")
    run_id = await regression.start_run(trigger="ci")
    return {"run_id": run_id, "running": True}


@app.get("/llm-providers")
async def get_llm_providers():
    """List available LLM providers (no auth required)."""
    return {"providers": VALID_PROVIDERS}


@app.post("/llm-provider")
async def set_llm_provider_endpoint(
    provider: str,
    session: dict = Depends(require_session),
    authorization: str | None = Header(default=None),
):
    """Set the LLM provider preference for the current session."""
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else None
    if token:
        set_llm_provider(token, provider)
    return {"status": "ok", "provider": provider}


@app.get("/data-views")
async def data_views():
    """List the data views (ES index patterns) the user may query."""
    return {
        "data_views": [
            {"id": dv, "label": DATA_VIEW_LABELS.get(dv, dv)}
            for dv in settings.data_view_list
        ],
        "default": _resolve_data_view(None),
    }


# ── Authorisation (feature grants) ────────────────────────────────────────────
class GrantBody(BaseModel):
    username: str
    feature: str


@app.get("/me/permissions")
async def my_permissions(session: dict = Depends(require_session)):
    """What the current user may see/do — the frontend renders from this."""
    username = session["username"]
    return {
        "username": username,
        "is_super": permissions.is_super(username),
        "features": permissions.user_features(username),
        "catalog": permissions.CATALOG,
        "approved": permissions.is_approved(username),
    }


@app.get("/admin/grants")
async def list_grants(session: dict = Depends(require_super)):
    """The full authorisation matrix (super admin only)."""
    return permissions.matrix()


@app.post("/admin/grants")
async def add_grant(body: GrantBody, session: dict = Depends(require_super)):
    if not permissions.grant(body.username, body.feature, session["username"]):
        raise HTTPException(status_code=400, detail="Unknown feature")
    return {"ok": True}


@app.delete("/admin/grants")
async def remove_grant(body: GrantBody, session: dict = Depends(require_super)):
    permissions.revoke(body.username, body.feature, session["username"])
    return {"ok": True}


@app.get("/admin/grants/audit")
async def grants_audit(session: dict = Depends(require_super)):
    return {"audit": permissions.audit_log(200)}


@app.get("/admin/users")
async def admin_users(session: dict = Depends(require_super)):
    return permissions.list_users()


@app.post("/admin/users/{username}/approve")
async def admin_user_approve(username: str, session: dict = Depends(require_super)):
    permissions.approve(username, session.get("username"))
    return {"ok": True, "status": "approved"}


@app.post("/admin/users/{username}/suspend")
async def admin_user_suspend(username: str, session: dict = Depends(require_super)):
    permissions.suspend(username, session.get("username"))
    return {"ok": True, "status": "suspended"}


@app.post("/login")
async def login(body: LoginRequest, request: Request):
    """Log in via Keycloak and create a session."""
    # Rate-limit by client IP to blunt credential stuffing. Prefer the real
    # socket peer; fall back to X-Forwarded-For's first hop behind a proxy.
    client_ip = request.client.host if request.client else None
    if not client_ip:
        fwd = request.headers.get("x-forwarded-for", "")
        client_ip = fwd.split(",")[0].strip() or "unknown"
    if not ratelimit.allow(
        f"login:{client_ip}", settings.login_rate_max, settings.login_rate_window_seconds
    ):
        raise HTTPException(
            status_code=429,
            detail="Te veel loginpogingen — probeer het over een minuut opnieuw.",
        )

    username = body.username.strip()
    password = body.password

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    try:
        sid = await keycloak_login(username, password)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
        logger.warning(f"Cannot reach Kibana for {username}: {e}")
        raise HTTPException(
            status_code=503,
            detail=(
                "Cannot reach Kibana. Please check that you are connected to the "
                "company network or VPN, then try again."
            ),
        )
    except Exception as e:
        msg = str(e)
        if "name resolution" in msg.lower() or "Errno -3" in msg or "Errno -5" in msg:
            logger.warning(f"Cannot reach Kibana (DNS) for {username}: {e}")
            raise HTTPException(
                status_code=503,
                detail=(
                    "Cannot reach Kibana. Please check that you are connected to the "
                    "company network or VPN, then try again."
                ),
            )
        # Log the real error server-side, but never echo internal details
        # (hostnames, Keycloak response bodies) back to the client.
        logger.error(f"Login failed for {username}: {e}")
        raise HTTPException(
            status_code=401,
            detail="Inloggen mislukt. Controleer je gebruikersnaam en wachtwoord en probeer het opnieuw.",
        )

    # Create session token
    token = create_session(username, sid)
    permissions.record_login(username)

    logger.info(f"User {username} logged in successfully")
    return {
        "token": token,
        "username": username,
    }


@app.post("/logout")
async def logout(authorization: str | None = Header(default=None)):
    """Clear the session."""
    if authorization and authorization.startswith("Bearer "):
        drop_session(authorization[7:])
    return {"status": "ok"}


@app.post("/chat")
async def chat(
    request: ChatRequest,
    session: dict = Depends(require_session),
):
    """Process a chat question: search ES via Kibana, generate answer with LLAMA."""
    if not permissions.is_approved(session.get("username")):
        raise HTTPException(status_code=403, detail="Account in afwachting van goedkeuring")
    sid = session["sid"]
    username = session["username"]

    question = request.question.strip()

    # Step 0: if a screenshot was attached, OCR it (offline, non-fatal) and fold
    # the text into the question so the rest of the pipeline — including document
    # id detection — works on it. OCR is blocking, so run it off the event loop.
    image_text = ""
    if request.image:
        image_text = await asyncio.to_thread(image_to_text, request.image)

    if not question and not image_text:
        raise HTTPException(status_code=400, detail="Provide a question or a readable image")

    # The full text we search/detect ids against (typed + extracted-from-image).
    search_text = "\n".join(t for t in (question, image_text) if t).strip()
    data_view = _resolve_data_view(request.data_view)
    doc_ids = extract_doc_ids(search_text)
    logger.info(f"[{username}] [{data_view}] Question: {question[:80]}"
                + (f" · image_text={len(image_text)}c" if image_text else "")
                + (f" · doc_ids={doc_ids}" if doc_ids else ""))

    async def _do_search() -> tuple[list[dict], str, str | None, str | None]:
        """Returns (sources, llm_context, instant_message, preamble). When
        instant_message is set, the data is genuinely empty and we answer
        immediately without the (slow) LLM. When preamble is set (health
        questions), it is deterministic facts shown INSTANTLY before the LLM
        prose streams underneath."""
        if doc_ids:
            # Intelligent path: the text names specific document id(s). Trace each
            # across a WIDE window AND across EVERY data view, enriched with the
            # official title from the public portal.
            id_hits, metas = await asyncio.gather(
                asyncio.gather(*[_collect_doc_events(sid, did) for did in doc_ids]),
                asyncio.gather(*[fetch_document_meta(did) for did in doc_ids], return_exceptions=True),
            )
            results = [hit for hits in id_hits for hit in hits]
            ctx = _build_doc_context(doc_ids, id_hits, metas, settings.chat_doc_scan_days)
            if not ctx.strip():
                views = ", ".join(settings.data_view_list)
                ctx = (
                    f"No log events were found for {', '.join(doc_ids)} in any data view "
                    f"({views}) over the last {settings.chat_doc_scan_days} days. State "
                    "this plainly: the id may be wrong, outside the retention window, or "
                    "the events are not yet indexed."
                )
            return results, ctx, None, None

        # Generic path: search the SELECTED view + window first. If that is empty,
        # automatically broaden BOTH the index (all data views) AND the time window
        # (recent activity may simply be older than the narrow selected range) so
        # the chat finds data wherever — and whenever — it lives.
        minutes = request.time_range_minutes

        # Health/status questions ("which services are failing/unhealthy",
        # "what's wrong right now") are answered from the SAME ground-truth data
        # the dashboard uses — the cluster snapshot plus document-pipeline health
        # — instead of a blind keyword log-search. This makes the chat agree with
        # the header's "N stuck" badge and directly answers "worst first, with
        # what's going wrong". Per-source failures are tolerated; if no health
        # context can be built we fall through to the generic search below.
        if _is_health_question(search_text):
            try:
                snap_res, health_res = await asyncio.wait_for(
                    asyncio.gather(
                        get_cached_snapshot(sid, minutes, data_view),
                        get_cached_health(sid, data_view),
                        return_exceptions=True,
                    ),
                    timeout=settings.chat_health_timeout,
                )
            except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
                logger.warning(f"Health facts unavailable ({e}); falling back to log search.")
                snap_res = health_res = None
            snap = snap_res if isinstance(snap_res, dict) else None
            health = health_res if isinstance(health_res, dict) else None
            health_ctx = _build_health_context(snap, health)
            if health_ctx.strip():
                # Deterministic facts shown instantly; AI prose streams after.
                facts = _render_health_facts(snap, health) or None
                return [], health_ctx, None, facts

        all_views = settings.data_view_list
        logs, errors = await _fetch_generic(sid, search_text, minutes, data_view)
        scope, window = data_view, f"the last {minutes} min"
        broadened = False
        if not logs and not errors:
            wide_minutes = max(minutes, settings.chat_widen_minutes)  # e.g. 24h
            logs, errors = await _fetch_generic(
                sid, search_text, wide_minutes, ",".join(all_views)
            )
            scope, window = "all data views", f"the last {wide_minutes // 60} h"
            broadened = True

        results = logs + errors
        if not results:
            instant = (
                f"I searched **{scope}** over {window} and found no log events to "
                "analyse.\n\nTry one of these:\n"
                "- Pick a different **data view**\n"
                "- The cluster may simply be quiet right now\n"
                "- For a specific document, paste or type its **id** and I'll trace it across every view"
            )
            return [], "", instant, None

        ctx = _build_context(logs, [], errors)
        if broadened:
            ctx += (
                f"\n\n(Note: no events matched in '{data_view}' for the selected range; "
                f"these results are from all data views over {window}. Mention this to the user.)"
            )
        return results, ctx, None, None

    async def _search_and_compose():
        """Spell-correct the question AND search Kibana concurrently, then assemble
        what the user sees and what the model is asked."""
        polish_coro = (
            polish_text(question, session) if (request.autocorrect and question) else _passthrough(question)
        )
        polished, (all_results, context, instant, preamble) = await asyncio.gather(polish_coro, _do_search())
        display_question = polished or "(screenshot)"
        llm_question = polished or "Analyze the attached screenshot and answer any question it contains."
        if image_text:
            llm_question = f"{llm_question}\n\n[Text extracted from the attached image]:\n{image_text}"
        return display_question, llm_question, all_results, context, instant, preamble

    # Streaming: return the SSE response IMMEDIATELY and do the (possibly slow)
    # search INSIDE the generator. This flushes the response headers right away and
    # lets the keepalive ping hold the connection open while we gather data — so a
    # slow cluster can never leave the client staring at a zero-byte response that
    # an intermediate proxy turns into a 504.
    if request.stream:
        async def _chat_events():
            try:
                display_question, llm_question, all_results, context, instant, preamble = await _search_and_compose()
            except Exception as e:  # noqa: BLE001
                logger.error(f"Chat search failed: {e}")
                yield {"event": "error", "data": f"Couldn't search the logs: {e}"}
                return
            if instant:
                async for ev in _instant_response(instant, display_question=display_question):
                    yield ev
                return
            # Health questions: the facts preamble is already authoritative, so the
            # model is asked for grounded analysis & actions — not to restate them.
            health_system = HEALTH_ANALYSIS_SYSTEM if preamble else None
            async for ev in _stream_response(
                llm_question, context, all_results, session,
                display_question=display_question, preamble=preamble, system=health_system,
            ):
                yield ev

        return EventSourceResponse(
            _chat_events(), media_type="text/event-stream", ping=settings.chat_sse_ping_seconds
        )

    # Non-streaming.
    try:
        display_question, llm_question, all_results, context, instant, preamble = await _search_and_compose()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Kibana query failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to query Kibana: {e}")

    if instant:
        return ChatResponse(answer=instant, sources=[])

    # Health questions: the deterministic facts are the answer; the LLM prose is a
    # best-effort, grounded analysis bonus, so a model failure never costs the
    # user the facts.
    health_system = HEALTH_ANALYSIS_SYSTEM if preamble else None
    try:
        answer = await generate_answer(llm_question, context, system=health_system, session=session)
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        if not preamble:
            raise HTTPException(status_code=502, detail=f"Failed to generate answer: {e}")
        answer = ""

    if not (answer or "").strip():
        answer = await _recover_answer(llm_question, context, session, system=health_system)
    if not (answer or "").strip() and not preamble:
        answer = _summarize_from_sources(all_results)

    if preamble:
        answer = preamble + (_AI_ANALYSIS_DIVIDER + answer if (answer or "").strip() else "")

    return ChatResponse(answer=answer, sources=all_results[:5])


async def _fetch_generic(sid: str, query: str, minutes: int, index: str) -> tuple[list[dict], list[dict]]:
    """Recent logs (a representative sample) + keyword matches + recent errors for
    a generic question, against one index (or a comma-joined set). Per-query
    failures are tolerated so one bad index never empties the whole context."""
    recent, matched, errors = await asyncio.gather(
        get_recent_logs(sid, size=12, time_range_minutes=minutes, index=index),
        search_logs(sid, query, size=8, time_range_minutes=minutes, index=index),
        get_recent_errors(sid, size=8, time_range_minutes=minutes, index=index),
        return_exceptions=True,
    )
    safe = lambda x: [] if isinstance(x, Exception) else x
    recent, matched, errors = safe(recent), safe(matched), safe(errors)
    seen: set = set()
    logs: list[dict] = []
    for entry in matched + recent:
        key = entry.get("timestamp", "") + entry.get("message", "")[:50]
        if key not in seen:
            seen.add(key)
            logs.append(entry)
    return logs, errors


async def _instant_response(message: str, display_question: str | None = None):
    """Stream a ready-made message immediately (no LLM call) as SSE."""
    if display_question:
        yield {"event": "question", "data": display_question}
    yield {"event": "chunk", "data": message}
    yield {"event": "sources", "data": json.dumps([])}
    yield {"event": "done", "data": ""}


async def _passthrough(value: str) -> str:
    """Return `value` unchanged — lets us gather it alongside the search when
    auto-correction is off, keeping one code path."""
    return value


async def _stream_response(
    question: str,
    context: str,
    sources: list[dict],
    session: dict,
    display_question: str | None = None,
    preamble: str | None = None,
    system: str | None = None,
):
    """Stream the answer as SSE events. If a `preamble` is given (deterministic
    health facts), it is emitted INSTANTLY first so the user has the answer before
    the model runs; the LLM prose then streams underneath as a bonus. The LLM is
    best-effort — once the facts are out, a model hiccup degrades to a short note
    instead of an error, so the facts are never lost. `system` overrides the model
    persona (the grounded analyst for health questions)."""
    if display_question:
        yield {"event": "question", "data": display_question}
    if preamble:
        yield {"event": "chunk", "data": preamble}
        yield {"event": "chunk", "data": _AI_ANALYSIS_DIVIDER}

    produced = False
    try:
        async for chunk in generate_answer_stream(question, context, session=session, system=system):
            if chunk:
                produced = True
                yield {"event": "chunk", "data": chunk}
    except Exception as e:  # noqa: BLE001
        logger.error(f"LLM stream failed: {e}")  # fall through to recovery below

    if not produced:
        # Never dead-end: retry once non-streaming / local model. If even that is
        # empty, synthesize from the gathered events — unless we already streamed
        # the facts preamble, in which case a brief note is enough.
        fallback = await _recover_answer(question, context, session, system=system)
        if fallback:
            yield {"event": "chunk", "data": fallback}
        elif preamble:
            yield {"event": "chunk",
                   "data": "_(AI analysis is unavailable right now — the facts above are from live monitoring data.)_"}
        else:
            yield {"event": "chunk", "data": _summarize_from_sources(sources)}

    yield {"event": "sources", "data": json.dumps(sources[:5])}
    yield {"event": "done", "data": ""}


async def _recover_answer(question: str, context: str, session: dict, system: str | None = None) -> str:
    """Recover from an empty streamed answer: retry once non-streaming with the
    same provider; if still empty and we were on Mistral, fall back to the local
    model (which is always available). Returns "" only if everything fails."""
    provider, _ = provider_model(session)
    try:
        answer = await generate_answer(question, context, system=system, session=session)
        if (answer or "").strip():
            return answer
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Non-streaming retry failed: {e}")
    if provider == "mistral":
        try:
            local = await generate_answer(question, context, system=system, session={"llm_provider": "ollama"})
            if (local or "").strip():
                return ("_(Mistral was unavailable — answered with the local model.)_\n\n" + local)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Local-model fallback failed: {e}")
    return ""


async def _collect_doc_events(sid: str, doc_id: str) -> list[dict]:
    """All log events mentioning a document id, searched across a WIDE window
    and EVERY allowed data view, de-duplicated and time-ordered (oldest first).
    Per-view failures are tolerated so one unavailable index never blocks the
    audit — the document is found wherever its logs actually live."""
    views = settings.data_view_list
    results = await asyncio.gather(
        *[
            search_by_document_id(
                sid, doc_id, index=v,
                size=settings.chat_doc_scan_size, days=settings.chat_doc_scan_days,
            )
            for v in views
        ],
        return_exceptions=True,
    )
    merged: list[dict] = []
    for res in results:
        if not isinstance(res, Exception):
            merged.extend(res)
    seen: set = set()
    unique: list[dict] = []
    for e in sorted(merged, key=lambda x: x.get("timestamp", "")):
        key = (e.get("timestamp", ""), (e.get("message", "") or "")[:80], e.get("index", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    return unique


def _build_doc_context(
    doc_ids: list[str],
    id_hits: list[list[dict]],
    metas: list,
    days: int,
) -> str:
    """Grounded context for a document-scoped question: the official metadata
    plus the full, time-ordered list of log events mentioning each id — so the
    LLM can audit timelines like a double publication."""
    parts: list[str] = []
    for did, events, meta in zip(doc_ids, id_hits, metas):
        parts.append(f"### Document {did}")
        if isinstance(meta, dict) and meta:
            if meta.get("title"):
                parts.append(f"- Official title: {meta['title']}")
            if meta.get("type"):
                parts.append(f"- Type: {meta['type']}")
            if meta.get("status"):
                parts.append(f"- Portal publication status: {meta['status']}")
            if meta.get("published"):
                parts.append(f"- Portal publication date: {meta['published']}")
            if meta.get("organization"):
                parts.append(f"- Organization: {meta['organization']}")
        parts.append(
            f"- Log events across all data views over the last {days} days: "
            f"{len(events)} (oldest first)"
        )
        for e in events[:80]:  # cap to keep the prompt focused
            ts = e.get("timestamp", "?")
            level = e.get("level", "")
            idx = e.get("index", "")
            msg = (e.get("message", "") or "")[:300]
            lvl = f"[{level}] " if level else ""
            src = f"({idx}) " if idx else ""
            parts.append(f"  - [{ts}] {lvl}{src}{msg}")
        parts.append("")
    return "\n".join(parts)


# Questions about the overall health of the cluster/pipeline — "which services
# are failing", "what's unhealthy", "any errors", "what's wrong right now". These
# are answered from the SAME ground-truth health data the dashboard uses, not a
# blind keyword log-search, so the chat agrees with the header's "N stuck" badge.
# A specific search / lookup intent (EN + NL) — "find the mailing-list error",
# "zoek de fout in X". These must NEVER be hijacked into the generic health digest;
# they answer from a real log search so the chat addresses the actual topic.
_SEARCH_INTENT_RE = re.compile(
    r"\b(find|search|look\s*(?:up|for)|show\s+me|locate|trace|lookup|list\s+the|"
    r"where(?:'s| is| are)?|"
    r"vind|zoek|toon|laat\s+zien|traceer|waar\s+(?:is|staat|zit))\b",
    re.I,
)

# Strong overall system/pipeline-health signals (EN + NL) — a health question on
# their own (kept bilingual so Dutch questions route consistently, not by accident).
_HEALTH_STRONG_RE = re.compile(
    r"\b("
    r"fail(?:ing|ed|ure|ures|s)?|unhealthy|healthy?|erroring|broken|kapot|"
    r"outage|storing|uitval|degraded|down|offline|onbereikbaar|"
    r"stuck|stalled|vastgelopen|worst|ergste|critical|kritiek(?:e)?|"
    r"which services?|welke services?|gezondheid|"
    r"what(?:'s| is)\s+(?:going\s+)?wrong|going\s+wrong|wat\s+(?:gaat|is)\s+er\s+mis"
    r")\b",
    re.I,
)

# Bare trouble words (EN + NL) — only a health question WITH a broad-scope cue,
# otherwise they belong to a specific search ("the mailing-list error").
_GENERIC_TROUBLE_RE = re.compile(
    r"\b(errors?|fout(?:en|melding|meldingen)?|issues?|problem(?:s|en|atisch)?)\b", re.I)
_BROAD_SCOPE_RE = re.compile(
    r"\b(right\s+now|currently|at\s+the\s+moment|overall|system|systeem|any|"
    r"op\s+dit\s+moment|momenteel|nu)\b", re.I)


def _is_health_question(text: str) -> bool:
    """True only for BROAD system/pipeline-health questions — NOT a specific search.

    Order matters: a STRONG health signal ("failing", "stuck", "what's going wrong")
    wins even when phrased as "show me…/list the…". Otherwise a specific search/lookup
    intent ("find the attendee mailing-list error") is routed to the real log search
    so the chat answers what was actually asked instead of returning the generic
    cluster-health digest. Bare "error/issue/problem" counts as health only alongside
    a broad-scope cue ("right now", "any", "system", …)."""
    t = text or ""
    if _HEALTH_STRONG_RE.search(t):
        return True
    if _SEARCH_INTENT_RE.search(t):
        return False
    return bool(_GENERIC_TROUBLE_RE.search(t) and _BROAD_SCOPE_RE.search(t))


def _redact_context(context: str) -> str:
    """Mask obvious PII (emails/IPs/tokens) from the assembled LLM context when
    the flag is on — the single shared choke point so BOTH Ollama and Mistral get
    the redacted string. Document ids, service names, HTTP codes, timestamps and
    *.overheid.nl hosts are preserved by redact.redact_pii. Never raises."""
    if settings.llm_redact_pii:
        return redact.redact_pii(context)
    return context


def _build_health_context(snap: dict | None, health: dict | None) -> str:
    """Ground-truth health context: the dashboard cluster snapshot (worst-affected
    services, error signatures, status codes) plus the document-pipeline health
    (stuck documents, per-stage errors). Directly answers 'which services are
    failing, worst first, with what's going wrong'."""
    parts: list[str] = []

    if snap:
        parts.append(
            f"## Cluster health for '{snap.get('data_view')}' "
            f"over the last {snap.get('period_minutes')} min"
        )
        parts.append(
            f"- Overall status: {str(snap.get('status_level', 'ok')).upper()} "
            f"({snap.get('total', 0)} error/critical events in the window)."
        )
        delta = snap.get("delta") or {}
        if delta.get("pct_vs_previous") is not None:
            parts.append(
                f"- Trend vs previous period: {delta['pct_vs_previous']:+.0f}% "
                f"(was {delta.get('previous', 0)})."
            )
        systems = snap.get("systems") or []
        if systems:
            parts.append("- Per-system error counts (this window):")
            for s in systems:
                avail = "" if s.get("available", True) else " (unavailable)"
                parts.append(f"  - {s.get('label') or s.get('data_view')}: {s.get('count', 0)}{avail}")
        services = snap.get("affected_services") or []
        if services:
            parts.append("- Worst-affected services (most errors first):")
            for s in services[:10]:
                parts.append(f"  - {s.get('name', '?')}: {s.get('count', 0)} error events")
        signatures = snap.get("top_signatures") or []
        if signatures:
            parts.append("- Top error signatures (what is going wrong):")
            for s in signatures[:8]:
                parts.append(f"  - {s.get('count', 0)}× {(s.get('signature') or '')[:200]}")
        codes = snap.get("status_codes") or []
        if codes:
            parts.append(
                "- HTTP status codes: "
                + ", ".join(f"{c.get('code')}×{c.get('count')}" for c in codes[:8])
            )
        urls = snap.get("failing_urls") or []
        if urls:
            parts.append("- Failing URLs:")
            for u in urls[:5]:
                parts.append(f"  - {u.get('count', 0)}× {(u.get('url') or '')[:160]}")

    if health:
        parts.append("")
        parts.append(f"## Document pipeline health (last {health.get('lookback_minutes', 0) // 60} h)")
        parts.append(
            f"- Stuck / at-risk documents: {health.get('stuck_count', 0)} "
            f"(of {health.get('documents_scanned', 0)} scanned)."
        )
        parts.append(
            f"- Total pipeline errors: {health.get('total_errors', 0)}, "
            f"warnings: {health.get('total_warnings', 0)}."
        )
        bad_stages = [s for s in (health.get("stage_health") or []) if s.get("errors") or s.get("warnings")]
        if bad_stages:
            parts.append("- Stages with trouble:")
            for s in bad_stages:
                parts.append(
                    f"  - {s.get('name')}: {s.get('errors', 0)} errors, "
                    f"{s.get('warnings', 0)} warnings ({s.get('events', 0)} events)"
                )
        stuck = health.get("stuck") or []
        if stuck:
            parts.append("- Most urgent stuck documents:")
            for d in stuck[:8]:
                title = d.get("title") or d.get("id")
                parts.append(
                    f"  - [{d.get('verdict')}] {title} — stuck at "
                    f"{d.get('stuck_stage')}: {d.get('headline', '')}"
                )

    if not parts:
        return ""
    parts.append("")
    parts.append(
        "Answer the user's question using ONLY the health data above. List the "
        "worst-affected services or pipeline stages first and say briefly what is "
        "going wrong for each. If everything is at zero, say the system looks healthy."
    )
    return _redact_context("\n".join(parts))


# Shown between the instant facts and the streamed AI prose.
_AI_ANALYSIS_DIVIDER = "\n\n---\n_AI analysis:_\n\n"

_STATUS_ICON = {"CRITICAL": "🔴", "DEGRADED": "🟠", "OK": "🟢"}


def _render_health_facts(snap: dict | None, health: dict | None) -> str:
    """A deterministic, human-readable summary built straight from the cached
    health data. Shown INSTANTLY for a health question so the user never waits on
    the LLM for the facts — the AI prose is then streamed underneath as a bonus."""
    lines: list[str] = []

    if snap:
        status = str(snap.get("status_level", "ok")).upper()
        icon = _STATUS_ICON.get(status, "•")
        lines.append(
            f"**{icon} {status}** — {snap.get('total', 0)} error/critical events in the "
            f"last {snap.get('period_minutes')} min on `{snap.get('data_view')}`."
        )
        delta = snap.get("delta") or {}
        if delta.get("pct_vs_previous") is not None:
            pct = delta["pct_vs_previous"]
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "▶")
            lines.append(f"- Trend: {arrow} {abs(pct):.0f}% vs the previous period.")

        services = snap.get("affected_services") or []
        if services:
            lines.append("\n**Worst-affected services**")
            for s in services[:6]:
                lines.append(f"- `{s.get('name', '?')}` — {s.get('count', 0)} errors")

        codes = [c for c in (snap.get("status_codes") or []) if str(c.get("code", "")).startswith("5")]
        if codes:
            lines.append("\n**Server errors (5xx):** "
                         + ", ".join(f"{c.get('code')}×{c.get('count')}" for c in codes))

        signatures = snap.get("top_signatures") or []
        if signatures:
            lines.append("\n**What's going wrong**")
            for s in signatures[:6]:
                lines.append(f"- {s.get('count', 0)}× {(s.get('signature') or '')[:160]}")

    if health:
        stuck = health.get("stuck_count", 0)
        errs, warns = health.get("total_errors", 0), health.get("total_warnings", 0)
        lines.append("")
        if stuck:
            lines.append(f"**Pipeline:** {stuck} document(s) not live & unresolved "
                         f"({errs} errors, {warns} warnings).")
        else:
            lines.append(f"**Pipeline:** no stuck documents ({errs} errors, {warns} warnings).")
        bad = [s for s in (health.get("stage_health") or []) if s.get("errors")]
        for s in bad[:4]:
            lines.append(f"- {s.get('name')}: {s.get('errors', 0)} errors")

    return "\n".join(lines).strip()


def _summarize_from_sources(sources: list[dict]) -> str:
    """A deterministic, non-LLM answer built straight from the gathered log events.
    Used as the final safety net so the chat ALWAYS returns something useful even
    if the AI model is completely unavailable or returns nothing."""
    if not sources:
        return (
            "I couldn't get a written answer from the AI model just now, and there "
            "were no log events to summarize. Please try again in a moment, or "
            "switch the AI model in the header."
        )
    errors = [s for s in sources if (s.get("level") or "").lower() in ("error", "fatal", "critical")]
    lines = [
        "The AI model didn't return a written answer, so here is a direct summary "
        "of what I found in the logs:",
        "",
        f"- **{len(sources)}** matching log event(s)"
        + (f", including **{len(errors)}** at error level." if errors else "."),
    ]
    for s in (errors or sources)[:5]:
        ts = s.get("timestamp", "?")
        level = (s.get("level") or "").upper()
        host = s.get("host", "")
        msg = (s.get("message", "") or "")[:200]
        lines.append(
            f"  - [{ts}] "
            + (f"[{level}] " if level else "")
            + (f"({host}) " if host else "")
            + msg
        )
    lines.append("")
    lines.append("_Tip: switch the AI model in the header for a fuller analysis._")
    return "\n".join(lines)


def _build_context(
    logs: list[dict], metrics: list[dict], errors: list[dict]
) -> str:
    """Format ES results into a context string for the LLM."""
    parts = []

    if errors:
        parts.append("### Recent Errors")
        for entry in errors[:8]:
            ts = entry.get("timestamp", "?")
            msg = entry.get("message", "")[:300]
            host = entry.get("host", "?")
            parts.append(f"- [{ts}] ({host}) {msg}")

    if logs:
        parts.append("\n### Recent / Matching Log Entries")
        for entry in logs[:18]:
            ts = entry.get("timestamp", "?")
            msg = entry.get("message", "")[:300]
            level = entry.get("level", "")
            host = entry.get("host", "?")
            parts.append(f"- [{ts}] [{level}] ({host}) {msg}")

    if metrics:
        parts.append("\n### Matching Metrics")
        for entry in metrics[:5]:
            ts = entry.get("timestamp", "?")
            msg = entry.get("message", "")[:300]
            parts.append(f"- [{ts}] {msg}")

    return _redact_context("\n".join(parts))
