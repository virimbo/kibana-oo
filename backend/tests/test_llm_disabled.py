"""AI off-switch: when a session's provider is "none", every generation call
short-circuits to an empty result WITHOUT contacting Ollama/Mistral, so the
deterministic fallbacks take over and no network request is ever made."""
import llm
import session as session_mod


OFF = {"llm_provider": "none"}


def test_session_accepts_none_provider():
    assert "none" in session_mod.VALID_PROVIDERS


def test_ai_enabled_reflects_provider():
    assert llm.ai_enabled(OFF) is False
    assert llm.ai_enabled({"llm_provider": "ollama"}) is True
    assert llm.ai_enabled({"llm_provider": "mistral"}) is True


def test_provider_model_reports_disabled():
    assert llm.provider_model(OFF) == ("none", "disabled")


async def test_generate_answer_returns_empty_when_off():
    # No httpx mock needed: a network call would raise, so an empty string proves
    # the short-circuit fired before any request was attempted.
    assert await llm.generate_answer("any question", "some context", session=OFF) == ""


async def test_generate_answer_stream_yields_nothing_when_off():
    chunks = [c async for c in llm.generate_answer_stream("q", "ctx", session=OFF)]
    assert chunks == []


async def test_polish_text_returns_original_when_off():
    text = "fix   this    sentence please"
    assert await llm.polish_text(text, session=OFF) == text.strip()
