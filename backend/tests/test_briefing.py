import briefing
from monitoring import DashboardSnapshot, Delta, SystemBreakdown


def _snapshot():
    return DashboardSnapshot(
        date="2026-06-08", window_start="s", window_end="e",
        total=42, delta=Delta(previous=10, avg_7d=10.0, pct_vs_previous=320.0, pct_vs_avg=320.0),
        status_level="degraded",
        systems=[SystemBreakdown(data_view="ds-prod5-koop-plooi*", label="KOOP Plooi (prod5)", count=42),
                 SystemBreakdown(data_view="ds-prod5-koop-sp", label="KOOP SP (prod5)", count=0)],
        timeseries=[{"timestamp": "2026-06-08T09:00:00+02:00", "count": 30}],
        top_signatures=[{"signature": "NullPointerException", "count": 30,
                         "first_seen": "2026-06-08T09:12:00Z", "last_seen": "2026-06-08T09:40:00Z"}],
        affected_services=[{"name": "registration-service", "count": 30}],
        status_codes=[{"code": 500, "count": 8}], failing_urls=[{"url": "/api/submit", "count": 8}],
        partial=False,
    )


def test_prompt_contains_facts_and_guardrails():
    prompt = briefing.build_prompt(_snapshot())
    assert "42" in prompt
    assert "NullPointerException" in prompt
    assert "registration-service" in prompt
    assert "/api/submit" in prompt
    low = prompt.lower()
    assert "only" in low and ("do not invent" in low or "not invent" in low)
    assert "insufficient data" in low


def test_prompt_handles_all_clear():
    snap = _snapshot()
    snap.total = 0
    snap.status_level = "ok"
    snap.top_signatures = []
    prompt = briefing.build_prompt(snap)
    assert "0" in prompt
