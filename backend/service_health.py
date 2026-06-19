"""Service health monitor — backend microservices (KOOP/Plooi).

Read-only HTTP-probes a configured list of services (Spring actuators + service/UI
endpoints), grouped per service, and grades each. Reuses the uptime monitor's probing
approach but is configured and presented per service. Internal/VPN-honest: a connect
failure is `unreachable` (grey, can't tell down from off-VPN), a 5xx / actuator DOWN is
`down` (red). Inert unless settings.service_health_enabled; never raises into a request.

Design rules:
- Allowlist-only & unauthenticated: only the configured URLs are fetched (no
  user-supplied URL → no SSRF), plain GET, no credentials, short timeout, body parsed
  only for the Spring Actuator `status` field.
- Additive: nothing here touches the existing uptime board or any other feature.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

from config import settings

logger = logging.getLogger(__name__)

UP, DEGRADED, DOWN, UNREACHABLE = "up", "degraded", "down", "unreachable"
_RANK = {UP: 0, DEGRADED: 1, UNREACHABLE: 2, DOWN: 3}  # worst endpoint = service verdict
_latest: dict | None = None


# ── Target parsing ────────────────────────────────────────────────────────────
def _parse_targets() -> list[dict]:
    """`Name | url | url …` per line → [{service, endpoints:[{url, kind}]}]."""
    services: list[dict] = []
    for raw in (settings.service_health_targets or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        name, urls = parts[0], [u for u in parts[1:] if u]
        if not name or not urls:
            continue
        endpoints = [{"url": u, "kind": "actuator" if "actuator" in u.lower() else "service"}
                     for u in urls]
        services.append({"service": name, "endpoints": endpoints})
    return services


def is_configured() -> bool:
    return settings.service_health_enabled and bool(_parse_targets())


# ── Probe one endpoint ────────────────────────────────────────────────────────
def _actuator_status(resp: httpx.Response, kind: str) -> str | None:
    """For actuator endpoints, the Spring health `status` (UP/DOWN), else None."""
    if kind != "actuator":
        return None
    ctype = resp.headers.get("content-type", "")
    if "json" not in ctype:
        return None
    try:
        val = resp.json().get("status")
        return str(val).upper() if val else None
    except (ValueError, AttributeError):
        return None


async def _probe(client: httpx.AsyncClient, ep: dict) -> dict:
    """Probe one endpoint → result dict. 5xx / actuator DOWN = down; 2xx–4xx = up
    (a secured 401/403 or a 405 still means the service responds); connect-fail =
    unreachable; slow = degraded."""
    started = time.monotonic()
    try:
        resp = await client.get(ep["url"], follow_redirects=True)
        latency_ms = int((time.monotonic() - started) * 1000)
        health = _actuator_status(resp, ep["kind"])
        if resp.status_code >= 500 or health == "DOWN":
            state = DOWN
        elif latency_ms > settings.service_health_degraded_ms:
            state = DEGRADED
        else:
            state = UP
        return {"url": ep["url"], "kind": ep["kind"], "state": state,
                "http_status": resp.status_code, "latency_ms": latency_ms,
                "health": health, "error": None}
    except (httpx.HTTPError, OSError) as e:
        return {"url": ep["url"], "kind": ep["kind"], "state": UNREACHABLE,
                "http_status": None, "latency_ms": None, "health": None,
                "error": type(e).__name__}


def _service_verdict(results: list[dict]) -> str:
    """Worst endpoint wins: down > unreachable > degraded > up."""
    return max((r["state"] for r in results), key=lambda s: _RANK.get(s, 0), default=UP)


# ── Scan (probe all → build view) ─────────────────────────────────────────────
async def scan(now: datetime | None = None) -> dict:
    """One full pass. Never raises into a request."""
    global _latest
    if not is_configured():
        _latest = {"enabled": False}
        return _latest
    now = now or datetime.now(timezone.utc)
    targets = _parse_targets()
    timeout = httpx.Timeout(settings.service_health_timeout,
                            connect=min(settings.service_health_timeout, 5.0))
    services: list[dict] = []
    async with httpx.AsyncClient(timeout=timeout,
                                 headers={"User-Agent": "KIBANA-OO-servicehealth/1.0"}) as client:
        for t in targets:
            results = await asyncio.gather(*(_probe(client, ep) for ep in t["endpoints"]))
            results = list(results)
            services.append({
                "service": t["service"],
                "verdict": _service_verdict(results),
                "endpoints": results,
            })
    services.sort(key=lambda s: (-_RANK.get(s["verdict"], 0), s["service"].lower()))
    counts: dict[str, int] = {}
    for s in services:
        counts[s["verdict"]] = counts.get(s["verdict"], 0) + 1
    total = len(services)
    healthy = counts.get(UP, 0) + counts.get(DEGRADED, 0)
    if counts.get(DOWN):
        overall = DOWN
    elif counts.get(UNREACHABLE):
        overall = UNREACHABLE
    elif counts.get(DEGRADED):
        overall = DEGRADED
    else:
        overall = UP
    _latest = {
        "enabled": True,
        "summary": {"total": total, "healthy": healthy,
                    "down": counts.get(DOWN, 0), "degraded": counts.get(DEGRADED, 0),
                    "unreachable": counts.get(UNREACHABLE, 0), "verdict": overall},
        "services": services,
        "checked_at": now.isoformat(),
    }
    return _latest


async def latest() -> dict:
    return _latest if _latest is not None else await scan()


async def run_service_health_loop() -> None:
    """Background poll so the card is warm even when unwatched."""
    interval = max(15, settings.service_health_interval)
    await asyncio.sleep(20)
    while True:
        if settings.service_health_enabled:
            try:
                await scan()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error("service_health: cycle failed: %s", e)
        await asyncio.sleep(interval)
