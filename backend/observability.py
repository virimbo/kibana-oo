"""Observability overview — the critical monitoring signals for the KOOP/Plooi
document-publishing platform, each explained in plain Dutch for a non-technical
admin.

This is a READ-ONLY roll-up of facts the dashboard already computes (it reuses
get_cached_snapshot / get_cached_health / aanlever.scan and the freshness probe
from monitor_checkers) — it adds no new query logic. It runs in a REQUEST context
(the admin is logged in) so a Keycloak `sid` is available; it must never be called
from a background poll loop.

Each source is wrapped so one failing source can never break the page: a failure
degrades that one signal to status "unknown" and the rest still render. Nothing
here raises.
"""
import logging
from datetime import datetime, timezone

from config import settings

logger = logging.getLogger(__name__)

# Status vocabulary, worst-first, so we can pick the "worst-of" for the banner.
_ORDER = {"crit": 3, "warn": 2, "unknown": 1, "ok": 0}


def worst_status(statuses) -> str:
    """The most severe status among the signals (crit > warn > unknown > ok).
    An empty list is 'unknown' (we have nothing to show)."""
    seen = [s for s in statuses if s in _ORDER]
    if not seen:
        return "unknown"
    return max(seen, key=lambda s: _ORDER[s])


# ── Pure status/threshold helpers (unit-tested) ──────────────────────────────
def freshness_status(age_minutes: float | None,
                     ok_minutes: int | None = None,
                     warn_minutes: int | None = None) -> str:
    """Ingestion freshness → status. None (query failed / no data) → 'unknown'.
    ok if age ≤ ok_minutes, warn if ≤ warn_minutes, else crit."""
    if age_minutes is None:
        return "unknown"
    ok_at = settings.obs_fresh_ok_minutes if ok_minutes is None else ok_minutes
    warn_at = settings.obs_fresh_warn_minutes if warn_minutes is None else warn_minutes
    if age_minutes <= ok_at:
        return "ok"
    if age_minutes <= warn_at:
        return "warn"
    return "crit"


def stuck_status(stuck_count: int | None) -> str:
    """Vastgelopen documenten → status. 0 = ok, 1..9 = warn, ≥10 = crit."""
    if stuck_count is None:
        return "unknown"
    if stuck_count <= 0:
        return "ok"
    if stuck_count < 10:
        return "warn"
    return "crit"


def rejections_status(count: int | None) -> str:
    """Afgewezen aanleveringen → status. 0 = ok, ≥1 = warn."""
    if count is None:
        return "unknown"
    return "ok" if count <= 0 else "warn"


def errors_status(total: int | None, snapshot_level: str | None = None) -> str:
    """Errors & 5xx → status. Prefer the snapshot's own status_level when present
    (mapping 'critical'→crit, 'degraded'→warn, 'ok'→ok); otherwise derive from the
    total count."""
    if total is None and not snapshot_level:
        return "unknown"
    mapped = {"critical": "crit", "degraded": "warn", "ok": "ok"}.get(snapshot_level or "")
    if mapped:
        return mapped
    if total is None:
        return "unknown"
    if total <= 0:
        return "ok"
    if total < 10:
        return "warn"
    return "crit"


def _fmt_minutes(age_minutes: float) -> str:
    """'X min geleden' / 'X uur geleden' — friendly for a non-technical reader."""
    m = int(round(age_minutes))
    if m < 60:
        return f"laatste log {m} min geleden"
    hours = age_minutes / 60
    if hours < 24:
        return f"laatste log {hours:.1f} uur geleden"
    return f"laatste log {hours / 24:.1f} dagen geleden"


def _headline(overall: str, signals: list[dict]) -> str:
    """One intelligent line summarising the worst-of state for the banner."""
    if overall == "unknown":
        return "Kan de observability-signalen nu niet ophalen — probeer te vernieuwen."
    if overall == "ok":
        return "Alles in orde: data stroomt binnen, documenten worden gepubliceerd en er zijn geen opvallende fouten."
    # Name the signals that are not OK, worst-first, so the admin knows where to look.
    bad = [s for s in signals if s.get("status") in ("crit", "warn")]
    bad.sort(key=lambda s: _ORDER.get(s.get("status"), 0), reverse=True)
    titles = ", ".join(s["title"] for s in bad) or "onbekend"
    if overall == "crit":
        return f"Kritiek — directe aandacht nodig bij: {titles}."
    return f"Let op — controleer: {titles}."


# ── Signal builders (each self-contained, never raises) ──────────────────────
async def _signal_datastroom(sid: str, data_view: str) -> dict:
    """Ingestion freshness: age of the newest @timestamp in the selected data view."""
    metric = "onbekend"
    status = "unknown"
    note = None
    try:
        from monitor_checkers import _es_max_timestamp
        ts = await _es_max_timestamp(data_view, "@timestamp", sid)
        if not ts:
            note = "Geen data of Elasticsearch onbereikbaar."
        else:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 60
            age = max(age, 0.0)
            status = freshness_status(age)
            metric = _fmt_minutes(age)
    except Exception as e:  # noqa: BLE001 — one failing source never breaks the page
        logger.warning("observability datastroom failed: %s", e)
        note = "Bevraging mislukt."
    return {
        "key": "datastroom",
        "title": "Datastroom",
        "status": status,
        "metric": metric,
        "what": "Stroomt er nog data de monitoring in?",
        "why": "Geen nieuwe logs betekent dat de verwerkingsstraat mogelijk stilstaat — óf dat we 'blind' zijn en problemen niet meer zien.",
        "action": "Bij rood: controleer de verwerkingsstraat en de log-verzending (shipping) naar Elasticsearch/Kibana.",
        "note": note,
    }


async def _signal_publicatie(health: dict | None, error: bool) -> dict:
    stuck = None if error or health is None else health.get("stuck_count")
    status = stuck_status(stuck)
    metric = "onbekend" if stuck is None else f"{stuck} vastgelopen document(en)"
    return {
        "key": "publicatie",
        "title": "Publicatie",
        "status": status,
        "metric": metric,
        "what": "Bereiken documenten open.overheid.nl?",
        "why": "Vastgelopen of mislukte documenten worden niet gepubliceerd — burgers kunnen ze niet vinden.",
        "action": "Open Documenten → 'Vereist aandacht' om de vastgelopen documenten te tracen.",
        "note": "Bevraging mislukt." if error else None,
    }


async def _signal_aanleverfouten(aanlever_view: dict | None, error: bool) -> dict:
    count = None if error or aanlever_view is None else aanlever_view.get("count")
    status = rejections_status(count)
    metric = "onbekend" if count is None else f"{count} afgewezen aanlevering(en)"
    return {
        "key": "aanleverfouten",
        "title": "Aanleverfouten",
        "status": status,
        "metric": metric,
        "what": "Worden aanleveringen geweigerd?",
        "why": "Een afgewezen aanlevering betekent dat een bronhouder niet kan publiceren.",
        "action": "Bekijk de Aanleverfouten-kaart; neem zo nodig contact op met de bronhouder.",
        "note": "Bevraging mislukt." if error else None,
    }


async def _signal_fouten(snapshot: dict | None, error: bool) -> dict:
    total = None
    worst = "—"
    status = "unknown"
    note = "Bevraging mislukt." if error else None
    if not error and snapshot is not None:
        total = snapshot.get("total")
        status = errors_status(total, snapshot.get("status_level"))
        services = snapshot.get("affected_services") or []
        if services:
            top = max(services, key=lambda s: s.get("count", 0))
            worst = top.get("name") or top.get("service") or "—"
    metric = "onbekend" if total is None else f"{total} errors · ergste: {worst}"
    return {
        "key": "fouten",
        "title": "Fouten & 5xx",
        "status": status,
        "metric": metric,
        "what": "Zijn er veel errors of server-fouten (5xx)?",
        "why": "Een piek wijst op een service die faalt of overbelast is.",
        "action": "Kijk welke service bovenaan staat en onderzoek/herstart die service.",
        "note": note,
    }


async def build_observability(sid: str, data_view: str | None, minutes: int) -> dict:
    """Assemble the observability signals + an overall banner. Reuses the
    dashboard's cached snapshot/health and the aanlever scan; never raises."""
    import aanlever
    from dashboard import get_cached_health, get_cached_snapshot
    from monitoring import resolve_data_view

    dv = resolve_data_view(data_view)

    # Each source is fetched independently: a failure degrades only its own signal.
    snapshot = health = aanlever_view = None
    snap_err = health_err = aanlever_err = False
    try:
        snapshot = await get_cached_snapshot(sid, minutes, dv)
    except Exception as e:  # noqa: BLE001
        logger.warning("observability snapshot failed: %s", e)
        snap_err = True
    try:
        health = await get_cached_health(sid, dv)
    except Exception as e:  # noqa: BLE001
        logger.warning("observability health failed: %s", e)
        health_err = True
    try:
        aanlever_view = await aanlever.scan(sid, dv)
    except Exception as e:  # noqa: BLE001
        logger.warning("observability aanlever failed: %s", e)
        aanlever_err = True

    signals = [
        await _signal_datastroom(sid, dv),
        await _signal_publicatie(health, health_err),
        await _signal_aanleverfouten(aanlever_view, aanlever_err),
        await _signal_fouten(snapshot, snap_err),
    ]

    overall = worst_status([s["status"] for s in signals])
    return {
        "data_view": dv,
        "period_minutes": minutes,
        "signals": signals,
        "overall": {"status": overall, "headline": _headline(overall, signals)},
    }
