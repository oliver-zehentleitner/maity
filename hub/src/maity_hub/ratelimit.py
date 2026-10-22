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
        return self.take(key, 1)

    def take(self, key: str, count: int) -> int:
        """Record `count` attempts at once; 0 when all fit, else the seconds until
        enough have left the window for all of them (none is recorded then)."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > 1024:
                self._prune(now)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            over = len(hits) + count - self.limit
            if over > 0:
                if over > len(hits):  # more than the whole window holds
                    return max(1, math.ceil(self.window))
                return max(1, math.ceil(hits[over - 1] + self.window - now))
            hits.extend([now] * count)
            return 0

    def give_back(self, key: str, count: int) -> None:
        """Forget the `count` newest attempts: what `take` recorded for work that
        did not happen after all."""
        with self._lock:
            hits = self._hits.get(key)
            for _ in range(min(count, len(hits or ()))):
                assert hits is not None
                hits.pop()

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
