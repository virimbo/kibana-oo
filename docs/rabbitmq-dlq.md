# RabbitMQ DLQ monitor

Bewaakt de **dead-letter queues** op `rabbitmq.koop-plooi-prd.prod5.s15m.nl`. Een
niet-lege `*.dlq` betekent dat berichten niet verwerkt konden worden en vastzitten —
dit toont ze proactief, op het dashboard en via alerts.

## Bron

De **RabbitMQ Management API** (`GET /api/queues`) met een **read-only monitoring-user**
(HTTP Basic). Read-only = least privilege: hij kan niets publishen, consumen of
wijzigen. Inert tot `RABBITMQ_USER` / `RABBITMQ_PASSWORD` gezet zijn.

## Wat het toont

Voor elke queue die eindigt op `.dlq` (suffix instelbaar): de **depth** (ready +
unacked), **state**, **hoe lang die al niet-leeg is**, en de context van zijn **source
queue** (strip `.dlq`) — cruciaal: of de source **consumers** heeft.

## Severity

| Conditie | Verdict |
|---|---|
| DLQ leeg | OK |
| DLQ heeft ≥ 1 message | **WARN** (reprocess) |
| DLQ ≥ `RABBITMQ_CRITICAL_MESSAGES` (default 100) **of** source heeft 0 consumers | **CRITICAL** |

Een DLQ met messages waarvan de **source geen consumer** heeft is critical ongeacht het
aantal — niets zal hem drainen. Totaal-verdict = de slechtste DLQ.

## Lifecycle (lightweight)

De broker is de realtime source of truth voor depth, dus we slaan geen depths op. We
houden alleen minimale state in `kibana_oo.db` (`dlq_state`): de **first-non-empty
timestamp** (→ "stuck 3h 20m") en een **alert-dedup-marker**. Wanneer een DLQ naar 0
draint, wordt zijn row **verwijderd** — zodat hij auto-resolvet en de volgende keer weer
netjes alert.

## Surfacing & alerts

- **Background poll** elke `RABBITMQ_POLL_INTERVAL_MINUTES` (default 5) zodat alerts
  afgaan ook als niemand kijkt.
- **Alert** (webhook + email, deduped) wanneer een DLQ niet-leeg wordt of escaleert naar
  critical. Toggle met `RABBITMQ_ALERT_ENABLED`.
- **Dashboard-card** + een **header-badge** (count van niet-lege DLQs).

## Security & access

- Endpoint `GET /dashboard/dlq` is gegate door de **`rabbitmq` authorization-feature**
  (deny-by-default; de super admin grant het — zie [authorization.md](authorization.md)).
  Gerouteerd onder `/dashboard/` zodat het al door de nginx-proxy gedekt is.
- Read-only creds in `.env`, nooit gecommit.

## Config (`.env`)

| Var | Default | Doel |
|---|---|---|
| `RABBITMQ_API_URL` | `https://rabbitmq.koop-plooi-prd.prod5.s15m.nl` | Management API base |
| `RABBITMQ_USER` / `RABBITMQ_PASSWORD` | _(leeg)_ | Read-only monitoring-user (activeert de feature) |
| `RABBITMQ_DLQ_SUFFIX` | `.dlq` | Wat een dead-letter queue markeert |
| `RABBITMQ_CRITICAL_MESSAGES` | `100` | DLQ-depth die CRITICAL is |
| `RABBITMQ_POLL_INTERVAL_MINUTES` | `5` | Cadans van de background poll |
| `RABBITMQ_ALERT_ENABLED` | `true` | Alert op nieuwe/geëscaleerde DLQs |

> Vereist netwerk-bereik van de backend naar de broker (VPN) + de read-only user.
> Detectie wordt instelbaar geleverd; kalibreer tegen de live broker.
