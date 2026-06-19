# Authorization — feature grants & de super admin

Toegang is een **per-user × per-feature matrix**, beheerd door een **super admin**.
Een feature is een card/page/tool; een gebruiker ziet en kan alleen de features
gebruiken die aan hem zijn granted (deny-by-default), behalve de **Chat**-baseline die
open is voor elke geauthenticeerde gebruiker.

## Rollen

- **Super admin** — gedefinieerd in **config** (`SUPER_ADMINS`, komma-gescheiden
  e-mails; geseed met `anton.partono@koop.overheid.nl`). Bezit **elke** feature
  impliciet en is de **enige** rol die de matrix kan beheren. Config-based zodat die
  nooit via de UI ingetrokken kan worden (geen lock-out).
- **Granted user** — elke ingelogde gebruiker met één of meer feature-grants.
- **Iedereen anders** — alleen Chat.

## Feature-catalogus (matrix-kolommen)

Code-defined in `permissions.CATALOG`: `dashboard`, `certificates`, `outcomes`,
`pipeline_health`, `aanleverfouten`, `documents`, `regression`, `settings`.
Baseline (altijd open): `chat`. Super-only (niet grantbaar): `authorization`.
Een card/tool toevoegen = één catalogus-entry toevoegen.

## Enforcement (defense in depth)

- **De backend is de source of truth.** Elk endpoint wordt bewaakt door
  `auth.require_feature("<key>")`; de matrix-manager-endpoints door
  `auth.require_super`. Een request voor een niet-granted feature → **403**.
- **De frontend weerspiegelt het.** `GET /me/permissions` geeft
  `{ is_super, features[], catalog }`; de UI rendert alleen granted pages/cards
  (`can(feature)`), zodat niets niet-granted überhaupt getoond wordt.

## Beheer

Super admin → **Beheer → 🔐 Autorisatie**: een grid van users (rows) × features
(kolommen). Vink een vakje aan om te granten, uit om in te trekken — direct effectief.
Voeg een user **op e-mail** toe om hem vooraf te autoriseren vóór zijn eerste login.
Een **change log** registreert elke grant/revoke (wie, wat, wanneer).

## Opslag

In de gedeelde `kibana_oo.db` (zie [database.md](database.md)):
`feature_grants` (één row per user+feature) en `feature_grants_audit`.

## Rollout / migratie

Bij de eerste start draait `permissions.ensure_seeded()` één keer: elke bestaande
`DASHBOARD_ADMINS`-user wordt **granted op alle features** zodat niets breekt bij
deploy — daarna versmalt de super admin de toegang bewust. (Super admins hebben geen
rows nodig; zij hebben alles.)

## API

| Method | Path | Auth | Doel |
|---|---|---|---|
| GET | `/me/permissions` | any session | De features + is_super van de caller |
| GET | `/admin/grants` | super | De volledige matrix |
| POST | `/admin/grants` | super | Grant `{username, feature}` |
| DELETE | `/admin/grants` | super | Revoke `{username, feature}` |
| GET | `/admin/grants/audit` | super | Recente grant/revoke-log |

## Config (`.env`)

```
SUPER_ADMINS=anton.partono@koop.overheid.nl
DASHBOARD_ADMINS=...        # seeded to all features on first run
```
