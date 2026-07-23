---
title: "RCA - Service-session lockout (Keycloak brute-force)"
category: "Runbooks"
created: 2026-07-23
updated: 2026-07-23
tags: [kibana-oo, rca, incident, login, keycloak, lockout, brute-force, service-account, beheer, nl]
aliases: [RCA lockout, Account geblokkeerd, Inloggen mislukt lockout, Service-session backoff]
---

# RCA — Zelfveroorzaakte account-lockout via de servicesessie

> **Root Cause Analysis** van het inlog-incident op **2026-07-21**. Anders dan
> [[RCA - Login incident (Kibana OIDC + Docker VPN)]] lag dit **niet** aan het
> netwerk of aan Kibana, maar aan **onze eigen achtergrond-servicesessie**: die
> bleef met een verlopen wachtwoord elke minuut inloggen en zette daarmee het
> Keycloak-account op slot — hetzelfde account waarmee de beheerder inlogt.
> Gerelateerd: [[Credentials en beveiliging (pilot)]], [[Runbook - wat te doen]].

## Samenvatting (TL;DR)

Inloggen faalde met **"Inloggen mislukt. Controleer je gebruikersnaam en
wachtwoord."** Wachtwoord resetten hielp niet. Onderzoek toonde één oorzaak met
een venijnige terugkoppeling:

1. Het wachtwoord van het **service-account** in `.env` (`MONITOR_SERVICE_*`) was
   **verlopen** (centrale rotatie; RabbitMQ gaf tegelijk 401).
2. De **servicesessie** ([[Smart context paneel|service_session.py]]) probeerde
   daarop **elke ~60 seconden** opnieuw in te loggen — zonder ophouden.
3. Keycloak heeft **brute-force-detectie**: te veel mislukte pogingen → account
   **tijdelijk geblokkeerd**. Tijdens die blokkade geeft Keycloak **dezelfde**
   melding als bij een fout wachtwoord ("Ongeldige gebruikersnaam of wachtwoord").
4. Omdat het service-account een **persoonlijk account** was, blokkeerde dit ook
   het inloggen van de **mens**. En omdat de app elke minuut bleef proberen, ging
   het slot telkens opnieuw dicht zodra het verliep: **een vicieuze cirkel**.

> [!info] Het bewijs dat het wachtwoord níet fout was
> Dezelfde inlogflow, met exact dezelfde `.env`-waarden, **slaagde** in een los
> testscript (geldige Kibana-`sid`) — precies tussen twee mislukte app-pogingen
> in. Een fout wachtwoord kan geen geldige sessie opleveren. De melding kwam dus
> van de **lockout**, niet van de credentials.

## Tijdlijn (2026-07-21, UTC)

| Tijd | Gebeurtenis |
|---|---|
| 05:58 | Eerste mislukte servicesessie-login; daarna ~1×/min |
| 07–09u | ~123 mislukte pogingen; account in lockout-cyclus |
| ~11:13 | Los testscript mét dezelfde `.env` → **sessie geslaagd** (bewijs) |
| ~11:15 | Servicesessie in `.env` uitgezet (`#`) → cirkel doorbroken |
| later | Account weer vrij (lockout verloopt in minuten zodra het bestoken stopt) |

## Directe mitigatie (wat op het moment zelf werkte)

1. **Servicesessie uitzetten** — `MONITOR_SERVICE_USER` + `MONITOR_SERVICE_PASSWORD`
   in `.env` uncommenten met `#`, backend herstarten. Stopt het bestoken meteen.
2. **Wachten** (5–15 min) of de Keycloak-beheerder het account laten deblokkeren
   (Keycloak-console → *Users* → account → **Unlock user**).
3. Inloggen als mens werkt weer; alleen de achtergrondmonitors die een eigen
   sessie nodig hebben liggen stil tot een geldig wachtwoord terugstaat.

> [!warning] Browser-autofill maskeerde het herstel
> Ook ná de wachtwoordreset vulde de browser het **oude** wachtwoord automatisch
> in op `localhost:3000`. Maak het wachtwoordveld leeg en typ het nieuwe met de
> hand; sla het daarna opnieuw op. En let op: `localhost:3000/login` is de **API**
> (toont "Method Not Allowed"), gebruik `http://localhost:3000/`.

## Structurele fix (code — PR)

Een servicesessie hoort een verlopen wachtwoord **niet eindeloop** te blijven
proberen. Toegevoegd: een **circuit breaker met exponentiële backoff** in
`service_session.py`.

- Na `service_sid_quick_retries` (standaard **3**) opeenvolgende mislukte logins
  gaat de breaker **open**: de sessie logt **niet** meer in, maar wacht.
- De wachttijd **verdubbelt** per volgende mislukking (60s → 120s → 240s …),
  begrensd door `service_sid_backoff_cap_minutes` (standaard **60 min**).
- Een **geslaagde** login **reset** de teller.
- Effect: één verlopen wachtwoord levert nog een handjevol pogingen op en valt
  daarna stil — **ruim onder** de drempel die een Keycloak-lockout uitlokt.

Getest (`tests/test_service_session.py`, **10 passed**): aanhoudende fout → stopt
met bestoken; venster verloopt → precies één nieuwe poging; succes → teller reset.

## Preventie (de echte les)

- [ ] **Dedicated service-account** `svc-oo-monitoring` i.p.v. een persoonlijk
      account — dan sleept een kapotte servicesessie **nooit** het inloggen van de
      mens mee. Zie [[Credentials en beveiliging (pilot)]] §2.2. **Dit is de
      belangrijkste maatregel** — dit incident is de tweede keer dat een
      persoonlijk service-account schade gaf.
- [x] Circuit breaker met backoff in de servicesessie (deze PR).
- [ ] Bij wachtwoordrotatie: `.env` bijwerken **en** de app herstarten; controleer
      in de logs dat `service-session login failed` verdwenen is.
- [ ] Overweeg een **Elasticsearch API-key / Kibana service-token** i.p.v. een
      wachtwoord — dan is er niets dat kan "verlopen en hameren".

## Herkenning (volgende keer sneller)

Zie je in de backend-logs een **regelmatige** `service-session login failed`
(≈1×/min) én kan de mens niet meer inloggen? Dan is dit het patroon. Zet eerst de
servicesessie uit (stopt de schade), deblokkeer het account, herstel dan het
wachtwoord. Sinds de backoff-fix stopt het hameren vanzelf, maar de onderliggende
credential moet nog steeds gerepareerd worden.
