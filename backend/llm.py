"""Ollama/LLAMA client for generating answers from context."""

from collections.abc import AsyncIterator

import httpx

from config import settings

SYSTEM_PROMPT = """\
You are KIBANA-OO, an AI assistant that answers questions about infrastructure \
logs and metrics from an Elasticsearch/Kibana cluster (koop-plooi-prod).

Rules:
- Answer based ONLY on the provided context data. Do not make up information.
- If the context doesn't contain enough information, say so clearly.
- When referencing log entries, include timestamps and relevant details.
- Format your answers clearly with bullet points or tables when appropriate.
- If you see error patterns, highlight them and suggest possible causes.
- Be concise but thorough.
"""


def _build_prompt(question: str, context: str, system: str | None = None) -> list[dict]:
    """Build the message list for the LLM. `system` overrides the default
    chat persona — used by the dashboard briefing to supply a grounded analyst
    system prompt instead of the generic assistant one."""
    return [
        {"role": "system", "content": system or SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"## Context from Elasticsearch\n\n{context}\n\n"
                f"## Question\n\n{question}"
            ),
        },
    ]


async def generate_answer(question: str, context: str, system: str | None = None) -> str:
    """Generate a complete answer (non-streaming)."""
    messages = _build_prompt(question, context, system=system)

    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


async def generate_answer_stream(
    question: str, context: str
) -> AsyncIterator[str]:
    """Generate a streaming answer, yielding chunks as they arrive."""
    messages = _build_prompt(question, context)

    async with httpx.AsyncClient(timeout=600.0) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            import json

            async for line in response.aiter_lines():
                if line.strip():
                    chunk = json.loads(line)
                    if "message" in chunk and "content" in chunk["message"]:
                        yield chunk["message"]["content"]
