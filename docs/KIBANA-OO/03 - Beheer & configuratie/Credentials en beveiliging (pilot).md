---
title: "Credentials en beveiliging (pilot)"
category: "Beheer & configuratie"
created: 2026-07-21
updated: 2026-07-21
tags: [kibana-oo, security, credentials, secrets, bio, avg, pilot, beheer, nl]
aliases: [Credentials, Secrets, Least privilege, Compromise runbook, Wachtwoorden]
---

# Credentials & beveiliging (pilot)

> Hoe deze **lokale pilot** met geheimen omgaat, wat er is aangetoond, en wat er
> nog moet. Geschreven zodat een **beheerder** het kan uitvoeren én het
> **management/FG** het kan beoordelen. Verwant:
> [[FG-DPO checklist (AVG, EU AI Act, BIO)]], [[Presentatie - Management]],
> [[Webhooks (Mattermost)]], [[Autorisatie]].

## ⭐ Managementsamenvatting (in één blok)

- **Gebruikers loggen in via Keycloak (SP)** — de app slaat **nooit** een
  gebruikerswachtwoord op. Data-queries lopen op de **eigen sessie** van de
  ingelogde gebruiker.
- **Geen enkel geheim staat in de broncode of in git** — aantoonbaar: `.env` is
  **nooit** gecommit, staat in `.gitignore`, zit **niet** in het Docker-image en
  bestaat **niet** als bestand in de container (alleen runtime-variabelen).
- **Scope = pilot:** één gebruiker, lokaal, **alleen-lezen** monitoring; de app
  schrijft niets naar de productieketen.
- **Het grootste risico was niet "waar staan de geheimen", maar "hoeveel mogen
  ze"** — daarom is de kern van deze maatregel **least privilege**: na de stappen
  hieronder is een eventueel gelekt geheim **onschadelijk** (alleen-lezen).

## 1. Wat is aangetoond (audit 2026-07-21)

| Controle | Resultaat |
|---|---|
| `.env` in git-historie? | ✅ **Nooit gecommit** (staat in `.gitignore`) |
| In het Docker-image gebakken? | ✅ **Nee** — valt buiten de build-context |
| Als bestand in de container? | ✅ **Nee** — runtime-variabelen |
| Repo in OneDrive/Dropbox? | ✅ **Nee** |
| Bestandsrechten | ✅ `chmod 600 .env` (alleen eigenaar) |
| `.dockerignore` | ✅ toegevoegd (`.env`, sleutels, db's) |

## 2. De drie kritieke credentials — risico & fix

> **Kernidee:** verberg geheimen niet alleen beter — **maak ze waardeloos als ze
> lekken.**

| # | Credential | Nu | Risico als het lekt | Fix |
|---|---|---|---|---|
| 1 | **Keycloak** (`MONITOR_SERVICE_*`) | een **persoonlijk account** | iemand is **jou**, met ál je rechten; audittrail onbruikbaar | dedicated **service-account**, alleen-lezen |
| 2 | **RabbitMQ** (`RABBITMQ_*`) | **`admin`** (volledige controle) | queues legen/lezen/verwijderen → **pipeline kapot** | user met tag **`monitoring`** (alleen-lezen) |
| 3 | **Mattermost webhook** | post-token in `.env` **en** in de DB | iemand kan **nepberichten** posten (geen leesrechten) | **roteren** + opslaan als `env:VARNAME` |

### 2.1 RabbitMQ → alleen-lezen (doe dit eerst, grootste winst)

```bash
rabbitmqctl add_user svc_oo_monitor '<lang-willekeurig-wachtwoord>'
rabbitmqctl set_user_tags svc_oo_monitor monitoring     # read-only management API
rabbitmqctl set_permissions -p / svc_oo_monitor "^$" "^$" "^$"   # geen publish/consume
```
Of via de Management-UI: **Admin → Users → Add user**, tag `monitoring`, permissies leeg.
Zet daarna `RABBITMQ_USER=svc_oo_monitor` + het nieuwe wachtwoord in `.env`, en
**verwijder/roteer het `admin`-wachtwoord**.

### 2.2 Keycloak → dedicated service-account

1. Maak in het **SP-realm** een gebruiker **`svc-oo-monitoring`** (geen persoon).
2. Geef **alleen** de rol(len) voor **alleen-lezen** Kibana-toegang.
3. Lang, willekeurig wachtwoord (password manager). Documenteer de eigenaar.
4. Zet `MONITOR_SERVICE_USER=svc-oo-monitoring` (+ wachtwoord) in `.env`.
5. **Verwijder het persoonlijke account** uit `.env` en wijzig dat wachtwoord.

> *Waarom geen client-credentials?* Kibana vereist een **sessie-cookie** uit de
> interactieve OIDC-flow; daarom is een **service-gebruiker** (geen client) nu de
> juiste keuze. Langere termijn: een **Elasticsearch API-key** of Kibana
> service-account-token → dan is er **geen wachtwoord** meer nodig.

### 2.3 Webhook → roteren + `env:`-referentie

De app ondersteunt nu **`env:VARNAME`** als webhook-waarde: dan staat in de
database alleen de **naam**, nooit de geheime URL.
1. Maak in Mattermost een **nieuwe** incoming webhook.
2. Zet de URL in `.env`, bv. `MATTERMOST_PROD_HOOK=https://chat…/hooks/xxxx`.
3. **Beheer → Webhooks** → nieuwe webhook met URL-veld: **`env:MATTERMOST_PROD_HOOK`**.
4. **Test** → **Activeer** → verwijder de oude webhook (in de app én in Mattermost).

## 3. Geheimen versleuteld op schijf (`.env.enc`)

Voor deze lokale pilot staat het geheimenbestand **versleuteld** op schijf; de
platte tekst bestaat alleen de seconden die Docker nodig heeft om te starten.

```bash
./scripts/encrypt-env.sh     # eenmalig: .env  ->  .env.enc  (AES-256, PBKDF2 200k)
# test dat starten werkt:
./scripts/secure-up.sh       # vraagt passphrase -> ontsleutelt -> start -> wist platte tekst
# pas als dat werkt:
shred -u .env                # verwijder de platte tekst definitief
```

- **Bewaar de passphrase in je password manager — er is géén herstel.**
- Start de app voortaan met **`./scripts/secure-up.sh`** (niet met `docker compose up`).
- Laptop gestolen terwijl hij uit staat → de geheimen zijn **onbruikbaar**.

## 4. Laptop-hardening (dit is het echte dreigingsmodel)

- [ ] **BitLocker aan** (volledige schijfversleuteling) — belangrijkste maatregel.
- [x] `.env` op **600** (alleen eigenaar).
- [x] Repo **niet** in OneDrive/Dropbox.
- [x] `.dockerignore` + `.gitignore` dekken `.env`.
- [ ] Schermvergrendeling + korte time-out.
- [ ] Minder geheimen: gebruik in de pilot het **lokale Ollama-model** → dan kan
      `MISTRAL_API_KEY` weg **en** verlaat er geen data je machine (ook beter voor AVG).

## 5. 🚨 Compromise-runbook (als er tóch iets lekt)

**Handel in deze volgorde — het duurt < 15 minuten:**

1. **RabbitMQ:** wachtwoord van `svc_oo_monitor` wijzigen (Management-UI of
   `rabbitmqctl change_password`). Controleer of er geen onbekende users zijn.
2. **Keycloak:** wachtwoord van `svc-oo-monitoring` wijzigen; **sessies intrekken**
   in Keycloak; controleer de login-historie op onbekende IP's.
3. **Webhook:** in Mattermost de webhook **verwijderen** en een nieuwe maken; in
   **Beheer → Webhooks** de nieuwe activeren en de oude verwijderen.
4. **Mistral (indien in gebruik):** API-key intrekken in de portal en vervangen.
5. **`.env.enc`:** nieuwe passphrase (`encrypt-env.sh` opnieuw draaien).
6. **Melden:** informeer je **FG/security-officer**; leg tijdlijn + genomen stappen
   vast (dit is óók je eigen bescherming — aantoonbare zorgvuldigheid).

> Zet dit blad geprint of offline binnen handbereik — bij een incident wil je niet
> hoeven zoeken.

## 6. Wat de app zelf al goed doet

- **Geen wachtwoordopslag** voor gebruikers (Keycloak SSO — zie [[Autorisatie]]).
- **Alleen-lezen**: de app schrijft niets naar de publicatieketen.
- **`secret_ref`-patroon**: monitoring-connecties en de SMB-check slaan alleen de
  **naam** van een `.env`-variabele op, nooit de waarde — en nu ook de webhooks
  (`env:VARNAME`).
- **Maskering in de UI**: geheime waarden worden nooit teruggegeven door de API.
- **Autorisatie**: rechten-matrix per gebruiker × functie + goedkeuringsgate.

## 7. Openstaand (eerlijk)

- [ ] RabbitMQ-monitoring-user aanmaken (§2.1) — **hoogste prioriteit**
- [ ] Keycloak service-account aanmaken (§2.2)
- [ ] Webhook roteren + `env:`-referentie gebruiken (§2.3)
- [ ] `.env` versleutelen en platte tekst verwijderen (§3)
- [ ] BitLocker verifiëren (§4)
- [ ] Bij opschaling naar productie: geheimen naar **OpenShift Secrets / Vault**
      (dan vervalt §3) — zie [[FG-DPO checklist (AVG, EU AI Act, BIO)]].
