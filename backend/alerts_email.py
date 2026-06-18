"""Pure rendering for alert emails: (item, kind, prev_severity) → (subject, html,
text). No I/O. All dynamic values are HTML-escaped in the HTML part."""
from __future__ import annotations

from datetime import datetime, timezone
from html import escape

# Per-category suggested administrator action (Dutch — audience is the beheerder).
SUGGESTED = {
    "environment": "Controleer de service/ingress en of de host bereikbaar is; "
                   "kijk in de logs en herstart zo nodig de betreffende pod.",
    "dlq": "Open de dead-letter queue, controleer of de bron-consumer draait, "
           "onderzoek de faalreden en requeue of verwijder de berichten.",
    "certificate": "Vernieuw/roteer het certificaat tijdig en controleer de "
                   "volledige keten (chain) en vervaldatum.",
}
KIND_LABEL = {"new": "New alert", "repeated": "Repeated alert",
              "escalation": "Escalation", "recovery": "Recovery"}
KIND_ICON = {"new": "⛔", "repeated": "🔁", "escalation": "🔺", "recovery": "✅"}


def render(item: dict, kind: str, prev_severity: str, dashboard_url: str
           ) -> tuple[str, str, str]:
    icon = KIND_ICON.get(kind, "⛔")
    label = KIND_LABEL.get(kind, kind)
    sev = item["severity"].upper()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    verb = "is hersteld" if kind == "recovery" else f"is {sev}"
    subject = f"{icon} [{item['env']}] {item['name']} {verb} ({label})"
    action = SUGGESTED.get(item["category"], "Onderzoek de melding op het dashboard.")

    fields = [
        ("Kind", label), ("Severity", sev), ("Environment", item["env"]),
        ("Component", item["name"]), ("Category", item["category"]),
        ("Current status", item["status"] or sev),
        ("Previous status", (prev_severity or "ok")),
        ("Time detected", now), ("Suggested action", action),
        ("Dashboard", dashboard_url),
    ]
    text = "\n".join(f"{k}: {v}" for k, v in fields)

    rows = "".join(
        f"<tr><td style='padding:4px 12px;color:#888'>{escape(k)}</td>"
        f"<td style='padding:4px 12px'><b>{escape(str(v))}</b></td></tr>"
        for k, v in fields)
    html = (f"<div style='font-family:sans-serif'>"
            f"<h2>{escape(icon)} {escape(item['name'])} — {escape(label)}</h2>"
            f"<table style='border-collapse:collapse'>{rows}</table></div>")
    return subject, html, text
