"""In-process sliding-window limits (login, join exchange). One replica in V1."""

from __future__ import annotations

import math
import threading
import time
from collections import deque


class Limiter:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> int:
        """Record an attempt; 0 when allowed, else the seconds until the next one is."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 1024:
                self._prune(now)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, math.ceil(hits[0] + self.window - now))
            hits.append(now)
            return 0

    def blocked(self, key: str) -> int:
        """Like `hit`, without recording an attempt."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits.get(key)
            if hits is None:
                return 0
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return max(1, math.ceil(hits[0] + self.window - now))
            return 0

    def _prune(self, now: float) -> None:
        """Forget keys with no attempt inside the window; every new handle or
        address would otherwise stay in memory for good."""
        stale = [k for k, hits in self._hits.items() if not hits or hits[-1] <= now - self.window]
        for key in stale:
            del self._hits[key]

    def __len__(self) -> int:
        return len(self._hits)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
