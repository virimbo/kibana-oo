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


def trim_context(context: str, budget: int | None = None) -> str:
    """Bound the context to a character budget so the prompt can never overflow
    the model's context window. (When it does, Ollama silently drops the front of
    the prompt and frequently returns an empty answer.) Keeps the most relevant
    head, trims back to a line boundary, and appends a clear truncation marker."""
    budget = settings.chat_context_char_budget if budget is None else budget
    if budget <= 0 or len(context) <= budget:
        return context
    kept = context[:budget]
    newline = kept.rfind("\n")
    if newline > budget // 2:  # avoid slicing a line in half
        kept = kept[:newline]
    return kept + "\n\n…(context truncated to fit the model — showing the most relevant entries)."


def _ollama_options() -> dict:
    """Generation options sent on every Ollama request. Setting num_ctx
    explicitly is what prevents the silent-truncation → empty-answer failure."""
    return {
        "num_ctx": settings.ollama_num_ctx,
        "num_predict": settings.ollama_num_predict,
    }


HEALTH_ANALYSIS_SYSTEM = """\
You are KIBANA-OO's incident analyst for the koop-plooi-prod cluster.

The user has ALREADY been shown a factual summary (overall status, worst-affected
services, error signatures, HTTP status codes, and pipeline state). Do NOT repeat
those numbers back — add analysis they can act on.

Answer in three short, clearly-labelled parts:
1. **Likely cause** — the most probable root cause(s), reasoned only from the data.
2. **Check first** — the single most useful thing to look at next.
3. **Recommended actions** — concrete, prioritized steps.

Trust rules (these matter most):
- Use ONLY the services, numbers, error types and document ids that appear in the
  provided context. NEVER invent service names, counts, hostnames, URLs or causes.
- If the data is insufficient to determine a cause, say so plainly — do not guess.
- Separate what the data SHOWS from what you INFER (say "this suggests…",
  "likely…"). Do not present an inference as an established fact.
- Be concise. No preamble, no restating the question.
"""


def _build_prompt(question: str, context: str, system: str | None = None) -> list[dict]:
    """Build the message list for the LLM. `system` overrides the default
    chat persona — used by the dashboard briefing to supply a grounded analyst
    system prompt instead of the generic assistant one. The context is always
    trimmed to a safe budget so the prompt cannot overflow the context window."""
    return [
        {"role": "system", "content": system or SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"## Context from Elasticsearch\n\n{trim_context(context)}\n\n"
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


# Sentinel provider meaning "AI is switched off" — every generation call
# short-circuits to an empty result so the deterministic fallbacks take over and
# no request is ever sent to Ollama/Mistral.
DISABLED_PROVIDER = "none"


def ai_enabled(session: dict | None = None) -> bool:
    """True when an AI model is selected for this session (not switched off)."""
    return _get_provider(session) != DISABLED_PROVIDER


def provider_model(session: dict | None = None) -> tuple[str, str]:
    """The (provider, model) pair that will actually answer for this session —
    used by the UI to show which AI produced a result."""
    provider = _get_provider(session)
    if provider == DISABLED_PROVIDER:
        return DISABLED_PROVIDER, "disabled"
    model = settings.mistral_model if provider == "mistral" else settings.ollama_model
    return provider, model


_POLISH_SYSTEM = (
    "You are a text corrector. Fix spelling, grammar and punctuation in the "
    "user's message so it reads as clear, professional English. PRESERVE exactly: "
    "all IDs, UUIDs, codes, numbers, dates, URLs, field names and technical terms. "
    "Do NOT answer the message, do NOT add commentary or quotes. Return ONLY the "
    "corrected message text."
)


async def polish_text(text: str, session: dict | None = None) -> str:
    """Return a spelling/grammar-corrected version of `text`. Best-effort: on any
    error (or an over-long/empty input) the original text is returned unchanged so
    a correction failure never blocks the question."""
    cleaned = (text or "").strip()
    if len(cleaned) < 3 or len(cleaned) > 2000:
        return cleaned
    messages = [
        {"role": "system", "content": _POLISH_SYSTEM},
        {"role": "user", "content": cleaned},
    ]
    provider = _get_provider(session)
    if provider == DISABLED_PROVIDER:
        return cleaned  # AI off — never touch the original text.
    try:
        if provider == "mistral":
            result = await _generate_mistral_answer(messages)
        else:
            result = await _generate_ollama_answer(messages, stream=False)
    except (httpx.HTTPStatusError, httpx.RequestError, KeyError):
        return cleaned
    result = (result or "").strip().strip('"').strip()
    # Guard against a model that "helpfully" answered instead of correcting.
    return result if result and len(result) <= len(cleaned) * 3 else cleaned


async def generate_answer(question: str, context: str, system: str | None = None, session: dict | None = None) -> str:
    """Generate a complete answer (non-streaming)."""
    provider = _get_provider(session)
    if provider == DISABLED_PROVIDER:
        return ""  # AI off — caller falls back to the deterministic summary.
    messages = _build_prompt(question, context, system=system)
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
                "options": _ollama_options(),
            },
        )
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "") or ""


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
    question: str, context: str, session: dict | None = None, system: str | None = None
) -> AsyncIterator[str]:
    """Generate a streaming answer, yielding chunks as they arrive. `system`
    overrides the default chat persona (e.g. the grounded health-incident analyst)."""
    provider = _get_provider(session)
    if provider == DISABLED_PROVIDER:
        return  # AI off — yield nothing; caller emits the deterministic summary.
    messages = _build_prompt(question, context, system=system)
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
                "options": _ollama_options(),
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
