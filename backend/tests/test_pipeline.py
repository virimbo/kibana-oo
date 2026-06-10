from datetime import datetime, timezone

import pipeline


# ── service → canonical stage ───────────────────────────────

def test_stage_for_service_maps_real_services():
    assert pipeline.stage_for_service("msvc-doculoket") == "intake"
    assert pipeline.stage_for_service("gateway-service") == "intake"
    assert pipeline.stage_for_service("msvc-documentopslag") == "storage"
    assert pipeline.stage_for_service("service.StorageAccess") == "storage"
    assert pipeline.stage_for_service("antivirus-microservice") == "virus"
    assert pipeline.stage_for_service("verwerkings-orkestratie") == "processing"
    assert pipeline.stage_for_service("msvc-publicatiebeheer") == "publication"
    assert pipeline.stage_for_service("msvc-indexatie") == "indexing"
    assert pipeline.stage_for_service("solr") == "indexing"
    assert pipeline.stage_for_service("msvc-export") == "export"
    assert pipeline.stage_for_service("zoekportaal") == "live"
    assert pipeline.stage_for_service("totally-unknown") is None


# ── message-aware health (the bug we fixed) ─────────────────

def test_classify_message_catches_real_problems():
    assert pipeline.classify_message('404 NOT_FOUND "No static resource overheid/openbaarmakingen/api"')["key"] == "not_found"
    assert pipeline.classify_message("Connection reset by peer")["key"] == "connection_reset"
    assert pipeline.classify_message("Broken pipe")["key"] == "broken_pipe"
    assert pipeline.classify_message("NullPointerException at ...")["severity"] == "error"
    assert pipeline.classify_message("null") is None       # bare null is not a problem
    assert pipeline.classify_message("stored ok") is None


def test_event_severity_reads_message_not_just_level():
    # INFO-level lines that are clearly problems must NOT be "ok"
    assert pipeline.event_severity("INFO", "Connection reset by peer") == "warning"
    assert pipeline.event_severity("INFO", "404 NOT_FOUND ...") == "warning"
    assert pipeline.event_severity("ERROR", "boom") == "error"
    assert pipeline.event_severity("INFO", "all good") == "ok"
    assert pipeline.event_severity("WARN", "heads up") == "warning"


# ── the user's exact trace: gateway 404 + documentopslag reset ──

def _ev(ts, service, message):
    return {"timestamp": ts, "service": service, "message": message,
            "severity": pipeline.event_severity("INFO", message)}


SCENARIO = [
    _ev("2026-06-09T12:15:00+00:00", "gateway-service", '404 NOT_FOUND "No static resource ...openbaarmakingen/api"'),
    _ev("2026-06-09T13:01:06+00:00", "msvc-documentopslag", "Connection reset by peer"),
    _ev("2026-06-09T17:12:14+00:00", "msvc-documentopslag", "Broken pipe"),
]


def test_pipeline_view_is_honest_and_maps_to_architecture():
    now = datetime(2026, 6, 9, 23, 0, tzinfo=timezone.utc)  # hours after last event
    view = pipeline.build_pipeline_view(SCENARIO, now=now)

    stages = {s["key"]: s for s in view["stages"]}
    assert len(view["stages"]) == 8                      # all canonical stages shown

    # reached stages are honestly flagged as warnings (NOT green "ok")
    assert stages["intake"]["reached"] and stages["intake"]["status"] == "warning"
    assert stages["storage"]["reached"] and stages["storage"]["status"] == "warning"
    # later stages were never reached
    assert stages["publication"]["status"] == "missing"
    assert stages["live"]["status"] == "missing"
    assert stages["live"]["reached"] is False

    # the verdict is honest: not the old "no errors"
    assert view["furthest_stage"] == "Storage"
    assert view["verdict"] == "stuck"        # not terminal + no activity for hours
    assert view["stuck"] is True
    # problems surfaced with plain keys
    keys = {p["key"] for p in view["problems_total"]}
    assert "connection_reset" in keys and "not_found" in keys


def test_pipeline_view_healthy_complete():
    base = "2026-06-09T12:00:0"
    evs = [_ev(f"{base}{i}+00:00", svc, "ok") for i, svc in enumerate(
        ["msvc-doculoket", "msvc-documentopslag", "antivirus", "verwerkings-orkestratie",
         "msvc-publicatiebeheer", "msvc-indexatie", "msvc-export", "zoekportaal"])]
    view = pipeline.build_pipeline_view(evs, now=datetime(2026, 6, 9, 12, 5, tzinfo=timezone.utc))
    assert view["verdict"] == "healthy"
    assert view["reached_count"] == 8
    assert view["stages"][-1]["reached"] is True
