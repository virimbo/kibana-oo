# Alerting (meldingen)

> 🇳🇱 Eén centrale, beheerbare e-mailmelder die afgaat zodra een kaart op het
> dashboard **RED** wordt. Te beheren via **Beheer → Alerting**. Vervangt de drie
> losse, ingebouwde melders (uptime, DLQ, certificaten) door één plek met
> schakelaars, ontvangers, cooldown, herstelmeldingen en geschiedenis.

Gerelateerd: [[Beschikbaarheid (uptime)]] · [[Certificaten en TLS]] ·
[[Woo Gateway]] (DLQ-context) · [[Navigatie]] · [[Monitoring dashboard]]

---

## Wat & waarom

Het dashboard bewaakt drie families van signalen:

1. **Omgevingsstatus** (Beschikbaarheid) — PROD / ACC / TST: is elke site up?
2. **Dead-letter queues (DLQ)** — Antivirus, Document-Harvester, Documentopslag,
   Export, Indexatie, Orchestratie: blijven er berichten hangen?
3. **Certificaten & TLS** — PROD / ACC / TST: verlopen er certificaten of klopt de
   keten niet?

Vroeger stuurde **elk** van die drie onderdelen z'n eigen mailtje, zonder centrale
knoppen, zonder cooldown, zonder herstelmelding en zonder overzicht. **Alerting**
lost dat op: één motor leest de bestaande monitoren (alleen-lezen), beslist slim
wat een echte melding is, en stuurt één nette e-mail naar de ingestelde ontvangers.

De motor **raakt de bestaande monitoren niet aan** — hij leest alleen hun oordeel.
De certificaatcode blijft volledig bevroren (FROZEN).

---

## Hoe te gebruiken

Ga naar **Beheer → Alerting (meldingen)**. Bovenaan staan de schakelaars, daaronder
de ontvangers/instellingen en onderaan de geschiedenis.

**Schakelaars (hiërarchie — alles AND).** Een melding gaat alléén af als élk niveau
aan staat: **globaal AND categorie AND omgeving AND die specifieke kaart**. Eén niveau
uit = die hele tak zwijgt. Standaard staat alles **AAN**; een nieuwe kaart wordt dus
automatisch meegenomen. Voorbeeld: zet **ACC** uit tijdens onderhoud → geen mails
over ACC, terwijl PROD gewoon blijft melden.

- **Globaal** — de hoofdschakelaar; uit = niemand krijgt iets.
- **Categorie** — Omgevingsstatus / Dead-letter queues / Certificaten & TLS.
- **Omgeving** — PROD / ACC / TST.
- **Kaart** — per individuele site/queue/host (met kleurstip voor de huidige status).

**Ontvangers.** Komma-gescheiden e-mailadressen; serverzijde gevalideerd. Worden in
de database bewaard (niet in de frontend) en bij elke verzending in de geschiedenis
vastgelegd.

**Instellingen.**
- **Cooldown (min.)** — minimale tijd tussen herhaalmails voor dezelfde kaart
  (standaard 60). Anti-spam.
- **Drempel** — `critical` (alleen rood, standaard) of `warn` (waarschuwing + rood).

**Geschiedenis.** Tabel met tijd, kaart, soort (new/repeated/recovery/escalation),
severity en of de mail verzonden is (✓/✗). Dit is meteen het verzend-auditspoor.

---

## Een echt voorbeeld

`open-acc.overheid.nl` geeft HTTP 404 en gaat **DOWN**. De motor ziet bij de
volgende ronde:

1. Kaart `environment:ACC:open-acc.overheid.nl` → severity **critical**.
2. Globaal ✓, categorie Omgevingsstatus ✓, omgeving ACC ✓, kaart ✓, drempel
   `critical` gehaald → **mag melden**.
3. Was groen, nu rood → soort **New alert**. E-mail eruit, regel in de geschiedenis.

Onderwerp van de mail:

```
⛔ [ACC] open-acc.overheid.nl is CRITICAL (New alert)
```

Inhoud: severity, omgeving, component, huidige status (`HTTP 404 / DOWN`), vorige
status (`ok`), tijdstip, dashboardlink en een **voorgestelde actie** ("controleer de
service/ingress, kijk in de logs, herstart zo nodig de pod").

Blijft 'ie down? Binnen de cooldown: **geen** herhaalmail. Na de cooldown: één
**Repeated**-mail. Loopt warn → critical op? Dan **Escalation**, direct (cooldown
overgeslagen). Komt 'ie weer up? Eén **Recovery**-mail ("is hersteld") en de kaart
wordt opnieuw scherp gezet.

---

## Betekenis van de kleuren, drempels en soorten

- 🟢 **ok** — gezond, geen melding.
- 🟠 **warn** — waarschuwing (bv. DLQ met enkele berichten, certificaat < 30 dagen).
  Meldt alleen als de drempel op `warn` staat.
- 🔴 **critical** — echt mis (site DOWN, DLQ vol of zonder consumer, certificaat
  < 14 dagen / ketenfout). Meldt altijd (drempel `critical`).

**Soorten melding:** **New** (was groen, nu rood) · **Repeated** (nog steeds rood, na
cooldown) · **Escalation** (warn → critical, direct) · **Recovery** (weer groen).

---

## Configuratie & randgevallen

`.env` (server; nooit in de frontend):

```ini
ALERTS_ENABLED=true            # functie aan (false = alles uit, instant rollback)
ALERTS_INTERVAL=60             # seconden tussen rondes
ALERTS_COOLDOWN_MINUTES=60     # standaard cooldown per kaart
ALERTS_DEFAULT_THRESHOLD=critical   # of: warn
ALERTS_RECIPIENT_SEED=jij@example.com   # eerste ontvanger(s); daarna in de UI te beheren

# Zet de drie oude melders UIT zodra deze motor aanstaat (anders dubbele mail):
UPTIME_ALERT_ENABLED=false
RABBITMQ_ALERT_ENABLED=false
CERT_ALERT_ENABLED=false
```

**E-mail** loopt via de bestaande SMTP-instellingen (`SMTP_*`). Vul die in; de
geheimen blijven serverzijde.

**Mattermost (later).** De motor post elke melding ook als webhook. Wil je naar
Mattermost i.p.v. (of naast) e-mail? Zet `DIGEST_WEBHOOK_URL` op een **Mattermost
incoming webhook** — de motor stuurt al een `{"text": ...}`-payload die Mattermost
direct accepteert. Geen codewijziging nodig.

**Rechten.** Bekijken vereist het recht **`alerts`** (Beheer → Autorisatie). Wijzigen
(schakelaars, ontvangers, instellingen) kan **alleen de super-admin**. Elke wijziging
wordt geaudit.

**Veilig falen.** Mislukt een verzending, dan wordt dat gelogd en als `delivered=✗`
in de geschiedenis gezet; de ronde gaat door en er crasht niets.

**Rollback.** `ALERTS_ENABLED=false` → motor inert, nul mails, dashboard ongewijzigd.
Wil je de oude melders terug? Zet de drie `*_ALERT_ENABLED` weer op `true`.
