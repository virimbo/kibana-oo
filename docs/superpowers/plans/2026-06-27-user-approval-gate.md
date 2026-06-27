# User Approval Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New users who authenticate via SP/Keycloak land in `pending` with zero access until the super-admin approves them with a single toggle (which doubles as suspend); existing users + super-admins are grandfathered so nobody is locked out.

**Architecture:** A new `app_users` status table + helpers in `permissions.py`; the gate is enforced at `has_feature()` + `user_features()` (after the `is_super` short-circuit) plus an explicit `/chat` guard; new super-admin `/admin/users` endpoints; a frontend pending screen + an Authorization approval section + a nav badge. Additive; `is_super` always resolves to approved (fail-safe); grandfather runs once on boot.

**Tech Stack:** Python 3.13 / FastAPI / sqlite3 (`db.py`), React 19 / Vite, pytest in `python:3.13` Docker.

**Spec:** `docs/superpowers/specs/2026-06-27-user-approval-gate-design.md`
**Branch:** `feat/user-approval-gate` (already created).

---

## Conventions

**Backend tests** (repo root):
```bash
cd /c/ANT-PROJECT/KIBANA-OO/backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 \
  docker run --rm -v "$HP:/app" -w /app python:3.13 sh -c \
  "pip install -q -r requirements.txt && python -m pytest tests/<FILE> -q"
```
**Frontend build:**
```bash
cd /c/ANT-PROJECT/KIBANA-OO/frontend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 \
  docker run --rm -v "$HP:/app" -w /app node:20 sh -c "npm install --no-audit --no-fund && npm run build" 2>&1 | tail -6
```
Test DB isolation: per-test `monkeypatch.setattr(settings, "app_db_path", str(tmp_path/"t.db"))` (NO module-level mutation), matching `backend/tests/test_monitor_api.py`.

**Current shapes (verified):**
- `permissions.has_feature(session, feature)` — `is_super`→True (l.97); `feature in BASELINE`→True (l.99); else grant check. **Gate goes right after the is_super check (l.98).**
- `permissions.user_features(username)` — `is_super`→all (l.119); else grants. **Gate after l.120.**
- `permissions.ensure_seeded()` — idempotent, guarded by meta key `'seeded'` (already set on live deployments → grandfather needs its OWN meta key).
- `permissions._conn()` runs `_SCHEMA` per connect (lazy). `_norm(u)`, `_now()`, `_audit(conn, actor, action, user, feature)` exist.
- `/chat` is `Depends(require_session)` (NOT require_feature) → needs an explicit approval guard.

---

# PHASE 1 — Status model + gate (`permissions.py`)

### Task 1: `app_users` schema + status helpers

**Files:** Modify `backend/permissions.py`; Test `backend/tests/test_approval.py`

- [ ] **Step 1: Write the failing test** — `backend/tests/test_approval.py`:
```python
import pytest
from config import settings
import permissions as p

@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_db_path", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings, "super_admins", "boss@koop.nl")  # is_super source
    yield

def test_record_login_registers_unknown_as_pending():
    assert p.record_login("new.user@koop.nl") == "pending"
    assert p.user_status("new.user@koop.nl") == "pending"

def test_super_admin_always_approved():
    assert p.record_login("boss@koop.nl") == "approved"
    assert p.user_status("boss@koop.nl") == "approved"
    assert p.is_approved("boss@koop.nl") is True

def test_approve_and_suspend_transitions():
    p.record_login("u@koop.nl")
    p.approve("u@koop.nl", actor="boss@koop.nl")
    assert p.user_status("u@koop.nl") == "approved" and p.is_approved("u@koop.nl") is True
    p.suspend("u@koop.nl", actor="boss@koop.nl")
    assert p.user_status("u@koop.nl") == "suspended" and p.is_approved("u@koop.nl") is False

def test_list_users_includes_status():
    p.record_login("a@koop.nl")
    rows = {r["username"]: r for r in p.list_users()}
    assert rows["a@koop.nl"]["status"] == "pending"

def test_is_approved_failsafe_when_table_empty():
    # super-admin approved even with no app_users rows at all
    assert p.is_approved("boss@koop.nl") is True
```
> `settings.super_admins` is the super-admin source; confirm the exact attribute name in `config.py`/`permissions.is_super` and adjust the monkeypatch if it differs (e.g. `super_admin_list`). Set it so `is_super("boss@koop.nl")` is True.

- [ ] **Step 2: Run → FAIL** (`AttributeError: module 'permissions' has no attribute 'record_login'`).

- [ ] **Step 3: Implement** — add to `backend/permissions.py`. First extend `_SCHEMA` (append inside the triple-quoted `_SCHEMA` string, before its closing `"""`):
```sql
CREATE TABLE IF NOT EXISTS app_users (
  username    TEXT PRIMARY KEY,
  status      TEXT NOT NULL DEFAULT 'pending',
  first_seen  TEXT NOT NULL,
  approved_at TEXT,
  approved_by TEXT
);
```
Then add the helpers (near the other grant helpers):
```python
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
```

- [ ] **Step 4: Run → PASS** (5 tests). Fix until green.

- [ ] **Step 5: Commit**
```bash
cd /c/ANT-PROJECT/KIBANA-OO && git add backend/permissions.py backend/tests/test_approval.py
git commit -m "feat(auth): app_users status model (record_login/approve/suspend/list_users)"
```

### Task 2: The gate — `has_feature` + `user_features` deny non-approved

**Files:** Modify `backend/permissions.py`; Modify `backend/tests/test_approval.py`

- [ ] **Step 1: Add failing tests:**
```python
def test_pending_user_has_no_features(tmp_path, monkeypatch):
    p.record_login("u@koop.nl")
    p.grant("u@koop.nl", "dashboard", actor="boss@koop.nl")  # granted but NOT approved
    assert p.user_features("u@koop.nl") == []                # gate: nothing until approved
    assert p.has_feature({"username": "u@koop.nl"}, "dashboard") is False
    assert p.has_feature({"username": "u@koop.nl"}, "chat") is False   # baseline gated too

def test_approved_user_gets_features_and_baseline():
    p.record_login("u2@koop.nl")
    p.approve("u2@koop.nl", actor="boss@koop.nl")
    p.grant("u2@koop.nl", "dashboard", actor="boss@koop.nl")
    assert "dashboard" in p.user_features("u2@koop.nl")
    assert p.has_feature({"username": "u2@koop.nl"}, "chat") is True
    assert p.has_feature({"username": "u2@koop.nl"}, "dashboard") is True

def test_super_admin_unaffected_by_gate():
    assert p.has_feature({"username": "boss@koop.nl"}, "chat") is True
    assert "dashboard" in p.user_features("boss@koop.nl")
```

- [ ] **Step 2: Run → FAIL** (pending user still has features).

- [ ] **Step 3: Implement the gate.** In `has_feature`, add the approval check immediately AFTER the `is_super` short-circuit (after `if is_super(username): return True`, before `if feature in BASELINE`):
```python
    if not is_approved(username):
        return False
```
In `user_features`, add immediately AFTER the `is_super` short-circuit (after `if is_super(username): return list(GRANTABLE)`):
```python
    if not is_approved(username):
        return []
```

- [ ] **Step 4: Run → PASS** (the 3 new + the 5 from Task 1). Fix until green.

- [ ] **Step 5: Commit**
```bash
cd /c/ANT-PROJECT/KIBANA-OO && git add backend/permissions.py backend/tests/test_approval.py
git commit -m "feat(auth): gate has_feature + user_features on approval (deny pending/suspended)"
```

### Task 3: Grandfather migration in `ensure_seeded`

**Files:** Modify `backend/permissions.py`; Modify `backend/tests/test_approval.py`

- [ ] **Step 1: Add failing test:**
```python
def test_grandfather_marks_existing_grant_holders_approved():
    p.grant("legacy@koop.nl", "dashboard", actor="seed")   # a pre-existing user with a grant
    p.ensure_seeded()
    assert p.user_status("legacy@koop.nl") == "approved"    # grandfathered, not locked out
    # a brand-new user (no grant) is NOT auto-approved by grandfather:
    p.record_login("fresh@koop.nl")
    assert p.user_status("fresh@koop.nl") == "pending"
```

- [ ] **Step 2: Run → FAIL** (legacy user still pending after seed).

- [ ] **Step 3: Implement.** In `ensure_seeded()`, ADD a separate idempotent grandfather block (its own meta key, because `'seeded'` is already set on live deployments). Put it at the END of `ensure_seeded`, after the existing seeding/commit, as its own guarded block:
```python
    # Grandfather: existing grant-holders + super-admins → approved (own guard key,
    # since 'seeded' may already be set on a live deployment).
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
```
> Confirm the super-admin list attribute name (`settings.super_admin_list`) matches `is_super`; adjust if it's named differently.

- [ ] **Step 4: Run → PASS** (full `test_approval.py`). **Step 5: Commit** `feat(auth): grandfather existing users + super-admins on boot (fail-safe)`.

---

# PHASE 2 — Enforcement wiring + API (`main.py`)

### Task 4: `record_login` on the login path + `approved` in `/me/permissions`

**Files:** Modify `backend/main.py`; Test `backend/tests/test_approval_api.py`

- [ ] **Step 1:** Read `backend/main.py` — find the login endpoint (where, after a successful SP/Keycloak auth, `create_session(...)` is called and the username is known) and the `/me/permissions` handler (`my_permissions`).

- [ ] **Step 2: Write failing test** `backend/tests/test_approval_api.py` — use the super-admin auth pattern from `backend/tests/test_monitor_api.py` (inject a session into `session._sessions` + `Authorization: Bearer <tok>` header, set `settings.super_admins`). Per-test tmp db. Tests:
```python
# (setup mirrors test_monitor_api.py: TestClient(main.app), settings.super_admins,
#  session._sessions["tok"]={"username":...,"sid":...}, headers={"Authorization":"Bearer tok"})

def test_me_permissions_has_approved_flag(approved_super_headers):
    r = client.get("/me/permissions", headers=approved_super_headers)
    assert r.status_code == 200 and r.json().get("approved") is True
```

- [ ] **Step 3: Implement:**
  (a) In the login endpoint, right after the username is authenticated and before returning the token, add: `permissions.record_login(username)` (use the same `username` var the session is created with). Login still returns the token for pending users.
  (b) In `my_permissions`, add `"approved": permissions.is_approved(username)` to the returned dict.

- [ ] **Step 4: Run → PASS.** **Step 5: Commit** `feat(auth): record_login on login + approved flag in /me/permissions`.

### Task 5: `/chat` approval guard + `/admin/users` endpoints

**Files:** Modify `backend/main.py`; Modify `backend/tests/test_approval_api.py`

- [ ] **Step 1: Add failing tests:**
```python
def test_pending_user_blocked_from_chat(pending_headers):
    # pending_headers = a session whose username is registered pending (not super, no approval)
    r = client.post("/chat", headers=pending_headers, json={"question": "hi", "stream": False})
    assert r.status_code == 403

def test_admin_users_list_and_approve(approved_super_headers):
    # register a pending user via record_login, then approve via the endpoint
    import permissions
    permissions.record_login("pend@koop.nl")
    r = client.get("/admin/users", headers=approved_super_headers)
    assert any(u["username"] == "pend@koop.nl" and u["status"] == "pending" for u in r.json())
    r2 = client.post("/admin/users/pend@koop.nl/approve", headers=approved_super_headers)
    assert r2.status_code == 200
    assert permissions.user_status("pend@koop.nl") == "approved"
    r3 = client.post("/admin/users/pend@koop.nl/suspend", headers=approved_super_headers)
    assert permissions.user_status("pend@koop.nl") == "suspended"
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** in `backend/main.py`:
  (a) In the `/chat` handler (and any streaming chat handler), at the very top after the session dependency resolves, add:
```python
    if not permissions.is_approved(session.get("username")):
        raise HTTPException(status_code=403, detail="Account in afwachting van goedkeuring")
```
  (b) Add the admin endpoints near the existing `/admin/grants` ones (same `require_super` dependency + `session.get("username")` as actor):
```python
@app.get("/admin/users")
async def admin_users(session: dict = Depends(require_super)):
    return permissions.list_users()

@app.post("/admin/users/{username}/approve")
async def admin_user_approve(username: str, session: dict = Depends(require_super)):
    permissions.approve(username, session.get("username"))
    return {"ok": True, "status": "approved"}

@app.post("/admin/users/{username}/suspend")
async def admin_user_suspend(username: str, session: dict = Depends(require_super)):
    permissions.suspend(username, session.get("username"))
    return {"ok": True, "status": "suspended"}
```

- [ ] **Step 4: Run → PASS, then full suite green:**
```bash
cd /c/ANT-PROJECT/KIBANA-OO/backend && HP=$(pwd -W) && MSYS_NO_PATHCONV=1 docker run --rm -v "$HP:/app" -w /app python:3.13 sh -c "pip install -q -r requirements.txt && python -m pytest tests/ -q"
```
- [ ] **Step 5: Commit** `feat(auth): /chat approval guard + /admin/users approve/suspend endpoints`. **This completes the backend — ship PR 1** (push → PR → merge → mirror; body references the spec).

---

# PHASE 3 — Frontend pending screen

### Task 6: PendingApproval screen (`App.jsx`) + api.js

**Files:** Modify `frontend/src/App.jsx`; Modify `frontend/src/api.js`

- [ ] **Step 1:** In `frontend/src/api.js` add (after the existing exports):
```js
export const fetchUsers = (token) => getJSON("/admin/users", token);
export const approveUser = (token, username) => sendJSON(`/admin/users/${encodeURIComponent(username)}/approve`, token, "POST", {});
export const suspendUser = (token, username) => sendJSON(`/admin/users/${encodeURIComponent(username)}/suspend`, token, "POST", {});
```

- [ ] **Step 2:** In `frontend/src/App.jsx`, find where `/me/permissions` is fetched into state (the object has `is_super`, `features`, `catalog` — it now also has `approved`). After login, when `me.approved === false && !me.is_super`, render a dedicated screen INSTEAD of the app shell. Add a small component:
```jsx
function PendingApproval({ username, onLogout }) {
  return (
    <div className="login-page login-page--gx">
      <div className="gx-hero" style={{ textAlign: "center", margin: "auto" }}>
        <span className="gx-eyebrow">• TOEGANG</span>
        <h1 className="gx-h1">In afwachting van goedkeuring</h1>
        <p className="gx-sub">
          Je account ({username}) is aangemaakt en wacht op goedkeuring door de beheerder
          (anton.partono@koop.overheid.nl). Je krijgt toegang zodra je bent goedgekeurd.
        </p>
        <button type="button" className="gx-cta" onClick={onLogout}>Afmelden</button>
      </div>
    </div>
  );
}
```
Render it: in the main render branch, before the authenticated app shell, add `if (me && me.approved === false && !me.is_super) return <PendingApproval username={me.username} onLogout={handleLogout} />;` (match the exact state var names the file uses for the permissions object + logout handler).

- [ ] **Step 3: Build-green** (frontend build command). Manually: a pending user sees the screen; an approved user sees the app.
- [ ] **Step 4: Commit** `feat(auth): pending-approval screen for unapproved users`.

---

# PHASE 4 — Authorization approval UI + nav badge

### Task 7: Pending section + approve/suspend toggle (`Authorization.jsx`) + nav badge (`Nav.jsx`)

**Files:** Modify `frontend/src/Authorization.jsx`, `frontend/src/Nav.jsx`

- [ ] **Step 1:** Read `frontend/src/Authorization.jsx` (the matrix page) and `frontend/src/Nav.jsx` (`BEHEER_SUB` + how a badge/count could be shown; check if any nav item already shows a count, e.g. stuck/dlq badges).

- [ ] **Step 2 (Authorization.jsx):** Load users via `fetchUsers(token)` alongside the existing matrix fetch. Add, ABOVE the matrix, a `.gx-panel` section:
  - Heading `.gx-h2` "In afwachting van goedkeuring" + InfoTip (inlined, like ServiceHealth's) explaining new users need approval.
  - For each user with `status === "pending"`: a row (username · first_seen) + a **Goedkeuren** `.gx-cta` calling `approveUser(token, username)` then refetch. Empty state `<p className="muted">Geen gebruikers in afwachting.</p>`.
  - In the existing matrix, for each user row add a **status pill** (`approved`→ok/`pending`→warn/`suspended`→muted, reuse existing pill classes) and an **active `.switch`** (on=approved, off=suspended): on→off calls `suspendUser`, off→on calls `approveUser`, then refetch. Dim a suspended user's feature checkboxes (visual only — keep the existing grant handlers/data keys UNCHANGED).
  - Refetch users + matrix after every mutation.

- [ ] **Step 3 (Nav.jsx):** Show a small count badge on the Authorization `BEHEER_SUB` entry = number of pending users (super-admin only). Fetch the count via `fetchUsers` (filter `status==="pending"`) where the nav already has the token, OR lift it from the Authorization page through existing props — match how other nav counts (e.g. stuckCount/dlqCount, already passed into Nav) are wired; add a `pendingCount` prop the same way and render the badge with the existing badge markup/CSS.

- [ ] **Step 4: Build-green.** Manually: pending users appear in the section; Goedkeuren activates them (they vanish from pending, appear approved in the matrix); the suspend toggle works; the nav badge shows the count.
- [ ] **Step 5: Commit** `feat(auth): Authorization approval section + suspend toggle + nav badge`.

---

# PHASE 5 — Docs, deploy, ship PR 2

### Task 8: Vault note + deploy + ship

**Files:** Modify/Create the authorization vault note (find it: `docs/KIBANA-OO/Autorisatie.md` or similar; if none, create one)

- [ ] **Step 1:** Document the approval gate in the auth vault note (NL): new users are `pending` until the super-admin approves; approve/suspend toggle; grandfather + super-admin fail-safe; the `app_users` table. Link `[[AI-architectuur]]`.
- [ ] **Step 2:** Full backend suite + frontend build → green.
- [ ] **Step 3:** Deploy `docker compose up -d --build backend frontend`. Smoke-test: confirm boot clean; `GET /me/permissions` carries `approved`; an unapproved session is 403'd on `/chat`; the Authorization page shows the pending section. (You can register a throwaway pending user via the login path or by calling `permissions.record_login` in the container to verify the gate end-to-end.)
- [ ] **Step 4: Commit** `docs(auth): approval gate note`.
- [ ] **Step 5: Ship PR 2** (push → PR → merge → checkout main → pull → push gitlab main → delete branch).

---

## Self-review

- **Spec coverage:** §3 data model → Task 1. §4 status fns + gate + grandfather → Tasks 1–3. §5 enforcement (record_login, /me approved, /chat guard, /admin/users) → Tasks 4–5. §6 frontend pending screen → Task 6; approval UI + nav badge → Task 7; api.js → Tasks 6–7. §8 testing → each task TDD + full-suite gate (Task 5). §9 safety (is_super short-circuit, grandfather, rollback=one gate line) → Tasks 1–3. docs → Task 8. No gaps.
- **Placeholder scan:** none — concrete schema, function bodies, gate insertions (exact anchor lines), endpoints, and frontend recipe with the component code. Frontend tasks give the API contract + the template files to mirror (ServiceHealth/Settings) rather than full JSX, which is the right altitude.
- **Type/name consistency:** `record_login`, `user_status`, `is_approved`, `approve`, `suspend`, `list_users`, `_set_status`; gate inserts in `has_feature`/`user_features`; meta key `'users_grandfathered'`; endpoints `/admin/users[/{username}/approve|suspend]`; `/me/permissions` `approved`; api.js `fetchUsers/approveUser/suspendUser`; statuses `pending|approved|suspended` — all consistent across tasks.
- **Implementer notes:** confirm the super-admin settings attribute name (`super_admins`/`super_admin_list`) against `permissions.is_super`/`config.py` and use it consistently. PR split: Phase 1–2 (backend) = PR 1; Phases 3–5 (frontend+docs) = PR 2 — same two-PR rhythm as the monitoring feature.
