"""Permanent guards against the 'AI model returned an empty response' failure.

Root cause: Ollama's default context window is 2048 tokens; a larger prompt is
silently truncated and the model then often returns an empty answer. These tests
assert that (a) we always send an explicit num_ctx, (b) the context is trimmed to
a safe budget before it reaches the model, and (c) a missing/empty message body
never raises — it degrades to an empty string the caller can recover from."""
import llm


def test_trim_context_under_budget_is_unchanged():
    assert llm.trim_context("short context", budget=100) == "short context"


def test_trim_context_caps_oversized_context_at_a_line_boundary():
    ctx = "\n".join(f"line {i} " + "x" * 50 for i in range(1000))
    out = llm.trim_context(ctx, budget=500)
    # Bounded to the budget plus the short truncation marker, and never mid-line.
    assert len(out) <= 500 + 120
    assert "truncated to fit" in out
    assert "\nx" not in out  # we trimmed back to a newline, not through a line


def test_trim_context_zero_or_negative_budget_disables_trimming():
    assert llm.trim_context("anything", budget=0) == "anything"


def test_build_prompt_always_trims_the_context(monkeypatch):
    monkeypatch.setattr(llm.settings, "chat_context_char_budget", 200)
    messages = llm._build_prompt("Which services are failing?", "y" * 5000)
    user = messages[1]["content"]
    assert "truncated to fit" in user
    assert len(user) < 5000


def test_ollama_options_come_from_settings(monkeypatch):
    monkeypatch.setattr(llm.settings, "ollama_num_ctx", 4096)
    monkeypatch.setattr(llm.settings, "ollama_num_predict", 256)
    assert llm._ollama_options() == {"num_ctx": 4096, "num_predict": 256}


async def test_ollama_call_sends_num_ctx_and_tolerates_missing_content(monkeypatch):
    """The exact failure: Ollama returns a body with no usable 'message.content'.
    Must NOT raise KeyError — it returns '' so the caller's recovery path runs.
    And every request MUST carry an explicit num_ctx."""
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {}  # no "message" key at all

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(llm.httpx, "AsyncClient", _Client)
    out = await llm._generate_ollama_answer([{"role": "user", "content": "hi"}])
    assert out == ""  # graceful, not a crash
    assert captured["json"]["options"]["num_ctx"] == llm.settings.ollama_num_ctx
    assert captured["json"]["options"]["num_predict"] == llm.settings.ollama_num_predict
