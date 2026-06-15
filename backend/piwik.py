"""Piwik PRO Analytics integration — public page views & unique visitors per document.

Reads visitor analytics from Piwik PRO's Analytics Query API, the proper source
for "how many people viewed this document" (the Elasticsearch processing logs do
not carry reliable page-view data). The whole module is inert until credentials
are configured: every entry point returns {"configured": False} so the UI
degrades gracefully, and a query failure is returned inline rather than raised.

Auth: OAuth2 client-credentials → bearer token (cached, ~30 min lifetime).
Query: POST {account}/api/analytics/v1/query/ filtered to the document URL.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta
from urllib.parse import urlparse

import httpx

from config import settings

# Token cache (process-wide). Piwik tokens live 1800s; we refresh a minute early.
_TOKEN_LOCK = asyncio.Lock()
_token: str | None = None
_token_expiry: float = 0.0  # time.monotonic() seconds


def is_configured() -> bool:
    return settings.piwik_configured


def _match_token(url_or_id: str) -> str:
    """The most specific stable token to match in Piwik's page_url: the final
    path segment of a public document URL (the document id), which catches both
    /documenten/<id> and /details/<id>. Falls back to the value as given."""
    value = (url_or_id or "").strip()
    if not value:
        return ""
    path = urlparse(value).path if "://" in value else value
    segments = [s for s in path.split("/") if s]
    return segments[-1] if segments else value


async def _get_token() -> str:
    """Return a valid bearer token, fetching/refreshing under a lock so concurrent
    callers don't stampede the token endpoint."""
    global _token, _token_expiry
    async with _TOKEN_LOCK:
        if _token and time.monotonic() < _token_expiry:
            return _token
        base = settings.piwik_account_url.rstrip("/")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/auth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.piwik_client_id,
                    "client_secret": settings.piwik_client_secret,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        _token = payload["access_token"]
        _token_expiry = time.monotonic() + max(60, int(payload.get("expires_in", 1800)) - 60)
        return _token


def _short_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"Piwik PRO returned HTTP {e.response.status_code}"
    if isinstance(e, (httpx.RequestError,)):
        return "Could not reach Piwik PRO"
    return "Unexpected Piwik PRO response"


async def document_views(url_or_id: str, days: int = 30) -> dict:
    """Page views + unique visitors for a document over the last `days`.

    Returns {"configured": False} when Piwik PRO is not set up, or
    {"configured": True, "error": "..."} on a query failure. Never raises — the
    caller's document trace must render regardless."""
    if not is_configured():
        return {"configured": False}

    match = _match_token(url_or_id)
    if not match:
        return {"configured": True, "error": "no document URL to look up"}

    days = max(1, min(int(days), 365))
    end = date.today()
    start = end - timedelta(days=days - 1)
    body = {
        "website_id": settings.piwik_website_id,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "columns": [{"column_id": "page_views"}, {"column_id": "unique_visitors"}],
        "filters": {
            "operator": "and",
            "conditions": [
                {
                    "column_id": "page_url",
                    "condition": {"operator": "contains", "value": match},
                }
            ],
        },
    }
    base = settings.piwik_account_url.rstrip("/")
    try:
        token = await _get_token()
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/api/analytics/v1/query/",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
    except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError) as e:
        return {"configured": True, "error": _short_error(e), "match": match, "days": days}

    row = data[0] if data and isinstance(data[0], (list, tuple)) else [0, 0]
    views = int(row[0]) if len(row) > 0 and row[0] is not None else 0
    uniques = int(row[1]) if len(row) > 1 and row[1] is not None else 0
    return {
        "configured": True,
        "match": match,
        "days": days,
        "page_views": views,
        "unique_visitors": uniques,
    }
