"""Tests for the admin-managed Mattermost webhook store (webhooks_store).

Focus: the fail-safe fallback to DIGEST_WEBHOOK_URL, single-active invariant,
first-webhook auto-activation, and URL masking.
"""
import pytest

import webhooks_store
from config import settings


@pytest.fixture(autouse=True)
def isolated_app_db(tmp_path, monkeypatch):
    """Each test gets its own empty kibana_oo.db so webhook rows never leak."""
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "kibana_oo.db"))
    yield


def test_active_url_falls_back_to_env_when_no_managed_webhook(monkeypatch):
    monkeypatch.setattr(settings, "digest_webhook_url", "https://mm.example/hooks/ENVCODE")
    # No managed webhooks yet → dispatch must use the .env fallback unchanged.
    assert webhooks_store.active_url() == "https://mm.example/hooks/ENVCODE"
    assert webhooks_store.get_active() is None
    assert webhooks_store.fallback_configured() is True


def test_active_url_empty_when_no_managed_and_no_env(monkeypatch):
    monkeypatch.setattr(settings, "digest_webhook_url", "")
    assert webhooks_store.active_url() == ""
    assert webhooks_store.fallback_configured() is False


def test_first_webhook_auto_activates_and_overrides_env(monkeypatch):
    monkeypatch.setattr(settings, "digest_webhook_url", "https://mm.example/hooks/ENVCODE")
    wh = webhooks_store.add_webhook("PROD", "https://mm.example/hooks/PRODCODE", actor="anton")
    assert wh["active"] is True  # first one becomes active automatically
    # Managed active webhook now wins over the .env fallback.
    assert webhooks_store.active_url() == "https://mm.example/hooks/PRODCODE"


def test_second_webhook_is_inactive_until_activated():
    a = webhooks_store.add_webhook("PROD", "https://mm.example/hooks/PRODCODE", actor="anton")
    b = webhooks_store.add_webhook("ACC", "https://mm.example/hooks/ACCCODE", actor="anton")
    assert a["active"] is True
    assert b["active"] is False
    assert webhooks_store.active_url().endswith("PRODCODE")


def test_set_active_is_exclusive():
    a = webhooks_store.add_webhook("PROD", "https://mm.example/hooks/PRODCODE", actor="anton")
    b = webhooks_store.add_webhook("ACC", "https://mm.example/hooks/ACCCODE", actor="anton")
    webhooks_store.set_active(b["id"], actor="anton")
    rows = {w["label"]: w["active"] for w in webhooks_store.list_webhooks()}
    assert rows == {"PROD": False, "ACC": True}
    assert webhooks_store.active_url().endswith("ACCCODE")


def test_set_active_unknown_id_returns_none():
    assert webhooks_store.set_active(999, actor="anton") is None


def test_update_changes_label_and_url():
    a = webhooks_store.add_webhook("PROD", "https://mm.example/hooks/OLD", actor="anton")
    upd = webhooks_store.update_webhook(a["id"], label="PROD-new",
                                        url="https://mm.example/hooks/NEWCODE", actor="anton")
    assert upd["label"] == "PROD-new"
    assert webhooks_store.active_url().endswith("NEWCODE")


def test_update_unknown_id_returns_none():
    assert webhooks_store.update_webhook(999, label="x", url=None, actor="anton") is None


def test_delete_removes_row():
    a = webhooks_store.add_webhook("PROD", "https://mm.example/hooks/PRODCODE", actor="anton")
    assert webhooks_store.delete_webhook(a["id"]) is True
    assert webhooks_store.list_webhooks() == []
    assert webhooks_store.delete_webhook(a["id"]) is False


def test_delete_active_falls_back_to_env(monkeypatch):
    monkeypatch.setattr(settings, "digest_webhook_url", "https://mm.example/hooks/ENVCODE")
    a = webhooks_store.add_webhook("PROD", "https://mm.example/hooks/PRODCODE", actor="anton")
    webhooks_store.delete_webhook(a["id"])
    # With the only managed webhook gone, dispatch reverts to the .env fallback.
    assert webhooks_store.active_url() == "https://mm.example/hooks/ENVCODE"


def test_list_masks_the_secret_code():
    webhooks_store.add_webhook("PROD", "https://mm.example/hooks/abcdef1234567890", actor="anton")
    listed = webhooks_store.list_webhooks()[0]
    assert "abcdef1234567890" not in listed["url"]
    assert listed["url"].endswith("7890")  # last 4 kept for recognition
    assert listed["url"].startswith("https://mm.example/hooks/")


def test_get_webhook_reveal_returns_full_url():
    a = webhooks_store.add_webhook("PROD", "https://mm.example/hooks/FULLCODE", actor="anton")
    assert webhooks_store.get_webhook(a["id"], reveal=True)["url"] == "https://mm.example/hooks/FULLCODE"
    assert "FULLCODE" not in webhooks_store.get_webhook(a["id"])["url"]


def test_mask_url_handles_nonstandard_and_empty():
    assert webhooks_store.mask_url("") == ""
    masked = webhooks_store.mask_url("https://example.com/other/path1234")
    assert "1234" in masked and "…" in masked
