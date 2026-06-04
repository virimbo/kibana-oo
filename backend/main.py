"""KIBANA-OO Backend — FastAPI app connecting LLAMA to Elasticsearch via Kibana."""

import json
import logging
import secrets

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config import settings
from elastic import get_recent_errors, get_recent_logs, keycloak_login, search_logs, search_metrics
from llm import generate_answer, generate_answer_stream

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

# In-memory session store: token -> {username, sid}
_sessions: dict[str, dict] = {}


class LoginRequest(BaseModel):
    username: str
    password: str


class ChatRequest(BaseModel):
    question: str
    time_range_minutes: int = 60
    stream: bool = True


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]


def _get_session(authorization: str | None) -> dict:
    """Validate session token and return session data."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not logged in")
    token = authorization[7:]
    session = _sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return session


@app.get("/health")
async def health():
    """Health check endpoint (no auth required)."""
    return {"status": "ok", "model": settings.ollama_model}


@app.post("/login")
async def login(request: LoginRequest):
    """Log in via Keycloak and create a session."""
    username = request.username.strip()
    password = request.password

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    try:
        sid = await keycloak_login(username, password)
    except Exception as e:
        logger.warning(f"Login failed for {username}: {e}")
        raise HTTPException(status_code=401, detail=str(e))

    # Create session token
    token = secrets.token_urlsafe(32)
    _sessions[token] = {"username": username, "sid": sid}

    logger.info(f"User {username} logged in successfully")
    return {
        "token": token,
        "username": username,
    }


@app.post("/logout")
async def logout(authorization: str | None = Header(default=None)):
    """Clear the session."""
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        _sessions.pop(token, None)
    return {"status": "ok"}


@app.post("/chat")
async def chat(
    request: ChatRequest,
    authorization: str | None = Header(default=None),
):
    """Process a chat question: search ES via Kibana, generate answer with LLAMA."""
    session = _get_session(authorization)
    sid = session["sid"]
    username = session["username"]

    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    logger.info(f"[{username}] Question: {question[:100]}")

    # Step 1: Search Elasticsearch via Kibana
    try:
        # Always get recent logs for context
        recent_logs = await get_recent_logs(sid, size=5, time_range_minutes=request.time_range_minutes)
        # Also search for specific terms from the question
        log_results = await search_logs(sid, question, size=5, time_range_minutes=request.time_range_minutes)
        error_results = await get_recent_errors(sid, size=5, time_range_minutes=request.time_range_minutes)
        # Merge, deduplicate by timestamp
        seen = set()
        merged_logs = []
        for entry in log_results + recent_logs:
            key = entry.get("timestamp", "") + entry.get("message", "")[:50]
            if key not in seen:
                seen.add(key)
                merged_logs.append(entry)
        log_results = merged_logs
    except Exception as e:
        logger.error(f"Kibana query failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to query Kibana: {e}")

    # Step 2: Build context string for the LLM
    all_results = log_results + error_results
    context = _build_context(log_results, [], error_results)

    if not context.strip():
        context = "No matching data found in Elasticsearch for the given time range."

    # Step 3: Generate answer with LLAMA
    if request.stream:
        return EventSourceResponse(
            _stream_response(question, context, all_results),
            media_type="text/event-stream",
        )

    try:
        answer = await generate_answer(question, context)
    except Exception as e:
        logger.error(f"LLM generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to generate answer: {e}")

    return ChatResponse(answer=answer, sources=all_results[:5])


async def _stream_response(question: str, context: str, sources: list[dict]):
    """Stream the LLM response as SSE events."""
    try:
        async for chunk in generate_answer_stream(question, context):
            yield {"event": "chunk", "data": chunk}
        yield {"event": "sources", "data": json.dumps(sources[:5])}
        yield {"event": "done", "data": ""}
    except Exception as e:
        logger.error(f"Streaming failed: {e}")
        yield {"event": "error", "data": str(e)}


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
