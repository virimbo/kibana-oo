# RabbitMQ DLQ monitor

Watches the **dead-letter queues** on `rabbitmq.koop-plooi-prd.prod5.s15m.nl`. A
non-empty `*.dlq` means messages failed processing and are stuck — this surfaces
them proactively, on the dashboard and via alerts.

## Source

The **RabbitMQ Management API** (`GET /api/queues`) with a **read-only monitoring
user** (HTTP Basic). Read-only = least privilege: it can't publish, consume, or
change anything. Inert until `RABBITMQ_USER` / `RABBITMQ_PASSWORD` are set.

## What it shows

For every queue ending in `.dlq` (suffix configurable): its **depth** (ready +
unacked), **state**, **how long it's been non-empty**, and its **source queue**'s
context (strip `.dlq`) — crucially, whether the source has **consumers**.

## Severity

| Condition | Verdict |
|---|---|
| DLQ empty | OK |
| DLQ has ≥ 1 message | **WARN** (reprocess) |
| DLQ ≥ `RABBITMQ_CRITICAL_MESSAGES` (default 100) **or** source has 0 consumers | **CRITICAL** |

A DLQ with messages whose **source has no consumer** is critical regardless of
count — nothing will drain it. Overall verdict = the worst DLQ.

## Lifecycle (lightweight)

The broker is the real-time source of truth for depth, so we don't store depths.
We keep only minimal state in `kibana_oo.db` (`dlq_state`): the **first-non-empty
timestamp** (→ "stuck 3h 20m") and an **alert-dedup marker**. When a DLQ drains to
0, its row is **deleted** — so it auto-resolves and re-alerts cleanly next time.

## Surfacing & alerts

- **Background poll** every `RABBITMQ_POLL_INTERVAL_MINUTES` (default 5) so alerts
  fire even when nobody's watching.
- **Alert** (webhook + email, deduped) when a DLQ goes non-empty or escalates to
  critical. Toggle with `RABBITMQ_ALERT_ENABLED`.
- **Dashboard card** + a **header badge** (count of non-empty DLQs).

## Security & access

- Endpoint `GET /dashboard/dlq` is gated by the **`rabbitmq` authorization
  feature** (deny-by-default; the super admin grants it — see
  [authorization.md](authorization.md)). Routed under `/dashboard/` so it's
  already covered by the nginx proxy.
- Read-only creds in `.env`, never committed.

## Config (`.env`)

| Var | Default | Purpose |
|---|---|---|
| `RABBITMQ_API_URL` | `https://rabbitmq.koop-plooi-prd.prod5.s15m.nl` | Management API base |
| `RABBITMQ_USER` / `RABBITMQ_PASSWORD` | _(empty)_ | Read-only monitoring user (enables the feature) |
| `RABBITMQ_DLQ_SUFFIX` | `.dlq` | What marks a dead-letter queue |
| `RABBITMQ_CRITICAL_MESSAGES` | `100` | DLQ depth that's CRITICAL |
| `RABBITMQ_POLL_INTERVAL_MINUTES` | `5` | Background poll cadence |
| `RABBITMQ_ALERT_ENABLED` | `true` | Alert on new/escalated DLQs |

> Needs network reach from the backend to the broker (VPN) + the read-only user.
> Detection ships configurable; calibrate against the live broker.
