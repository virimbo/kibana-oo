import asyncio, monitor_checkers as mc

class _Resp:
    def __init__(self, status): self.status_code = status
class _Client:
    def __init__(self, status=None, exc=None): self._s, self._e = status, exc
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def get(self, url, **k):
        if self._e: raise self._e
        return _Resp(self._s)

def test_http_checker_classifies(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Client(status=200))
    t = {"type": "http", "config": {"url": "http://x", "expected_status": [200]}}
    r = asyncio.run(mc.run_check(t, None))
    assert r["status"] == "ok"

def test_http_checker_5xx_is_down(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Client(status=503))
    t = {"type": "http", "config": {"url": "http://x", "expected_status": [200]}}
    assert asyncio.run(mc.run_check(t, None))["status"] == "down"

def test_http_checker_connfail_is_unreachable(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Client(exc=httpx.ConnectError("x")))
    t = {"type": "http", "config": {"url": "http://x"}}
    assert asyncio.run(mc.run_check(t, None))["status"] == "unreachable"

def test_types_schema_lists_http_fields():
    schema = mc.types_schema()
    assert "http" in schema and any(f["name"] == "url" for f in schema["http"]["fields"])

def test_log_freshness_stale(monkeypatch):
    import monitor_checkers as mc, asyncio
    from datetime import datetime, timezone, timedelta
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    async def fake(index, field, sid): return old
    monkeypatch.setattr(mc, "_es_max_timestamp", fake)
    t = {"type": "log-freshness", "config": {"index": "logs-*", "max_age_minutes": 10}}
    assert asyncio.run(mc.run_check(t, None))["status"] == "stale"

def test_log_freshness_ok(monkeypatch):
    import monitor_checkers as mc, asyncio
    from datetime import datetime, timezone
    async def fake(index, field, sid): return datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(mc, "_es_max_timestamp", fake)
    t = {"type": "log-freshness", "config": {"index": "logs-*", "max_age_minutes": 10}}
    assert asyncio.run(mc.run_check(t, None))["status"] == "ok"

def test_log_freshness_no_data_is_unreachable(monkeypatch):
    import monitor_checkers as mc, asyncio
    async def fake(index, field, sid): return None
    monkeypatch.setattr(mc, "_es_max_timestamp", fake)
    t = {"type": "log-freshness", "config": {"index": "logs-*", "max_age_minutes": 10}}
    assert asyncio.run(mc.run_check(t, None))["status"] == "unreachable"

def test_jaeger_traces_stale(monkeypatch):
    import httpx, asyncio, monitor_checkers as mc
    class R:
        status_code = 200
        def json(self): return {"data": []}
    class C:
        async def __aenter__(s): return s
        async def __aexit__(s, *a): return False
        async def get(s, u, **k): return R()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: C())
    t = {"type": "jaeger-traces", "config": {"service": "repo", "min_traces": 1}}
    conn = {"base_url": "http://jaeger:16686", "secret_ref": None}
    assert asyncio.run(mc.run_check(t, conn))["status"] == "stale"

def test_jaeger_traces_ok(monkeypatch):
    import httpx, asyncio, monitor_checkers as mc
    class R:
        status_code = 200
        def json(self): return {"data": [{"traceID": "a"}, {"traceID": "b"}]}
    class C:
        async def __aenter__(s): return s
        async def __aexit__(s, *a): return False
        async def get(s, u, **k): return R()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: C())
    t = {"type": "jaeger-traces", "config": {"service": "repo", "min_traces": 1}}
    conn = {"base_url": "http://jaeger:16686", "secret_ref": None}
    assert asyncio.run(mc.run_check(t, conn))["status"] == "ok"

def test_prometheus_query_ok(monkeypatch):
    import httpx, asyncio, monitor_checkers as mc
    class R:
        status_code = 200
        def json(self): return {"data": {"result": [{"value": [0, "1"]}]}}
    class C:
        async def __aenter__(s): return s
        async def __aexit__(s, *a): return False
        async def get(s, u, **k): return R()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: C())
    t = {"type": "prometheus-query", "config": {"query": "up", "op": ">", "threshold": 0}}
    conn = {"base_url": "http://prom:9090", "secret_ref": None}
    assert asyncio.run(mc.run_check(t, conn))["status"] == "ok"

def test_prometheus_query_empty_is_stale(monkeypatch):
    import httpx, asyncio, monitor_checkers as mc
    class R:
        status_code = 200
        def json(self): return {"data": {"result": []}}
    class C:
        async def __aenter__(s): return s
        async def __aexit__(s, *a): return False
        async def get(s, u, **k): return R()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: C())
    t = {"type": "prometheus-query", "config": {"query": "up", "op": "exists"}}
    conn = {"base_url": "http://prom:9090", "secret_ref": None}
    assert asyncio.run(mc.run_check(t, conn))["status"] == "stale"

def test_jaeger_discover(monkeypatch):
    import httpx, asyncio, monitor_checkers as mc
    class R:
        status_code = 200
        def json(self): return {"data": ["repo", "search"]}
    class C:
        async def __aenter__(s): return s
        async def __aexit__(s, *a): return False
        async def get(s, u, **k): return R()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: C())
    sug = asyncio.run(mc.CHECKERS["jaeger-traces"]["discover"]({"id": 1, "base_url": "http://j", "secret_ref": None}))
    services = [s["config"]["service"] for s in sug]
    assert "repo" in services and "search" in services
    assert sug[0]["type"] == "jaeger-traces" and sug[0]["connection_id"] == 1

def test_prometheus_discover(monkeypatch):
    import httpx, asyncio, monitor_checkers as mc
    class R:
        status_code = 200
        def json(self): return {"data": {"activeTargets": [
            {"labels": {"job": "gateway"}}, {"labels": {"job": "repo"}}]}}
    class C:
        async def __aenter__(s): return s
        async def __aexit__(s, *a): return False
        async def get(s, u, **k): return R()
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: C())
    sug = asyncio.run(mc.CHECKERS["prometheus-query"]["discover"]({"id": 2, "base_url": "http://p", "secret_ref": None}))
    jobs = [s["name"] for s in sug]
    assert any("gateway" in j for j in jobs)
    assert sug[0]["type"] == "prometheus-query" and sug[0]["connection_id"] == 2
