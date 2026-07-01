"""Observability overview — the pure status/threshold helpers, and that
build_observability assembles a signals list + overall banner from monkeypatched
sources (no real network). A failing source degrades only its own signal to
'unknown'; the page never raises."""
import observability
from observability import (
    build_observability,
    errors_status,
    freshness_status,
    rejections_status,
    stuck_status,
    worst_status,
)


# ── freshness age → status ───────────────────────────────────────────────────
def test_freshness_ok_within_ok_window():
    assert freshness_status(3, ok_minutes=15, warn_minutes=60) == "ok"
    assert freshness_status(15, ok_minutes=15, warn_minutes=60) == "ok"


def test_freshness_warn_between_windows():
    assert freshness_status(16, ok_minutes=15, warn_minutes=60) == "warn"
    assert freshness_status(60, ok_minutes=15, warn_minutes=60) == "warn"


def test_freshness_crit_beyond_warn():
    assert freshness_status(61, ok_minutes=15, warn_minutes=60) == "crit"


def test_freshness_none_is_unknown():
    assert freshness_status(None) == "unknown"


def test_freshness_uses_config_defaults():
    # Defaults are obs_fresh_ok_minutes=15 / obs_fresh_warn_minutes=60.
    assert freshness_status(5) == "ok"
    assert freshness_status(30) == "warn"
    assert freshness_status(120) == "crit"


# ── stuck → status ───────────────────────────────────────────────────────────
def test_stuck_zero_ok():
    assert stuck_status(0) == "ok"


def test_stuck_low_warn():
    assert stuck_status(1) == "warn"
    assert stuck_status(9) == "warn"


def test_stuck_high_crit():
    assert stuck_status(10) == "crit"
    assert stuck_status(42) == "crit"


def test_stuck_none_unknown():
    assert stuck_status(None) == "unknown"


# ── rejections → status ──────────────────────────────────────────────────────
def test_rejections_zero_ok_else_warn():
    assert rejections_status(0) == "ok"
    assert rejections_status(1) == "warn"
    assert rejections_status(5) == "warn"
    assert rejections_status(None) == "unknown"


# ── errors → status ──────────────────────────────────────────────────────────
def test_errors_prefers_snapshot_level():
    assert errors_status(999, "ok") == "ok"
    assert errors_status(0, "degraded") == "warn"
    assert errors_status(0, "critical") == "crit"


def test_errors_falls_back_to_total():
    assert errors_status(0, None) == "ok"
    assert errors_status(3, None) == "warn"
    assert errors_status(50, None) == "crit"


def test_errors_none_unknown():
    assert errors_status(None, None) == "unknown"


# ── worst-of ─────────────────────────────────────────────────────────────────
def test_worst_status_picks_most_severe():
    assert worst_status(["ok", "warn", "crit"]) == "crit"
    assert worst_status(["ok", "warn"]) == "warn"
    assert worst_status(["ok", "ok"]) == "ok"
    assert worst_status(["ok", "unknown"]) == "unknown"
    assert worst_status([]) == "unknown"


# ── build_observability assembly (monkeypatched sources) ─────────────────────
def _patch_sources(monkeypatch, *, snapshot=None, health=None, aanlever_view=None,
                   ts="fresh", snap_raise=False, health_raise=False, aanlever_raise=False):
    """Patch the three data sources + the freshness probe used by the page."""
    from datetime import datetime, timezone
    import dashboard
    import aanlever
    import monitor_checkers

    async def fake_snapshot(sid, minutes, dv, *a, **k):
        if snap_raise:
            raise RuntimeError("es down")
        return snapshot

    async def fake_health(sid, dv, *a, **k):
        if health_raise:
            raise RuntimeError("health down")
        return health

    async def fake_scan(sid, dv=None, *a, **k):
        if aanlever_raise:
            raise RuntimeError("aanlever down")
        return aanlever_view

    async def fake_max_ts(index, field, sid):
        if ts == "fresh":
            return datetime.now(timezone.utc).isoformat()
        return ts  # None or an explicit ISO string

    monkeypatch.setattr(dashboard, "get_cached_snapshot", fake_snapshot)
    monkeypatch.setattr(dashboard, "get_cached_health", fake_health)
    monkeypatch.setattr(aanlever, "scan", fake_scan)
    monkeypatch.setattr(monitor_checkers, "_es_max_timestamp", fake_max_ts)


async def test_build_observability_all_ok(monkeypatch):
    _patch_sources(
        monkeypatch,
        snapshot={"total": 0, "status_level": "ok", "affected_services": []},
        health={"stuck_count": 0},
        aanlever_view={"count": 0},
        ts="fresh",
    )
    out = await build_observability("sid", "logs-*", 60)

    assert isinstance(out["signals"], list)
    keys = {s["key"] for s in out["signals"]}
    assert keys == {"datastroom", "publicatie", "aanleverfouten", "fouten"}
    # Every signal carries the plain-language explainer fields.
    for s in out["signals"]:
        for field in ("title", "status", "metric", "what", "why", "action"):
            assert s[field], f"{s['key']} missing {field}"
    assert out["overall"]["status"] == "ok"
    assert out["overall"]["headline"]


async def test_build_observability_worst_of_is_crit(monkeypatch):
    _patch_sources(
        monkeypatch,
        snapshot={"total": 2, "status_level": "ok", "affected_services": []},
        health={"stuck_count": 25},   # crit
        aanlever_view={"count": 1},    # warn
        ts="fresh",
    )
    out = await build_observability("sid", "logs-*", 60)
    assert out["overall"]["status"] == "crit"
    by_key = {s["key"]: s for s in out["signals"]}
    assert by_key["publicatie"]["status"] == "crit"
    assert by_key["aanleverfouten"]["status"] == "warn"


async def test_build_observability_worst_affected_service_in_metric(monkeypatch):
    _patch_sources(
        monkeypatch,
        snapshot={"total": 12, "status_level": "critical",
                  "affected_services": [{"name": "search", "count": 3},
                                        {"name": "harvester", "count": 9}]},
        health={"stuck_count": 0},
        aanlever_view={"count": 0},
        ts="fresh",
    )
    out = await build_observability("sid", "logs-*", 60)
    fouten = next(s for s in out["signals"] if s["key"] == "fouten")
    assert fouten["status"] == "crit"
    assert "harvester" in fouten["metric"]  # worst-affected by count


async def test_build_observability_never_raises_on_failing_source(monkeypatch):
    """Every source blows up → the page still returns, all signals 'unknown'."""
    _patch_sources(
        monkeypatch,
        snap_raise=True, health_raise=True, aanlever_raise=True,
        ts=None,  # freshness probe returns no data
    )
    out = await build_observability("sid", "logs-*", 60)
    assert len(out["signals"]) == 4
    assert all(s["status"] == "unknown" for s in out["signals"])
    assert out["overall"]["status"] == "unknown"
    assert out["overall"]["headline"]


async def test_build_observability_stale_datastroom(monkeypatch):
    """An old newest-timestamp → datastroom is crit and drives the banner."""
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    _patch_sources(
        monkeypatch,
        snapshot={"total": 0, "status_level": "ok", "affected_services": []},
        health={"stuck_count": 0},
        aanlever_view={"count": 0},
        ts=old,
    )
    out = await build_observability("sid", "logs-*", 60)
    ds = next(s for s in out["signals"] if s["key"] == "datastroom")
    assert ds["status"] == "crit"
    assert "geleden" in ds["metric"]
    assert out["overall"]["status"] == "crit"
