"""Burst control (anti-alert-storm): when a single scan would dispatch many NEW
alerts of the SAME category, send ONE consolidated summary instead of N individual
messages — WITHOUT changing dedup semantics (state MUST still be recorded for
every item so none re-alert next scan).

No real network/monitors — items are injected via a patched _collect, and the
dispatch calls are counted with monkeypatched spies.
"""
import asyncio

import pytest

import alerts
import alerts_mattermost
import alerts_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "burst.db"))
    monkeypatch.setattr(settings, "alerts_cooldown_minutes", 60)
    monkeypatch.setattr(settings, "alerts_default_threshold", "warn")
    monkeypatch.setattr(settings, "alerts_recipient_seed", "ops@example.com")
    alerts_store.ensure_seeded()
    return alerts_store


def _docs(n: int) -> list[dict]:
    """n distinct NEW stuck-document (category 'document') critical items."""
    out = []
    for i in range(n):
        item = alerts._item("document", "PROD", f"doc-{i}", "critical",
                            status="vastgelopen bij verwerking")
        item["doc_id"] = f"doc-{i}"
        item["link"] = f"https://open.overheid.nl/details/doc-{i}"
        item["stage"] = "verwerking"
        out.append(item)
    return out


def _spy(monkeypatch):
    """Patch dispatch fns to counters; enable alerts. Returns (individual, summary)."""
    from config import settings
    monkeypatch.setattr(settings, "alerts_enabled", True)
    individual: list[str] = []
    summary: list[tuple] = []

    async def _fake_dispatch(item, kind, prev_severity, recipients, mention="none"):
        individual.append(item["card_id"])

    async def _fake_summary(category, count, env, mention, recipients):
        summary.append((category, count, env, mention))

    monkeypatch.setattr(alerts, "_dispatch", _fake_dispatch)
    monkeypatch.setattr(alerts, "_dispatch_summary", _fake_summary)
    return individual, summary


def test_group_at_or_below_cap_dispatches_individually(store, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "alert_burst_max", 5)
    individual, summary = _spy(monkeypatch)
    monkeypatch.setattr(alerts, "_collect", lambda *a, **k: _docs(4))

    res = asyncio.run(alerts.scan())
    assert len(individual) == 4          # each dispatched individually
    assert summary == []                 # no summary
    assert res["sent"] == 4


def test_group_above_cap_dispatches_one_summary(store, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "alert_burst_max", 5)
    individual, summary = _spy(monkeypatch)
    monkeypatch.setattr(alerts, "_collect", lambda *a, **k: _docs(26))

    res = asyncio.run(alerts.scan())
    assert individual == []               # ZERO individual dispatches
    assert len(summary) == 1              # exactly ONE summary
    cat, count, env, mention = summary[0]
    assert cat == "document" and count == 26
    assert res["sent"] == 1


def test_storm_still_records_state_for_every_item(store, monkeypatch):
    """Dedup preserved: state recorded for ALL items even when summarized, so none
    re-alert on the next scan."""
    from config import settings
    monkeypatch.setattr(settings, "alert_burst_max", 5)
    set_state_calls: list[str] = []
    real_set_state = alerts_store.set_state

    def _spy_set_state(card_id, *a, **k):
        set_state_calls.append(card_id)
        return real_set_state(card_id, *a, **k)

    monkeypatch.setattr(alerts_store, "set_state", _spy_set_state)
    _spy(monkeypatch)
    monkeypatch.setattr(alerts, "_collect", lambda *a, **k: _docs(26))

    asyncio.run(alerts.scan())
    for i in range(26):
        assert f"document:PROD:doc-{i}" in set_state_calls
    # Second scan: every item already has state → nothing new dispatched
    individual2, summary2 = _spy(monkeypatch)
    monkeypatch.setattr(alerts, "_collect", lambda *a, **k: _docs(26))
    res2 = asyncio.run(alerts.scan())
    assert individual2 == [] and summary2 == []
    assert res2["sent"] == 0


def test_burst_max_zero_disables_cap(store, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "alert_burst_max", 0)
    individual, summary = _spy(monkeypatch)
    monkeypatch.setattr(alerts, "_collect", lambda *a, **k: _docs(26))

    res = asyncio.run(alerts.scan())
    assert len(individual) == 26          # all individual, cap disabled
    assert summary == []
    assert res["sent"] == 26


def test_summary_payload_contains_count_label_and_single_mention():
    p = alerts_mattermost.summary_payload("document", 26, "PROD",
                                          "http://dash/", "FB-OO:Anton",
                                          mention="here")
    # single top-level mention token (never one-per-item)
    assert p.get("text") == "@here"
    assert p["username"] == "FB-OO:Anton"
    a = p["attachments"][0]
    blob = a["title"] + " " + a["text"]
    assert "26" in blob
    # category label ("Vastgelopen document") present
    assert "Vastgelopen document" in blob or "vastgelopen document" in blob.lower()
    assert a["title_link"] == "http://dash/"


def test_summary_payload_no_mention_when_none():
    p = alerts_mattermost.summary_payload("document", 10, "PROD",
                                          "http://dash/", "S", mention="none")
    assert "text" not in p
