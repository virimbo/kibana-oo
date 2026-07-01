"""Tiny in-process sliding-window rate limiter (no external deps).

Backs the per-IP login limiter. Each key keeps a list of recent hit timestamps;
timestamps older than the window are pruned on every call, and `allow` returns
False once the number of hits in the window reaches `max_hits`. In-memory by
design (counters reset on restart) — good enough to blunt credential stuffing.
"""
import time

# key -> list of epoch-second timestamps of recent hits (pruned per call).
_hits: dict[str, list[float]] = {}


def allow(key: str, max_hits: int, window_seconds: int, now: float | None = None) -> bool:
    """Record a hit for `key` and report whether it is within the limit.

    Returns True when the hit is allowed (fewer than `max_hits` in the trailing
    `window_seconds`), False when the key is over the limit. Passing `now` makes
    the window testable without sleeping.
    """
    ts = time.time() if now is None else now
    cutoff = ts - window_seconds
    recent = [t for t in _hits.get(key, []) if t > cutoff]
    if len(recent) >= max_hits:
        _hits[key] = recent  # keep the pruned list; do not count this hit
        return False
    recent.append(ts)
    _hits[key] = recent
    return True


def reset(key: str | None = None) -> None:
    """Clear counters — a specific key, or all of them. Handy in tests."""
    if key is None:
        _hits.clear()
    else:
        _hits.pop(key, None)
