"""Build the 'documents needing attention' digest from a pipeline-health snapshot.
Pure function — produces a subject, a plain-text body (for webhooks) and an HTML
body (for email). Reuses the publication-reconciled at-risk list, so it only
reports documents that are genuinely not yet live."""
import html as _html

from config import settings


def _mark(d: dict) -> str:
    return "CRITICAL" if d.get("verdict") == "problem" else "stuck"


def build_digest(health: dict) -> dict:
    stuck = health.get("stuck", []) or []
    n = len(stuck)
    crit = sum(1 for d in stuck if d.get("verdict") == "problem")
    hours = round((health.get("lookback_minutes", 1440)) / 60)
    published = health.get("confirmed_published", 0)
    portal = settings.portal_base_url.rstrip("/")

    if n == 0:
        subject = "KIBANA-OO — ✅ all documents flowing normally"
    else:
        subject = f"KIBANA-OO — 🚨 {n} document{'s' if n != 1 else ''} need attention"
        if crit:
            subject += f" ({crit} critical)"

    # ── plain text (webhooks / email fallback) ──
    lines = [subject, ""]
    if n == 0:
        lines.append(f"No documents at risk in the last {hours}h — everything is reaching {portal}.")
    else:
        lines.append(f"{n} document{'s' if n != 1 else ''} at risk in the last {hours}h"
                     + (f" — {crit} critical:" if crit else ":"))
        lines.append("")
        for d in stuck:
            title = d.get("title") or d.get("id")
            lines.append(f"• [{_mark(d)} @ {d.get('stuck_stage')}] {title}")
            lines.append(f"    {d.get('headline')}")
        if published:
            lines.append("")
            lines.append(f"({published} other document{'s' if published != 1 else ''} had hiccups "
                         "but are already published & readable — not at risk.)")
    text = "\n".join(lines)

    # ── HTML (email) ──
    rows = ""
    for d in stuck:
        title = _html.escape(d.get("title") or d.get("id") or "")
        headline = _html.escape(d.get("headline") or "")
        is_crit = d.get("verdict") == "problem"
        colour = "#c0392b" if is_crit else "#b7791f"
        badge = f"{_mark(d)} @ {_html.escape(d.get('stuck_stage') or '')}"
        link = f"{portal}/details/{_html.escape(d.get('id') or '')}"
        rows += (
            f'<tr>'
            f'<td style="padding:8px 10px;white-space:nowrap;color:{colour};font-weight:700;'
            f'border-bottom:1px solid #eee;">{badge}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #eee;">'
            f'<a href="{link}" style="color:#1f6feb;text-decoration:none;font-weight:600;">{title}</a>'
            f'<div style="color:#555;font-size:13px;">{headline}</div></td>'
            f'</tr>'
        )
    body_html = (
        f'<p style="font-size:15px;">{_html.escape(subject)}</p>'
        if n == 0 else
        f'<p style="font-size:15px;"><b>{n}</b> document(s) at risk in the last {hours}h'
        + (f" — <b style=\"color:#c0392b;\">{crit} critical</b>." if crit else ".")
        + '</p>'
        f'<table style="border-collapse:collapse;width:100%;font-size:14px;">{rows}</table>'
        + (f'<p style="color:#888;font-size:13px;margin-top:12px;">✓ {published} other document(s) '
           'had hiccups but are already published &amp; readable — not at risk.</p>' if published else "")
    )
    html = (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a1a1a;max-width:680px;">'
        '<h2 style="margin:0 0 4px;">KIBANA-OO — Documents needing attention</h2>'
        '<p style="color:#888;margin:0 0 16px;font-size:13px;">Proactive daily check of the KOOP/Woo pipeline.</p>'
        f'{body_html}'
        '<p style="color:#aaa;font-size:12px;margin-top:20px;">Documents shown are NOT yet live on '
        'open.overheid.nl. Those already published are excluded.</p>'
        '</div>'
    )

    return {"subject": subject, "text": text, "html": html, "count": n, "critical": crit}
