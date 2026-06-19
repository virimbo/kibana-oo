# Service health

> 🇳🇱 Een aparte dashboard-card die de **backend-microservices** van KOOP/Plooi
> (Harvester, Antivirus, Repository, Search, DCN, Keycloak, Solr, RabbitMQ,
> Documentopslag, …) **alleen-lezen** controleert: werken hun endpoints of niet?
> Per service één oordeel; klik een tegel open voor de losse endpoints.

Gerelateerd: [[Beschikbaarheid (uptime)]] (publieke sites) · [[Woo Gateway]] ·
[[Monitoring dashboard]]

---

## Wat & waarom

[[Beschikbaarheid (uptime)]] bewaakt de **publieke sites** (open.overheid.nl …).
**Service health** is het tegenstuk voor de **interne backend-services**: de
Spring-microservices en admin-UIs op `koop-plooi-prd`. Het beantwoordt: *"reageert
elke service nog?"* — zodat je in één oogopslag ziet welke service up, traag,
onbereikbaar of down is.

Het is **additief**: het raakt de bestaande uptime-card of andere functies niet aan.

## Hoe het werkt

De motor doet per service een **read-only GET** op de geconfigureerde endpoints
(een Spring-`actuator` + een `service`/UI-endpoint), op de achtergrond elke 60 s.
Per endpoint:

- 🟢 **up** — HTTP `2xx/3xx/4xx` (de service reageert; een beveiligde `401/403` of
  een `405` betekent óók dat de service leeft) én een actuator die niet `DOWN` meldt.
- 🔴 **down** — HTTP `5xx`, of een Spring-actuator-JSON met `"status":"DOWN"`
  (bereikt, maar ongezond).
- 🟠 **traag (degraded)** — up, maar trager dan `SERVICE_HEALTH_DEGRADED_MS`.
- ⚪ **unreachable** — connectie-fout/timeout: we kunnen het niet bereiken (down óf
  geen VPN) — eerlijk grijs, nooit een valse rode melding.

**Actuator-bewust:** voor `/actuator`-endpoints leest de motor het JSON-veld
`status` (UP/DOWN) als dat er is; anders valt hij terug op de HTTP-status.

**Per-service oordeel:** de slechtste endpoint wint — `down > unreachable >
degraded > up`.

## Hoe te gebruiken

Op het **Dashboard** verschijnt de card **🧩 Service health** (onder
Beschikbaarheid). Bovenaan een samenvatting (`✓ N/M healthy`, en pills voor down /
unreachable / traag). Daaronder een tegel per service met een gekleurde rand; **klik
een tegel** om de losse endpoints te zien (pad · status · HTTP-code · latency).

Tonen/verbergen kan via **Beheer → Instellingen → Dashboard-weergave → Service
health**. Bekijken vereist het recht **`service_health`** (Beheer → Autorisatie).

## Een echt voorbeeld

`Repository` heeft twee endpoints: `…/actuator` en `…/`. Geeft de actuator
`{"status":"UP"}` en het service-endpoint HTTP 200 → **🟢 up**. Geeft het
service-endpoint HTTP 503 → **🔴 down** (bereikt, maar ongezond) en de card kleurt
rood met `⛔ 1 down`. Kan de backend de host helemaal niet bereiken (geen VPN) →
**⚪ unreachable** (grijs), géén valse rode melding.

## Configuratie & randgevallen

`.env` (server):

```ini
SERVICE_HEALTH_ENABLED=false      # functie aan/uit (instant rollback)
SERVICE_HEALTH_INTERVAL=60        # seconden tussen rondes
SERVICE_HEALTH_TIMEOUT=8          # timeout per request
SERVICE_HEALTH_DEGRADED_MS=2500   # trager dan dit (maar up) = traag
# Eén service per regel: `Naam | url | url …` (kind wordt afgeleid: actuator als de
# URL "actuator" bevat, anders service). Default = de echte prod-services.
SERVICE_HEALTH_TARGETS=...
```

- **VPN:** de endpoints staan op `koop-plooi-prd` (intern). De backend moet ze via
  VPN kunnen bereiken; anders tonen alle services eerlijk **unreachable** (grijs).
- **Alleen-lezen & veilig:** alleen de geconfigureerde URLs worden opgehaald (geen
  user-input → geen SSRF), plain GET, geen credentials, korte timeout. De body wordt
  alleen voor het actuator-`status`-veld geparset.
- **Veilig falen:** één kapot endpoint breekt nooit de hele ronde; de card degradeert
  netjes en crasht nooit het dashboard.

**Rollback:** `SERVICE_HEALTH_ENABLED=false` → card verdwijnt, motor inert.

## Later (additief)

Service-down ook in de [[Alerting (meldingen)]] (een "Services"-categorie →
e-mail/Mattermost); per-endpoint history/sparklines; actuator-detail (DB/disk).
