import briefing
from monitoring import DashboardSnapshot, Delta, SystemBreakdown


def _snapshot():
    return DashboardSnapshot(
        period_minutes=15, data_view="logs-*", window_start="s", window_end="e",
        total=42, delta=Delta(previous=10, pct_vs_previous=320.0),
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


def test_facts_contain_numbers_and_entities():
    facts = briefing.build_facts(_snapshot())
    assert "42" in facts
    assert "NullPointerException" in facts
    assert "registration-service" in facts
    assert "/api/submit" in facts


def test_system_prompt_has_guardrails():
    low = briefing.SYSTEM.lower()
    assert "only" in low and ("do not invent" in low or "not invent" in low)
    assert "insufficient data" in low


def test_facts_handle_all_clear():
    snap = _snapshot()
    snap.total = 0
    snap.status_level = "ok"
    snap.top_signatures = []
    facts = briefing.build_facts(snap)
    assert '"total_criticals": 0' in facts
