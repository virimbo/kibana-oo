"""Piwik PRO page-views integration: inert until configured, robust on failure,
and parses the query response correctly. Network is fully mocked — no real call."""
import httpx
import pytest

import piwik
from config import settings


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "piwik_account_url", "https://koop.piwik.pro")
    monkeypatch.setattr(settings, "piwik_client_id", "cid")
    monkeypatch.setattr(settings, "piwik_client_secret", "secret")
    monkeypatch.setattr(settings, "piwik_website_id", "site-uuid")
    # Reset the cached token between tests.
    piwik._token = None
    piwik._token_expiry = 0.0
    yield


def test_inert_when_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "piwik_account_url", "")
    assert piwik.is_configured() is False


async def test_returns_unconfigured_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "piwik_account_url", "")
    result = await piwik.document_views("https://open.overheid.nl/documenten/abc-123")
    assert result == {"configured": False}


def test_match_token_extracts_document_id():
    assert piwik._match_token("https://open.overheid.nl/documenten/abc-123") == "abc-123"
    assert piwik._match_token("https://open.overheid.nl/details/abc-123/") == "abc-123"
    assert piwik._match_token("/documenten/xyz") == "xyz"
    assert piwik._match_token("ronl-archief-9f") == "ronl-archief-9f"


async def test_document_views_parses_query_response(configured, monkeypatch):
    calls = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 1800})
        if request.url.path == "/api/analytics/v1/query/":
            calls["body"] = request.read().decode()
            return httpx.Response(200, json={"data": [[1234, 567]]})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    _patch_client(monkeypatch, transport)

    result = await piwik.document_views(
        "https://open.overheid.nl/documenten/1a7e9fc7-0be6", days=30
    )
    assert result["configured"] is True
    assert result["page_views"] == 1234
    assert result["unique_visitors"] == 567
    assert result["days"] == 30
    # The filter must target the document id, not the whole URL.
    assert "1a7e9fc7-0be6" in calls["body"]
    assert "page_views" in calls["body"]


async def test_document_views_empty_result_is_zero(configured, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 1800})
        return httpx.Response(200, json={"data": []})

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    result = await piwik.document_views("https://open.overheid.nl/documenten/none", days=7)
    assert result["page_views"] == 0
    assert result["unique_visitors"] == 0


async def test_document_views_returns_error_inline_on_http_failure(configured, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 1800})
        return httpx.Response(500, json={})

    _patch_client(monkeypatch, httpx.MockTransport(handler))
    result = await piwik.document_views("https://open.overheid.nl/documenten/x")
    assert result["configured"] is True
    assert "error" in result  # surfaced inline, not raised


def _patch_client(monkeypatch, transport):
    """Route every httpx.AsyncClient in piwik through the mock transport."""
    real_init = httpx.AsyncClient.__init__

    def init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
