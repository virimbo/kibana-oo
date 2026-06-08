"""TLS certificate expiry, read from Kibana monitoring data (Heartbeat /
Synthetics) — never by opening a TLS connection. Produces countdown cards."""
import asyncio
from datetime import datetime, timezone

from pydantic import BaseModel

from elastic import _es_search
from config import settings

# Status thresholds (days remaining).
WARNING_DAYS = 30
CRITICAL_DAYS = 14


class Certificate(BaseModel):
    host: str
    common_name: str | None = None
    issuer: str | None = None
    not_after: str
    days_remaining: int
    status: str  # ok | warning | critical | expired


def _dig(d: object, *path: str):
    """Safely walk a nested dict by keys, returning None if any step is missing."""
    for key in path:
        if not isinstance(d, dict):
            return None
        d = d.get(key)
    return d


def _parse_dt(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def cert_status(days_remaining: int) -> str:
    if days_remaining < 0:
        return "expired"
    if days_remaining < CRITICAL_DAYS:
        return "critical"
    if days_remaining < WARNING_DAYS:
        return "warning"
    return "ok"


def _query() -> dict:
    """Latest docs that carry a TLS certificate expiry (ECS or legacy field)."""
    return {
        "size": 200,
        "sort": [{"@timestamp": {"order": "desc"}}],
        "query": {
            "bool": {
                "minimum_should_match": 1,
                "should": [
                    {"exists": {"field": "tls.server.x509.not_after"}},
                    {"exists": {"field": "tls.certificate_not_valid_after"}},
                ],
            }
        },
        "_source": ["tls", "url", "monitor", "@timestamp"],
    }


def parse_certificates(hits: list[dict], now: datetime | None = None) -> list[Certificate]:
    now = now or datetime.now(timezone.utc)
    seen: set[str] = set()
    certs: list[Certificate] = []
    for hit in hits:
        src = hit.get("_source", {})
        expiry = _parse_dt(
            _dig(src, "tls", "server", "x509", "not_after")
            or _dig(src, "tls", "certificate_not_valid_after")
        )
        if expiry is None:
            continue
        host = (
            _dig(src, "url", "domain")
            or _dig(src, "monitor", "name")
            or _dig(src, "tls", "server", "x509", "subject", "common_name")
            or _dig(src, "url", "full")
            or "(unknown)"
        )
        if host in seen:  # hits are newest-first; keep the most recent per host
            continue
        seen.add(host)
        days = (expiry - now).days
        certs.append(
            Certificate(
                host=host,
                common_name=_dig(src, "tls", "server", "x509", "subject", "common_name"),
                issuer=(
                    _dig(src, "tls", "server", "x509", "issuer", "common_name")
                    or _dig(src, "tls", "server", "x509", "issuer", "distinguished_name")
                ),
                not_after=expiry.isoformat(),
                days_remaining=days,
                status=cert_status(days),
            )
        )
    certs.sort(key=lambda c: c.days_remaining)
    return certs


async def fetch_certificates(sid: str, now: datetime | None = None) -> list[Certificate]:
    """Query every configured cert index, merge, and return countdown cards.
    Indices that error (e.g. don't exist) are skipped silently."""
    indices = [i.strip() for i in settings.cert_index.split(",") if i.strip()]
    results = await asyncio.gather(
        *(_es_search(sid, idx, _query()) for idx in indices),
        return_exceptions=True,
    )
    hits: list[dict] = []
    for res in results:
        if isinstance(res, Exception):
            continue
        hits.extend(res.get("hits", {}).get("hits", []))
    return parse_certificates(hits, now)
