"""Elasticsearch client for querying logs and metrics."""

from datetime import datetime, timedelta, timezone

from elasticsearch import Elasticsearch

from config import settings


def create_client(username: str, password: str) -> Elasticsearch:
    """Create an authenticated Elasticsearch client with user-provided credentials."""
    return Elasticsearch(
        hosts=[settings.elasticsearch_url],
        basic_auth=(username, password),
        verify_certs=True,
        request_timeout=30,
    )


def test_connection(username: str, password: str) -> dict:
    """Test if the credentials work. Returns cluster health or raises."""
    client = create_client(username, password)
    return client.cluster.health().body


def search_logs(
    client: Elasticsearch,
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

    result = client.search(index=settings.es_log_index, body=body)
    return _format_hits(result["hits"]["hits"])


def search_metrics(
    client: Elasticsearch,
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

    result = client.search(index=settings.es_metric_index, body=body)
    return _format_hits(result["hits"]["hits"])


def get_recent_errors(
    client: Elasticsearch,
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

    result = client.search(index=settings.es_log_index, body=body)
    return _format_hits(result["hits"]["hits"])


def _format_hits(hits: list[dict]) -> list[dict]:
    """Extract relevant fields from ES hits."""
    formatted = []
    for hit in hits:
        source = hit["_source"]
        entry = {
            "index": hit["_index"],
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
