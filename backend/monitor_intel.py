"""Intelligence helpers — pure functions over results/targets so they're unit-testable.
No I/O here; the engine feeds data in and acts on the verdicts."""
from statistics import median

_RED = {"down", "stale", "unreachable"}
_DIM = {"log-freshness": "logs", "jaeger-traces": "traces", "prometheus-query": "metrics", "http": "http"}

def is_flapping_clear(recent_statuses: list[str], threshold: int) -> bool:
    """True = SUPPRESS (not enough consecutive reds yet). recent_statuses newest-first."""
    streak = 0
    for s in recent_statuses:
        if s in _RED: streak += 1
        else: break
    return streak < threshold

def effective_threshold(static: float, baseline_min: float | None, k: int = 3) -> float:
    if not baseline_min: return static
    return max(static, k * baseline_min)

def baseline_minutes(fresh_gaps_min: list[float]) -> float | None:
    return round(median(fresh_gaps_min), 2) if fresh_gaps_min else None

def correlate(red_targets: list[dict]) -> list[dict]:
    groups: dict[tuple, dict] = {}
    for t in red_targets:
        svc = (t.get("config") or {}).get("service") or t.get("name")
        key = (t.get("environment", "na"), svc)
        g = groups.setdefault(key, {"environment": key[0], "service": svc, "targets": []})
        g["targets"].append(t)
    return list(groups.values())

def coverage(targets_with_status: list[dict]) -> dict:
    by_env: dict[str, dict] = {}
    for t in targets_with_status:
        env = t.get("environment", "na"); dim = _DIM.get(t["type"], "http")
        e = by_env.setdefault(env, {})
        cur = e.get(dim)
        st = "down" if t["_status"] in _RED else "ok"
        e[dim] = "down" if cur == "down" or st == "down" else st
    out = {}
    for env, dims in by_env.items():
        total = len(dims); ok = sum(1 for v in dims.values() if v == "ok")
        out[env] = {"score": round(ok / total, 2) if total else 1.0, **dims}
    return out
