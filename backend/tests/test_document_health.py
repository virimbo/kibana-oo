from config import settings
import documents as d

def test_health_ok_when_quiet():
    h = d._build_health(events=19, events_prior=18, errors=0, error_pct_change=None, events_pct_change=5.6)
    assert h["level"] == "ok" and h["signals"] == []
    assert "19 documenten" in h["headline"] and "0 fouten" in h["headline"]

def test_health_stalled_is_critical_even_with_zero_errors():
    h = d._build_health(events=0, events_prior=20, errors=0, error_pct_change=None, events_pct_change=-100.0)
    kinds = {s["kind"] for s in h["signals"]}
    assert "stalled" in kinds and h["level"] == "critical"
    assert "verwerking mogelijk gestopt" in h["headline"].lower()

def test_health_error_spike_threshold():
    h = d._build_health(events=50, events_prior=50, errors=settings.doc_error_threshold, error_pct_change=10.0, events_pct_change=0.0)
    assert any(s["kind"] == "error_spike" for s in h["signals"]) and h["level"] == "critical"

def test_health_error_spike_by_pct():
    h = d._build_health(events=50, events_prior=50, errors=3, error_pct_change=150.0, events_pct_change=0.0)
    sig = [s for s in h["signals"] if s["kind"] == "error_spike"][0]
    assert sig["severity"] == "warning" and "+150" in sig["message"]

def test_health_volume_swing_warns():
    h = d._build_health(events=4, events_prior=20, errors=0, error_pct_change=None, events_pct_change=-80.0)
    assert any(s["kind"] == "volume" for s in h["signals"]) and h["level"] == "warning"

def test_health_volume_not_flagged_when_prior_zero():
    h = d._build_health(events=4, events_prior=0, errors=0, error_pct_change=None, events_pct_change=None)
    assert all(s["kind"] != "volume" for s in h["signals"])

def test_every_signal_has_message_and_action():
    h = d._build_health(events=0, events_prior=20, errors=15, error_pct_change=200.0, events_pct_change=-100.0)
    assert h["signals"] and all(s.get("message") and s.get("action") for s in h["signals"])

def test_document_activity_model_has_health_fields():
    from documents import DocumentActivity
    fields = DocumentActivity.model_fields
    assert "health" in fields and "events_prior" in fields and "events_pct_change" in fields

def test_classify_prefers_structured_action_field():
    import documents as d
    assert d.classify_event_action({"event": {"action": "created"}}, "geen keyword hier") == "created"

def test_classify_canonicalises_and_falls_back():
    import documents as d
    assert d.classify_event_action({"event": {"action": "create"}}, "x") == "created"   # canon
    assert d.classify_event_action({}, "document deleted from index") == "deleted"        # keyword
    assert d.classify_event_action({}, "willekeurige logregel") == "other"               # fallback
