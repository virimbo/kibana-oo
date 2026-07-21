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
- **Geen enkel geheim staat in de broncode of in git** — en dat is **gemeten, niet
  aangenomen**: de echte waarden zijn gezocht in **alle 503 commits** → **0
  treffers** (§1.1, met de commando's zodat een auditor het kan overdoen). `.env`
  zit ook niet in het Docker-image en bestaat niet als bestand in de container.
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
| Bestandsrechten | ✅ alleen eigenaar — **via `icacls`**, zie de waarschuwing hieronder |
| `.dockerignore` | ✅ toegevoegd (`.env`, sleutels, db's) |

> [!warning] Op Windows werkt `chmod` **niet**
> Deze notitie claimde eerst `chmod 600 .env`. Dat is op een NTFS-schijf een
> **schijnzekerheid**: Git Bash meldt succes, maar Windows houdt de overgeërfde
> ACL. Bij controle op 2026-07-21 bleek `.env` daadwerkelijk **leesbaar voor
> `Gebruikers`** en zelfs **wijzigbaar voor `Geverifieerde gebruikers`**.
> Gecorrigeerd met:
> ```bash
> icacls .env /inheritance:r /grant:r "$(whoami):(F)"
> # controle:
> icacls .env      # verwacht: alleen <MACHINE>\<jij>:(F)
> ```
> `encrypt-env.sh` en `secure-up.sh` doen dit nu automatisch.
> **Les:** op Windows is **BitLocker** de maatregel die telt, niet de
> bestandsrechten — een aanvaller met fysieke toegang leest de schijf gewoon
> buiten Windows om.

### 1.1 Bewijs: er staat géén wachtwoord in git 🔍

> [!success] Dit is de vraag die het management stelt — en dit is het antwoord
> **Wij hebben niet aangenomen dat git schoon is, wij hebben het gemeten:** de
> **echte** geheime waarden uit `.env` zijn letterlijk gezocht in **alle 503
> commits op alle branches**. **Nul treffers.**

Deze meting is **herhaalbaar** — een auditor kan hem zelf uitvoeren en hetzelfde
resultaat krijgen. Dat is het verschil tussen "wij denken van niet" en bewijs.

| # | Controle | Uitkomst (2026-07-21) |
|---|---|---|
| 1 | Is `.env` ooit gecommit? | **Nee** — alleen `.env.example` (URL's/instellingen, géén geheimen) |
| 2 | Staat `.env` in `.gitignore`? | **Ja** (`.gitignore:14`) |
| 3 | De 5 echte geheimen gezocht in 503 commits | **0 treffers** |
| 4 | Treffers op `SMTP_PASSWORD=` e.d. in de historie | Alleen **documentatie met placeholders** (`<Resend API-key>`, `XXX/YYY/ZZZ`) |

**Controle 3 per geheim** — `MISTRAL_API_KEY`, `SMTP_PASSWORD`, `DIGEST_WEBHOOK_URL`,
`MONITOR_SERVICE_PASSWORD`, `RABBITMQ_PASSWORD`: **allemaal "not in history"**.

<details><summary>De commando's (zelf na te lopen)</summary>

```bash
# 1) is .env ooit gecommit? -> toont alleen .env.example
git log --all --full-history --name-only --format="" -- .env .env.* | sort -u

# 2) wordt .env genegeerd?
git check-ignore -v .env

# 3) de sterkste test: zoek de ECHTE waarden in ALLE commits.
#    Leeg resultaat = die waarde staat in geen enkele commit.
git grep -I -l -F '<de-echte-waarde>' -- $(git rev-list --all)
```

Waarom controle 3 doorslaggevend is: 1 en 2 tonen aan dat het bestand nooit is
meegegaan; 3 vangt ook het geval dat een geheim per ongeluk in **een ander**
bestand terechtkwam (een script, een testbestand, een notitie).
</details>

> [!danger] Wat deze meting óók aan het licht bracht
> Git is schoon, **maar het RabbitMQ-wachtwoord is 5 tekens lang** — op het
> account `admin`, dat volledige controle over de queues heeft. Dat is in
> seconden te raden. **Dit weegt zwaarder dan de vraag waar het bestand staat.**
> Zie §2.1: maak de read-only `monitoring`-user aan mét een lang, willekeurig
> wachtwoord, en **wijzig ook het `admin`-wachtwoord**.

**Wees precies in wat je claimt.** Wel hard te maken: geheimen staan niet in de
code, niet in de historie, niet in het image, en `.env` is alleen voor de
eigenaar leesbaar. **Nog niet** hard te maken: dat een gelekt geheim onschadelijk
is (§2) en dat de schijf versleuteld is (§4, BitLocker). Een halve claim die
later sneuvelt kost meer vertrouwen dan een eerlijk openstaand punt.

## 2. De drie kritieke credentials — risico & fix

> **Kernidee:** verberg geheimen niet alleen beter — **maak ze waardeloos als ze
> lekken.**

| # | Credential | Nu | Risico als het lekt | Fix |
|---|---|---|---|---|
| 1 | **Keycloak** (`MONITOR_SERVICE_*`) | een **persoonlijk account** | iemand is **jou**, met ál je rechten; audittrail onbruikbaar | dedicated **service-account**, alleen-lezen |
| 2 | **RabbitMQ** (`RABBITMQ_*`) | **`admin`** (volledige controle) **met een wachtwoord van 5 tekens** | in seconden te raden → queues legen/lezen/verwijderen → **pipeline kapot** | user met tag **`monitoring`** (alleen-lezen) **+ `admin`-wachtwoord wijzigen** |
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
  **Inloggen in de browser verandert niet:** `http://localhost:3000` → Keycloak (SP).
- **Op Windows/SSD wist `shred` niet gegarandeerd** (NTFS journaling + wear
  levelling laten resten achter). Ook daarom is **BitLocker** de maatregel die
  telt: dan zijn die resten versleuteld.
- Laptop gestolen terwijl hij uit staat → de geheimen zijn **onbruikbaar**.

## 4. Laptop-hardening (dit is het echte dreigingsmodel)

- [ ] **BitLocker aan** (volledige schijfversleuteling) — **verreweg de
      belangrijkste maatregel op Windows**; bestandsrechten houden alleen andere
      accounts op dezelfde draaiende machine tegen, BitLocker beschermt de schijf.
- [x] `.env` alleen voor de eigenaar leesbaar (**`icacls`**, niet `chmod` — zie §1).
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

- [ ] RabbitMQ-monitoring-user aanmaken **én het 5-tekens `admin`-wachtwoord
      wijzigen** (§2.1) — **hoogste prioriteit, dit is het grootste gat**
- [ ] Keycloak service-account aanmaken (§2.2)
- [ ] Webhook roteren + `env:`-referentie gebruiken (§2.3)
- [ ] `.env` versleutelen en platte tekst verwijderen (§3)
- [ ] BitLocker verifiëren (§4)
- [ ] Bij opschaling naar productie: geheimen naar **OpenShift Secrets / Vault**
      (dan vervalt §3) — zie [[FG-DPO checklist (AVG, EU AI Act, BIO)]].
