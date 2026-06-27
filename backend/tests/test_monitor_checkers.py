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
