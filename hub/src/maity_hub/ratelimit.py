"""Sliding-window limits (login, join exchange, and every other limit of the hub).

On PostgreSQL every replica counts in one table (`shared_counts`, hub/context/replicas.md
2bd65fec): a limit is exact across the pods, read as a sliding window from two fixed ones. On
SQLite and MariaDB, where the hub runs one replica, and before the counts are configured, a
limit counts in the process, exactly.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from maity_hub import shared_counts

Mark = float | datetime | None  # what `place` recorded: a moment in the process, or a window


class Limiter:
    def __init__(self, limit: int, window_seconds: float, *, name: str) -> None:
        self.limit = limit
        self.window = window_seconds
        self.name = name  # the bucket the counts share across replicas
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> int:
        """Record an attempt; 0 when allowed, else the seconds until the next one is."""
        return self.take(key, 1)

    def take(self, key: str, count: int) -> int:
        """Record `count` attempts at once; 0 when all fit, else the seconds until
        enough have left the window for all of them (none is recorded then). `count`
        is at most the limit: more never fits, and no wait would be true."""
        if count > self.limit:
            raise ValueError(f"{self.name}: {count} attempts never fit a limit of {self.limit}")
        if shared_counts.active():
            return self._shared_take(key, count)[0]
        return self._take_at(key, count, time.monotonic())

    def _shared_take(self, key: str, count: int) -> tuple[int, datetime]:
        window = shared_counts.add(self.name, key, self.window, count)
        if window.estimate() <= self.limit:
            return 0, window.start
        shared_counts.subtract(self.name, key, window.start, count)  # none is recorded
        return self._wait(window, count), window.start

    def _wait(self, window: shared_counts.Window, count: int) -> int:
        """Seconds until the estimate with `count` more fits the limit again. `window.current`
        holds those `count` already. Within this window the previous one's weight falls; when
        even an empty previous window would not make room, the wait runs into the next window,
        where this window's attempts are the previous ones and fall in turn."""
        limit, current, previous = self.limit, window.current, window.previous
        remaining = (1 - window.elapsed) * self.window
        if current <= limit and previous > 0:
            fits_at = 1 - (limit - current) / previous  # the fraction of this window
            if fits_at < 1:
                return max(1, math.ceil((fits_at - window.elapsed) * self.window))
        before = current - count  # what this window already held, the next window's previous
        if before <= 0:
            return max(1, math.ceil(remaining))
        fits_at = max(0.0, 1 - (limit - count) / before)  # the fraction of the next window
        return max(1, math.ceil(remaining + fits_at * self.window))

    def _take_at(self, key: str, count: int, now: float) -> int:
        """`take` at a moment the caller read from the clock."""
        with self._lock:
            if len(self._hits) > 1024:
                self._prune(now)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            over = len(hits) + count - self.limit
            if over > 0:  # at most len(hits), as `count` is at most the limit
                return max(1, math.ceil(hits[over - 1] + self.window - now))
            hits.extend([now] * count)
            return 0

    def place(self, key: str, count: int = 1) -> tuple[int, Mark]:
        """Like `take`, and the mark of the attempts it recorded (None when refused), for
        `release` to give back exactly those later: work that did not happen after all."""
        if count > self.limit:
            raise ValueError(f"{self.name}: {count} attempts never fit a limit of {self.limit}")
        if shared_counts.active():
            wait, start = self._shared_take(key, count)
            return wait, (None if wait else start)
        now = time.monotonic()
        wait = self._take_at(key, count, now)
        return wait, (None if wait else now)

    def release(self, key: str, mark: Mark, count: int = 1) -> None:
        """Give back the `count` attempts `place` recorded at `mark`; nothing when they have
        left the window already, so a late release never frees an attempt made after them."""
        if mark is None:
            return
        if isinstance(mark, datetime):
            # The window they were counted in, while that window is still read (current or
            # previous); an older one counts for nothing any more.
            current = shared_counts.read(self.name, key, self.window).start
            if mark >= current - timedelta(seconds=self.window):
                shared_counts.subtract(self.name, key, mark, count)
            return
        with self._lock:
            hits = self._hits.get(key)
            for _ in range(count):
                if hits is None or mark not in hits:
                    break
                hits.remove(mark)

    def blocked(self, key: str) -> int:
        """Like `hit`, without recording an attempt."""
        if shared_counts.active():
            window = shared_counts.read(self.name, key, self.window)
            one_more = shared_counts.Window(  # as if one more attempt were taken now
                window.current + 1, window.previous, window.elapsed, window.start
            )
            if one_more.estimate() <= self.limit:  # what `hit` would let through
                return 0
            return self._wait(one_more, 1)
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
        if shared_counts.active():
            shared_counts.clear(self.name)
