"""A tiny in-memory TTL cache so we don't hit news feeds on every page view."""

from __future__ import annotations

import time
from typing import Any, Callable


class TTLCache:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = ttl_seconds
        self._clock = clock
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if self._clock() >= expires_at:
            del self._data[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (self._clock() + self.ttl, value)

    def clear(self) -> None:
        self._data.clear()
