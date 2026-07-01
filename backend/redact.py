"""PII-redaction for LLM context.

`redact_pii(text)` conservatively masks obvious personal data from the log
context string BEFORE it is sent to any LLM provider (Ollama *or* Mistral
cloud). It is applied in the shared context builders in `main.py`, never inside
a provider code path.

Design constraints (see docs / CLAUDE.md guardrails):
  - Mask ONLY high-confidence PII: email addresses, IPv4/IPv6 addresses, and
    long JWT/bearer-like tokens.
  - DO NOT touch analysis-critical identifiers: `ronl-...` / document ids,
    service names, HTTP status codes, ISO timestamps, or `*.overheid.nl`
    hostnames — these are needed for the document-trace feature.
  - Idempotent (running twice yields the same result) and never raises: on any
    error the input is returned unchanged, so redaction can never break a chat.

This only affects what the model sees; the `sources`/facts shown to the user in
the UI keep their real data.
"""
from __future__ import annotations

import re

EMAIL_MASK = "[email]"
IP_MASK = "[ip]"
TOKEN_MASK = "[token]"

# ── Email addresses ────────────────────────────────────────────────────────
# Standard local@domain.tld. The trailing TLD keeps us from matching bare
# `service.name` tokens (no local part) or paths.
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# ── JWT / bearer-like tokens ───────────────────────────────────────────────
# A JWT is three base64url segments separated by dots and starting `eyJ`
# (the base64 of `{"`). Match those first so a long token is masked as one unit.
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+")

# A long opaque base64url blob (40+ chars). Bounded by non-word edges so it does
# not eat into surrounding punctuation. Long enough that ordinary words, ids and
# hostnames never reach the threshold.
_LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_-]{40,}\b")

# ── IP addresses ───────────────────────────────────────────────────────────
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
)

# IPv6: a run of hex groups / `::` compression with at least one colon-pair, so
# we don't accidentally match timestamps like `12:34:56`. Requires a hex digit
# group adjacent to `::`, or 3+ colon-separated hextet groups.
_IPV6_RE = re.compile(
    r"\b(?:"
    r"(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}"        # full/partial form
    r"|(?:[0-9A-Fa-f]{1,4}:){1,7}:"                        # trailing ::
    r"|:(?::[0-9A-Fa-f]{1,4}){1,7}"                        # leading ::
    r"|(?:[0-9A-Fa-f]{1,4}:){1,6}:[0-9A-Fa-f]{1,4}"       # mixed ::
    r")\b"
)


def redact_pii(text: str) -> str:
    """Return `text` with obvious PII masked. Never raises.

    Masks, in order that keeps larger matches intact:
      email → ``[email]``, JWT/long-token → ``[token]``, IPv6/IPv4 → ``[ip]``.

    Preserves document ids, service names, HTTP status codes, ISO timestamps
    and ``*.overheid.nl`` hostnames. Idempotent — the mask tokens themselves are
    inert to every pattern.
    """
    if not text:
        return text
    try:
        out = _EMAIL_RE.sub(EMAIL_MASK, text)
        out = _JWT_RE.sub(TOKEN_MASK, out)
        out = _LONG_TOKEN_RE.sub(TOKEN_MASK, out)
        out = _IPV6_RE.sub(IP_MASK, out)
        out = _IPV4_RE.sub(IP_MASK, out)
        return out
    except Exception:  # noqa: BLE001 — redaction must never break a chat
        return text
