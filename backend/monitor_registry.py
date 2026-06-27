"""Monitoring Targets registry — schema + CRUD for connections, targets, results.
Additive: own tables in the shared app db (db.py). Secrets are NEVER stored here —
only `secret_ref`, the NAME of an .env var read at check time."""
import json
from datetime import datetime, timezone
from db import cursor

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitor_connections (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, base_url TEXT NOT NULL,
  secret_ref TEXT, enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT, updated_at TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS monitor_targets (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
  environment TEXT NOT NULL DEFAULT 'na', enabled INTEGER NOT NULL DEFAULT 1,
  alert_enabled INTEGER NOT NULL DEFAULT 1, connection_id INTEGER,
  config TEXT NOT NULL DEFAULT '{}', created_at TEXT, updated_at TEXT, created_by TEXT);
CREATE TABLE IF NOT EXISTS monitor_results (
  id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL, ts TEXT NOT NULL,
  status TEXT NOT NULL, detail TEXT, latency_ms INTEGER);
CREATE INDEX IF NOT EXISTS ix_mon_results_target_ts ON monitor_results(target_id, ts);
"""
with cursor() as _c:
    _c.executescript(_SCHEMA)

def _row(r): return dict(r) if r is not None else None

def add_connection(kind, name, base_url, secret_ref=None, actor=None) -> int:
    with cursor() as c:
        cur = c.execute(
            "INSERT INTO monitor_connections (kind,name,base_url,secret_ref,created_at,updated_at,created_by)"
            " VALUES (?,?,?,?,?,?,?)", (kind, name, base_url, secret_ref, _now(), _now(), actor))
        return cur.lastrowid

def get_connection(cid):
    with cursor() as c:
        return _row(c.execute("SELECT * FROM monitor_connections WHERE id=?", (cid,)).fetchone())

def list_connections():
    with cursor() as c:
        return [dict(r) for r in c.execute("SELECT * FROM monitor_connections ORDER BY id").fetchall()]

def update_connection(cid, patch: dict):
    allowed = {"kind","name","base_url","secret_ref","enabled"}
    sets = {k: v for k, v in patch.items() if k in allowed}
    if not sets: return
    cols = ",".join(f"{k}=?" for k in sets) + ",updated_at=?"
    with cursor() as c:
        c.execute(f"UPDATE monitor_connections SET {cols} WHERE id=?", (*sets.values(), _now(), cid))

def delete_connection(cid):
    with cursor() as c:
        c.execute("DELETE FROM monitor_connections WHERE id=?", (cid,))

def add_target(name, type, environment="na", config=None, connection_id=None, actor=None) -> int:
    with cursor() as c:
        cur = c.execute(
            "INSERT INTO monitor_targets (name,type,environment,connection_id,config,created_at,updated_at,created_by)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (name, type, environment, connection_id, json.dumps(config or {}), _now(), _now(), actor))
        return cur.lastrowid

def get_target(tid):
    with cursor() as c:
        r = c.execute("SELECT * FROM monitor_targets WHERE id=?", (tid,)).fetchone()
    if r is None: return None
    d = dict(r); d["config"] = json.loads(d["config"] or "{}"); return d

def list_targets(enabled_only=False):
    q = "SELECT * FROM monitor_targets" + (" WHERE enabled=1" if enabled_only else "") + " ORDER BY environment,type,id"
    with cursor() as c:
        out = []
        for r in c.execute(q).fetchall():
            d = dict(r); d["config"] = json.loads(d["config"] or "{}"); out.append(d)
        return out

def update_target(tid, patch: dict):
    allowed = {"name","type","environment","enabled","alert_enabled","connection_id","config"}
    sets = {k: (json.dumps(v) if k == "config" else v) for k, v in patch.items() if k in allowed}
    if not sets: return
    cols = ",".join(f"{k}=?" for k in sets) + ",updated_at=?"
    with cursor() as c:
        c.execute(f"UPDATE monitor_targets SET {cols} WHERE id=?", (*sets.values(), _now(), tid))

def set_target_enabled(tid, on: bool): update_target(tid, {"enabled": 1 if on else 0})

def delete_target(tid):
    with cursor() as c:
        c.execute("DELETE FROM monitor_results WHERE target_id=?", (tid,))
        c.execute("DELETE FROM monitor_targets WHERE id=?", (tid,))

def record_result(target_id, status, detail=None, latency_ms=None):
    with cursor() as c:
        c.execute("INSERT INTO monitor_results (target_id,ts,status,detail,latency_ms) VALUES (?,?,?,?,?)",
                  (target_id, _now(), status, json.dumps(detail or {}), latency_ms))

def latest_result(target_id):
    with cursor() as c:
        r = c.execute("SELECT * FROM monitor_results WHERE target_id=? ORDER BY ts DESC LIMIT 1",
                      (target_id,)).fetchone()
    if r is None: return None
    d = dict(r); d["detail"] = json.loads(d["detail"] or "{}"); return d

def recent_results(target_id, limit=50):
    with cursor() as c:
        rows = c.execute("SELECT * FROM monitor_results WHERE target_id=? ORDER BY ts DESC LIMIT ?",
                         (target_id, limit)).fetchall()
    return [dict(r) for r in rows]
