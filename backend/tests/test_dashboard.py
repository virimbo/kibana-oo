import cache


# ── Task 8: TTL cache ───────────────────────────────────────

def test_ttl_cache_hit_and_expiry():
    clock = {"t": 1000.0}
    c = cache.TTLCache(ttl=60, now=lambda: clock["t"])
    c.set("k", "v")
    assert c.get("k") == "v"          # fresh
    clock["t"] = 1059.0
    assert c.get("k") == "v"          # still within TTL
    clock["t"] = 1061.0
    assert c.get("k") is None         # expired


# ── Task 10: router (admin-gated, cached) ───────────────────

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import dashboard
import monitoring
from session import _sessions


@pytest.fixture
def client(monkeypatch, tmp_path):
    app = FastAPI()
    app.include_router(dashboard.router)
    # New model: access is by feature grant. Make the admin a SUPER admin (has all
    # features); the non-admin has no grants in the isolated DB → 403.
    monkeypatch.setattr(dashboard.settings, "super_admins", "boss@koop.nl")
    monkeypatch.setattr(dashboard.settings, "dashboard_admins", "boss@koop.nl")
    monkeypatch.setattr(dashboard.settings, "app_db_path", str(tmp_path / "app.db"))
    _sessions.clear()
    _sessions["admin-tok"] = {"username": "boss@koop.nl", "sid": "sid1"}
    _sessions["user-tok"] = {"username": "intern@koop.nl", "sid": "sid2"}
    dashboard._summary_cache.clear()

    async def fake_snapshot(sid, period, data_view, *, start=None, end=None):
        return monitoring.DashboardSnapshot(
            period_minutes=period, data_view=data_view, window_start="s", window_end="e",
            total=42, delta=monitoring.Delta(previous=10, pct_vs_previous=320.0),
            status_level="degraded", systems=[], timeseries=[], top_signatures=[],
            affected_services=[], status_codes=[], failing_urls=[], partial=False,
        )

    monkeypatch.setattr(dashboard, "build_snapshot", fake_snapshot)
    return TestClient(app)


def test_summary_requires_login(client):
    assert client.get("/dashboard/summary").status_code == 401


def test_summary_forbidden_for_non_admin(client):
    r = client.get("/dashboard/summary", headers={"Authorization": "Bearer user-tok"})
    assert r.status_code == 403


def test_summary_ok_for_admin(client):
    r = client.get("/dashboard/summary", headers={"Authorization": "Bearer admin-tok"})
    assert r.status_code == 200
    assert r.json()["total"] == 42
