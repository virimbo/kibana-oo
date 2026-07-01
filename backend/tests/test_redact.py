"""PII-redaction layer: emails/IPs/tokens are masked before the LLM context,
while analysis-critical data (doc ids, service names, HTTP codes, timestamps,
*.overheid.nl hostnames) is preserved. Plus the shared context builder applies
redaction when the flag is on and skips it when off. No network."""
import redact
from config import settings

import main


# ── redact_pii: masks PII ───────────────────────────────────────────────────

def test_email_masked():
    out = redact.redact_pii("contact jan.jansen@example.com for details")
    assert "jan.jansen@example.com" not in out
    assert "[email]" in out


def test_ipv4_masked():
    out = redact.redact_pii("client 192.168.10.24 connected")
    assert "192.168.10.24" not in out
    assert "[ip]" in out


def test_ipv6_masked():
    out = redact.redact_pii("peer 2001:0db8:85a3:0000:0000:8a2e:0370:7334 seen")
    assert "2001:0db8" not in out
    assert "[ip]" in out


def test_jwt_token_masked():
    jwt = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
           "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
           "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
    out = redact.redact_pii(f"Authorization: Bearer {jwt}")
    assert jwt not in out
    assert "[token]" in out


def test_long_base64_blob_masked():
    blob = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0UvWx"  # 44 chars
    out = redact.redact_pii(f"token={blob}")
    assert blob not in out
    assert "[token]" in out


# ── redact_pii: preserves analysis-critical data ────────────────────────────

def test_preserves_doc_id():
    text = "document ronl-abc-123 failed"
    assert redact.redact_pii(text) == text


def test_preserves_service_name_and_http_code_and_timestamp():
    text = "[2026-07-01T12:34:56Z] harvester-production-service returned 500"
    out = redact.redact_pii(text)
    assert "harvester-production-service" in out
    assert "500" in out
    assert "2026-07-01T12:34:56Z" in out
    assert out == text


def test_preserves_overheid_hostname():
    text = "fetched https://open.overheid.nl/details/ronl-xyz ok"
    out = redact.redact_pii(text)
    assert "open.overheid.nl" in out
    assert out == text


# ── redact_pii: robustness ──────────────────────────────────────────────────

def test_idempotent():
    text = "mail me at a@b.com from 10.0.0.5"
    once = redact.redact_pii(text)
    twice = redact.redact_pii(once)
    assert once == twice
    assert "[email]" in twice and "[ip]" in twice


def test_empty_and_none_safe():
    assert redact.redact_pii("") == ""
    assert redact.redact_pii(None) is None


# ── shared context builder applies / skips redaction via the flag ───────────

def _sample_logs():
    return [{
        "timestamp": "2026-07-01T12:00:00Z",
        "level": "ERROR",
        "host": "harvester-production-service",
        "message": "delivery failed for ronl-abc-123 from user@example.com at 10.1.2.3 (HTTP 500)",
    }]


def test_context_builder_redacts_when_flag_on(monkeypatch):
    monkeypatch.setattr(settings, "llm_redact_pii", True)
    ctx = main._build_context(_sample_logs(), [], [])
    # PII gone
    assert "user@example.com" not in ctx
    assert "10.1.2.3" not in ctx
    assert "[email]" in ctx and "[ip]" in ctx
    # analysis data kept
    assert "ronl-abc-123" in ctx
    assert "harvester-production-service" in ctx
    assert "500" in ctx


def test_context_builder_skips_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "llm_redact_pii", False)
    ctx = main._build_context(_sample_logs(), [], [])
    assert "user@example.com" in ctx
    assert "10.1.2.3" in ctx
    assert "[email]" not in ctx
