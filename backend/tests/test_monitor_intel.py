import monitor_intel as intel

def test_flap_requires_consecutive_reds():
    assert intel.is_flapping_clear(["down", "ok"], threshold=2) is True    # not enough reds → suppress
    assert intel.is_flapping_clear(["down", "down"], threshold=2) is False # 2 reds → real, do alert

def test_effective_threshold_uses_baseline():
    assert intel.effective_threshold(static=10, baseline_min=2, k=3) == 10
    assert intel.effective_threshold(static=10, baseline_min=5, k=3) == 15

def test_correlate_groups_by_env_and_service():
    reds = [
        {"id": 1, "environment": "prod", "config": {"service": "repo"}, "type": "http"},
        {"id": 2, "environment": "prod", "config": {"service": "repo"}, "type": "log-freshness"},
        {"id": 3, "environment": "acc", "config": {"service": "x"}, "type": "http"},
    ]
    groups = intel.correlate(reds)
    assert any(len(g["targets"]) == 2 and g["environment"] == "prod" for g in groups)

def test_coverage_score():
    targets = [
        {"environment": "prod", "type": "log-freshness", "_status": "ok"},
        {"environment": "prod", "type": "jaeger-traces", "_status": "ok"},
        {"environment": "prod", "type": "prometheus-query", "_status": "down"},
    ]
    cov = intel.coverage(targets)["prod"]
    assert cov["score"] == round(2/3, 2) and cov["metrics"] == "down"

def test_ai_rootcause_is_best_effort(monkeypatch):
    import monitor_intel as intel, asyncio
    async def boom(*a, **k): raise RuntimeError("ai off")
    monkeypatch.setattr(intel, "_llm_summarize", boom)
    grp = {"environment": "prod", "service": "repo",
           "targets": [{"name": "x", "type": "http", "_status": "down"}]}
    assert asyncio.run(intel.ai_rootcause(grp, sid="s")) is None

def test_ai_rootcause_none_without_sid():
    import monitor_intel as intel, asyncio
    grp = {"environment": "prod", "service": "repo", "targets": []}
    assert asyncio.run(intel.ai_rootcause(grp, sid=None)) is None

def test_ai_rootcause_returns_text(monkeypatch):
    import monitor_intel as intel, asyncio
    async def ok(prompt, sid): return "  Waarschijnlijk de Gateway-route.  "
    monkeypatch.setattr(intel, "_llm_summarize", ok)
    grp = {"environment": "prod", "service": "repo",
           "targets": [{"name": "x", "type": "http", "_status": "down"}]}
    assert asyncio.run(intel.ai_rootcause(grp, sid="s")) == "Waarschijnlijk de Gateway-route."
