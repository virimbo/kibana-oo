"""RabbitMQ DLQ monitor: severity tiers, DLQ↔source pairing, the verdict view,
and the lightweight first-seen/alert-dedup state. Network mocked."""
import pytest

import rabbitmq_dlq as R
from config import settings


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "app.db"))
    monkeypatch.setattr(settings, "rabbitmq_user", "mon")
    monkeypatch.setattr(settings, "rabbitmq_password", "x")
    monkeypatch.setattr(settings, "rabbitmq_critical_messages", 100)
    monkeypatch.setattr(settings, "rabbitmq_alert_enabled", False)
    R._latest = None
    yield


def _q(name, messages=0, consumers=0, state="running"):
    return {"name": name, "vhost": "/", "messages": messages, "messages_ready": messages,
            "messages_unacknowledged": 0, "consumers": consumers, "state": state}


def test_severity_tiers():
    assert R._severity(0, 2) == "ok"
    assert R._severity(5, 2) == "warn"
    assert R._severity(150, 2) == "critical"      # over threshold
    assert R._severity(3, 0) == "critical"        # source has no consumer


def test_classify_pairs_dlq_with_source():
    queues = [_q("svc-a", consumers=2), _q("svc-a.dlq", messages=5),
              _q("svc-b", consumers=0), _q("svc-b.dlq", messages=3)]
    dlqs = R.classify(queues)
    assert {d["name"] for d in dlqs} == {"svc-a.dlq", "svc-b.dlq"}
    a = next(d for d in dlqs if d["name"] == "svc-a.dlq")
    b = next(d for d in dlqs if d["name"] == "svc-b.dlq")
    assert a["source"] == "svc-a" and a["source_consumers"] == 2 and a["severity"] == "warn"
    assert b["severity"] == "critical"            # source has 0 consumers
    assert dlqs[0]["severity"] == "critical"      # critical sorted first


def test_view_verdict_and_count():
    dlqs = R.classify([_q("a"), _q("a.dlq", messages=0), _q("b", consumers=1), _q("b.dlq", messages=4)])
    v = R._view(dlqs)
    assert v["verdict"] == "WARN" and v["count"] == 1 and v["total_dlqs"] == 2


def test_state_first_seen_alert_and_drain():
    dlqs = R.classify([_q("a", consumers=1), _q("a.dlq", messages=2)])
    newly = R._reconcile_state_sync(dlqs, "2026-06-16T10:00:00+00:00")
    assert [d["name"] for d in newly] == ["a.dlq"]            # newly non-empty → alert
    assert dlqs[0]["first_seen"] == "2026-06-16T10:00:00+00:00"
    # same state again → no re-alert (deduped), age preserved
    dlqs2 = R.classify([_q("a", consumers=1), _q("a.dlq", messages=2)])
    assert R._reconcile_state_sync(dlqs2, "2026-06-16T11:00:00+00:00") == []
    assert dlqs2[0]["first_seen"] == "2026-06-16T10:00:00+00:00"
    # drains → state cleared
    drained = R.classify([_q("a", consumers=1), _q("a.dlq", messages=0)])
    R._reconcile_state_sync(drained, "2026-06-16T12:00:00+00:00")
    # going non-empty again re-alerts (fresh first_seen)
    again = R.classify([_q("a", consumers=1), _q("a.dlq", messages=1)])
    assert [d["name"] for d in R._reconcile_state_sync(again, "2026-06-16T13:00:00+00:00")] == ["a.dlq"]


def test_escalation_to_critical_alerts():
    R._reconcile_state_sync(R.classify([_q("a", consumers=1), _q("a.dlq", messages=2)]), "t1")  # warn
    crit = R.classify([_q("a", consumers=1), _q("a.dlq", messages=200)])                          # → critical
    assert [d["name"] for d in R._reconcile_state_sync(crit, "t2")] == ["a.dlq"]


async def test_scan_end_to_end(monkeypatch):
    async def fake_fetch():
        return [_q("svc", consumers=0), _q("svc.dlq", messages=7), _q("ok.dlq", messages=0)]
    monkeypatch.setattr(R, "_fetch_queues", fake_fetch)
    view = await R.scan()
    assert view["configured"] is True and view["verdict"] == "CRITICAL" and view["count"] == 1


async def test_scan_inert_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "rabbitmq_user", "")
    assert (await R.scan()) == {"configured": False}
