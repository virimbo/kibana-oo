"""Background poll loop + dashboard snapshot. Fail-safe per target; AI/intel best-effort.
Off unless settings.monitor_enabled."""
import asyncio, logging
import monitor_registry as reg
import monitor_checkers
import monitor_intel as intel
from config import settings

logger = logging.getLogger(__name__)
_RED = {"down", "stale", "unreachable"}

async def _check_connection(conn) -> bool:
    """Cheap reachability for dependency suppression. http GET base_url."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=settings.monitor_timeout) as c:
            await c.get(conn["base_url"])
        return True
    except Exception:  # noqa: BLE001
        return False

async def run_once(sid: str | None = None):
    conns = {c["id"]: c for c in reg.list_connections() if c["enabled"]}
    conn_up = {cid: await _check_connection(c) for cid, c in conns.items()}
    for t in reg.list_targets(enabled_only=True):
        conn = conns.get(t.get("connection_id"))
        if conn and not conn_up.get(conn["id"], True):
            reg.record_result(t["id"], "unreachable", {"dependency": conn["name"]}, None)
            continue
        t["_ctx"] = {"sid": sid}
        if t["type"] in ("log-freshness",) and t["config"].get("adaptive", True):
            base = intel.baseline_minutes([])  # baseline grows from history in a fuller impl
            t["config"]["_effective_threshold"] = intel.effective_threshold(
                t["config"].get("max_age_minutes", 10), base)
        try:
            res = await monitor_checkers.run_check(t, conn)
        except Exception as e:  # noqa: BLE001 — one bad target never breaks the round
            res = {"status": "unreachable", "detail": {"error": str(e)}, "latency_ms": None}
        reg.record_result(t["id"], res["status"], res.get("detail"), res.get("latency_ms"))
    await _evaluate_alerts(sid)

async def _evaluate_alerts(sid):
    """Flap-guarded, correlated, dependency-aware alerting via the existing engine."""
    targets = []
    for t in reg.list_targets(enabled_only=True):
        lr = reg.latest_result(t["id"]) or {"status": "ok"}
        t["_status"] = lr["status"]; targets.append(t)
    reds = []
    for t in targets:
        if t["_status"] in _RED and t["alert_enabled"]:
            recent = [r["status"] for r in reg.recent_results(t["id"], limit=settings.monitor_flap_threshold)]
            if not intel.is_flapping_clear(recent, settings.monitor_flap_threshold):
                reds.append(t)
    for group in intel.correlate(reds):
        rc = await intel.ai_rootcause(group, sid)   # best-effort
        _raise_monitoring_alert(group, rc)

def _raise_monitoring_alert(group, rootcause):
    """Bridge to the existing alert engine (Task 9 adds alerts.raise_external)."""
    try:
        import alerts
        alerts.raise_external(category="monitoring",
                              key=f"{group['environment']}:{group['service']}",
                              env=group["environment"],
                              title=f"Monitoring: {group['service']} ({group['environment']})",
                              detail=rootcause or ", ".join(t["name"] for t in group["targets"]))
    except Exception as e:  # noqa: BLE001 — never break the loop on alert issues
        logger.warning("monitoring alert bridge failed: %s", e)

def snapshot() -> dict:
    targets = []
    for t in reg.list_targets():
        lr = reg.latest_result(t["id"]) or {"status": "unknown", "detail": {}}
        t["_status"] = lr["status"]; t["_detail"] = lr.get("detail", {}); t["_ts"] = lr.get("ts")
        targets.append(t)
    by_env: dict[str, list] = {}
    for t in targets:
        by_env.setdefault(t["environment"], []).append({
            "id": t["id"], "name": t["name"], "type": t["type"],
            "status": t["_status"], "detail": t["_detail"], "enabled": t["enabled"]})
    return {"enabled": True, "by_env": by_env,
            "coverage": intel.coverage([t for t in targets if t["enabled"]])}

async def run_monitor_loop():
    if not settings.monitor_enabled:
        logger.info("monitor loop disabled"); return
    while True:
        try:
            await run_once(sid=None)
        except Exception as e:  # noqa: BLE001
            logger.error("monitor loop cycle failed: %s", e)
        await asyncio.sleep(settings.monitor_interval)
