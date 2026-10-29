"""What the hub says about its own load, as plain `key=value` lines (hub/context/serving.md).

Every request is logged by `HubMiddleware` as `METHOD path status ms=<n> route=<pattern>`;
here that same call is also counted, and once a minute one `stats` line says how many requests
the last window had, how many of them were 5xx, the slowest, and the state of the connection
pool. There is no log stack to read them with (k3s and `kubectl logs`), so the lines are
meant for `grep`, and an alarm built on them needs nothing from the hub.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine

log = logging.getLogger("maity_hub.stats")

INTERVAL = 60.0  # seconds between two `stats` lines


@dataclass(frozen=True)
class Snapshot:
    requests: int
    errors: int  # 5xx
    slowest_ms: int


class Window:
    """The requests since the last `stats` line."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests = 0
        self._errors = 0
        self._slowest = 0

    def record(self, status: int, ms: int) -> None:
        with self._lock:
            self._requests += 1
            if status >= 500:
                self._errors += 1
            self._slowest = max(self._slowest, ms)

    def take(self) -> Snapshot:
        """What the window holds, which then starts again."""
        with self._lock:
            taken = Snapshot(self._requests, self._errors, self._slowest)
            self._requests = self._errors = self._slowest = 0
        return taken


WINDOW = Window()


def route_of(scope: Any) -> str:
    """The route's pattern (`/api/v1/tasks/{id}`): the path with each value the router took
    out of it put back as its `{name}`, so it holds nothing from the request. `-` for a
    request no route answered. (The route object's own `path` leaves the `/api/v1` prefix out.)"""
    if scope.get("route") is None:
        return "-"
    path = str(scope.get("path", ""))
    cursor = 0
    for name, value in (scope.get("path_params") or {}).items():
        found = path.find(str(value), cursor) if str(value) else -1
        if found < 0:
            continue
        path = f"{path[:found]}{{{name}}}{path[found + len(str(value)):]}"
        cursor = found + len(name) + 2
    return path


def pool_fields(engine: Engine) -> str:
    """The pool of a server database as `key=value`; SQLite has no pool worth counting."""
    pool: Any = engine.pool
    if not all(hasattr(pool, name) for name in ("checkedout", "checkedin", "size")):
        return "pool=none"
    checked_out, checked_in = pool.checkedout(), pool.checkedin()
    ceiling = pool.size() + max(getattr(pool, "_max_overflow", 0), 0)
    return f"pool_open={checked_out + checked_in} pool_checked_out={checked_out} pool_max={ceiling}"


def line(window: Window, engine: Engine, seconds: float) -> str:
    taken = window.take()
    return (
        f"stats window={seconds:g}s requests={taken.requests} 5xx={taken.errors} "
        f"max_ms={taken.slowest_ms} {pool_fields(engine)}"
    )


class Reporter:
    """Logs the `stats` line once a minute."""

    def __init__(
        self, engine: Engine, interval: float | None = None, window: Window | None = None
    ) -> None:
        self.engine = engine
        self.interval = INTERVAL if interval is None else interval  # read now: tests set it
        self.window = WINDOW if window is None else window
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-stats", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                log.info(line(self.window, self.engine, self.interval))
            except Exception:
                log.exception("the stats line failed")
