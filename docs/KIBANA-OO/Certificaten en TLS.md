---
title: Certificaten en TLS
tags: [security, tls, beheer, nl]
component: certificates
purpose-business: Voorkomt dat sites onbereikbaar worden door een verlopen of niet-vertrouwd TLS-certificaat.
purpose-technical: Actieve probe + Kibana-monitoring van expiry, keten, vertrouwen, hostname en protocollen.
dependencies: [open.overheid.nl, doculoket.overheid.nl, Kibana Heartbeat/Synthetics]
related: [Monitoring dashboard]
risk: high
owner: KOOP Beheer
---

# Certificaten en TLS

Terug naar [[Home]].

Bewaakt het **TLS-certificaat** van de belangrijkste sites: aftelling tot verloop,
plus eventuele problemen met vertrouwen, keten, hostname of protocol.

> [!warning] FROZEN code
> De certificaat-/TLS-code (`backend/certificates.py`, `backend/cert_monitor.py`) is
> bevroren. Dit Smart-context-paneel **leest** alleen; het wijzigt niets.

## Betekenis van de kleuren

- **groen** = > 30 dagen geldig en vertrouwd.
- **oranje** = < 30 dagen of een waarschuwing.
- **rood** = < 14 dagen, verlopen of niet vertrouwd.

## TO DO

- [ ] Tweede alert-kanaal naast e-mail/webhook
- [x] Dagelijkse proactieve audit met grade WARN/CRITICAL alert

## Configuratie

Zie `.env`: `CERT_*`. Probe-hosts via `CERT_PROBE_HOSTS`.
