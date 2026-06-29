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


def test_decide_new_then_silent_while_down():
    """One alert when it breaks, then NOTHING until it recovers — no repeats ever."""
    now = datetime(2026, 6, 18, 12, 0, tzinfo=timezone.utc)
    crit = alerts._item("dlq", "PROD", "export.dlq", "critical")
    # No prior state, red → NEW (the single down-alert)
    kind, nxt = alerts._decide(crit, prev=None, cooldown_min=60, now=now)
    assert kind == "new" and nxt["severity"] == "critical" and nxt["red_since"]

    prev = nxt
    # 30 min later, still down → silent
    assert alerts._decide(crit, prev=prev, cooldown_min=60,
                          now=now + timedelta(minutes=30))[0] is None
    # 6 hours later, STILL down → STILL silent (no time-based repeat)
    assert alerts._decide(crit, prev=prev, cooldown_min=60,
                          now=now + timedelta(hours=6))[0] is None
    # a full day later → still silent
    assert alerts._decide(crit, prev=prev, cooldown_min=60,
                          now=now + timedelta(days=1))[0] is None


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
    monkeypatch.setattr(alerts_send, "post_webhook", _noop_webhook)
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
    monkeypatch.setattr(alerts_send, "post_webhook", _noop_webhook)
    monkeypatch.setattr(alerts, "_collect", lambda: [
        alerts._item("dlq", "PROD", "export.dlq", "critical")])
    asyncio.run(alerts.scan())
    assert sent == []


def test_email_validation():
    import alerts_api
    assert alerts_api._valid_email("ops@example.com") is True
    assert alerts_api._valid_email("not-an-email") is False
    assert alerts_api._valid_email("a@b") is False
    assert alerts_api._valid_email("x" * 300 + "@e.com") is False


def test_send_test_no_recipients():
    import alerts_api
    res = asyncio.run(alerts_api.send_test(
        alerts_api.TestBody(recipients=[]), session={"username": "a@x"}))
    assert res == {"delivered": False, "reason": "no_recipients", "count": 0}


def test_send_test_rejects_invalid_email():
    import alerts_api
    with pytest.raises(HTTPException) as ei:
        asyncio.run(alerts_api.send_test(
            alerts_api.TestBody(recipients=["not-an-email"]), session={"username": "a@x"}))
    assert ei.value.status_code == 400


def test_send_test_smtp_unconfigured(monkeypatch):
    import alerts_api
    from config import settings
    monkeypatch.setattr(settings, "smtp_host", "")
    res = asyncio.run(alerts_api.send_test(
        alerts_api.TestBody(recipients=["ops@example.com"]), session={"username": "a@x"}))
    assert res["delivered"] is False
    assert res["reason"] == "smtp_unconfigured"
    assert res["count"] == 1


def test_send_test_delivers(monkeypatch):
    import alerts_api
    import alerts_send
    from config import settings
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from", "no-reply@example.com")
    sent = {}
    def _fake_send(recipients, subject, html, text):
        sent["to"] = recipients
        return True
    monkeypatch.setattr(alerts_send, "send_email_to", _fake_send)
    res = asyncio.run(alerts_api.send_test(
        alerts_api.TestBody(recipients=["ops@example.com", "beheer@example.com"]),
        session={"username": "a@x"}))
    assert res == {"delivered": True, "reason": "sent", "count": 2}
    assert sent["to"] == ["ops@example.com", "beheer@example.com"]


def test_api_requires_super(monkeypatch):
    import permissions
    monkeypatch.setattr(permissions, "is_super", lambda u: False)
    from auth import require_super
    with pytest.raises(HTTPException) as ei:
        require_super(session={"username": "user@x"})
    assert ei.value.status_code == 403


import alerts_mattermost


def test_mattermost_payload_critical():
    item = alerts._item("environment", "ACC", "open-acc.overheid.nl", "critical",
                        status="HTTP 404 / DOWN")
    p = alerts_mattermost.payload(item, "new", "ok", "http://d/", "FB-OO:Anton")
    assert p["username"] == "FB-OO:Anton"
    a = p["attachments"][0]
    assert a["color"] == "#f85149"
    assert "open-acc.overheid.nl" in a["title"]
    assert a["title_link"] == "http://d/"
    fields = {f["title"]: f["value"] for f in a["fields"]}
    assert fields["Omgeving"] == "ACC"
    assert "HTTP 404 / DOWN" in fields["Huidige status"]
    assert any("Aanbevolen actie" in f["title"] for f in a["fields"])
    assert isinstance(a["ts"], int)


def test_mattermost_payload_recovery_has_no_action():
    item = alerts._item("certificate", "PROD", "open.overheid.nl", "ok",
                        status="grade OK")
    p = alerts_mattermost.payload(item, "recovery", "critical", "http://d/", "S")
    a = p["attachments"][0]
    assert a["color"] == "#46c97a"
    assert "hersteld" in a["text"].lower()
    assert not any("Aanbevolen actie" in f["title"] for f in a["fields"])
