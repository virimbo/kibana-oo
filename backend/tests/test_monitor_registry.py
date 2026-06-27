import pytest
from config import settings
import monitor_registry as reg


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(reg, "_schema_ready", False)   # force schema re-create in the fresh db
    yield

def test_connection_crud_hides_no_secret_value():
    cid = reg.add_connection(kind="prometheus", name="Prom PROD",
                             base_url="http://prom:9090", secret_ref="PROM_TOKEN", actor="anton")
    got = reg.get_connection(cid)
    assert got["base_url"] == "http://prom:9090"
    assert got["secret_ref"] == "PROM_TOKEN"
    assert "secret_value" not in got

def test_target_crud_and_toggle():
    tid = reg.add_target(name="GW logs PROD", type="log-freshness", environment="prod",
                         config={"index": "logs-gw-*", "max_age_minutes": 10}, actor="anton")
    reg.set_target_enabled(tid, False)
    assert reg.get_target(tid)["enabled"] == 0
    reg.update_target(tid, {"environment": "acc"})
    assert reg.get_target(tid)["environment"] == "acc"
    reg.delete_target(tid)
    assert reg.get_target(tid) is None

def test_result_store_and_latest():
    tid = reg.add_target(name="x", type="http", environment="na", config={"url": "http://x"}, actor="a")
    reg.record_result(tid, status="ok", detail={"http": 200}, latency_ms=12)
    reg.record_result(tid, status="down", detail={"http": 503}, latency_ms=8)
    assert reg.latest_result(tid)["status"] == "down"
    assert len(reg.recent_results(tid, limit=10)) == 2
