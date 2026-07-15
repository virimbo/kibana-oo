---
title: "RCA - Login incident (Kibana OIDC + Docker VPN)"
category: "Runbooks"
created: 2026-07-04
updated: 2026-07-04
tags: [kibana-oo, rca, incident, login, oidc, keycloak, docker, vpn, beheer, nl]
aliases: [RCA login, Root Cause Analysis login, Kan Kibana niet bereiken, Inloggen mislukt]
---

# RCA — Inloggen mislukt (Kibana OIDC + Docker/VPN)

> **Root Cause Analysis** van het inlog-incident op **2026-07-04**. Er waren
> **drie losse oorzaken** die na elkaar zichtbaar werden. Twee waren omgeving
> (VPN/Docker en browser-cache), één was een echte **serverkant-wijziging bij
> Kibana** die een codefix vereiste. Gerelateerd: [[Runbook - wat te doen]],
> [[AI-architectuur]], [[Chat pipeline]].

## Samenvatting (TL;DR)

Inloggen faalde eerst met **"Cannot reach Kibana"** en later met **"Inloggen
mislukt"**. Onderzoek toonde **drie onafhankelijke problemen**:

1. **Netwerk** — een VPN-herverbinding brak de WSL2-netwerklaag van Docker
   Desktop; de backend-container kon de interne Kibana-host niet meer bereiken.
2. **White Screen of Death (WSOD)** — een verouderde *service worker* / cache in
   de browser serveerde dode assets na de container-herstart.
3. **Kibana-authenticatie gewijzigd (de echte hoofdoorzaak)** — KOOP heeft de
   Kibana-login serverkant veranderd: de oude login-route was uitgeschakeld en
   SSO is verhuisd. Onze app gebruikte een **hardgecodeerde** oude OIDC-provider
   en brak daardoor.

Alle drie zijn opgelost; #3 vereiste een codewijziging in `elastic.keycloak_login`.

## Impact

- **Wie:** alle gebruikers van Open Overheid – Monitoring (login volledig geblokkeerd).
- **Wat:** geen toegang tot dashboard/chat; achtergrond-monitors konden geen
  `sid` krijgen (service-sessie login faalde ook).
- **Duur:** de duur van de storing op 2026-07-04 tot de fix live stond.
- **Data:** geen dataverlies; puur toegang/authenticatie.

## Tijdlijn (wat we zagen)

1. Login-scherm: **"Cannot reach Kibana. Please check … VPN …"** — terwijl de VPN
   (`KOOP-udp-gn2`) **wél** verbonden was (`KOOP-tcp-gn3` was verbroken).
2. Docker-engine gaf **HTTP 500** op elke `docker`-opdracht → Docker Desktop zelf
   was ontregeld (WSL2-netwerk kapot na de VPN-herverbinding).
3. Na `wsl --shutdown`: containers herstart, **Kibana weer bereikbaar** (DNS →
   `10.200.131.202`, HTTPS `302`). "Cannot reach Kibana" wég.
4. Nu **WSOD** (wit scherm) in de browser → cache/service-worker opgeschoond →
   pagina rendert weer.
5. Nu **"Inloggen mislukt"**. Logs: `POST /internal/security/login → 400
   "uri … not available with the current configuration"` — Kibana wees de
   login-route af, ongeacht provider (oidc én basic).
6. Browser-test: Kibana → knop **"Log in with keycloak"** → redirect naar
   **`sso-gn2.cicd.s15m.nl/realms/SP`**, client `cicd4-elastic-prod`, callback
   `/api/security/oidc/callback`.
7. Backend-ontdekking: `GET /api/security/oidc/initiate_login?iss=<issuer>` → **302**
   naar Keycloak (dít is de nieuwe manier). Fix geschreven, getest → **sid verkregen**,
   `/login` via nginx → **200**.

## Root causes (per probleem)

### 1. "Cannot reach Kibana" — Docker/WSL2 ↔ VPN
- **Oorzaak:** Docker Desktop draait containers in **WSL2**. WSL2 erft **niet**
  automatisch de routes/DNS van een host-VPN. Een VPN die **herverbindt terwijl
  Docker draait** laat het containernetwerk verweesd achter; de engine liep vast
  (HTTP 500).
- **Waarom "VPN staat aan" niet genoeg was:** de host had de VPN, maar de
  WSL2/Docker-netwerklaag zag die niet (meer).
- **Fix:** `wsl --shutdown` → Docker Desktop herbouwt zijn WSL2-netwerk **onder de
  huidige VPN-routes**. Containers herstarten automatisch (volumes blijven).

### 2. White Screen of Death — verouderde service worker/cache
- **Oorzaak:** de browser had ooit een **service worker** geregistreerd voor
  `localhost:3000`. Na een frontend-herbouw wezen gecachte assets naar bestanden
  die niet meer bestaan → wit scherm. De huidige build heeft géén service worker,
  dus de app kon de oude niet zelf opruimen.
- **Bewijs:** serverkant was 100% gezond (`index.html` `no-cache` 200, JS-bundle
  200, `/health` 200). `/sw.js` was slechts de SPA-fallback (`index.html`).
- **Fix:** in de browser — service worker deregistreren + **site-data wissen** +
  harde refresh (Ctrl+Shift+R), of Incognito.

### 3. Inloggen mislukt — Kibana-auth serverkant gewijzigd  ⭐ hoofdoorzaak
- **Oorzaak:** KOOP heeft Kibana's authenticatie veranderd:
  - de **provider-selector route** `POST /internal/security/login` is
    **uitgeschakeld** ("not available with the current configuration");
  - **SSO is verhuisd** naar `sso-gn2.cicd.s15m.nl`, realm **`SP`**, client
    `cicd4-elastic-prod`; de provider heet nu "keycloak" (niet meer `oidc1`).
- **Waarom onze app brak:** `elastic.keycloak_login` **hardcodede** stap 1 als
  `POST /internal/security/login` met `providerName: "oidc1"`. Die route bestaat
  niet meer → 400 → login faalde vóór het wachtwoord überhaupt werd geprobeerd.
- **Waarom het "ineens" gebeurde:** het werkte eerder dezelfde dag; de
  Kibana-configuratie is in dat venster serverkant gewijzigd (buiten onze app).

## Oplossing (#3, code)

`elastic.keycloak_login` herschreven: initieer OIDC via de **issuer** i.p.v. een
hardgecodeerde providernaam:

- **Stap 1 nu:** `GET /api/security/oidc/initiate_login?iss=<issuer>` → Kibana
  302't naar Keycloak (en zet een state-cookie die we bewaren).
- Stappen 2–4 ongewijzigd van opzet: Keycloak-formulier ophalen → inloggegevens
  posten → callback volgen → `sid`-cookie eruit halen.
- **Issuer is configureerbaar:** `KIBANA_OIDC_ISSUER` (`config.py`
  `kibana_oidc_issuer`, default `https://sso-gn2.cicd.s15m.nl/realms/SP`). Verhuist
  SSO opnieuw, dan is het een **`.env`-wijziging**, geen codewijziging.
- **Getest:** live tegen echte Kibana+Keycloak → sid verkregen; `/login` via
  nginx → 200; volledige backend-suite groen (op één ongerelateerde
  pre-existing test na).

## Preventie & actiepunten

- [x] **Login los van hardgecodeerde provider** — issuer-based + `KIBANA_OIDC_ISSUER`.
- [ ] **Service-worker kill-switch** in de frontend, zodat een oude SW zichzelf
  opruimt en WSOD na een deploy niet meer voorkomt (voorgesteld).
- [ ] **Volgorde vastleggen:** eerst **VPN verbinden**, dan **Docker Desktop
  starten**. Bij een VPN-herverbinding: `wsl --shutdown`.
- [ ] **Beide VPN-tunnels** controleren (`KOOP-tcp-gn3` was verbroken; SSO staat nu
  op `gn2` — houd dit in de gaten).
- [ ] **Afstemming met KOOP-ops:** wijzigingen aan Kibana-auth (SSO-host, realm,
  provider) vooraf laten communiceren.

## Snelle checklist bij "kan niet inloggen"

1. **"Cannot reach Kibana"?** → VPN verbonden? → `wsl --shutdown` → Docker Desktop
   herstart → containers komen terug.
2. **Wit scherm?** → harde refresh / site-data wissen / Incognito.
3. **"Inloggen mislukt"?** → check `docker logs kibana-oo-backend` op
   `internal/security/login` of `initiate_login`. Test in de browser hoe Kibana
   nu inlogt (SSO-host/realm/provider) en werk **`KIBANA_OIDC_ISSUER`** bij.

## Referenties (code/config)

- `backend/elastic.py` — `keycloak_login` (nieuwe issuer-based OIDC-flow).
- `backend/config.py` — `kibana_oidc_issuer` (`KIBANA_OIDC_ISSUER`).
- `backend/main.py` — `/login` endpoint + de "Cannot reach Kibana"-melding.
- Kibana-init: `GET /api/security/oidc/initiate_login?iss=…` (werkt); de oude
  `POST /internal/security/login` is uitgeschakeld.
