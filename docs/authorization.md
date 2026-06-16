# Authorization — feature grants & the super admin

Access is a **per-user × per-feature matrix**, managed by a **super admin**. A
feature is a card/page/tool; a user sees and can use only the features granted to
them (deny-by-default), except the **Chat** baseline which is open to any
authenticated user.

## Roles

- **Super admin** — defined in **config** (`SUPER_ADMINS`, comma-separated emails;
  seeded with `anton.partono@koop.overheid.nl`). Holds **every** feature
  implicitly and is the **only** role that can manage the matrix. Config-based so
  it can never be revoked through the UI (no lock-out).
- **Granted user** — any logged-in user with one or more feature grants.
- **Everyone else** — Chat only.

## Feature catalog (matrix columns)

Code-defined in `permissions.CATALOG`: `dashboard`, `certificates`, `outcomes`,
`pipeline_health`, `aanleverfouten`, `documents`, `regression`, `settings`.
Baseline (always open): `chat`. Super-only (not grantable): `authorization`.
Adding a card/tool = adding one catalog entry.

## Enforcement (defense in depth)

- **Backend is the source of truth.** Each endpoint is guarded by
  `auth.require_feature("<key>")`; the matrix manager endpoints by
  `auth.require_super`. A request for an ungranted feature → **403**.
- **Frontend reflects it.** `GET /me/permissions` returns
  `{ is_super, features[], catalog }`; the UI renders only granted pages/cards
  (`can(feature)`), so nothing ungranted is even shown.

## Management

Super admin → **Beheer → 🔐 Autorisatie**: a grid of users (rows) × features
(columns). Check a box to grant, uncheck to revoke — effective immediately. Add a
user **by email** to pre-authorise them before their first login. A **change log**
records every grant/revoke (who, what, when).

## Storage

In the shared `kibana_oo.db` (see [database.md](database.md)):
`feature_grants` (one row per user+feature) and `feature_grants_audit`.

## Rollout / migration

On first start, `permissions.ensure_seeded()` runs once: every existing
`DASHBOARD_ADMINS` user is **granted all features** so nothing breaks on
deploy — then the super admin narrows access deliberately. (Super admins need no
rows; they have everything.)

## API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/me/permissions` | any session | The caller's features + is_super |
| GET | `/admin/grants` | super | The full matrix |
| POST | `/admin/grants` | super | Grant `{username, feature}` |
| DELETE | `/admin/grants` | super | Revoke `{username, feature}` |
| GET | `/admin/grants/audit` | super | Recent grant/revoke log |

## Config (`.env`)

```
SUPER_ADMINS=anton.partono@koop.overheid.nl
DASHBOARD_ADMINS=...        # seeded to all features on first run
```
