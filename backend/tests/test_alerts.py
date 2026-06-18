"""Unified alerting: env normalization, monitor→item normalization, toggle filter,
the cooldown/dedup/recovery decision machine, email rendering, and the API guards.
No real network or monitors — snapshots are passed in directly."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

import alerts


def test_norm_env_maps_test_variants_to_tst():
    assert alerts._norm_env("TEST") == "TST"
    assert alerts._norm_env("tst") == "TST"
    assert alerts._norm_env("Acceptance") == "ACC"
    assert alerts._norm_env("acc") == "ACC"
    assert alerts._norm_env("PROD") == "PROD"
    assert alerts._norm_env("anything") == "ANYTHING"


def test_env_from_host():
    assert alerts._env_from_host("open-acc.overheid.nl") == "ACC"
    assert alerts._env_from_host("gateway-zoek.koop-plooi-tst.test5.s15m.nl") == "TST"
    assert alerts._env_from_host("open.overheid.nl") == "PROD"


def test_normalize_uptime_snapshot():
    snap = {
        "enabled": True,
        "groups": [
            {"env": "PROD", "sites": [
                {"name": "open.overheid.nl", "env": "PROD", "state": "up",
                 "http_status": 200, "error": None},
            ]},
            {"env": "ACC", "sites": [
                {"name": "open-acc.overheid.nl", "env": "ACC", "state": "down",
                 "http_status": 404, "error": None},
            ]},
        ],
    }
    items = alerts._normalize_uptime(snap)
    by_name = {i["name"]: i for i in items}
    assert by_name["open.overheid.nl"]["severity"] == "ok"
    down = by_name["open-acc.overheid.nl"]
    assert down["severity"] == "critical"
    assert down["category"] == "environment"
    assert down["env"] == "ACC"
    assert down["card_id"] == "environment:ACC:open-acc.overheid.nl"


def test_normalize_dlq_snapshot():
    snap = {"configured": True, "dlqs": [
        {"name": "antivirus.dlq", "depth": 0, "severity": "ok"},
        {"name": "export.dlq", "depth": 250, "severity": "critical",
         "source_consumers": 0},
    ]}
    items = alerts._normalize_dlq(snap)
    by_name = {i["name"]: i for i in items}
    assert by_name["antivirus.dlq"]["severity"] == "ok"
    crit = by_name["export.dlq"]
    assert crit["severity"] == "critical"
    assert crit["category"] == "dlq"
    assert crit["env"] == "PROD"


def test_normalize_cert_list():
    class FakeCert:
        def __init__(self, host, grade, days):
            self.host, self.grade, self.days_remaining = host, grade, days
            self.status = "ok"
    certs = [
        FakeCert("open.overheid.nl", "OK", 50),
        FakeCert("open-acc.overheid.nl", "CRITICAL", 5),
        FakeCert("gateway.koop-plooi-tst.test5.s15m.nl", "WARN", 20),
    ]
    items = alerts._normalize_cert(certs)
    by_name = {i["name"]: i for i in items}
    assert by_name["open.overheid.nl"]["severity"] == "ok"
    assert by_name["open-acc.overheid.nl"]["severity"] == "critical"
    assert by_name["open-acc.overheid.nl"]["env"] == "ACC"
    assert by_name["gateway.koop-plooi-tst.test5.s15m.nl"]["severity"] == "warn"
    assert by_name["gateway.koop-plooi-tst.test5.s15m.nl"]["env"] == "TST"


import alerts_store


@pytest.fixture()
def store(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings, "alerts_cooldown_minutes", 60)
    monkeypatch.setattr(settings, "alerts_default_threshold", "critical")
    monkeypatch.setattr(settings, "alerts_recipient_seed", "ops@example.com")
    alerts_store.ensure_seeded()
    return alerts_store


def test_config_defaults_and_seed(store):
    cfg = store.get_config()
    assert cfg["global_enabled"] is True
    assert cfg["cooldown_minutes"] == 60
    assert cfg["severity_threshold"] == "critical"
    assert cfg["recipients"] == ["ops@example.com"]


def test_toggle_absent_is_on_and_can_disable(store):
    assert store.is_enabled("category", "dlq") is True       # absent = on
    store.set_toggle("category", "dlq", False, actor="admin@x")
    assert store.is_enabled("category", "dlq") is False
    store.set_toggle("category", "dlq", True, actor="admin@x")
    assert store.is_enabled("category", "dlq") is True


def test_history_and_audit_written(store):
    store.record_history(card_id="dlq:PROD:export.dlq", category="dlq", env="PROD",
                         kind="new", severity="critical", prev_severity="ok",
                         recipients=["ops@example.com"], delivered=1, detail="x")
    rows = store.list_history(limit=10)
    assert len(rows) == 1 and rows[0]["kind"] == "new"
    store.record_audit("admin@x", "set_toggle", "category:dlq", "disabled")
    assert store.list_audit(limit=10)[0]["action"] == "set_toggle"


def test_eligible_respects_threshold_and_hierarchy(store):
    crit = alerts._item("dlq", "PROD", "export.dlq", "critical")
    warn = alerts._item("environment", "PROD", "x", "warn")
    # threshold = critical → warn not eligible, critical eligible
    assert alerts._eligible(crit, threshold="critical") is True
    assert alerts._eligible(warn, threshold="critical") is False
    # lower threshold to warn → warn becomes eligible
    assert alerts._eligible(warn, threshold="warn") is True
    # disabling the category suppresses even a critical
    store.set_toggle("category", "dlq", False, actor="a")
    assert alerts._eligible(crit, threshold="critical") is False


import alerts_email


def test_render_email_contains_required_fields():
    item = alerts._item("environment", "ACC", "open-acc.overheid.nl", "critical",
                        status="HTTP 404 / DOWN")
    subject, html, text = alerts_email.render(item, kind="new", prev_severity="ok",
                                              dashboard_url="https://dash.example/")
    assert "[ACC]" in subject and "open-acc.overheid.nl" in subject
    for needle in ["CRITICAL", "ACC", "open-acc.overheid.nl", "HTTP 404 / DOWN",
                   "ok", "New alert", "https://dash.example/"]:
        assert needle in text
    # HTML escapes the status (no raw injection)
    evil = alerts._item("dlq", "PROD", "x", "critical", status="<script>")
    _, ehtml, _ = alerts_email.render(evil, kind="new", prev_severity="ok",
                                      dashboard_url="https://d/")
    assert "<script>" not in ehtml and "&lt;script&gt;" in ehtml


def test_render_recovery_kind():
    item = alerts._item("certificate", "PROD", "open.overheid.nl", "ok",
                        status="grade OK")
    subject, _, text = alerts_email.render(item, kind="recovery", prev_severity="critical",
                                           dashboard_url="https://d/")
    assert "recovery" in text.lower() or "hersteld" in text.lower()
    assert "✅" in subject or "recovery" in subject.lower()


def test_decide_new_then_cooldown_then_repeat():
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    crit = alerts._item("dlq", "PROD", "export.dlq", "critical")
    # No prior state, red → NEW
    kind, nxt = alerts._decide(crit, prev=None, cooldown_min=60, now=now)
    assert kind == "new" and nxt["severity"] == "critical" and nxt["red_since"]

    # 30 min later, same severity, within cooldown → suppressed
    prev = nxt
    kind2, _ = alerts._decide(crit, prev=prev, cooldown_min=60,
                              now=now + timedelta(minutes=30))
    assert kind2 is None

    # 61 min after last send, still red → REPEATED
    kind3, _ = alerts._decide(crit, prev=prev, cooldown_min=60,
                              now=now + timedelta(minutes=61))
    assert kind3 == "repeated"


def test_decide_escalation_bypasses_cooldown():
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    warn = alerts._item("dlq", "PROD", "export.dlq", "warn")
    _, prev = alerts._decide(warn, prev=None, cooldown_min=60, now=now)
    crit = alerts._item("dlq", "PROD", "export.dlq", "critical")
    kind, _ = alerts._decide(crit, prev=prev, cooldown_min=60,
                             now=now + timedelta(minutes=1))
    assert kind == "escalation"


def test_decide_recovery_and_rearm():
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    crit = alerts._item("environment", "ACC", "x", "critical")
    _, prev = alerts._decide(crit, prev=None, cooldown_min=60, now=now)
    ok = alerts._item("environment", "ACC", "x", "ok")
    kind, nxt = alerts._decide(ok, prev=prev, cooldown_min=60,
                               now=now + timedelta(minutes=5))
    assert kind == "recovery" and nxt["red_since"] is None and nxt["severity"] == "ok"
    # After recovery, a new red fires NEW again
    kind2, _ = alerts._decide(crit, prev=nxt, cooldown_min=60,
                              now=now + timedelta(minutes=10))
    assert kind2 == "new"


def test_decide_ok_with_no_prior_is_silent():
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    ok = alerts._item("dlq", "PROD", "x", "ok")
    kind, nxt = alerts._decide(ok, prev=None, cooldown_min=60, now=now)
    assert kind is None and nxt is None


async def _noop_webhook(*a, **k):
    return True


def test_scan_sends_red_not_green_and_records(store, monkeypatch):
    from config import settings
    import alerts_send
    monkeypatch.setattr(settings, "alerts_enabled", True)
    sent = []
    monkeypatch.setattr(alerts_send, "send_email_to",
                        lambda recips, subject, html, text: sent.append(subject) or True)
    monkeypatch.setattr(alerts.notify, "send_webhook", _noop_webhook)
    monkeypatch.setattr(alerts, "_collect", lambda: alerts._normalize_uptime(
        {"enabled": True, "groups": [{"env": "ACC", "sites": [
            {"name": "open-acc.overheid.nl", "env": "ACC", "state": "down",
             "http_status": 404}]}]}) + alerts._normalize_dlq(
        {"configured": True, "dlqs": [
            {"name": "antivirus.dlq", "depth": 0, "severity": "ok"}]}))

    asyncio.run(alerts.scan())
    assert any("open-acc.overheid.nl" in s for s in sent)        # red → emailed
    assert all("antivirus" not in s for s in sent)               # green → not
    hist = store.list_history()
    assert any(h["card_id"] == "environment:ACC:open-acc.overheid.nl" for h in hist)


def test_scan_disabled_global_sends_nothing(store, monkeypatch):
    from config import settings
    import alerts_send
    monkeypatch.setattr(settings, "alerts_enabled", True)
    store.set_config("global_enabled", False, actor="a")
    sent = []
    monkeypatch.setattr(alerts_send, "send_email_to",
                        lambda *a, **k: sent.append(1) or True)
    monkeypatch.setattr(alerts.notify, "send_webhook", _noop_webhook)
    monkeypatch.setattr(alerts, "_collect", lambda: [
        alerts._item("dlq", "PROD", "export.dlq", "critical")])
    asyncio.run(alerts.scan())
    assert sent == []
