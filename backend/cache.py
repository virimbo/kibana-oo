"""Tiny in-memory TTL cache. `now` is injectable for testing."""
import time
from typing import Callable


class TTLCache:
    def __init__(self, ttl: float, now: Callable[[], float] = time.monotonic):
        self._ttl = ttl
        self._now = now
        self._store: dict[str, tuple[float, object]] = {}

    def get(self, key: str):
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if self._now() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: object, ttl: float | None = None) -> None:
        """Store with the default TTL, or a per-entry override (e.g. a short TTL
        for a degraded/transient result so it self-heals quickly)."""
        self._store[key] = (self._now() + (self._ttl if ttl is None else ttl), value)

    def clear(self) -> None:
        self._store.clear()
