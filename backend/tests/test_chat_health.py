"""Health-question routing (Fix C) and the deterministic non-LLM fallback (Fix B).

A question like "which services are failing/unhealthy right now" must be answered
from the same ground-truth data the dashboard uses — so chat agrees with the
header's "N stuck" badge — and the chat must never dead-end on an empty answer."""
import main


def test_is_health_question_detects_failure_phrasing():
    assert main._is_health_question("Which services are failing, erroring or unhealthy right now?")
    assert main._is_health_question("List the worst first with what's going wrong.")
    assert main._is_health_question("are there any errors in the last hour?")
    assert main._is_health_question("show me stuck documents")
    assert main._is_health_question("is anything degraded or down?")


def test_is_health_question_false_for_neutral_questions():
    assert not main._is_health_question("show me recent log activity")
    assert not main._is_health_question("what happened in the last 30 minutes?")
    assert not main._is_health_question("")


def test_build_health_context_lists_worst_services_first():
    snap = {
        "data_view": "logs-*", "period_minutes": 15, "status_level": "critical",
        "total": 120, "delta": {"previous": 80, "pct_vs_previous": 50.0},
        "systems": [{"label": "Plooi", "data_view": "x", "count": 100, "available": True}],
        "affected_services": [{"name": "indexer", "count": 70}, {"name": "export", "count": 12}],
        "top_signatures": [{"signature": "connection reset by peer", "count": 40}],
        "status_codes": [{"code": 500, "count": 33}],
        "failing_urls": [{"url": "/api/x", "count": 9}],
    }
    health = {
        "lookback_minutes": 1440, "stuck_count": 55, "documents_scanned": 900,
        "total_errors": 70, "total_warnings": 5,
        "stage_health": [
            {"name": "Indexing", "key": "indexing", "errors": 40, "warnings": 2, "events": 100},
            {"name": "Intake", "key": "intake", "errors": 0, "warnings": 0, "events": 50},
        ],
        "stuck": [{"verdict": "problem", "title": "Doc A", "stuck_stage": "Indexing",
                   "headline": "failed to index"}],
    }
    ctx = main._build_health_context(snap, health)
    assert "indexer: 70" in ctx
    assert ctx.index("indexer") < ctx.index("export")   # worst-affected first
    assert "CRITICAL" in ctx
    assert "55" in ctx                                   # stuck count surfaced
    assert "Indexing: 40 errors" in ctx
    assert "Doc A" in ctx
    # A perfectly healthy stage is omitted from the "stages with trouble" list.
    assert "Intake: 0 errors" not in ctx


def test_build_health_context_empty_when_no_data():
    assert main._build_health_context(None, None) == ""


def test_build_health_context_reports_healthy_when_all_zero():
    snap = {
        "data_view": "logs-*", "period_minutes": 15, "status_level": "ok", "total": 0,
        "delta": {}, "systems": [], "affected_services": [], "top_signatures": [],
        "status_codes": [], "failing_urls": [],
    }
    ctx = main._build_health_context(snap, None)
    assert "OK" in ctx
    assert "healthy" in ctx.lower()


def test_summarize_from_sources_surfaces_errors():
    sources = [
        {"timestamp": "T1", "level": "error", "host": "h1", "message": "boom went the index"},
        {"timestamp": "T2", "level": "info", "host": "h2", "message": "all good"},
    ]
    out = main._summarize_from_sources(sources)
    assert "2" in out and "1" in out                     # 2 events, 1 at error level
    assert "boom went the index" in out


def test_summarize_from_sources_handles_no_data():
    out = main._summarize_from_sources([])
    assert "try again" in out.lower()


def test_render_health_facts_is_instant_and_worst_first():
    snap = {
        "data_view": "logs-*", "period_minutes": 15, "status_level": "critical",
        "total": 120, "delta": {"previous": 80, "pct_vs_previous": 50.0},
        "affected_services": [{"name": "indexer", "count": 70}, {"name": "export", "count": 12}],
        "top_signatures": [{"signature": "connection reset by peer", "count": 40}],
        "status_codes": [{"code": 500, "count": 33}, {"code": 404, "count": 9}],
        "failing_urls": [],
    }
    health = {
        "stuck_count": 55, "total_errors": 70, "total_warnings": 5,
        "stage_health": [{"name": "Indexing", "errors": 40, "warnings": 2, "events": 100}],
    }
    out = main._render_health_facts(snap, health)
    assert "CRITICAL" in out
    assert out.index("indexer") < out.index("export")   # worst-affected first
    assert "500×33" in out                                # 5xx surfaced
    assert "404" not in out.split("5xx")[1].split("\n")[0]  # only 5xx on that line
    assert "55 document" in out                            # stuck count
    assert "Indexing: 40 errors" in out


def test_render_health_facts_empty_without_data():
    assert main._render_health_facts(None, None) == ""


def test_health_analysis_system_enforces_grounding_and_actions():
    """The analyst persona must (a) give actions, not restate facts, and (b) be
    explicitly grounded — the trust guarantee."""
    s = main.HEALTH_ANALYSIS_SYSTEM.lower()
    # part labels are Dutch (chat answers in Nederlands); descriptions stay English
    assert "waarschijnlijke oorzaak" in s and "aanbevolen acties" in s
    assert "never invent" in s          # no fabricated services/numbers/causes
    assert "do not repeat" in s         # don't re-narrate the facts preamble
