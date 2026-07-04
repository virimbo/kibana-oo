---
title: Autorisatie
tags: [beheer, autorisatie, security, nl]
aliases: [Autorisatie, Authorization, Approval gate, Goedkeuring]
component: authorization
purpose-business: Nieuwe gebruikers krijgen pas toegang nadat de super-admin ze goedkeurt; per gebruiker is per functie te bepalen wat ze mogen.
purpose-technical: Deny-by-default grant-matrix + een approval-gate (app_users status pending/approved/suspended) afgedwongen in has_feature/user_features, met grandfather + super-admin fail-safe.
related: [Navigatie, AI-architectuur, Monitoring targets]
owner: KOOP Beheer
category: "Beheer & configuratie"
created: 2026-06-27
updated: 2026-07-01
---

# Autorisatie

> 🇳🇱 Twee lagen: (1) een **approval-gate** — een nieuwe gebruiker heeft **geen
> toegang** totdat de super-admin (`anton.partono@koop.overheid.nl`) hem goedkeurt;
> (2) de **grant-matrix** — per gebruiker × per functie bepalen wat hij mag. Beide
> beheer je op **Beheer → Autorisatie** (alleen super-admin).

Gerelateerd: [[Navigatie]] · [[AI-architectuur]]

---

## De approval-gate

**Hoe het werkt**
1. Iemand logt in via SP/Keycloak. Onbekende gebruiker → automatisch geregistreerd
   als **`pending`** (geen handmatige invoer nodig). Inloggen lukt wél — we gaten
   *autorisatie*, niet *authenticatie*.
2. **`pending` = nul toegang** — ook geen chat. De gebruiker ziet alleen het scherm
   *"In afwachting van goedkeuring"*.
3. De super-admin ziet de gebruiker bovenaan **Beheer → Autorisatie** in de sectie
   **In afwachting van goedkeuring** en klikt **Goedkeuren**.
4. **`approved`** → de gebruiker krijgt de chat-baseline + wat de matrix toekent.
   De **active-toggle** in de matrix zet dezelfde gebruiker desgewenst op
   **`suspended`** (toegang direct weg; de grants blijven bewaard, dus opnieuw
   goedkeuren herstelt alles — handig bij offboarding).

**Status per gebruiker:** `pending` (amber) · `approved` (groen) · `suspended` (grijs)
· super-admin (altijd toegang).

## Afdwinging (server-side)

De gate zit in `permissions.py`: zowel `has_feature()` als `user_features()` geven
**niets** terug voor een niet-goedgekeurde gebruiker (na de `is_super`-short-circuit).
Daardoor weigeren álle feature-endpoints automatisch; de chat-endpoint heeft een
expliciete 403-guard. `/me/permissions` bevat een `approved`-vlag waar de frontend
het wachtscherm op toont.

## Veiligheid & migratie (niemand wordt buitengesloten)

- **Super-admin fail-safe:** `is_super` levert overal `approved` — de super-admin kan
  zichzelf nooit buitensluiten, ook niet als de `app_users`-tabel leeg is.
- **Grandfather (eenmalig bij opstart):** elke gebruiker die al een grant heeft +
  alle super-admins → `approved`. Alleen écht nieuwe gebruikers komen op `pending`.
  Eigen meta-vlag (`users_grandfathered`), dus draait ook op een bestaande deploy.
- **Audit:** elke auto-registratie / goedkeuring / blokkade staat in
  `feature_grants_audit`.

## De grant-matrix

Per gebruiker een rij; per functie (kaart/tool uit de `CATALOG`) een vinkje:
aanvinken = toegang geven, uitvinken = intrekken. **Deny-by-default**: zonder grant
geen toegang (chat is de baseline, maar óók die vereist eerst goedkeuring). Het recht
om de matrix te beheren is super-admin-only.

## Data & bestanden

- `app_users (username, status, first_seen, approved_at, approved_by)` — de approval-status.
- `feature_grants` — de matrix; `feature_grants_audit` — het wijzigingslog.
- Backend: `backend/permissions.py` (status + gate + grandfather), `backend/main.py`
  (`record_login`, `/chat`-guard, `/admin/users` approve/suspend, `approved` in
  `/me/permissions`). Frontend: `frontend/src/Authorization.jsx` (sectie + toggle),
  `frontend/src/App.jsx` (wachtscherm).

## Later (roadmap)

Rol-/template-presets (Viewer/Operator/Admin), pre-provisioning (een gebruiker
uitnodigen vóór de eerste login), e-mailmelding aan de super-admin bij een nieuwe
`pending`, en een nav-badge met het aantal openstaande goedkeuringen (nu toont de
sectiekop het aantal).

## Super-admins configureren (SUPER_ADMINS)

Super-admins worden **niet** meer in de source vastgelegd, maar via de omgeving:
`SUPER_ADMINS` in `.env` (comma-gescheiden). Elke waarde moet **exact** overeenkomen
met wat die persoon bij de **SP/Keycloak-login** typt (het e-mailadres).

```
SUPER_ADMINS=anton.partono@koop.overheid.nl,anton.partono@logius.nl
```

- **Primair:** `anton.partono@koop.overheid.nl`
- **Backup:** `anton.partono@logius.nl` — meerdere super-admins = geen single point of
  failure (de een kan de ander herstellen).
- ⚠️ **Leeg = géén super-admin** (lock-out): zet dit dus in **productie** in `.env`.
  `.env` is gitignored; `.env.example` documenteert de variabele.
- Een super-admin heeft **volledige controle** en is overal `approved` (fail-safe).
