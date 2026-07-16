"""Kibana API client via Keycloak OIDC authentication.

All requests go through Kibana's console proxy API, which forwards
searches to the underlying Elasticsearch cluster.
"""

import json
import re
from datetime import datetime, timedelta, timezone

import httpx

from config import settings

KIBANA_URL = settings.kibana_url
KIBANA_SPACE = settings.kibana_space


_REDIRECT_CODES = (301, 302, 303, 307, 308)


def _sid_from(client: httpx.AsyncClient) -> str | None:
    for cookie in client.cookies.jar:
        if cookie.name == "sid":
            return cookie.value
    return None


async def keycloak_login(username: str, password: str) -> str:
    """Log in via Keycloak OIDC and return the Kibana session cookie (sid).

    Kibana's provider-selector route (POST /internal/security/login) is disabled
    server-side, so we initiate the OIDC flow through the issuer instead of a
    hardcoded provider name: GET /api/security/oidc/initiate_login?iss=<issuer>.
    Kibana 302-redirects to Keycloak (setting a state cookie we keep in the shared
    jar); we submit the credentials to the Keycloak form and follow the callback
    back to Kibana to obtain the sid. Issuer is configurable (KIBANA_OIDC_ISSUER)
    so a future SSO move is an .env change, not a code change.
    """
    async with httpx.AsyncClient(verify=True, follow_redirects=False, timeout=20.0) as client:
        # Step 1: initiate OIDC → Kibana 302s to the Keycloak auth URL (+ state cookie).
        r1 = await client.get(
            f"{KIBANA_URL}/api/security/oidc/initiate_login",
            params={"iss": settings.kibana_oidc_issuer},
        )
        if r1.status_code not in _REDIRECT_CODES or "location" not in r1.headers:
            raise Exception(f"OIDC login-init failed (status {r1.status_code}) — "
                            "check KIBANA_OIDC_ISSUER / Kibana auth config")
        keycloak_url = r1.headers["location"]

        # Step 2: fetch the Keycloak login form (follow any intermediate redirects).
        r2 = await client.get(keycloak_url, follow_redirects=True)
        r2.raise_for_status()
        action_match = re.search(r'action="([^"]*)"', r2.text)
        if not action_match:
            raise Exception("Could not find Keycloak login form")
        action_url = action_match.group(1).replace("&amp;", "&")

        # Step 3: submit credentials to Keycloak (a success is a 3xx redirect).
        r3 = await client.post(action_url, data={"username": username, "password": password})
        if r3.status_code not in _REDIRECT_CODES:
            err_match = re.search(r'id="input-error"[^>]*>(.*?)<', r3.text)
            if err_match:
                raise Exception(f"Login failed: {err_match.group(1).strip()}")
            raise Exception("Invalid username or password")

        # Step 4: follow the redirect chain through Kibana's OIDC callback, which
        # sets the sid cookie. Stop as soon as sid appears (cap the hops).
        location = r3.headers.get("location")
        for _ in range(6):
            if not location:
                break
            resp = await client.get(location)
            sid = _sid_from(client)
            if sid:
                return sid
            location = resp.headers.get("location") if resp.status_code in _REDIRECT_CODES else None

        sid = _sid_from(client)
        if sid:
            return sid
        raise Exception("Login succeeded but no session cookie received")


def _headers(sid: str) -> dict:
    """Build headers with session cookie for Kibana API requests."""
    return {
        "Cookie": f"sid={sid}",
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }


# Index patterns may only contain ES-safe characters. This guards the
# value before it is interpolated into the Kibana proxy URL path.
_SAFE_INDEX = re.compile(r"^[A-Za-z0-9_.\-*,]+$")


async def _es_search(sid: str, index: str, body: dict) -> dict:
    """Execute an Elasticsearch search via Kibana's internal search API.

    Kibana's Dev-Tools console proxy (/api/console/proxy) is disabled server-side
    ("not available with the current configuration"), so we use the still-enabled
    'es' search strategy (/internal/search/es) that Kibana's own Discover uses.
    The ES response comes back wrapped in `rawResponse`; we unwrap it so callers
    keep the normal {hits, aggregations, ...} shape unchanged."""
    if not index or not _SAFE_INDEX.match(index):
        raise ValueError(f"Invalid index pattern: {index!r}")

    url = f"{KIBANA_URL}/s/{KIBANA_SPACE}/internal/search/es"
    headers = {**_headers(sid), "x-elastic-internal-origin": "Kibana"}
    payload = {"params": {"index": index, "body": body}}

    async with httpx.AsyncClient(verify=True, timeout=30.0) as client:
        response = await client.post(url, headers=headers, content=json.dumps(payload))
        response.raise_for_status()
        data = response.json()
    return data.get("rawResponse") or data


# Document ids embedded in a free-text question: a UUID (Plooi publication id)
# or a KOOP "ronl-…" identifier. Used to pivot chat into a document trace.
_DOC_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|ronl-[A-Za-z0-9-]+",
    re.IGNORECASE,
)


def extract_doc_ids(text: str) -> list[str]:
    """Return the distinct document ids mentioned in a question, in order."""
    seen: list[str] = []
    for match in _DOC_ID_RE.findall(text or ""):
        if match not in seen:
            seen.append(match)
    return seen


async def search_by_document_id(
    sid: str,
    doc_id: str,
    index: str | None = None,
    size: int = 200,
    days: int = 30,
) -> list[dict]:
    """All log events mentioning a document id across a WIDE window (oldest
    first), so a question about a specific document is answered regardless of
    the narrow time range selected for general chat."""
    now = datetime.now(timezone.utc)
    time_from = now - timedelta(days=days)
    body = {
        "size": size,
        "sort": [{"@timestamp": {"order": "asc"}}],
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": time_from.isoformat(), "lte": now.isoformat()}}},
                    {"query_string": {"query": f'"{doc_id}"', "default_field": "*", "lenient": True}},
                ]
            }
        },
    }
    result = await _es_search(sid, index or settings.es_log_index, body)
    return _format_hits(result.get("hits", {}).get("hits", []))


async def get_recent_logs(
    sid: str,
    size: int = 15,
    time_range_minutes: int = 60,
    index: str | None = None,
) -> list[dict]:
    """Get the most recent logs regardless of content."""
    now = datetime.now(timezone.utc)
    time_from = now - timedelta(minutes=time_range_minutes)

    body = {
        "size": size,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {
            "range": {
                "@timestamp": {
                    "gte": time_from.isoformat(),
                    "lte": now.isoformat(),
                }
            }
        },
    }

    result = await _es_search(sid, index or settings.es_log_index, body)
    return _format_hits(result.get("hits", {}).get("hits", []))


async def search_logs(
    sid: str,
    query: str,
    size: int = 20,
    time_range_minutes: int = 60,
    index: str | None = None,
) -> list[dict]:
    """Search logs matching a query string within a time range."""
    now = datetime.now(timezone.utc)
    time_from = now - timedelta(minutes=time_range_minutes)

    body = {
        "size": size,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {
            "bool": {
                "must": [
                    {
                        "multi_match": {
                            "query": query,
                            "fields": ["message", "log.*", "error.*", "event.*"],
                            "type": "best_fields",
                        }
                    }
                ],
                "filter": [
                    {
                        "range": {
                            "@timestamp": {
                                "gte": time_from.isoformat(),
                                "lte": now.isoformat(),
                            }
                        }
                    }
                ],
            }
        },
    }

    result = await _es_search(sid, index or settings.es_log_index, body)
    return _format_hits(result.get("hits", {}).get("hits", []))


async def get_recent_errors(
    sid: str,
    size: int = 10,
    time_range_minutes: int = 30,
    index: str | None = None,
) -> list[dict]:
    """Get recent error-level log entries."""
    now = datetime.now(timezone.utc)
    time_from = now - timedelta(minutes=time_range_minutes)

    body = {
        "size": size,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {
            "bool": {
                "must": [
                    {
                        "bool": {
                            "should": [
                                {"terms": {"log.level": ["error", "ERROR", "fatal", "FATAL", "critical", "CRITICAL"]}},
                                {"terms": {"level": ["error", "ERROR", "fatal", "FATAL", "critical", "CRITICAL"]}},
                                {"exists": {"field": "error.message"}},
                            ]
                        }
                    }
                ],
                "filter": [
                    {
                        "range": {
                            "@timestamp": {
                                "gte": time_from.isoformat(),
                                "lte": now.isoformat(),
                            }
                        }
                    }
                ],
            }
        },
    }

    result = await _es_search(sid, index or settings.es_log_index, body)
    return _format_hits(result.get("hits", {}).get("hits", []))


def _format_hits(hits: list[dict]) -> list[dict]:
    """Extract relevant fields from ES hits."""
    formatted = []
    for hit in hits:
        source = hit.get("_source", {})
        entry = {
            "index": hit.get("_index", ""),
            "timestamp": source.get("@timestamp", ""),
            "message": source.get("message", ""),
        }
        if "log" in source and "level" in source["log"]:
            entry["level"] = source["log"]["level"]
        elif "level" in source:
            entry["level"] = source["level"]
        if "host" in source and "name" in source["host"]:
            entry["host"] = source["host"]["name"]
        if "error" in source:
            entry["error"] = source["error"]
        formatted.append(entry)
    return formatted
