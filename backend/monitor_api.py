"""Monitoring registry API. Config = super-admin; results = require_feature('monitoring').
Secrets (values) never enter requests/responses — only secret_ref names."""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from auth import require_super, require_feature
from config import settings
import monitor_registry as reg
import monitor_checkers
import monitor_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/monitor")

class ConnectionIn(BaseModel):
    kind: str; name: str; base_url: str; secret_ref: str | None = None; enabled: bool = True
class TargetIn(BaseModel):
    name: str; type: str; environment: str = "na"; connection_id: int | None = None
    config: dict = {}; enabled: bool = True; alert_enabled: bool = True

@router.get("/types")
async def types(_: dict = Depends(require_super)): return monitor_checkers.types_schema()

@router.get("/connections")
async def conns(_: dict = Depends(require_super)): return reg.list_connections()
@router.post("/connections")
async def add_conn(body: ConnectionIn, s: dict = Depends(require_super)):
    cid = reg.add_connection(body.kind, body.name, body.base_url, body.secret_ref, s.get("username"))
    return reg.get_connection(cid)
@router.delete("/connections/{cid}")
async def del_conn(cid: int, _: dict = Depends(require_super)): reg.delete_connection(cid); return {"ok": True}

@router.get("/targets")
async def targets(_: dict = Depends(require_super)): return reg.list_targets()
@router.post("/targets")
async def add_tgt(body: TargetIn, s: dict = Depends(require_super)):
    tid = reg.add_target(body.name, body.type, body.environment, body.config,
                         body.connection_id, s.get("username"))
    if not body.enabled: reg.set_target_enabled(tid, False)
    if not body.alert_enabled: reg.update_target(tid, {"alert_enabled": 0})
    return reg.get_target(tid)
@router.patch("/targets/{tid}")
async def patch_tgt(tid: int, patch: dict, _: dict = Depends(require_super)):
    reg.update_target(tid, patch); return reg.get_target(tid)
@router.delete("/targets/{tid}")
async def del_tgt(tid: int, _: dict = Depends(require_super)): reg.delete_target(tid); return {"ok": True}

@router.post("/test")
async def test_target(body: TargetIn, _: dict = Depends(require_super)):
    conn = reg.get_connection(body.connection_id) if body.connection_id else None
    return await monitor_checkers.run_check({"type": body.type, "config": body.config}, conn)

@router.get("/discover")
async def discover(connection_id: int, _: dict = Depends(require_super)):
    conn = reg.get_connection(connection_id)
    if not conn: raise HTTPException(404, "connection not found")
    chk = monitor_checkers.CHECKERS.get({"prometheus": "prometheus-query", "jaeger": "jaeger-traces"}.get(conn["kind"], ""))
    if not chk or not chk.get("discover"): return {"suggestions": []}
    return {"suggestions": await chk["discover"](conn)}

results_router = APIRouter(prefix="/dashboard/monitoring")
@results_router.get("")
async def card(_: dict = Depends(require_feature("monitoring"))):
    if not settings.monitor_enabled: return {"enabled": False}
    try: return monitor_engine.snapshot()
    except Exception as e:  # noqa: BLE001
        logger.error("monitoring snapshot failed: %s", e)
        raise HTTPException(502, "Monitoring unavailable") from e
