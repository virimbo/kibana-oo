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

import os

def _auth_headers(connection):
    ref = (connection or {}).get("secret_ref")
    tok = os.environ.get(ref) if ref else None
    return {"Authorization": f"Bearer {tok}"} if tok else {}

_JAEGER_FIELDS = [
    {"name": "service", "label": "Service", "kind": "text", "required": True},
    {"name": "lookback_minutes", "label": "Lookback (min)", "kind": "int", "default": 15},
    {"name": "min_traces", "label": "Min. traces", "kind": "int", "default": 1},
]
async def _check_jaeger(target, connection):
    if not connection:
        return {"status": "unreachable", "detail": {"error": "no connection"}, "latency_ms": None}
    cfg = target["config"]; lb = cfg.get("lookback_minutes", 15)
    url = f"{connection['base_url'].rstrip('/')}/api/traces"
    params = {"service": cfg["service"], "lookback": f"{lb}m", "limit": 20}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.monitor_timeout) as c:
            resp = await c.get(url, params=params, headers=_auth_headers(connection))
        ms = int((time.monotonic() - t0) * 1000)
        n = len((resp.json() or {}).get("data") or [])
        status = "ok" if n >= cfg.get("min_traces", 1) else "stale"
        return {"status": status, "detail": {"traces": n, "lookback_min": lb}, "latency_ms": ms}
    except (httpx.RequestError,) as e:
        return {"status": "unreachable", "detail": {"error": type(e).__name__}, "latency_ms": None}

_PROM_FIELDS = [
    {"name": "query", "label": "PromQL", "kind": "text", "required": True},
    {"name": "op", "label": "Operator", "kind": "select", "options": [">", ">=", "<", "<=", "==", "exists"], "default": "exists"},
    {"name": "threshold", "label": "Drempel", "kind": "float", "default": 0},
]
def _cmp(v, op, thr):
    return {">": v > thr, ">=": v >= thr, "<": v < thr, "<=": v <= thr, "==": v == thr}.get(op, True)
async def _check_prometheus(target, connection):
    if not connection:
        return {"status": "unreachable", "detail": {"error": "no connection"}, "latency_ms": None}
    cfg = target["config"]; url = f"{connection['base_url'].rstrip('/')}/api/v1/query"
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.monitor_timeout) as c:
            resp = await c.get(url, params={"query": cfg["query"]}, headers=_auth_headers(connection))
        ms = int((time.monotonic() - t0) * 1000)
        result = ((resp.json() or {}).get("data") or {}).get("result") or []
        if not result:
            return {"status": "stale", "detail": {"reason": "empty result"}, "latency_ms": ms}
        op = cfg.get("op", "exists")
        if op == "exists":
            return {"status": "ok", "detail": {"series": len(result)}, "latency_ms": ms}
        val = float(result[0]["value"][1])
        ok = _cmp(val, op, float(cfg.get("threshold", 0)))
        return {"status": "ok" if ok else "down", "detail": {"value": val, "op": op}, "latency_ms": ms}
    except (httpx.RequestError, KeyError, ValueError) as e:
        return {"status": "unreachable", "detail": {"error": type(e).__name__}, "latency_ms": None}

async def _discover_jaeger(connection):
    """List Jaeger services → one jaeger-traces target suggestion each."""
    url = f"{connection['base_url'].rstrip('/')}/api/services"
    try:
        async with httpx.AsyncClient(timeout=settings.monitor_timeout) as c:
            resp = await c.get(url, headers=_auth_headers(connection))
        services = (resp.json() or {}).get("data") or []
    except Exception:  # noqa: BLE001
        return []
    return [{"name": f"traces: {s}", "type": "jaeger-traces", "environment": "na",
             "connection_id": connection.get("id"),
             "config": {"service": s, "lookback_minutes": 15, "min_traces": 1}}
            for s in services]

async def _discover_prometheus(connection):
    """List Prometheus scrape jobs → an up{job=...} target suggestion each."""
    url = f"{connection['base_url'].rstrip('/')}/api/v1/targets"
    try:
        async with httpx.AsyncClient(timeout=settings.monitor_timeout) as c:
            resp = await c.get(url, headers=_auth_headers(connection))
        targets = (((resp.json() or {}).get("data") or {}).get("activeTargets")) or []
    except Exception:  # noqa: BLE001
        return []
    jobs = sorted({(t.get("labels") or {}).get("job") for t in targets if (t.get("labels") or {}).get("job")})
    return [{"name": f"up: {job}", "type": "prometheus-query", "environment": "na",
             "connection_id": connection.get("id"),
             "config": {"query": f'up{{job="{job}"}}', "op": ">", "threshold": 0}}
            for job in jobs]

register("jaeger-traces", _JAEGER_FIELDS, _check_jaeger, discover=_discover_jaeger)
register("prometheus-query", _PROM_FIELDS, _check_prometheus, discover=_discover_prometheus)

# ── smb (Windows/CIFS file share, port 445) ──────────────────────────────────
# Self-contained target (no connection): host/share/creds live in config; the
# password is read from the .env var named by `secret_ref` at check time — never
# stored. Layered probe: TCP reach → SMB session → share → read → optional write.
import asyncio

_SMB_FIELDS = [
    {"name": "host", "label": "Host / server", "kind": "text", "required": True},
    {"name": "share", "label": "Share", "kind": "text", "required": True},
    {"name": "port", "label": "Poort", "kind": "int", "default": 445},
    {"name": "username", "label": "Gebruiker (service-account)", "kind": "text", "required": True},
    {"name": "domain", "label": "Domein (optioneel)", "kind": "text", "default": ""},
    {"name": "secret_ref", "label": ".env-naam met wachtwoord", "kind": "text", "required": True},
    {"name": "path", "label": "Canary-pad om te lezen (optioneel)", "kind": "text", "default": ""},
    {"name": "write_test", "label": "Schrijftest uitvoeren", "kind": "bool", "default": False},
    {"name": "write_dir", "label": "Schrijf-map voor canary (optioneel)", "kind": "text", "default": ""},
    {"name": "encrypt", "label": "SMB3-encryptie vereisen", "kind": "bool", "default": True},
    {"name": "timeout_s", "label": "Timeout (s)", "kind": "int", "default": None},
    {"name": "latency_warn_ms", "label": "Latency-waarschuwing (ms)", "kind": "int", "default": None},
    {"name": "service", "label": "Service-label (correlatie)", "kind": "text", "default": None},
]


def _smb_probe(host, share, port, username, password, domain, path,
               write_test, write_dir, encrypt, timeout):
    """Blocking SMB probe — run via asyncio.to_thread so the poll loop stays async.
    Layered so the `detail.stage` pinpoints where it failed. Never raises."""
    import socket
    import time as _t
    import uuid
    t0 = _t.monotonic()
    # 1) TCP reach — separates 'unreachable' (network/firewall/host) from auth/share.
    try:
        socket.create_connection((host, port), timeout=timeout).close()
    except Exception as e:  # noqa: BLE001
        return {"status": "unreachable", "detail": {"stage": "tcp", "error": type(e).__name__}, "latency_ms": None}
    try:
        import smbclient
    except ImportError:
        return {"status": "unreachable", "detail": {"stage": "deps", "error": "smbprotocol niet geïnstalleerd"}, "latency_ms": None}
    user = f"{domain}\\{username}" if domain else username
    base = r"\\%s\%s" % (host, share)
    # 2) SMB session (auth + protocol). Reachable but rejected → 'down'.
    try:
        smbclient.register_session(host, username=user, password=password, port=port,
                                   encrypt=encrypt, connection_timeout=int(timeout))
    except Exception as e:  # noqa: BLE001
        return {"status": "down", "detail": {"stage": "session", "error": type(e).__name__, "msg": str(e)[:160]}, "latency_ms": None}
    detail = {}
    try:
        # 3) Share / tree-connect + 4) read canary
        detail["entries"] = len(smbclient.listdir(base, port=port))
        if path:
            full = base + "\\" + path.lstrip("\\/").replace("/", "\\")
            if not smbclient.path.exists(full, port=port):
                return {"status": "down", "detail": {"stage": "read", "error": "pad niet gevonden", "path": path},
                        "latency_ms": int((_t.monotonic() - t0) * 1000)}
        # 5) optional write canary — unique temp file in a dedicated dir, always cleaned up
        if write_test:
            wdir = base + ("\\" + write_dir.strip("\\/").replace("/", "\\") if write_dir else "")
            fname = wdir + "\\.healthcheck-" + uuid.uuid4().hex + ".tmp"
            with smbclient.open_file(fname, mode="wb", port=port) as fh:
                fh.write(b"healthcheck")
            smbclient.remove(fname, port=port)
            detail["write"] = "ok"
        ms = int((_t.monotonic() - t0) * 1000)
        return {"status": "ok", "detail": detail, "latency_ms": ms}
    except Exception as e:  # noqa: BLE001 — reachable + authed but share/IO failed → down
        return {"status": "down", "detail": {"stage": "io", "error": type(e).__name__, "msg": str(e)[:160]},
                "latency_ms": int((_t.monotonic() - t0) * 1000)}
    finally:
        try:
            smbclient.delete_session(host, port=port)
        except Exception:  # noqa: BLE001
            pass


async def _check_smb(target, connection):
    cfg = target["config"]
    host = (cfg.get("host") or (connection or {}).get("base_url") or "").strip().strip("\\")
    if not host:
        return {"status": "unreachable", "detail": {"error": "geen host"}, "latency_ms": None}
    if not cfg.get("share"):
        return {"status": "unreachable", "detail": {"error": "geen share"}, "latency_ms": None}
    ref = cfg.get("secret_ref") or (connection or {}).get("secret_ref") or ""
    password = os.environ.get(ref, "") if ref else ""
    timeout = cfg.get("timeout_s") or settings.monitor_timeout
    res = await asyncio.to_thread(
        _smb_probe, host, cfg["share"], int(cfg.get("port") or 445),
        cfg.get("username", "") or "", password, cfg.get("domain", "") or "",
        cfg.get("path", "") or "", bool(cfg.get("write_test")), cfg.get("write_dir", "") or "",
        bool(cfg.get("encrypt", True)), timeout)
    # Latency degradation → soft 'warn' (only when the probe was otherwise ok).
    warn = cfg.get("latency_warn_ms")
    if res.get("status") == "ok" and warn and res.get("latency_ms") and res["latency_ms"] > warn:
        res = {**res, "status": "warn",
               "detail": {**res.get("detail", {}), "slow": True, "latency_warn_ms": warn}}
    return res


register("smb", _SMB_FIELDS, _check_smb)
