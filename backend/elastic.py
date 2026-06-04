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


async def keycloak_login(username: str, password: str) -> str:
    """Log in via Keycloak OIDC and return the Kibana session cookie (sid)."""
    async with httpx.AsyncClient(verify=True, follow_redirects=False, timeout=20.0) as client:
        # Step 1: Initiate OIDC login to get Keycloak URL
        r1 = await client.post(
            f"{KIBANA_URL}/internal/security/login",
            headers={"kbn-xsrf": "true", "Content-Type": "application/json"},
            json={
                "providerType": "oidc",
                "providerName": "oidc1",
                "currentURL": f"{KIBANA_URL}/login",
            },
        )
        r1.raise_for_status()
        keycloak_url = r1.json()["location"]

        # Step 2: Get the Keycloak login form
        r2 = await client.get(keycloak_url)
        r2.raise_for_status()
        action_match = re.search(r'action="([^"]*)"', r2.text)
        if not action_match:
            raise Exception("Could not find Keycloak login form")
        action_url = action_match.group(1).replace("&amp;", "&")

        # Step 3: Submit credentials to Keycloak
        r3 = await client.post(
            action_url,
            data={"username": username, "password": password},
        )
        if r3.status_code != 302:
            err_match = re.search(r'id="input-error"[^>]*>(.*?)<', r3.text)
            if err_match:
                raise Exception(f"Login failed: {err_match.group(1).strip()}")
            raise Exception("Invalid username or password")

        # Step 4: Follow redirect to Kibana callback
        callback_url = r3.headers["location"]
        await client.get(callback_url)

        # Extract sid cookie
        for cookie in client.cookies.jar:
            if cookie.name == "sid":
                return cookie.value

        raise Exception("Login succeeded but no session cookie received")


def _headers(sid: str) -> dict:
    """Build headers with session cookie for Kibana API requests."""
    return {
        "Cookie": f"sid={sid}",
        "kbn-xsrf": "true",
        "Content-Type": "application/json",
    }


async def _es_search(sid: str, index: str, body: dict) -> dict:
    """Execute an Elasticsearch search via Kibana's console proxy."""
    url = f"{KIBANA_URL}/s/{KIBANA_SPACE}/api/console/proxy?path={index}/_search&method=POST"

    async with httpx.AsyncClient(verify=True, timeout=30.0) as client:
        response = await client.post(
            url,
            headers=_headers(sid),
            content=json.dumps(body),
        )
        response.raise_for_status()
        return response.json()


async def get_recent_logs(
    sid: str,
    size: int = 15,
    time_range_minutes: int = 60,
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

    result = await _es_search(sid, settings.es_log_index, body)
    return _format_hits(result.get("hits", {}).get("hits", []))


async def search_logs(
    sid: str,
    query: str,
    size: int = 20,
    time_range_minutes: int = 60,
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

    result = await _es_search(sid, settings.es_log_index, body)
    return _format_hits(result.get("hits", {}).get("hits", []))


async def search_metrics(
    sid: str,
    query: str,
    size: int = 20,
    time_range_minutes: int = 60,
) -> list[dict]:
    """Search metrics matching a query string within a time range."""
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
                            "fields": ["*"],
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

    result = await _es_search(sid, settings.es_metric_index, body)
    return _format_hits(result.get("hits", {}).get("hits", []))


async def get_recent_errors(
    sid: str,
    size: int = 10,
    time_range_minutes: int = 30,
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
                                {"match": {"log.level": "error"}},
                                {"match": {"log.level": "ERROR"}},
                                {"match": {"level": "error"}},
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

    result = await _es_search(sid, settings.es_log_index, body)
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
