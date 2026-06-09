"""LLM client for generating answers from context. Supports Ollama and Mistral."""

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


def _llm_error_message(exc: Exception, provider: str) -> str:
    """Translate a provider error into a clear, user-facing message."""
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code in (401, 403):
            return f"The {provider} AI provider rejected the API key ({code}). Check the API key (and that billing is enabled)."
        if code == 429:
            return f"The {provider} AI provider rate-limited the request (429). Try again shortly."
        return f"The {provider} AI provider returned an error ({code})."
    if isinstance(exc, httpx.RequestError):
        return f"Cannot reach the {provider} AI provider. Check the connection / base URL."
    return f"AI generation failed: {exc}"


def _get_provider(session: dict | None = None) -> str:
    """Get the LLM provider to use. Session preference takes precedence over global config."""
    if session and session.get("llm_provider"):
        return session["llm_provider"]
    return settings.llm_provider


def provider_model(session: dict | None = None) -> tuple[str, str]:
    """The (provider, model) pair that will actually answer for this session —
    used by the UI to show which AI produced a result."""
    provider = _get_provider(session)
    model = settings.mistral_model if provider == "mistral" else settings.ollama_model
    return provider, model


async def generate_answer(question: str, context: str, system: str | None = None, session: dict | None = None) -> str:
    """Generate a complete answer (non-streaming)."""
    messages = _build_prompt(question, context, system=system)
    provider = _get_provider(session)
    try:
        if provider == "mistral":
            return await _generate_mistral_answer(messages)
        return await _generate_ollama_answer(messages, stream=False)
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        raise RuntimeError(_llm_error_message(e, provider)) from e


async def _generate_ollama_answer(messages: list[dict], stream: bool = False) -> str:
    """Generate answer using Ollama API."""
    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": stream,
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"]


async def _generate_mistral_answer(messages: list[dict]) -> str:
    """Generate answer using Mistral OpenAI-compatible API."""
    async with httpx.AsyncClient(timeout=600.0) as client:
        response = await client.post(
            f"{settings.mistral_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
            json={
                "model": settings.mistral_model,
                "messages": messages,
                "temperature": 0.7,
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


async def generate_answer_stream(
    question: str, context: str, session: dict | None = None
) -> AsyncIterator[str]:
    """Generate a streaming answer, yielding chunks as they arrive."""
    messages = _build_prompt(question, context)
    provider = _get_provider(session)
    try:
        if provider == "mistral":
            async for chunk in _generate_mistral_answer_stream(messages):
                yield chunk
        else:
            async for chunk in _generate_ollama_answer_stream(messages):
                yield chunk
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        raise RuntimeError(_llm_error_message(e, provider)) from e


async def _generate_ollama_answer_stream(messages: list[dict]) -> AsyncIterator[str]:
    """Generate streaming answer using Ollama API."""
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


async def _generate_mistral_answer_stream(messages: list[dict]) -> AsyncIterator[str]:
    """Generate streaming answer using Mistral OpenAI-compatible API."""
    async with httpx.AsyncClient(timeout=600.0) as client:
        async with client.stream(
            "POST",
            f"{settings.mistral_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.mistral_api_key}"},
            json={
                "model": settings.mistral_model,
                "messages": messages,
                "stream": True,
                "temperature": 0.7,
            },
        ) as response:
            response.raise_for_status()
            import json

            async for line in response.aiter_lines():
                if line.strip() and line.startswith("data:"):
                    data = line[5:].strip()
                    if data != "[DONE]":
                        chunk = json.loads(data)
                        if "choices" in chunk and len(chunk["choices"]) > 0:
                            content = chunk["choices"][0].get("delta", {}).get("content", "")
                            if content:
                                yield content
