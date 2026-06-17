"""Website availability monitor (Beschikbaarheid / environment status).

A background loop HTTP-probes a configured list of targets (PROD/ACC/TEST),
classifies each as up / degraded / down / unreachable, keeps a short rolling
history per target (for the sparkline + uptime%), and alerts via the existing
webhook/email when a target goes genuinely DOWN (after a settle period, so a
single blip never pages anyone).

Design rules:
- **Allowlist-only & unauthenticated:** only the configured targets are ever
  fetched (no user-supplied URL → no SSRF), with a plain GET, no credentials,
  short timeout, body ignored. Read-only outbound.
- **Honest states:** a target marked `internal` (VPN-only) that fails to connect
  is `unreachable` (grey) — we cannot tell down from off-VPN. A *public* target
  that fails to connect is `down` (red) — a real outage. Alerts fire only on
  `down`, so being off-VPN never pages.
- **Graceful & additive:** inert unless `UPTIME_ENABLED`; never raises into a
  request; nothing here touches the FROZEN certificate code.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import httpx

import notify
from config import settings

logger = logging.getLogger(__name__)

# state per target name: {history: [str], since: iso, alerted: bool, down_since: monotonic|None}
_state: dict[str, dict] = {}
_latest: dict | None = None  # cached view for the endpoint

UP, DEGRADED, DOWN, UNREACHABLE = "up", "degraded", "down", "unreachable"


# ── Target parsing ────────────────────────────────────────────────────────────
def _parse_targets() -> list[dict]:
    """`name | env | url | expected | internal?` per line. Blank → no targets."""
    targets: list[dict] = []
    for raw in (settings.uptime_targets or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3 or not parts[2]:
            continue
        name, env, url = parts[0], (parts[1] or "OTHER").upper(), parts[2]
        expected = parts[3] if len(parts) > 3 and parts[3] else "2xx,3xx"
        internal = len(parts) > 4 and parts[4].strip().lower() in ("internal", "true", "1", "yes")
        targets.append({"name": name or url, "env": env, "url": url,
                        "expected": _parse_expected(expected), "internal": internal})
    return targets


def _parse_expected(spec: str) -> list[str]:
    """Tokens like '2xx','3xx' or explicit codes '200,302,401'."""
    return [t.strip().lower() for t in spec.split(",") if t.strip()]


def _status_ok(status: int, expected: list[str]) -> bool:
    klass = f"{status // 100}xx"
    return klass in expected or str(status) in expected


def is_configured() -> bool:
    return settings.uptime_enabled and bool(_parse_targets())


# ── Probe + classify ──────────────────────────────────────────────────────────
async def _probe(client: httpx.AsyncClient, target: dict) -> dict:
    """Probe one target → result dict (no history/uptime yet)."""
    started = time.monotonic()
    try:
        resp = await client.get(target["url"], follow_redirects=True)
        latency_ms = int((time.monotonic() - started) * 1000)
        ok = _status_ok(resp.status_code, target["expected"])
        if not ok:
            state = DOWN
        elif latency_ms > settings.uptime_degraded_ms:
            state = DEGRADED
        else:
            state = UP
        return {"state": state, "http_status": resp.status_code, "latency_ms": latency_ms, "error": None}
    except (httpx.HTTPError, OSError) as e:
        # Could not reach it. Public → down (real outage); internal → unreachable.
        state = UNREACHABLE if target["internal"] else DOWN
        return {"state": state, "http_status": None, "latency_ms": None, "error": type(e).__name__}


def _verdict(counts: dict) -> str:
    if counts.get(DOWN):
        return "down"
    if counts.get(DEGRADED):
        return "degraded"
    if counts.get(UNREACHABLE):
        return "unreachable"
    return "ok"


# ── Scan (probe all → update state/history → build view → alert) ───────────────
async def scan(now: datetime | None = None) -> dict:
    """One full pass. Never raises into a request."""
    global _latest
    now = now or datetime.now(timezone.utc)
    targets = _parse_targets()
    if not settings.uptime_enabled or not targets:
        _latest = {"enabled": False}
        return _latest

    timeout = httpx.Timeout(settings.uptime_timeout, connect=min(settings.uptime_timeout, 5.0))
    results: list[dict] = []
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "KIBANA-OO-uptime/1.0"}) as client:
        probes = await asyncio.gather(*(_probe(client, t) for t in targets))
    newly_down: list[dict] = []
    for target, probe in zip(targets, probes):
        site = _apply_state(target, probe, now)
        results.append(site)
        if _should_alert(target["name"], probe["state"]):
            newly_down.append(site)

    view = _build_view(results)
    _latest = view
    if newly_down and settings.uptime_alert_enabled:
        try:
            await _alert(newly_down)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Uptime alert failed: {e}")
    return view


def _apply_state(target: dict, probe: dict, now: datetime) -> dict:
    name, state = target["name"], probe["state"]
    st = _state.setdefault(name, {"history": [], "since": now.isoformat(), "alerted": False, "down_since": None})
    prev = st["history"][-1] if st["history"] else None
    if state != prev:
        st["since"] = now.isoformat()
    st["history"].append(state)
    if len(st["history"]) > max(2, settings.uptime_history):
        st["history"] = st["history"][-settings.uptime_history:]
    # Down-settle tracking (for flap-resistant alerting).
    if state == DOWN:
        st["down_since"] = st["down_since"] or time.monotonic()
    else:
        st["down_since"] = None
        st["alerted"] = False

    hist = st["history"]
    healthy = sum(1 for s in hist if s in (UP, DEGRADED))
    uptime_pct = round(100 * healthy / len(hist)) if hist else None
    return {
        "name": name, "env": target["env"], "url": target["url"], "internal": target["internal"],
        "state": state, "http_status": probe["http_status"], "latency_ms": probe["latency_ms"],
        "error": probe["error"], "uptime_pct": uptime_pct, "history": list(hist),
        "since": st["since"], "checked_at": now.isoformat(),
    }


def _should_alert(name: str, state: str) -> bool:
    """Alert once per DOWN episode, only after it has persisted past the settle."""
    st = _state.get(name)
    if not st or state != DOWN or st["alerted"] or st["down_since"] is None:
        return False
    if (time.monotonic() - st["down_since"]) >= settings.uptime_settle_minutes * 60:
        st["alerted"] = True
        return True
    return False


def _build_view(results: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    # Group by env, PROD/ACC/TEST first.
    order = {"PROD": 0, "ACC": 1, "TEST": 2}
    envs: dict[str, list] = {}
    for r in results:
        envs.setdefault(r["env"], []).append(r)
    groups = [{"env": env, "sites": sites}
              for env, sites in sorted(envs.items(), key=lambda kv: (order.get(kv[0], 9), kv[0]))]
    total = len(results)
    return {
        "enabled": True,
        "summary": {
            "up": counts.get(UP, 0) + counts.get(DEGRADED, 0), "total": total,
            "down": counts.get(DOWN, 0), "degraded": counts.get(DEGRADED, 0),
            "unreachable": counts.get(UNREACHABLE, 0), "verdict": _verdict(counts),
        },
        "groups": groups,
        "checked_at": results[0]["checked_at"] if results else None,
    }


async def latest() -> dict:
    return _latest if _latest is not None else await scan()


async def run_uptime_monitor_loop() -> None:
    """Background poll so the board is warm and alerts fire even when unwatched."""
    interval = max(10, settings.uptime_interval)
    await asyncio.sleep(10)
    while True:
        if settings.uptime_enabled:
            try:
                await scan()
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.error(f"Uptime monitor cycle failed: {e}")
        await asyncio.sleep(interval)


async def _alert(newly_down: list[dict]) -> None:
    lines = ["⛔ Website(s) DOWN — Beschikbaarheid", ""]
    for s in newly_down:
        code = f"HTTP {s['http_status']}" if s["http_status"] else (s["error"] or "no response")
        lines.append(f"• [{s['env']}] {s['name']} — {code}")
    lines += ["", "Open the dashboard → Beschikbaarheid."]
    text = "\n".join(lines)
    await notify.send_webhook(text)
    await asyncio.to_thread(notify.send_email,
                            f"⛔ {len(newly_down)} website(s) DOWN",
                            "<pre>" + text.replace("<", "&lt;") + "</pre>", text)
