"""Monitoring alert bridge: alerts.raise_external(...) must reuse the existing
per-incident dedup/state machine so the same active incident notifies ONCE.

Uses an isolated DB via monkeypatch (so it reverts cleanly and never pollutes
sibling tests) and monkeypatches the real low-level send function
(alerts_send.send_email_to) that alerts._dispatch calls."""
from config import settings

import alerts
import alerts_send
import alerts_store


async def _async_noop(*a, **k):
    return True


def test_raise_external_dedups(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "mon.db"))
    monkeypatch.setattr(settings, "alerts_default_threshold", "critical")
    alerts_store.ensure_seeded()

    sent = []
    # Real low-level send used by alerts._dispatch (email leg of email→Mattermost).
    monkeypatch.setattr(
        alerts_send, "send_email_to",
        lambda *a, **k: sent.append(a) or True, raising=True)
    # Webhook leg is irrelevant to this assertion; stub it so it never touches I/O.
    monkeypatch.setattr(alerts_send, "post_webhook", _async_noop, raising=True)

    alerts.raise_external(
        category="monitoring", key="prod:repo", env="prod",
        title="T", detail="detail")
    alerts.raise_external(
        category="monitoring", key="prod:repo", env="prod",
        title="T", detail="detail")

    assert len(sent) == 1  # second call is a dedup (same incident still active)
