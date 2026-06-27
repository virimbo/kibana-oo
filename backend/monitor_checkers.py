"""Checker plugins. Each type declares its config `fields` (UI form builder) and an
async `check(target, connection)` returning {status, detail, latency_ms}. Never raises
out — wraps failures as 'unreachable'. Status vocab: ok|warn|stale|down|unreachable."""
import time, httpx
from config import settings

CHECKERS = {}   # type_id -> {"fields": [...], "check": fn, "discover": fn|None}

def register(type_id, fields, check, discover=None):
    CHECKERS[type_id] = {"fields": fields, "check": check, "discover": discover}

def types_schema() -> dict:
    return {k: {"fields": v["fields"]} for k, v in CHECKERS.items()}

async def run_check(target: dict, connection: dict | None) -> dict:
    chk = CHECKERS.get(target["type"])
    if not chk:
        return {"status": "unreachable", "detail": {"error": f"unknown type {target['type']}"}, "latency_ms": None}
    try:
        return await chk["check"](target, connection)
    except Exception as e:  # noqa: BLE001 — a checker must never break the round
        return {"status": "unreachable", "detail": {"error": str(e)}, "latency_ms": None}

# ── http ──
_HTTP_FIELDS = [
    {"name": "url", "label": "URL", "kind": "text", "required": True},
    {"name": "expected_status", "label": "Verwachte status", "kind": "list-int", "default": [200, 204, 301, 302, 401, 403, 405]},
    {"name": "timeout_s", "label": "Timeout (s)", "kind": "int", "default": None},
    {"name": "service", "label": "Service-label (voor correlatie)", "kind": "text", "default": None},
]
async def _check_http(target, connection):
    cfg = target["config"]; url = cfg["url"]
    timeout = cfg.get("timeout_s") or settings.monitor_timeout
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            resp = await client.get(url)
        ms = int((time.monotonic() - t0) * 1000)
        code = resp.status_code
        if code >= 500:
            return {"status": "down", "detail": {"http": code}, "latency_ms": ms}
        return {"status": "ok", "detail": {"http": code}, "latency_ms": ms}
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RequestError) as e:
        return {"status": "unreachable", "detail": {"error": type(e).__name__}, "latency_ms": None}

register("http", _HTTP_FIELDS, _check_http)

from datetime import datetime, timezone

_LOGFRESH_FIELDS = [
    {"name": "index", "label": "Index / data-stream", "kind": "text", "required": True},
    {"name": "timestamp_field", "label": "Timestamp-veld", "kind": "text", "default": "@timestamp"},
    {"name": "max_age_minutes", "label": "Max leeftijd (min)", "kind": "int", "default": 10},
    {"name": "adaptive", "label": "Adaptieve baseline", "kind": "bool", "default": True},
    {"name": "service", "label": "Service-label (voor correlatie)", "kind": "text", "default": None},
]

async def _es_max_timestamp(index, field, sid):
    """Newest timestamp in an index via the existing Kibana proxy (elastic._es_search).
    Returns an ISO string or None. Reuses the same authenticated path chat uses."""
    import elastic
    body = {"size": 0, "aggs": {"m": {"max": {"field": field}}}}
    try:
        res = await elastic._es_search(sid, index, body)
        return (((res or {}).get("aggregations") or {}).get("m") or {}).get("value_as_string")
    except Exception:  # noqa: BLE001 — treat any ES failure as "no data"
        return None

async def _check_log_freshness(target, connection):
    cfg = target["config"]
    sid = (target.get("_ctx") or {}).get("sid")
    ts = await _es_max_timestamp(cfg["index"], cfg.get("timestamp_field", "@timestamp"), sid)
    if not ts:
        return {"status": "unreachable", "detail": {"error": "no data / ES unreachable"}, "latency_ms": None}
    age_min = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 60
    threshold = cfg.get("_effective_threshold", cfg.get("max_age_minutes", 10))
    status = "stale" if age_min > threshold else "ok"
    return {"status": status, "detail": {"age_min": round(age_min, 1), "threshold": threshold}, "latency_ms": None}

register("log-freshness", _LOGFRESH_FIELDS, _check_log_freshness)
