---
title: Notifications & the daily digest
tags: [notifications, digest, ops, reference]
---

# 📧 Notifications & the daily digest

Back to [[Home]]. Proactively pushes the **"documents needing attention"** list
([[Document lifecycle (pipeline)]]) to people — so issues are caught even when no
one is looking at the [[Monitoring dashboard]].

> [!tip] Recommended: a webhook (easiest)
> A **Slack / Teams / Discord incoming webhook** is one URL — no passwords, no
> Gmail app-passwords. Set `DIGEST_WEBHOOK_URL` and you're done.

## Two ways it sends

- **On-demand** — the dashboard's *Documents needing attention* panel has a
  **📧 Send me this digest** button. Uses your live session; sends instantly.
- **Daily (unattended)** — `backend/send_digest.py` logs in with a service
  account, builds the snapshot and sends it. Schedule it (see below).

## Configure (`.env`)

```bash
# Webhook (recommended — Slack/Teams/Discord/generic)
DIGEST_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ

# …or email (Gmail needs an app password, not your normal password)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your-16-char-app-password
SMTP_FROM=you@gmail.com
DIGEST_RECIPIENTS=you@work.nl,colleague@work.nl

# For the unattended daily run (service account that can log in to Kibana)
DIGEST_KIBANA_USER=svc-monitor@koop.overheid.nl
DIGEST_KIBANA_PASSWORD=...
```

Only configure what you need — each channel is independent and best-effort.

## Schedule the daily digest

Linux/macOS cron (08:00 daily):

```cron
0 8 * * *  cd /path/to/KIBANA-OO && docker compose exec -T backend python send_digest.py
```

Windows Task Scheduler: a daily task running
`docker compose exec -T backend python send_digest.py`.

## What's in it

Only documents that are **genuinely not yet live** on open.overheid.nl —
⛔ critical (a real error) or 🕒 stuck/hanging. Documents that turned out
already published are **excluded** (see [[Document lifecycle (pipeline)]] —
publication status is ground truth). Each entry links to the document.

## Related

- [[Monitoring dashboard]] · [[Document lifecycle (pipeline)]] · [[Document tracer]] · [[Architecture]]
