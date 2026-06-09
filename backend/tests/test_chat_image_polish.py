import base64

import httpx

import llm
import ocr


# ── OCR robustness (never raises; bad input → "") ───────────

def test_ocr_empty_returns_empty():
    assert ocr.image_to_text("") == ""
    assert ocr.image_to_text(None) == ""


def test_ocr_bad_base64_returns_empty():
    assert ocr.image_to_text("!!!definitely not base64!!!") == ""


def test_ocr_non_image_bytes_returns_empty():
    b64 = base64.b64encode(b"this is plain text, not an image").decode()
    assert ocr.image_to_text(b64) == ""  # PIL can't open it → "", no tesseract call


def test_ocr_decode_strips_data_url_prefix():
    raw = b"\x89PNG\r\n fake bytes"
    b64 = base64.b64encode(raw).decode()
    assert ocr._decode(f"data:image/png;base64,{b64}") == raw
    assert ocr._decode(b64) == raw  # also accepts a bare base64 string


# ── grammar / spelling polish (best-effort, id-safe) ────────

async def test_polish_short_text_is_unchanged():
    assert await llm.polish_text("hi") == "hi"


async def test_polish_corrects_typos(monkeypatch):
    async def fake(messages, stream=False):
        return "What services are reporting high latency?"
    monkeypatch.setattr(llm, "_generate_ollama_answer", fake)
    monkeypatch.setattr(llm.settings, "llm_provider", "ollama")
    out = await llm.polish_text("wat servises r reportng hi latency")
    assert "services" in out and "latency" in out


async def test_polish_rejects_a_model_that_answered_instead(monkeypatch):
    async def fake(messages, stream=False):
        return "X" * 1000  # far longer than input → it answered, not corrected
    monkeypatch.setattr(llm, "_generate_ollama_answer", fake)
    monkeypatch.setattr(llm.settings, "llm_provider", "ollama")
    original = "fix my speling pls"
    assert await llm.polish_text(original) == original


async def test_polish_falls_back_to_original_on_error(monkeypatch):
    async def boom(messages, stream=False):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(llm, "_generate_ollama_answer", boom)
    monkeypatch.setattr(llm.settings, "llm_provider", "ollama")
    assert await llm.polish_text("some valid question here") == "some valid question here"
