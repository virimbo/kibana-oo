---
title: "SMB share health"
category: "Monitoring & signalen"
created: 2026-07-04
updated: 2026-07-04
tags: [kibana-oo, monitoring, smb, cifs, beheer, nl]
aliases: [SMB, CIFS, Netwerkschijf, Fileshare-monitoring]
---

# SMB share health (Windows/CIFS, poort 445)

> Bewaakt of een **Windows/CIFS-netwerkschijf** (SMB, poort **445**) bereikbaar
> en gezond is: bestaat de share, kun je inloggen, kun je **lezen** (en optioneel
> **schrijven**), en hoe snel reageert hij? Een nieuw **checker-type** binnen de
> bestaande [[Monitoring targets]]-registry — dus hij gebruikt dezelfde poll-lus,
> intelligentie, [[Alerting (meldingen)|alerts]] en het dashboard.
> Zie ook [[AI-architectuur]] (geen agents; gewoon een achtergrond-check).

## Wat & waarom

Documenten in de Woo-keten worden soms via een **netwerkschijf (SMB/CIFS)**
aangeleverd of uitgewisseld. Valt die schijf weg — niet bereikbaar, verkeerde
rechten, vol, of een verlopen service-account — dan **stokt de aanlevering**
zonder dat iemand het meteen ziet. Deze check merkt dat **proactief**.

De check is **gelaagd**, zodat je precies ziet wáár het misgaat (`detail.stage`):

| Laag | Controle | Vangt |
|---|---|---|
| 1. `tcp` | Poort **445** bereikbaar | netwerk/firewall/host down |
| 2. `session` | SMB-login (service-account) | verkeerd wachtwoord, domein/Kerberos, SMB-versie |
| 3. share | verbinden met `\\host\share` | share offline/hernoemd, geen rechten |
| 4. `read` | een bekend bestand/pad bestaat | share bereikbaar maar niet leesbaar |
| 5. `write` *(optioneel)* | tijdelijk bestand schrijven + verwijderen | alleen-lezen / vol / vergrendeld |
| + | **latency** (reactietijd) | trage degradatie |

## Hoe te gebruiken (Beheer → Monitoring-config)

1. Ga naar **Beheer → Monitoring** (super-admin).
2. **Nieuw target** → kies type **`smb`**. Het formulier toont automatisch de velden.
3. Vul in:
   - **Host / server** — bv. `fs01.koop.local`
   - **Share** — bv. `aanlever`
   - **Poort** — `445` (standaard)
   - **Gebruiker** — het **service-account** (bv. `svc_monitor`)
   - **Domein** — AD-domein indien van toepassing (anders leeg)
   - **.env-naam met wachtwoord** — de **naam** van de `.env`-variabele die het
     wachtwoord bevat, bv. `SMB_AANLEVER_PW` (het wachtwoord zelf staat **alleen**
     in `.env`, nooit in de database of het scherm)
   - **Canary-pad** *(optioneel)* — een bekend bestand dat er hoort te zijn
   - **Schrijftest** *(optioneel)* — aan als je ook wilt bewijzen dat schrijven kan
   - **Schrijf-map** — een **aparte** map speciaal voor de schrijf-canary
   - **SMB3-encryptie vereisen** — standaard **aan** (veiligheid)
   - **Latency-waarschuwing (ms)** *(optioneel)* — boven deze reactietijd → geel
4. Zet in `.env`: `SMB_AANLEVER_PW=...` en herstart de backend.
5. Klaar — de poll-lus draait de check mee; resultaten en alerts verschijnen als
   bij elk ander target.

## Een echt voorbeeld

- Target `smb` op `fs01 \ aanlever`, gebruiker `svc_monitor`, schrijftest **aan**
  in map `.healthcheck`, latency-waarschuwing `800 ms`.
- Normaal: **OK** — `detail: { entries: 42, write: "ok" }`, `latency_ms: 60`.
- Iemand trekt het service-account in → volgende ronde **DOWN**,
  `detail: { stage: "session", error: "SMBAuthenticationError" }` → alert.
- Netwerk/firewall dicht → **UNREACHABLE**, `detail: { stage: "tcp" }`.
- Schijf bijna vol / alleen-lezen → **DOWN**, `detail: { stage: "io" }`.
- Reactietijd loopt op naar 1200 ms → **WARN** (`slow: true`) — nog niet stuk,
  wel een vroeg signaal.

## Betekenis van de statussen/kleuren

- 🟢 **ok** — bereikbaar, ingelogd, share leesbaar (en schrijfbaar als getest).
- 🟡 **warn** — werkt, maar **traag** (boven de latency-drempel).
- 🔴 **down** — bereikbaar maar er is écht iets mis (login/share/lezen/schrijven);
  `detail.stage` zegt wat.
- ⚫ **unreachable** — niet eens te bereiken (netwerk/poort 445/host) of
  `smbprotocol` ontbreekt.

## Configuratie & productie-vereisten

- **Netwerk (belangrijkste!):** de backend-container moet de SMB-host op **TCP
  445** kunnen bereiken. SMB is meestal intern — reken op een firewall-regel /
  routering / juiste netwerk. *Zonder dit werkt niets.* De `tcp`-laag maakt dit
  meteen zichtbaar.
- **Service-account met minimale rechten:** alleen-lezen als je alleen leest;
  wil je de schrijftest, geef schrijfrechten op **één aparte canary-map**, nooit
  op echte data. Wachtwoord **uitsluitend** in `.env` (via `secret_ref`).
- **Veiligheid:** SMB3-encryptie standaard vereist (SMB1 wordt geweigerd); de
  schrijf-canary krijgt een unieke naam en wordt **altijd** opgeruimd; wachtwoord
  komt nooit in logs of UI.
- **Robuustheid:** harde timeout (SMB kan hangen); de blokkerende SMB-I/O draait
  in een aparte thread zodat de poll-lus async blijft; een fout laat de ronde
  nooit crashen (wordt `unreachable`/`down`).
- **Afhankelijkheid:** `smbprotocol` (pure-Python SMB 2/3) in `requirements.txt`
  — geen OS-mount nodig, werkt vanuit de Linux-container.
- **Randgevallen:** account verlopen → `stage: session`; pad weg → `stage: read`;
  schijf vol/alleen-lezen → `stage: io`; `smbprotocol` niet geïnstalleerd →
  `unreachable / stage: deps`. Kerberos-only omgevingen: gebruik voorlopig een
  account met wachtwoord (NTLM); Kerberos kan later als uitbreiding.
