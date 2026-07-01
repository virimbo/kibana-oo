"""Unified alerting engine.

Reads the existing monitors read-only (uptime / rabbitmq_dlq / cert_monitor),
normalizes their verdicts into flat items, filters through an admin toggle
hierarchy + severity threshold, applies a per-card cooldown/dedup/recovery state
machine, renders rich emails and sends them via alerts_send/notify, and records
sends + config in kibana_oo.db. Inert unless settings.alerts_enabled. Never raises
into a request; never touches the FROZEN certificate code (only reads
cert_monitor.latest).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import alerts_send
import alerts_store
import cert_monitor
import rabbitmq_dlq
import uptime
from config import settings

logger = logging.getLogger(__name__)

CATEGORY_ENVIRONMENT = "environment"
CATEGORY_DLQ = "dlq"
CATEGORY_CERT = "certificate"
CATEGORY_DOCUMENT = "document"
CATEGORY_ERRORRATE = "errorrate"
SEV_RANK = {"ok": 0, "warn": 1, "critical": 2}


# ── env + id helpers ──────────────────────────────────────────────────────────
def _norm_env(env: str | None) -> str:
    e = (env or "").strip().upper()
    if e in ("TST", "TEST", "T"):
        return "TST"
    if e.startswith("ACC"):
        return "ACC"
    if e in ("PROD", "PRODUCTION", "PRD"):
        return "PROD"
    return e or "OTHER"


def _env_from_host(host: str) -> str:
    h = (host or "").lower()
    if "acc" in h:
        return "ACC"
    if "tst" in h or "test" in h:
        return "TST"
    return "PROD"


def _item(category: str, env: str, name: str, severity: str,
          status: str = "", detail: str = "") -> dict:
    env = _norm_env(env)
    return {
        "card_id": f"{category}:{env}:{name}",
        "category": category, "env": env, "name": name,
        "severity": severity, "status": status, "detail": detail,
    }


# ── normalization (monitor verdict → items) ───────────────────────────────────
def _normalize_uptime(snap: dict | None) -> list[dict]:
    if not snap or not snap.get("enabled"):
        return []
    out: list[dict] = []
    for group in snap.get("groups", []):
        for site in group.get("sites", []):
            state = site.get("state")
            severity = {"down": "critical", "degraded": "warn"}.get(state, "ok")
            code = site.get("http_status")
            status = f"HTTP {code} / {str(state).upper()}" if code else str(state).upper()
            out.append(_item(CATEGORY_ENVIRONMENT, site.get("env") or group.get("env"),
                             site.get("name", "?"), severity, status,
                             site.get("error") or ""))
    return out


def _normalize_dlq(snap: dict | None) -> list[dict]:
    if not snap or not snap.get("configured"):
        return []
    out: list[dict] = []
    for d in snap.get("dlqs", []):
        severity = d.get("severity", "ok")
        depth = d.get("depth", 0)
        detail = "source has NO consumer" if d.get("source_consumers") == 0 else ""
        out.append(_item(CATEGORY_DLQ, "PROD", d.get("name", "?"), severity,
                         f"{depth} message(s)", detail))
    return out


def _normalize_dlq_intel(view: dict | None) -> list[dict]:
    """Richer DLQ items from dlq_intel: severity = smart verdict; status/detail carry
    the reason + headline + action so the email/Mattermost can show *why*."""
    if not view or not view.get("configured"):
        return []
    out: list[dict] = []
    for q in view.get("queues", []):
        top = q["reasons"][0]["reason"] if q.get("reasons") else "onbekend"
        status = f"{q['depth']} berichten · {q.get('trend','?')} · vooral {top}"
        item = _item(CATEGORY_DLQ, "PROD", q["name"], q["severity"], status,
                     q.get("action", ""))
        item["headline"] = q.get("headline", "")
        item["reasons"] = q.get("reasons", [])
        item["oldest_age_seconds"] = q.get("oldest_age_seconds")
        out.append(item)
    return out


def _normalize_cert(certs: list) -> list[dict]:
    out: list[dict] = []
    for c in certs or []:
        grade = (getattr(c, "grade", None) or "").upper()
        severity = {"CRITICAL": "critical", "WARN": "warn"}.get(grade, "ok")
        host = getattr(c, "host", "?")
        days = getattr(c, "days_remaining", None)
        out.append(_item(CATEGORY_CERT, _env_from_host(host), host, severity,
                         f"grade {grade or 'OK'} · {days} days left"))
    return out


# ── ES-fed normalization (need a background service-session sid) ──────────────
def _doc_link(row: dict) -> str:
    """Best-effort clickable link for a stuck document: prefer the link the health
    row already computed (portal details page); else the config templates."""
    doc_id = row.get("id") or ""
    link = row.get("link")
    if link:
        return link
    try:
        return settings.doculoket_link_template.format(id=doc_id)
    except Exception:  # noqa: BLE001 — a bad template never breaks the collector
        return settings.portal_base_url.rstrip("/") + f"/details/{doc_id}"


def _normalize_stuck_docs(health: dict | None) -> list[dict]:
    """One item per at-risk ("stuck"/"problem") document from the pipeline-health
    `stuck` list. Attaches doc_id + a clickable link so the alert can point the
    beheerder straight at the document. Capped to avoid an alert storm; the
    overflow is summarised in a single extra item."""
    if not health:
        return []
    rows = health.get("stuck") or []
    out: list[dict] = []
    cap = max(1, settings.alert_stuck_docs_max)
    for row in rows[:cap]:
        doc_id = row.get("id") or "?"
        verdict = row.get("verdict")
        severity = "critical" if verdict == "problem" else "warn"
        stage = row.get("stuck_stage") or "?"
        item = _item(CATEGORY_DOCUMENT, "PROD", doc_id, severity,
                     f"vastgelopen bij {stage}", row.get("headline") or "")
        item["doc_id"] = doc_id
        item["link"] = _doc_link(row)
        item["stage"] = stage
        item["title"] = row.get("title") or ""
        out.append(item)
    extra = len(rows) - cap
    if extra > 0:
        summary = _item(CATEGORY_DOCUMENT, "PROD", "overige",
                        "warn", f"nog {extra} vastgelopen document(en)")
        summary["doc_id"] = ""
        summary["link"] = settings.portal_base_url
        out.append(summary)
    return out


def _normalize_error_rate(snapshot: dict | None) -> list[dict]:
    """One item per worst-affected service whose error count in the window exceeds
    the configured minimum. Conservative: only the top few services, and only when
    over threshold."""
    if not snapshot:
        return []
    services = snapshot.get("affected_services") or []
    out: list[dict] = []
    lo = settings.alert_errorrate_min
    hi = settings.alert_errorrate_crit
    for svc in services[:5]:
        name = svc.get("name") or "?"
        count = int(svc.get("count") or 0)
        if count < lo:
            continue
        severity = "critical" if count >= hi else "warn"
        out.append(_item(CATEGORY_ERRORRATE, "PROD", name, severity,
                         f"{count} errors"))
    return out


# ── toggle hierarchy + severity threshold ─────────────────────────────────────
def _toggles_allow(item: dict) -> bool:
    """global ∧ category ∧ env ∧ card — any explicit OFF suppresses."""
    return (alerts_store.is_enabled("global", "")
            and alerts_store.is_enabled("category", item["category"])
            and alerts_store.is_enabled("env", item["env"])
            and alerts_store.is_enabled("card", item["card_id"]))


def _meets_threshold(severity: str, threshold: str) -> bool:
    return SEV_RANK.get(severity, 0) >= SEV_RANK.get(threshold, 2)


def _eligible(item: dict, threshold: str) -> bool:
    return _meets_threshold(item["severity"], threshold) and _toggles_allow(item)


def _effective_threshold(item: dict, cfg: dict) -> str:
    """Resolve the threshold for an item: a per-category override falls back to
    the global severity_threshold when unset."""
    return (cfg.get("category_thresholds") or {}).get(item["category"]) or cfg["severity_threshold"]


# ── decision machine (new / repeated / escalation / recovery + cooldown) ──────
def _is_red(severity: str) -> bool:
    return SEV_RANK.get(severity, 0) >= 1  # warn or critical


def _decide(item: dict, prev: dict | None, cooldown_min: int, now: datetime):
    """Pure decision. Returns (kind|None, next_state|None).

    next_state is None only when nothing changed and nothing was sent (a green card
    with no prior state) — the caller persists next_state when it is not None.
    """
    sev = item["severity"]
    prev_sev = (prev or {}).get("severity", "ok")
    red, was_red = _is_red(sev), _is_red(prev_sev)
    now_iso = now.isoformat()

    # Recovery: was red, now green → send once, clear red_since.
    if was_red and not red:
        return "recovery", {"severity": sev, "last_sent_at": now_iso,
                            "last_kind": "recovery", "red_since": None}

    if not red:
        return None, None  # green, stays green → nothing

    # From here the item is red.
    if not was_red:
        return "new", {"severity": sev, "last_sent_at": now_iso,
                       "last_kind": "new", "red_since": now_iso}

    # Still red. The ONLY extra alert per incident is a single escalation when the
    # problem worsens into a higher severity (in practice warn → critical).
    if SEV_RANK[sev] > SEV_RANK[prev_sev]:
        return "escalation", {"severity": sev, "last_sent_at": now_iso,
                              "last_kind": "escalation",
                              "red_since": prev.get("red_since") or now_iso}

    # Still red, severity unchanged → STAY SILENT. Exactly one alert when it breaks,
    # then nothing until it recovers. No time-based repeats (cooldown_min unused).
    return None, {**prev, "severity": sev}


# ── orchestration (collect → decide → send → persist) ─────────────────────────
def _dashboard_url() -> str:
    return settings.frontend_origin.rstrip("/") + "/"


async def _collect(sid: str | None = None) -> list[dict]:
    """Read each monitor's latest verdict (read-only) → flat items. Best-effort:
    a failure in one source must not stop the others.

    The session-less monitors (uptime / dlq / cert) always run exactly as before.
    The ES-fed categories (stuck documents, per-service error rate) need a valid
    service-session ``sid``; when it is falsy they are skipped entirely — no ES
    calls, no items — so behaviour is identical to today while no service account
    exists."""
    items: list[dict] = []
    try:
        items += _normalize_uptime(await uptime.latest())
    except Exception as e:  # noqa: BLE001
        logger.error("alerts: uptime collect failed: %s", e)
    try:
        if settings.dlq_intel_enabled:
            import dlq_intel
            items += _normalize_dlq_intel(await dlq_intel.latest())
        else:
            items += _normalize_dlq(await rabbitmq_dlq.latest())
    except Exception as e:  # noqa: BLE001
        logger.error("alerts: dlq collect failed: %s", e)
    try:
        certs, _ = cert_monitor.latest()
        items += _normalize_cert(certs)
    except Exception as e:  # noqa: BLE001
        logger.error("alerts: cert collect failed: %s", e)

    # ── ES-fed categories — only when a background service-session exists ──────
    if sid:
        import dashboard
        try:
            health = await dashboard.get_cached_health(sid, settings.default_data_view)
            items += _normalize_stuck_docs(health)
        except Exception as e:  # noqa: BLE001 — never break the pass
            logger.error("alerts: stuck-docs collect failed: %s", e)
        try:
            snapshot = await dashboard.get_cached_snapshot(
                sid, settings.alerts_interval // 60 or 15, settings.default_data_view)
            items += _normalize_error_rate(snapshot)
        except Exception as e:  # noqa: BLE001 — never break the pass
            logger.error("alerts: error-rate collect failed: %s", e)
    return items


async def scan(now: datetime | None = None) -> dict:
    """One evaluation pass. Never raises into a request."""
    if not settings.alerts_enabled:
        return {"enabled": False}
    alerts_store.ensure_seeded()
    cfg = alerts_store.get_config()
    if not cfg["global_enabled"]:
        return {"enabled": True, "global_enabled": False, "sent": 0}
    now = now or datetime.now(timezone.utc)
    # Background path: obtain a service-session sid (None when no service account
    # is configured) so the ES-fed categories page unattended once credentials
    # exist — and are skipped gracefully (sid=None) while they are absent.
    sid = None
    try:
        import service_session
        sid = await service_session.get_service_sid()
    except Exception as e:  # noqa: BLE001 — never break the pass on a session error
        logger.error("alerts: service-session lookup failed: %s", e)
    items = _collect(sid)
    if asyncio.iscoroutine(items):
        items = await items
    sent = 0
    for item in items:
        try:
            if _is_red(item["severity"]) and not _eligible(item, _effective_threshold(item, cfg)):
                continue  # red but suppressed by toggle/threshold
            prev = alerts_store.get_state(item["card_id"])
            # Skip recovery work for cards we never alerted on.
            if not _is_red(item["severity"]) and prev is None:
                continue
            kind, nxt = _decide(item, prev, cfg["cooldown_minutes"], now)
            if nxt is not None:
                alerts_store.set_state(item["card_id"], nxt["severity"],
                                       nxt["last_sent_at"], nxt["last_kind"],
                                       nxt["red_since"])
            if kind is None:
                continue
            await _dispatch(item, kind, (prev or {}).get("severity", "ok"),
                            cfg["recipients"], cfg.get("mention", "none"))
            sent += 1
        except Exception as e:  # noqa: BLE001 — one bad card never breaks the pass
            logger.error("alerts: card %s failed: %s", item.get("card_id"), e)
    return {"enabled": True, "global_enabled": True, "sent": sent, "checked": len(items)}


async def _dispatch(item: dict, kind: str, prev_severity: str, recipients: list[str],
                    mention: str = "none") -> None:
    import alerts_email
    import alerts_mattermost
    url = _dashboard_url()
    subject, html, text = alerts_email.render(item, kind, prev_severity, url)
    delivered = False
    try:
        # Both channels are branded with alerts_send.ALERT_SENDER and leave notify.py
        # untouched. Email → ADMIN-managed recipient list; webhook → a rich
        # Mattermost attachment card (colour bar, lead, field grid, action).
        delivered = await asyncio.to_thread(alerts_send.send_email_to, recipients,
                                            subject, html, text)
        payload = alerts_mattermost.payload(item, kind, prev_severity, url,
                                            alerts_send.ALERT_SENDER, mention=mention)
        await alerts_send.post_webhook(payload)
    except Exception as e:  # noqa: BLE001
        logger.error("alerts: dispatch failed for %s: %s", item["card_id"], e)
    alerts_store.record_history(
        card_id=item["card_id"], category=item["category"], env=item["env"],
        kind=kind, severity=item["severity"], prev_severity=prev_severity,
        recipients=recipients, delivered=delivered, detail=item.get("status", ""))


CATEGORY_MONITORING = "monitoring"


def raise_external(category, key, env, title, detail):
    """Additive bridge for the monitoring registry: raise an alert through the
    EXISTING per-incident dedup + email→Mattermost dispatch path.

    Reuses the same state machine as the built-in monitors (alerts_store
    get_state/set_state + _decide) keyed by ``f"{category}:{key}"`` so the same
    active incident notifies exactly ONCE until it recovers/clears. Dispatch goes
    through the existing _dispatch (email → Mattermost + history). Fully wrapped:
    a send failure is logged, never raised — the engine calls this in a loop.

    The card is always treated as a red ("critical") incident; clearing it (e.g.
    the monitor reporting healthy again) is the registry's job and would be a
    separate recovery call, mirroring how the other monitors recover a card.
    """
    try:
        card_id = f"{category}:{key}"
        item = {
            "card_id": card_id,
            "category": CATEGORY_MONITORING,
            "env": _norm_env(env),
            "name": title,
            "severity": "critical",
            "status": detail or title,
            "detail": detail or "",
        }
        cfg = alerts_store.get_config()
        prev = alerts_store.get_state(card_id)
        now = datetime.now(timezone.utc)
        kind, nxt = _decide(item, prev, cfg["cooldown_minutes"], now)
        if nxt is not None:
            alerts_store.set_state(card_id, nxt["severity"], nxt["last_sent_at"],
                                   nxt["last_kind"], nxt["red_since"])
        if kind is None:
            return  # same active incident already alerted → dedup, stay silent
        prev_severity = (prev or {}).get("severity", "ok")
        try:
            asyncio.run(_dispatch(item, kind, prev_severity, cfg["recipients"]))
        except RuntimeError:
            # Already inside a running loop (rare for this sync bridge): run the
            # coroutine on a dedicated loop so we never raise into the caller.
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(
                    _dispatch(item, kind, prev_severity, cfg["recipients"]))
            finally:
                loop.close()
    except Exception as e:  # noqa: BLE001 — the engine calls this in a loop
        logger.error("alerts: raise_external %s:%s failed: %s", category, key, e)


async def run_alert_loop() -> None:
    """Background poll so alerts fire even when nobody is watching the dashboard."""
    interval = max(10, settings.alerts_interval)
    await asyncio.sleep(12)
    while True:
        if settings.alerts_enabled:
            try:
                await scan()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error("alerts: scan cycle failed: %s", e)
        await asyncio.sleep(interval)
