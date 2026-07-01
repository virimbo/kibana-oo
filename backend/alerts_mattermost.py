"""Rich Mattermost (Slack-compatible) message payloads for alerts.

Renders a colour-barred card: severity headline, an intelligent lead sentence,
a two-column field grid, a recommended action, and a footer with a timestamp.
Pure — no I/O. Mattermost incoming webhooks render the top-level `attachments`
array; `fields` with short=true lay out in two columns, `color` draws the left
bar, `ts` renders the footer time.
"""
from __future__ import annotations

from datetime import datetime, timezone

SEV = {
    "critical": {"emoji": "🔴", "label": "KRITIEK", "color": "#f85149"},
    "warn":     {"emoji": "🟠", "label": "WAARSCHUWING", "color": "#e3b341"},
    "ok":       {"emoji": "🟢", "label": "OK", "color": "#46c97a"},
}
KIND = {
    "new":        {"emoji": "🆕", "label": "Nieuwe melding"},
    "repeated":   {"emoji": "🔁", "label": "Herhaalde melding"},
    "escalation": {"emoji": "🔺", "label": "Escalatie"},
    "recovery":   {"emoji": "✅", "label": "Hersteld"},
}
CATEGORY = {
    "environment": {"label": "Omgevingsstatus", "icon": "🌐"},
    "dlq":         {"label": "Dead-letter queue", "icon": "🐇"},
    "certificate": {"label": "Certificaat & TLS", "icon": "🔐"},
    "document":    {"label": "Vastgelopen document", "icon": "📄"},
    "errorrate":   {"label": "Errors per service", "icon": "🚨"},
}
ACTION = {
    "environment": "Controleer de service/ingress en bereikbaarheid van de host; "
                   "bekijk de logs en herstart zo nodig de betreffende pod.",
    "dlq": "Controleer of de bron-consumer draait; onderzoek de faalreden en "
           "requeue of verwijder de vastgelopen berichten.",
    "certificate": "Vernieuw/roteer het certificaat tijdig en controleer de "
                   "volledige keten (chain) en de vervaldatum.",
    "document": "Open het document via de link, controleer waar het is vastgelopen "
                "en herstart de verwerking of lever het opnieuw aan.",
    "errorrate": "Onderzoek de foutpiek bij deze service: bekijk de logs, "
                 "controleer afhankelijkheden en 5xx-responses en schaal/herstart "
                 "zo nodig de betreffende pod.",
}
_MONTHS_NL = ["", "jan", "feb", "mrt", "apr", "mei", "jun",
              "jul", "aug", "sep", "okt", "nov", "dec"]


def _human_time(dt: datetime) -> str:
    return f"{dt.day} {_MONTHS_NL[dt.month]} {dt.year} · {dt:%H:%M} UTC"


def _lead(item: dict, kind: str, prev_severity: str) -> str:
    """One intelligent, human sentence summarising what happened."""
    cat = CATEGORY.get(item["category"], {"label": item["category"]})["label"].lower()
    name, env, status = item["name"], item["env"], item["status"]
    sev = SEV.get(item["severity"], SEV["critical"])
    if kind == "recovery":
        return (f"✅ **{name}** ({env}) is **hersteld** en weer **OK**. "
                f"De {cat} stond eerder op `{prev_severity or 'kritiek'}`.")
    if kind == "escalation":
        return (f"🔺 De {cat} **{name}** ({env}) is **verergerd** van "
                f"`{prev_severity}` naar **{sev['label'].lower()}** — **{status}**.")
    if kind == "repeated":
        return (f"🔁 De {cat} **{name}** ({env}) is **nog steeds "
                f"{sev['label'].lower()}** — **{status}** — en de cooldown is verstreken.")
    return (f"{sev['emoji']} De {cat} **{name}** ({env}) is zojuist "
            f"**{sev['label'].lower()}** geworden — **{status}**.")


def payload(item: dict, kind: str, prev_severity: str, dashboard_url: str,
            sender: str, now: datetime | None = None, mention: str = "none") -> dict:
    now = now or datetime.now(timezone.utc)
    sev = SEV.get(item["severity"], SEV["critical"])
    knd = KIND.get(kind, {"emoji": "🔔", "label": kind})
    cat = CATEGORY.get(item["category"], {"label": item["category"], "icon": "🔔"})

    fields = [
        {"short": True, "title": "Omgeving", "value": item["env"]},
        {"short": True, "title": "Categorie", "value": f"{cat['icon']} {cat['label']}"},
        {"short": True, "title": "Huidige status", "value": f"`{item['status'] or sev['label']}`"},
        {"short": True, "title": "Vorige status", "value": f"`{prev_severity or 'ok'}`"},
        {"short": True, "title": "Soort melding", "value": f"{knd['emoji']} {knd['label']}"},
        {"short": True, "title": "Gedetecteerd", "value": _human_time(now)},
    ]
    if item.get("category") == "dlq" and item.get("reasons"):
        top = item["reasons"][0]
        fields.append({"short": True, "title": "Top-oorzaak",
                       "value": f"{top['reason']} ({top['count']}×)"})
    # Stuck-document alerts MUST carry the document-id + a clickable link so the
    # beheerder can open the document (open.overheid.nl / doculoket) in one click.
    if item.get("category") == "document" and item.get("doc_id"):
        link = item.get("link") or ""
        doc_id = item["doc_id"]
        value = f"[{doc_id}]({link})" if link else f"`{doc_id}`"
        fields.append({"short": False, "title": "Document", "value": value})
        if item.get("stage"):
            fields.append({"short": True, "title": "Vastgelopen bij",
                           "value": item["stage"]})
    if kind != "recovery":
        fields.append({"short": False, "title": "🛠️ Aanbevolen actie",
                       "value": ACTION.get(item["category"],
                                           "Onderzoek de melding op het dashboard.")})

    # A prominent one-line banner shown ABOVE the coloured card and in the push
    # notification preview — leads with severity + the key metric (e.g. the DLQ
    # message count) so an admin sees what needs attention at a glance.
    status_txt = item["status"] or sev["label"]
    if kind == "recovery":
        pretext = f"✅ **HERSTELD** · {item['name']} ({item['env']}) is weer **OK**."
    else:
        pretext = (f"{sev['emoji']} **{sev['label']}** · {cat['icon']} {cat['label']} — "
                   f"**{status_txt}** · {item['name']} ({item['env']})")

    attachment = {
        "fallback": f"{sev['label']} · {item['name']} ({item['env']}) — {status_txt}",
        "pretext": pretext,
        "color": sev["color"],
        "author_name": "KIBANA-OO · Alerting",
        "title": f"{sev['emoji']} {sev['label']} · {item['name']} — {status_txt}",
        "title_link": dashboard_url,
        "text": _lead(item, kind, prev_severity),
        "fields": fields,
        "footer": f"KIBANA-OO Monitoring · {sender}",
        "ts": int(now.timestamp()),
    }
    # Mattermost only pushes a channel-wide notification for a mention placed in the
    # TOP-LEVEL text (not inside an attachment). Opt-in and only for genuine, active
    # critical incidents — never on recovery or lower severities.
    if mention in ("here", "channel") and item.get("severity") == "critical" and kind != "recovery":
        return {"username": sender, "text": f"@{mention}", "attachments": [attachment]}
    return {"username": sender, "attachments": [attachment]}
