"""The shared dashboard caches that the chat health path reuses. The expensive
snapshot / pipeline-health computations must run at most once per TTL no matter
how many callers (dashboard endpoints + chat) ask for them — this is what stops
a health question from re-running dozens of queries and timing out."""
import dashboard


async def test_get_cached_snapshot_computes_once_then_serves_cache(monkeypatch):
    calls = {"n": 0}

    class _Snap:
        def model_dump(self):
            return {"total": 1, "data_view": "logs-*"}

    async def fake_build(sid, period, dv, *, start=None, end=None):
        calls["n"] += 1
        return _Snap()

    monkeypatch.setattr(dashboard, "build_snapshot", fake_build)
    dashboard._summary_cache.clear()

    a = await dashboard.get_cached_snapshot("sid", 15, "logs-*")
    b = await dashboard.get_cached_snapshot("sid", 15, "logs-*")
    assert a == b == {"total": 1, "data_view": "logs-*"}
    assert calls["n"] == 1  # second call served from cache, not recomputed


async def test_get_cached_health_computes_once_then_serves_cache(monkeypatch):
    calls = {"n": 0}

    async def fake_health(sid, dv):
        calls["n"] += 1
        return {"stuck_count": 3, "stuck": []}

    monkeypatch.setattr(dashboard, "build_pipeline_health", fake_health)
    dashboard._health_cache.clear()

    a = await dashboard.get_cached_health("sid", "logs-*")
    b = await dashboard.get_cached_health("sid", "logs-*")
    assert a == b == {"stuck_count": 3, "stuck": []}
    assert calls["n"] == 1


async def test_get_cached_snapshot_normalizes_bad_period(monkeypatch):
    """An odd period is normalized (so the cache key is stable and valid)."""
    async def fake_build(sid, period, dv, *, start=None, end=None):
        assert period in dashboard.ALLOWED_PERIODS  # normalized before use
        class _S:
            def model_dump(self_inner):
                return {"period_minutes": period}
        return _S()

    monkeypatch.setattr(dashboard, "build_snapshot", fake_build)
    dashboard._summary_cache.clear()
    out = await dashboard.get_cached_snapshot("sid", 999, "logs-*")
    assert out["period_minutes"] == 15  # fell back to the default period
