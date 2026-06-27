"""Feature authorisation: a per-user × per-feature access matrix.

Root of trust: SUPER_ADMINS (config) — they hold every feature implicitly and are
the only ones who can manage the matrix. Everyone else is DENY-BY-DEFAULT except
the `chat` baseline; the super admin grants specific features (cards/pages/tools)
to specific users. Grants + an audit trail live in the shared kibana_oo.db.

On first run the existing DASHBOARD_ADMINS are seeded with every grantable feature
so nothing breaks on rollout; the super admin then narrows from there.
Enforced server-side via auth.require_feature; the UI reads /me/permissions.
"""
import logging
from contextlib import closing
from datetime import datetime, timezone

import db
from config import settings

logger = logging.getLogger(__name__)

# ── Feature catalog (the matrix columns). Fixed + code-defined. ───────────────
# key, label, group. Adding a card/tool = adding one entry here.
CATALOG = [
    {"key": "dashboard", "label": "Monitoring dashboard", "group": "Dashboard"},
    {"key": "certificates", "label": "Certificate & TLS health", "group": "Dashboard"},
    {"key": "outcomes", "label": "Pipeline outcomes", "group": "Dashboard"},
    {"key": "pipeline_health", "label": "Documents needing attention", "group": "Dashboard"},
    {"key": "aanleverfouten", "label": "Aanleverfouten", "group": "Dashboard"},
    {"key": "documents", "label": "Documents (trace & search)", "group": "Documents"},
    {"key": "rabbitmq", "label": "Dead-letter queues (RabbitMQ)", "group": "Dashboard"},
    {"key": "smart_context", "label": "Smart context panel (hover-intelligentie)", "group": "Dashboard"},
    {"key": "uptime", "label": "Beschikbaarheid (environment status)", "group": "Dashboard"},
    {"key": "service_health", "label": "Service health (backend microservices)", "group": "Dashboard"},
    {"key": "monitoring", "label": "Monitoring targets", "group": "Dashboard"},
    {"key": "grafana", "label": "Infrastructuur (Grafana-links)", "group": "Dashboard"},
    {"key": "regression", "label": "Regressietest", "group": "Beheer"},
    {"key": "settings", "label": "Settings (AI & toggles)", "group": "Beheer"},
    {"key": "alerts", "label": "Alerting (meldingen)", "group": "Beheer"},
]
GRANTABLE = [f["key"] for f in CATALOG]
GRANTABLE_SET = set(GRANTABLE)
BASELINE = {"chat"}            # always available to any authenticated user
SUPER_ONLY = {"authorization"}  # the matrix manager itself


def is_super(username: str | None) -> bool:
    return bool(username) and username.strip().lower() in settings.super_admin_list


# ── SQLite store (shared app DB) ──────────────────────────────────────────────
_SCHEMA = """
CREATE TABLE IF NOT EXISTS feature_grants (
    username   TEXT NOT NULL,
    feature    TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    granted_by TEXT,
    PRIMARY KEY (username, feature)
);
CREATE TABLE IF NOT EXISTS feature_grants_audit (
    ts          TEXT NOT NULL,
    actor       TEXT,
    action      TEXT NOT NULL,     -- grant | revoke | seed
    target_user TEXT NOT NULL,
    feature     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feature_grants_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE INDEX IF NOT EXISTS idx_grants_user ON feature_grants(username);
CREATE TABLE IF NOT EXISTS app_users (
  username    TEXT PRIMARY KEY,
  status      TEXT NOT NULL DEFAULT 'pending',
  first_seen  TEXT NOT NULL,
  approved_at TEXT,
  approved_by TEXT
);
"""


def _conn():
    conn = db.connect()
    conn.executescript(_SCHEMA)
    return conn


def _norm(username: str) -> str:
    return (username or "").strip().lower()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(conn, actor: str | None, action: str, user: str, feature: str) -> None:
    conn.execute(
        "INSERT INTO feature_grants_audit (ts, actor, action, target_user, feature) VALUES (?,?,?,?,?)",
        (_now(), actor, action, user, feature),
    )


# ── Authorisation check ───────────────────────────────────────────────────────
def has_feature(session: dict, feature: str) -> bool:
    """True if this session may use `feature`. Super admin → all; chat → baseline;
    otherwise an explicit grant is required (deny-by-default)."""
    username = (session or {}).get("username")
    if is_super(username):
        return True
    if not is_approved(username):
        return False
    if feature in BASELINE:
        return True
    if feature in SUPER_ONLY:
        return False
    if feature not in GRANTABLE_SET:
        return False
    return _has_grant_sync(_norm(username), feature)


def _has_grant_sync(username: str, feature: str) -> bool:
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT 1 FROM feature_grants WHERE username = ? AND feature = ?", (username, feature)
        ).fetchone()
    return row is not None


# ── Grants management ─────────────────────────────────────────────────────────
def user_features(username: str) -> list[str]:
    """The feature keys this user may use (super → all grantable)."""
    if is_super(username):
        return list(GRANTABLE)
    if not is_approved(username):
        return []
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT feature FROM feature_grants WHERE username = ?", (_norm(username),)
        ).fetchall()
    return [r["feature"] for r in rows if r["feature"] in GRANTABLE_SET]


def grant(username: str, feature: str, actor: str | None) -> bool:
    if feature not in GRANTABLE_SET:
        return False
    u = _norm(username)
    with closing(_conn()) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO feature_grants (username, feature, granted_at, granted_by) VALUES (?,?,?,?)",
            (u, feature, _now(), actor),
        )
        if cur.rowcount:
            _audit(conn, actor, "grant", u, feature)
        conn.commit()
    return True


def revoke(username: str, feature: str, actor: str | None) -> bool:
    u = _norm(username)
    with closing(_conn()) as conn:
        cur = conn.execute(
            "DELETE FROM feature_grants WHERE username = ? AND feature = ?", (u, feature)
        )
        if cur.rowcount:
            _audit(conn, actor, "revoke", u, feature)
        conn.commit()
    return True


# ── User approval status (app_users) ──────────────────────────────────────────
def record_login(username: str) -> str:
    """Called on each successful login. Unknown user → registered 'pending'
    (super-admins → 'approved'). Returns the current status. Idempotent."""
    u = _norm(username)
    if not u:
        return "pending"
    initial = "approved" if is_super(u) else "pending"
    with closing(_conn()) as conn:
        existing = conn.execute("SELECT status FROM app_users WHERE username=?", (u,)).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO app_users (username, status, first_seen, approved_at, approved_by) "
                "VALUES (?,?,?,?,?)",
                (u, initial, _now(), _now() if initial == "approved" else None,
                 "auto" if initial == "approved" else None))
            _audit(conn, "auto", "auto_register", u, "-")
            conn.commit()
            return initial
        return existing["status"]


def user_status(username: str) -> str:
    """'approved' for super-admins (short-circuit); else the stored status, or
    'pending' if unknown."""
    u = _norm(username)
    if is_super(u):
        return "approved"
    with closing(_conn()) as conn:
        row = conn.execute("SELECT status FROM app_users WHERE username=?", (u,)).fetchone()
    return row["status"] if row else "pending"


def is_approved(username: str) -> bool:
    return is_super(username) or user_status(username) == "approved"


def _set_status(username: str, status: str, actor: str | None, action: str) -> None:
    u = _norm(username)
    with closing(_conn()) as conn:
        conn.execute(
            "INSERT INTO app_users (username, status, first_seen, approved_at, approved_by) "
            "VALUES (?,?,?,?,?) "
            "ON CONFLICT(username) DO UPDATE SET status=excluded.status, "
            "approved_at=excluded.approved_at, approved_by=excluded.approved_by",
            (u, status, _now(), _now(), actor))
        _audit(conn, actor, action, u, "-")
        conn.commit()


def approve(username: str, actor: str | None) -> None:
    _set_status(username, "approved", actor, "approve")


def suspend(username: str, actor: str | None) -> None:
    _set_status(username, "suspended", actor, "suspend")


def list_users() -> list[dict]:
    """Every known user + status, for the Authorization page. Super-admins always
    shown approved."""
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT username, status, first_seen, approved_at, approved_by FROM app_users "
            "ORDER BY (status='pending') DESC, username").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if is_super(d["username"]):
            d["status"] = "approved"
        d["is_super"] = is_super(d["username"])
        out.append(d)
    return out


def matrix() -> dict:
    """The full grid for the management UI: every known user and their grants,
    plus the catalog and the (config) super admins."""
    with closing(_conn()) as conn:
        rows = conn.execute("SELECT username, feature FROM feature_grants").fetchall()
    by_user: dict[str, list[str]] = {}
    for r in rows:
        by_user.setdefault(r["username"], []).append(r["feature"])
    users = [
        {"username": u, "features": sorted(f for f in feats if f in GRANTABLE_SET)}
        for u, feats in sorted(by_user.items())
    ]
    return {"catalog": CATALOG, "users": users, "super_admins": settings.super_admin_list}


def audit_log(limit: int = 100) -> list[dict]:
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT ts, actor, action, target_user, feature FROM feature_grants_audit "
            "ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def ensure_seeded() -> None:
    """One-time migration: seed existing DASHBOARD_ADMINS with every grantable
    feature, so admins keep full access on rollout. Idempotent (guarded by a meta
    flag) — the super admin narrows access afterwards."""
    with closing(_conn()) as conn:
        seeded = conn.execute(
            "SELECT value FROM feature_grants_meta WHERE key = 'seeded'"
        ).fetchone()
        if not seeded:
            for admin in settings.admin_list:
                u = _norm(admin)
                if is_super(u):
                    continue  # super admins don't need rows
                for feature in GRANTABLE:
                    cur = conn.execute(
                        "INSERT OR IGNORE INTO feature_grants (username, feature, granted_at, granted_by) "
                        "VALUES (?,?,?,?)", (u, feature, _now(), "seed"),
                    )
                    if cur.rowcount:
                        _audit(conn, "seed", "seed", u, feature)
            conn.execute(
                "INSERT OR REPLACE INTO feature_grants_meta (key, value) VALUES ('seeded', ?)", (_now(),)
            )
            conn.commit()
            logger.info("Feature-grant seeding complete (existing admins granted all features).")
    # Grandfather: existing grant-holders + super-admins → approved (own guard key,
    # since 'seeded' may already be set on a live deployment). Idempotent.
    with closing(_conn()) as conn:
        done = conn.execute(
            "SELECT value FROM feature_grants_meta WHERE key = 'users_grandfathered'").fetchone()
        if not done:
            users = {r["username"] for r in conn.execute(
                "SELECT DISTINCT username FROM feature_grants").fetchall()}
            users.update(_norm(a) for a in settings.super_admin_list)
            for u in users:
                if not u:
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO app_users (username, status, first_seen, approved_at, approved_by) "
                    "VALUES (?, 'approved', ?, ?, 'seed')", (u, _now(), _now()))
                if cur.rowcount:
                    _audit(conn, "seed", "approve", u, "-")
            conn.execute(
                "INSERT OR REPLACE INTO feature_grants_meta (key, value) VALUES ('users_grandfathered', ?)",
                (_now(),))
            conn.commit()
