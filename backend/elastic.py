"""Elasticsearch client for querying logs and metrics."""

from datetime import datetime, timedelta, timezone

from elasticsearch import Elasticsearch

from config import settings


def _create_client() -> Elasticsearch:
    """Create an authenticated Elasticsearch client."""
    kwargs: dict = {
        "hosts": [settings.elasticsearch_url],
        "verify_certs": True,
        "request_timeout": 30,
    }

    if settings.elasticsearch_api_key:
        kwargs["api_key"] = settings.elasticsearch_api_key
    elif settings.elasticsearch_user and settings.elasticsearch_password:
        kwargs["basic_auth"] = (
            settings.elasticsearch_user,
            settings.elasticsearch_password,
        )

    return Elasticsearch(**kwargs)


es_client = _create_client()


def search_logs(
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

    result = es_client.search(index=settings.es_log_index, body=body)
    return _format_hits(result["hits"]["hits"])


def search_metrics(
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

    result = es_client.search(index=settings.es_metric_index, body=body)
    return _format_hits(result["hits"]["hits"])


def get_recent_errors(size: int = 10, time_range_minutes: int = 30) -> list[dict]:
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

    result = es_client.search(index=settings.es_log_index, body=body)
    return _format_hits(result["hits"]["hits"])


def get_cluster_health() -> dict:
    """Get Elasticsearch cluster health status."""
    return es_client.cluster.health().body


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
        # Include log level if present
        if "log" in source and "level" in source["log"]:
            entry["level"] = source["log"]["level"]
        elif "level" in source:
            entry["level"] = source["level"]
        # Include host info if present
        if "host" in source and "name" in source["host"]:
            entry["host"] = source["host"]["name"]
        # Include error info if present
        if "error" in source:
            entry["error"] = source["error"]

        formatted.append(entry)
    return formatted
