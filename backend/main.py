"""KIBANA-OO Backend — FastAPI app connecting LLAMA to Elasticsearch via Kibana."""

import asyncio
import json
import logging

import httpx
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config import settings
from elastic import (
    extract_doc_ids,
    get_recent_errors,
    get_recent_logs,
    keycloak_login,
    search_by_document_id,
    search_logs,
    search_metrics,
)
from llm import generate_answer, generate_answer_stream
from portal import fetch_document_meta
from session import create_session, drop_session, require_session, set_llm_provider, VALID_PROVIDERS
from dashboard import router as dashboard_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="KIBANA-OO",
    description="AI-powered chat interface for Elasticsearch logs and metrics",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard_router)

class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    question: str
    time_range_minutes: int = 60
    data_view: str | None = None
    stream: bool = True


# Friendly labels for the known data views (falls back to the raw id).
DATA_VIEW_LABELS = {
    "logs-*": "All logs",
    "ds-prod5-koop-plooi*": "KOOP Plooi (prod5)",
    "ds-prod5-koop-sp": "KOOP SP (prod5)",
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


@app.post("/login")
async def login(request: LoginRequest):
    """Log in via Keycloak and create a session."""
    username = request.username.strip()
    password = request.password

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
        logger.warning(f"Login failed for {username}: {e}")
        raise HTTPException(status_code=401, detail=msg)

    # Create session token
    token = create_session(username, sid)

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
    sid = session["sid"]
    username = session["username"]

    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    data_view = _resolve_data_view(request.data_view)
    doc_ids = extract_doc_ids(question)
    logger.info(f"[{username}] [{data_view}] Question: {question[:100]}"
                + (f" · doc_ids={doc_ids}" if doc_ids else ""))

    # Step 1+2: Search Elasticsearch via Kibana and build the LLM context.
    try:
        if doc_ids:
            # Intelligent path: the question names specific document id(s). Trace
            # each across a WIDE window AND across EVERY data view (not just the
            # selected one — a document's pipeline logs may live in a different
            # index than the user has selected), and enrich with the official
            # title from the public portal.
            id_hits, metas = await asyncio.gather(
                asyncio.gather(*[_collect_doc_events(sid, did) for did in doc_ids]),
                asyncio.gather(*[fetch_document_meta(did) for did in doc_ids], return_exceptions=True),
            )
            all_results = [hit for hits in id_hits for hit in hits]
            context = _build_doc_context(doc_ids, id_hits, metas, settings.chat_doc_scan_days)
        else:
            # Generic path: run the three context queries CONCURRENTLY (was
            # sequential — three back-to-back round-trips through Kibana).
            recent_logs, log_results, error_results = await asyncio.gather(
                get_recent_logs(sid, size=5, time_range_minutes=request.time_range_minutes, index=data_view),
                search_logs(sid, question, size=5, time_range_minutes=request.time_range_minutes, index=data_view),
                get_recent_errors(sid, size=5, time_range_minutes=request.time_range_minutes, index=data_view),
            )
            seen = set()
            merged_logs = []
            for entry in log_results + recent_logs:
                key = entry.get("timestamp", "") + entry.get("message", "")[:50]
                if key not in seen:
                    seen.add(key)
                    merged_logs.append(entry)
            log_results = merged_logs
            all_results = log_results + error_results
            context = _build_context(log_results, [], error_results)
    except Exception as e:
        logger.error(f"Kibana query failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to query Kibana: {e}")

    if not context.strip():
        if doc_ids:
            views = ", ".join(settings.data_view_list)
            context = (
                f"No log events were found for {', '.join(doc_ids)} in any data view "
                f"({views}) over the last {settings.chat_doc_scan_days} days. State "
                "this plainly: the id may be wrong, outside the retention window, or "
                "the events are not yet indexed."
            )
        else:
            context = "No matching data found in Elasticsearch for the given time range."

    # Step 3: Generate answer with selected LLM
    if request.stream:
        return EventSourceResponse(
            _stream_response(question, context, all_results, session),
            media_type="text/event-stream",
        )

    try:
        answer = await generate_answer(question, context, session=session)
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to generate answer: {e}")

    return ChatResponse(answer=answer, sources=all_results[:5])


async def _stream_response(question: str, context: str, sources: list[dict], session: dict):
    """Stream the LLM response as SSE events."""
    try:
        async for chunk in generate_answer_stream(question, context, session=session):
            yield {"event": "chunk", "data": chunk}
        yield {"event": "sources", "data": json.dumps(sources[:5])}
        yield {"event": "done", "data": ""}
    except Exception as e:
        logger.error(f"Streaming failed: {e}")
        yield {"event": "error", "data": str(e)}


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


def _build_context(
    logs: list[dict], metrics: list[dict], errors: list[dict]
) -> str:
    """Format ES results into a context string for the LLM."""
    parts = []

    if errors:
        parts.append("### Recent Errors")
        for entry in errors[:5]:
            ts = entry.get("timestamp", "?")
            msg = entry.get("message", "")[:300]
            host = entry.get("host", "?")
            parts.append(f"- [{ts}] ({host}) {msg}")

    if logs:
        parts.append("\n### Matching Log Entries")
        for entry in logs[:10]:
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

    return "\n".join(parts)
