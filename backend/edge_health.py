"""Edge / ingress HTTP health for PROD.

Surfaces the signals an operator wants when the front door misbehaves:
  - HTTP 5xx errors (500/502/503) + the 5xx **ratio**
  - Gateway errors (502/503/504)
  - Time-outs (504)
  - Elevated latency (p95 of the ingress request_time)
  - Pod restarts (Prometheus, best-effort — only if a connection is configured)

The first four come from one ES aggregation over the ingress access logs; the
last from an optional Prometheus query. Read-only and additive. Never raises into
the request — it degrades to 'unknown'. Status vocab: ok | warn | critical | unknown.
"""
import logging
import os
from datetime import datetime, timezone

import httpx

import elastic
from config import settings

logger = logging.getLogger(__name__)

_CRIT, _WARN, _OK, _UNK = "critical", "warn", "ok", "unknown"
_RANK = {_OK: 0, _UNK: 1, _WARN: 2, _CRIT: 3}


def _worst(statuses: list[str]) -> str:
    return max(statuses, key=lambda s: _RANK.get(s, 0)) if statuses else _UNK


def _signal(key, label, status, metric, detail=""):
    return {"key": key, "label": label, "status": status, "metric": metric, "detail": detail}


def _status_counts(buckets) -> dict[int, int]:
    """{status_code -> count} from a terms agg, tolerant of str or int keys."""
    out: dict[int, int] = {}
    for b in buckets or []:
        try:
            code = int(b["key"])
        except (ValueError, TypeError, KeyError):
            continue
        out[code] = out.get(code, 0) + b.get("doc_count", 0)
    return out


def _classify_5xx(total: int, five_xx: int) -> tuple[str, str]:
    if total < settings.edge_min_requests:
        return _OK, f"{five_xx}/{total} (te weinig verkeer)"
    ratio = (five_xx / total * 100) if total else 0.0
    if ratio >= settings.edge_5xx_ratio_crit:
        s = _CRIT
    elif ratio >= settings.edge_5xx_ratio_warn:
        s = _WARN
    else:
        s = _OK
    return s, f"{ratio:.1f}% ({five_xx}/{total})"


def _classify_count(n: int, warn: int, crit: int) -> str:
    if n >= crit:
        return _CRIT
    if n >= warn:
        return _WARN
    return _OK


async def _pod_restarts() -> tuple[int | None, str]:
    """Best-effort pod-restart count over the last hour via the first configured
    Prometheus connection. Returns (count|None, note). None → not available."""
    try:
        import monitor_registry as reg
        conns = [c for c in reg.list_connections()
                 if c.get("kind") == "prometheus" and c.get("enabled")]
    except Exception:  # noqa: BLE001 — registry/db may be empty; treat as unconfigured
        conns = []
    if not conns:
        return None, "Prometheus niet geconfigureerd"
    conn = conns[0]
    ref = conn.get("secret_ref")
    token = os.environ.get(ref) if ref else None
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"{conn['base_url'].rstrip('/')}/api/v1/query"
    try:
        async with httpx.AsyncClient(timeout=settings.monitor_timeout) as c:
            r = await c.get(url, params={"query": settings.edge_pod_restart_query}, headers=headers)
        result = ((r.json() or {}).get("data") or {}).get("result") or []
        if not result:
            return 0, "geen restarts"
        return int(round(float(result[0]["value"][1]))), ""
    except Exception as e:  # noqa: BLE001
        logger.warning("edge: pod-restart query failed: %s", e)
        return None, "Prometheus onbereikbaar"


async def build_edge_health(sid: str, data_view: str | None = None,
                            minutes: int | None = None) -> dict:
    """One aggregation over the ingress logs + an optional Prometheus query,
    classified into the five signals with an overall roll-up."""
    if not settings.edge_enabled:
        return {"enabled": False}
    dv = data_view or settings.edge_data_view
    win = int(minutes or settings.edge_window_minutes)
    sf, lf = settings.edge_status_field, settings.edge_latency_field
    generated_at = datetime.now(timezone.utc).isoformat()

    counts: dict[int, int] = {}
    lat_ms: float | None = None
    err: str | None = None
    body = {
        "size": 0,
        "query": {"bool": {"filter": [
            {"range": {"@timestamp": {"gte": f"now-{win}m"}}},
            {"exists": {"field": sf}},
        ]}},
        "aggs": {
            "by_status": {"terms": {"field": sf, "size": 60}},
            "lat": {"percentiles": {"field": lf, "percents": [50, 95, 99]}},
        },
    }
    try:
        res = await elastic._es_search(sid, dv, body)
        aggs = res.get("aggregations") or {}
        counts = _status_counts((aggs.get("by_status") or {}).get("buckets"))
        p95 = ((aggs.get("lat") or {}).get("values") or {}).get("95.0")
        if isinstance(p95, (int, float)):
            lat_ms = p95 * 1000.0  # nginx request_time is in seconds
    except Exception as e:  # noqa: BLE001 — degrade, never 500 the dashboard
        err = type(e).__name__
        logger.warning("edge: ES query failed: %s", e)

    total = sum(counts.values())
    five_xx = sum(v for k, v in counts.items() if 500 <= k <= 599)
    c500, c502, c503, c504 = (counts.get(500, 0), counts.get(502, 0),
                              counts.get(503, 0), counts.get(504, 0))
    gateway = c502 + c503 + c504

    signals: list[dict] = []
    if err or not counts:
        note = "ingress-logs onbereikbaar" if err else "geen data in venster"
        for key, label in (("http5xx", "HTTP 5xx-fouten"),
                           ("gateway", "Gateway-fouten (502/503/504)"),
                           ("timeouts", "Time-outs (504)"),
                           ("latency", "Latency (p95)")):
            signals.append(_signal(key, label, _UNK, "onbekend", note))
    else:
        s5, m5 = _classify_5xx(total, five_xx)
        signals.append(_signal("http5xx", "HTTP 5xx-fouten", s5, m5,
                               f"500:{c500} · 502:{c502} · 503:{c503} · 504:{c504}"))
        signals.append(_signal("gateway", "Gateway-fouten (502/503/504)",
                               _classify_count(gateway, settings.edge_gateway_warn,
                                               settings.edge_gateway_crit), str(gateway)))
        signals.append(_signal("timeouts", "Time-outs (504)",
                               _classify_count(c504, settings.edge_gateway_warn,
                                               settings.edge_gateway_crit), str(c504)))
        if lat_ms is None:
            signals.append(_signal("latency", "Latency (p95)", _UNK, "onbekend",
                                   f"veld '{lf}' niet numeriek?"))
        else:
            sl = _CRIT if lat_ms >= settings.edge_latency_crit_ms else (
                _WARN if lat_ms >= settings.edge_latency_warn_ms else _OK)
            signals.append(_signal("latency", "Latency (p95)", sl, f"{int(lat_ms)} ms"))

    restarts, rnote = await _pod_restarts()
    if restarts is None:
        signals.append(_signal("pods", "Pod restarts (1u)", _UNK, "n.v.t.", rnote))
    else:
        signals.append(_signal("pods", "Pod restarts (1u)",
                               _classify_count(restarts, settings.edge_pod_restarts_warn,
                                               settings.edge_pod_restarts_crit),
                               str(restarts), rnote))

    return {
        "enabled": True,
        "overall": _worst([s["status"] for s in signals]),
        "window_minutes": win,
        "data_view": dv,
        "total_requests": total,
        "generated_at": generated_at,
        "signals": signals,
    }
