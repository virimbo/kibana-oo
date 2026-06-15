"""Daily proactive TLS audit. Runs the comprehensive certificate audit for every
configured host on a fixed interval, keeps the latest result in memory, and fires
an alert (digest webhook + email) when a host's grade is WARN or CRITICAL — or
recovers to OK. Alerts are de-duplicated so a steady problem is reported once, not
every cycle. Fully self-contained: the active probe needs no Kibana session."""
import asyncio
import logging
from datetime import datetime, timezone

import notify
from certificates import Certificate, probe_certificates
from config import settings

logger = logging.getLogger(__name__)

# Latest audit results + the signature last alerted per host (for de-duplication).
_latest: list[Certificate] = []
_latest_at: datetime | None = None
_last_alert_sig: dict[str, str] = {}


def latest() -> tuple[list[Certificate], datetime | None]:
    return _latest, _latest_at


def _signature(cert: Certificate) -> str:
    """A stable fingerprint of a host's audit verdict, so we only alert on change."""
    problems = sorted(f.text for f in cert.findings if f.level in ("warn", "bad"))
    return f"{cert.grade}|{';'.join(problems)}"


def _alert_text(problems: list[Certificate]) -> str:
    lines = ["⚠ TLS certificate audit — attention needed", ""]
    for c in problems:
        lines.append(f"• {c.host} — GRADE {c.grade} · {c.days_remaining} days left")
        for f in c.findings:
            if f.level in ("warn", "bad"):
                mark = "✗" if f.level == "bad" else "!"
                lines.append(f"    {mark} {f.text}")
    lines.append("")
    lines.append("Checked by KIBANA-OO. Open the dashboard → Certificate & TLS health.")
    return "\n".join(lines)


async def _send_alert(problems: list[Certificate]) -> None:
    text = _alert_text(problems)
    sent_webhook = await notify.send_webhook(text)
    sent_email = await asyncio.to_thread(
        notify.send_email,
        f"⚠ TLS audit: {len(problems)} host(s) need attention",
        "<pre>" + text.replace("<", "&lt;") + "</pre>",
        text,
    )
    logger.info(f"Cert alert dispatched (webhook={sent_webhook}, email={sent_email}).")


async def run_audit_once() -> list[Certificate]:
    """Run one comprehensive audit of all hosts, update the cache, and alert on any
    NEW or changed WARN/CRITICAL verdict (and on recovery to OK)."""
    global _latest, _latest_at
    now = datetime.now(timezone.utc)
    certs = [c for c in await probe_certificates(now) if c.source == "probe"]
    _latest, _latest_at = certs, now

    if not settings.cert_alert_enabled:
        return certs

    to_alert: list[Certificate] = []
    for c in certs:
        sig = _signature(c)
        prev = _last_alert_sig.get(c.host)
        if c.grade in ("WARN", "CRITICAL"):
            if sig != prev:                       # new or changed problem → alert
                to_alert.append(c)
            _last_alert_sig[c.host] = sig
        else:                                     # OK now
            if prev is not None and not prev.startswith("OK"):
                logger.info(f"Cert recovered to OK: {c.host}")
            _last_alert_sig[c.host] = sig

    if to_alert:
        try:
            await _send_alert(to_alert)
        except Exception as e:  # noqa: BLE001 — alerting must never crash the loop
            logger.error(f"Cert alert failed: {e}")
    return certs


async def run_cert_monitor_loop() -> None:
    """Background task: audit on startup, then every cert_audit_interval_hours."""
    interval = max(0.25, settings.cert_audit_interval_hours) * 3600
    await asyncio.sleep(10)  # let the app finish starting before the first probe
    while True:
        try:
            certs = await run_audit_once()
            grades = ", ".join(f"{c.host}={c.grade}" for c in certs)
            logger.info(f"Daily cert audit complete: {grades or 'no hosts'}")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"Cert monitor cycle failed: {e}")
        await asyncio.sleep(interval)
