"""KIBANA-OO Backend — FastAPI app connecting LLAMA to Elasticsearch."""

import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from config import settings
from elastic import get_cluster_health, get_recent_errors, search_logs, search_metrics
from llm import generate_answer, generate_answer_stream

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="KIBANA-OO",
    description="AI-powered chat interface for Elasticsearch logs and metrics",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    question: str
    time_range_minutes: int = 60
    stream: bool = True


class ChatResponse(BaseModel):
    answer: str
    sources: list[dict]


@app.get("/health")
async def health():
    """Health check endpoint."""
    try:
        es_health = get_cluster_health()
        return {
            "status": "ok",
            "elasticsearch": es_health.get("status", "unknown"),
            "model": settings.ollama_model,
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "degraded", "error": str(e)}


@app.post("/chat")
async def chat(request: ChatRequest):
    """Process a chat question: search ES, generate answer with LLAMA."""
    question = request.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    logger.info(f"Processing question: {question[:100]}")

    # Step 1: Search Elasticsearch for relevant context
    try:
        log_results = search_logs(question, time_range_minutes=request.time_range_minutes)
        metric_results = search_metrics(question, size=10, time_range_minutes=request.time_range_minutes)
        error_results = get_recent_errors(time_range_minutes=request.time_range_minutes)
    except Exception as e:
        logger.error(f"Elasticsearch query failed: {e}")
        raise HTTPException(status_code=502, detail=f"Failed to query Elasticsearch: {e}")

    # Step 2: Build context string for the LLM
    all_results = log_results + metric_results + error_results
    context = _build_context(log_results, metric_results, error_results)

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
        # Send sources at the end
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
