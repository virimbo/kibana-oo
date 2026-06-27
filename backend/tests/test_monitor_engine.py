import os, tempfile
os.environ["APP_DB_PATH"] = os.path.join(tempfile.gettempdir(), "mon_eng_test.db")
import importlib, config as _c; importlib.reload(_c)
from config import settings
settings.app_db_path = os.environ["APP_DB_PATH"]
import asyncio, monitor_engine as eng, monitor_registry as reg

def setup_function(_):
    with reg.cursor() as c:
        for t in ("monitor_results", "monitor_targets", "monitor_connections"):
            c.execute(f"DELETE FROM {t}")

def test_run_once_records_results_and_survives_bad_target(monkeypatch):
    good = reg.add_target(name="g", type="http", config={"url": "http://g"}, actor="a")
    bad = reg.add_target(name="b", type="nope", config={}, actor="a")
    async def fake_check(t, conn):
        if t["type"] == "http":
            return {"status": "ok", "detail": {}, "latency_ms": 1}
        raise RuntimeError("boom")
    monkeypatch.setattr(eng.monitor_checkers, "run_check", fake_check)
    asyncio.run(eng.run_once(sid="s"))
    assert reg.latest_result(good)["status"] == "ok"
    assert reg.latest_result(bad)["status"] == "unreachable"   # wrapped, not crashed

def test_snapshot_groups_by_env_and_has_coverage():
    tid = reg.add_target(name="g", type="log-freshness", environment="prod",
                         config={"index": "x"}, actor="a")
    reg.record_result(tid, "ok", {}, None)
    snap = eng.snapshot()
    assert "prod" in snap["by_env"] and "coverage" in snap and snap["enabled"] is True
