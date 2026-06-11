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
)
from llm import generate_answer, generate_answer_stream, polish_text
from ocr import image_to_text
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

    async def _do_search() -> tuple[list[dict], str, str | None]:
        """Returns (sources, llm_context, instant_message). When instant_message
        is set, the data is genuinely empty and we answer immediately without
        calling the (slow) LLM."""
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
            return results, ctx, None

        # Generic path: search the SELECTED view + window first. If that is empty,
        # automatically broaden BOTH the index (all data views) AND the time window
        # (recent activity may simply be older than the narrow selected range) so
        # the chat finds data wherever — and whenever — it lives.
        minutes = request.time_range_minutes
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
            return [], "", instant

        ctx = _build_context(logs, [], errors)
        if broadened:
            ctx += (
                f"\n\n(Note: no events matched in '{data_view}' for the selected range; "
                f"these results are from all data views over {window}. Mention this to the user.)"
            )
        return results, ctx, None

    # Step 1+2+polish: search Kibana AND spell/grammar-correct the typed question
    # CONCURRENTLY, so the correction adds (almost) no wall-clock time.
    try:
        polish_coro = (
            polish_text(question, session) if (request.autocorrect and question) else _passthrough(question)
        )
        polished, (all_results, context, instant) = await asyncio.gather(polish_coro, _do_search())
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Kibana query failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to query Kibana: {e}")

    # What the user sees in their bubble, and what the model is asked.
    display_question = polished or "(screenshot)"
    llm_question = polished or "Analyze the attached screenshot and answer any question it contains."
    if image_text:
        llm_question = f"{llm_question}\n\n[Text extracted from the attached image]:\n{image_text}"

    # Fast path: genuinely no data → answer instantly, skip the slow LLM call.
    if instant:
        if request.stream:
            return EventSourceResponse(
                _instant_response(instant, display_question=display_question),
                media_type="text/event-stream",
            )
        return ChatResponse(answer=instant, sources=[])

    # Step 3: Generate answer with selected LLM
    if request.stream:
        return EventSourceResponse(
            _stream_response(llm_question, context, all_results, session, display_question=display_question),
            media_type="text/event-stream",
        )

    try:
        answer = await generate_answer(llm_question, context, session=session)
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to generate answer: {e}")

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
):
    """Stream the LLM response as SSE events. If the question was corrected (or
    derived from an image), the cleaned text is sent first so the UI can update
    the user's bubble to what was actually asked."""
    try:
        if display_question:
            yield {"event": "question", "data": display_question}
        produced = False
        async for chunk in generate_answer_stream(question, context, session=session):
            if chunk:
                produced = True
                yield {"event": "chunk", "data": chunk}
        if not produced:
            # The model returned nothing (transient provider issue / over-strict
            # refusal). Never leave the user with a blank bubble — say so and
            # offer a concrete next step.
            yield {
                "event": "chunk",
                "data": (
                    "The AI model returned an empty response. This is usually a "
                    "transient issue with the selected provider.\n\n"
                    "- Try sending the question again\n"
                    "- Or switch the **AI model** (top of the page) and retry"
                ),
            }
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

    return "\n".join(parts)
