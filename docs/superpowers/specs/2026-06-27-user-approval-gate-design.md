# User Approval Gate — Design Spec

- **Date:** 2026-06-27
- **Status:** Approved design (Q1 A · Q2 A · Q3 A), ready for implementation plan
- **Author:** Anton Partono (with Claude)
- **Trigger:** New users must be explicitly approved by the super-admin
  (`anton.partono@koop.overheid.nl`) before they get *any* access — a single
  approve/suspend toggle on the Authorization page, with new users surfaced automatically.

## 1. Goal

Add an **approval gate** on top of the existing per-user × per-feature grant matrix: a new
user who authenticates via SP/Keycloak lands in **`pending`** with **zero access** until the
super-admin **approves** them. The Authorization page surfaces pending users (with a nav
count badge); approve is one toggle that doubles as **suspend**. Existing users and
super-admins are **grandfathered** so nobody is locked out.

**Hard constraints:**
- **Fail-safe:** `is_super` always resolves to approved — the super-admin can never be
  locked out. If the users table is empty/unreadable, super-admins still get in.
- **Grandfather:** on migration, every user who already holds a grant + all super-admins
  are marked `approved`. No current user loses access.
- **Additive where possible**; the targeted edits to existing auth code (`permissions.py`,
  the login path, `Authorization.jsx`) are exactly the requested change and are covered by
  the grandfather + fail-safe guarantees. FROZEN cert/Mistral code is untouched.

## 2. Decisions (the 3 questions)

1. **(Q1 A) Pending = zero access** — not even the `chat` baseline; the user only sees an
   "Account in afwachting van goedkeuring" screen until approved.
2. **(Q2 A) Auto-register on first login** — unknown authenticated user → recorded as
   `pending` automatically; they appear in the super-admin's queue. No allowlist/manual entry.
3. **(Q3 A) Approve = activate only** — approving grants the `chat` baseline; features are
   still granted per-user via the existing matrix. The same toggle off → `suspended`
   (access revoked, grants kept for easy re-enable).

## 3. Data model (additive, shared `kibana_oo.db` via `db.py`)

```sql
CREATE TABLE IF NOT EXISTS app_users (
  username    TEXT PRIMARY KEY,         -- normalised (lower, trimmed)
  status      TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'approved' | 'suspended'
  first_seen  TEXT NOT NULL,
  approved_at TEXT,
  approved_by TEXT
);
```

Transitions are written to the existing `feature_grants_audit` table with `action` values
`auto_register` | `approve` | `suspend` (target_user = the user, feature = `"-"`).

## 4. Backend — `permissions.py` (status model + the gate)

New functions (additive; place near the existing grant helpers):
- `record_login(username) -> str` — called on each successful login. Normalises; if unknown,
  INSERT `status='pending'` + audit `auto_register`; returns the current status. Super-admins
  are recorded as `approved` (idempotent).
- `user_status(username) -> str` — `'approved'` for super-admins (short-circuit); else the
  row's status, or `'pending'` if unknown.
- `is_approved(username) -> bool` — `is_super(u) or user_status(u) == 'approved'`.
- `approve(username, actor)` / `suspend(username, actor)` — upsert status + `approved_at`/
  `approved_by` + audit. (`approve` of an unknown user creates an approved row.)
- `list_users() -> list[dict]` — every known user with `{username, status, first_seen,
  approved_at, approved_by, is_super}` for the Authorization page (drives the pending section
  + status pills). Super-admins are always shown as approved.

**The gate** — modify `user_features(username)` so it returns **`[]`** when the user is not
approved (no baseline, no grants). Super-admins keep all features (their path already
short-circuits). This single change makes every `require_feature(...)` endpoint deny for
pending/suspended users automatically.

**Grandfather** — in the existing `ensure_seeded()` (runs once on boot): for every distinct
`username` in `feature_grants`, upsert `app_users` as `approved` (if not already present);
ensure all `super_admin_list` users are `approved`. Audit as `approve` (actor `"seed"`).

## 5. Backend — enforcement points (`main.py` / `auth.py`)

- **Login path** (where the session is created after a successful SP/Keycloak auth): call
  `permissions.record_login(username)`. Login still SUCCEEDS for pending users (they must
  reach the pending screen) — we gate *authorization*, not *authentication*.
- **`/me/permissions`** — add `"approved": permissions.is_approved(username)` to the
  response. (Frontend renders the pending screen off this.)
- **Chat endpoint(s)** (`/chat` and any streaming variant) — these are `require_session`-gated,
  not `require_feature`, so add an explicit guard: `if not permissions.is_approved(user):
  raise HTTPException(403, "Account in afwachting van goedkeuring")`. (All feature-gated
  endpoints are already covered by the empty `user_features`.)
- **New admin endpoints** (super-admin, `require_super`):
  - `GET /admin/users` → `permissions.list_users()`
  - `POST /admin/users/{username}/approve` → `permissions.approve(username, actor)`
  - `POST /admin/users/{username}/suspend` → `permissions.suspend(username, actor)`

## 6. Frontend

### 6.1 Pending screen (`App.jsx`)
After login, the app already fetches `/me/permissions`. When `approved === false` and the
user is not super, render a dedicated **PendingApproval** view (OO-GX styled) instead of the
app shell: a `.gx-hero` with eyebrow `• TOEGANG`, headline *"In afwachting van goedkeuring"*,
a Dutch explanation ("Je account is aangemaakt en wacht op goedkeuring door de beheerder
(anton.partono@koop.overheid.nl). Je krijgt toegang zodra je bent goedgekeurd."), and a
**Afmelden** button. No nav, no cards, no chat.

### 6.2 Authorization page (`Authorization.jsx`)
- **New "In afwachting van goedkeuring" `.gx-panel` at the top**: lists users with
  `status === 'pending'` (from `GET /admin/users`); each row = username + first-seen +
  an **Goedkeuren** `.gx-cta`/toggle (`POST …/approve`) + an InfoTip. Empty state:
  *"Geen gebruikers in afwachting."*
- **Existing matrix**: add a per-user **status pill** (`approved`/`suspended`/`pending`) and
  an **active toggle** (`.switch`) that approves (off→on) or suspends (on→off). A suspended
  user's feature checkboxes are visually dimmed (grants kept, just inactive). The matrix
  data keys/handlers stay unchanged — this is additive.
- Refetch users + matrix after each mutation.

### 6.3 Nav badge (`Nav.jsx`)
A small count badge on the Authorization item showing the number of pending users (super-admin
only). Driven by a lightweight `GET /admin/users` count (or a dedicated `/admin/users/pending-count`).
The "intelligence": new users announce themselves.

### 6.4 api.js
`fetchUsers`, `approveUser`, `suspendUser` (+ a pending-count helper) via the existing
`getJSON`/`sendJSON` wrappers.

## 7. Files

| File | Responsibility | Action |
|---|---|---|
| `backend/permissions.py` | `app_users` schema, status fns, gate `user_features`, grandfather | Modify (additive fns + 1 gate line + seed) |
| `backend/main.py` | `record_login` on login, chat approval guard, `/admin/users` endpoints, `/me/permissions` field | Modify (additive) |
| `frontend/src/App.jsx` | PendingApproval screen when `approved === false` | Modify |
| `frontend/src/Authorization.jsx` | pending section + status pill + approve/suspend toggle | Modify |
| `frontend/src/Nav.jsx` | pending-count badge | Modify |
| `frontend/src/api.js` | user/approval helpers | Modify (add) |
| `docs/KIBANA-OO/Autorisatie.md` (or the auth note) | document the gate | Modify/Create |

## 8. Testing

- **`permissions`:** `record_login` registers unknown → pending + audit; super-admin →
  approved; `user_features` returns `[]` for pending/suspended and the real set for approved;
  `is_approved` short-circuits for super-admins; `approve`/`suspend` transitions + audit;
  `grandfather` marks existing-grant users + super-admins approved; **fail-safe**: super-admin
  approved even with an empty `app_users` table.
- **API (TestClient, super-admin fixture):** `GET /admin/users` lists statuses;
  approve/suspend flip status; `/me/permissions` carries `approved`; a **pending** session is
  403'd on `/chat` and on any feature endpoint; an **approved** session is allowed.
- Run in the `python:3.13` Docker image with the full suite (must stay green).

## 9. Safety, rollback, additivity

- **Super-admin can never be locked out** — `is_super` → approved everywhere (short-circuit),
  independent of the `app_users` table.
- **Grandfather on boot** — existing users with grants + all super-admins → approved; only
  brand-new users are `pending`.
- **No FROZEN code touched** (cert/Mistral). The grant matrix data model/handlers are
  unchanged — status is a new, parallel concern.
- **Rollback:** the gate is one line in `user_features`; reverting it (or marking everyone
  approved) restores prior behaviour. The `app_users` table is additive and harmless if unused.
- Audit trail for every auto-register/approve/suspend.

## 10. Out of scope (YAGNI / roadmap)

Role/permission templates (Viewer/Operator/Admin presets), pre-provisioning an allowlist
(invite a user before first login), email notification to the super-admin on a new pending
user, self-service access requests with a justification note.
