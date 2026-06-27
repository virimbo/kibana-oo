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
