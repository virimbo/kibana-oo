"""Tests for the PROD edge/ingress HTTP health signals (edge_health).

Live ES + Prometheus are mocked; these cover the classification logic and the
aggregation plumbing (status counts, 5xx ratio, gateway/timeout counts, latency
p95, graceful degradation, pod-restart best-effort).
"""
import edge_health as eh
from config import settings


def _es(status_counts: dict, p95_seconds=None):
    return {"aggregations": {
        "by_status": {"buckets": [{"key": str(k), "doc_count": v} for k, v in status_counts.items()]},
        "lat": {"values": {"50.0": None, "95.0": p95_seconds, "99.0": None}},
    }}


def _patch_es(monkeypatch, resp=None, raises=False):
    async def fake(sid, index, body):
        if raises:
            raise RuntimeError("es down")
        return resp
    monkeypatch.setattr(eh.elastic, "_es_search", fake)


def _patch_pods(monkeypatch, value, note=""):
    async def fake():
        return (value, note)
    monkeypatch.setattr(eh, "_pod_restarts", fake)


def _sig(result, key):
    return next(s for s in result["signals"] if s["key"] == key)


async def test_disabled_short_circuits(monkeypatch):
    monkeypatch.setattr(settings, "edge_enabled", False)
    assert await eh.build_edge_health("sid") == {"enabled": False}


async def test_healthy_is_ok(monkeypatch):
    _patch_es(monkeypatch, _es({200: 1000, 500: 2}, 0.2))
    _patch_pods(monkeypatch, 0)
    r = await eh.build_edge_health("sid")
    assert r["overall"] == "ok"
    assert _sig(r, "http5xx")["status"] == "ok"
    assert _sig(r, "latency")["metric"] == "200 ms"
    assert r["total_requests"] == 1002


async def test_high_5xx_ratio_is_critical(monkeypatch):
    _patch_es(monkeypatch, _es({200: 900, 500: 100}, 0.1))
    _patch_pods(monkeypatch, 0)
    r = await eh.build_edge_health("sid")
    assert _sig(r, "http5xx")["status"] == "critical"   # 10% >= 5%
    assert r["overall"] == "critical"


async def test_gateway_errors_counted(monkeypatch):
    _patch_es(monkeypatch, _es({200: 1000, 502: 25, 504: 3}, 0.1))
    _patch_pods(monkeypatch, 0)
    r = await eh.build_edge_health("sid")
    assert _sig(r, "gateway")["metric"] == "28"          # 502+503+504
    assert _sig(r, "gateway")["status"] == "critical"    # 28 >= 20
    assert _sig(r, "timeouts")["metric"] == "3"          # 504 only


async def test_low_traffic_suppresses_ratio(monkeypatch):
    _patch_es(monkeypatch, _es({200: 10, 500: 5}, 0.1))  # 33% but total 15 < 50
    _patch_pods(monkeypatch, 0)
    r = await eh.build_edge_health("sid")
    assert _sig(r, "http5xx")["status"] == "ok"
    assert "te weinig verkeer" in _sig(r, "http5xx")["metric"]


async def test_latency_thresholds(monkeypatch):
    _patch_es(monkeypatch, _es({200: 1000}, 4.0))        # p95 = 4000 ms
    _patch_pods(monkeypatch, 0)
    r = await eh.build_edge_health("sid")
    assert _sig(r, "latency")["status"] == "critical"
    assert r["overall"] == "critical"


async def test_latency_non_numeric_is_unknown(monkeypatch):
    _patch_es(monkeypatch, _es({200: 1000}, None))       # no numeric p95
    _patch_pods(monkeypatch, 0)
    r = await eh.build_edge_health("sid")
    assert _sig(r, "latency")["status"] == "unknown"


async def test_es_failure_degrades_to_unknown(monkeypatch):
    _patch_es(monkeypatch, raises=True)
    _patch_pods(monkeypatch, None, "Prometheus niet geconfigureerd")
    r = await eh.build_edge_health("sid")
    for key in ("http5xx", "gateway", "timeouts", "latency"):
        assert _sig(r, key)["status"] == "unknown"
    assert r["overall"] == "unknown"          # all signals blind → overall unknown


async def test_pod_restarts_unavailable(monkeypatch):
    _patch_es(monkeypatch, _es({200: 1000}, 0.1))
    _patch_pods(monkeypatch, None, "Prometheus niet geconfigureerd")
    r = await eh.build_edge_health("sid")
    assert _sig(r, "pods")["status"] == "unknown"
    assert _sig(r, "pods")["metric"] == "n.v.t."
    assert r["overall"] == "ok"   # one unavailable optional signal must not grey out the card


async def test_pod_restarts_critical(monkeypatch):
    _patch_es(monkeypatch, _es({200: 1000}, 0.1))
    _patch_pods(monkeypatch, 9)
    r = await eh.build_edge_health("sid")
    assert _sig(r, "pods")["status"] == "critical"       # 9 >= 5
    assert r["overall"] == "critical"


def test_status_counts_tolerates_str_and_int_keys():
    buckets = [{"key": "200", "doc_count": 3}, {"key": 500, "doc_count": 2}, {"key": "x", "doc_count": 9}]
    assert eh._status_counts(buckets) == {200: 3, 500: 2}  # non-numeric 'x' skipped
