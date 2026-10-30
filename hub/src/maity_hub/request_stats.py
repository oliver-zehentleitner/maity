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

from maity_hub import API_VERSION

log = logging.getLogger("maity_hub.stats")

INTERVAL = 60.0  # seconds between two `stats` lines
API_PREFIX = f"/api/{API_VERSION}"


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
    """The pattern of the route that answered, as it was declared (`/api/v1/tasks/{id}`), so it
    holds nothing from the request; `-` for a request no route answered, or one whose route
    cannot be told from the path. The route object's own `path` leaves out the prefix the router
    was included under (FastAPI 0.159 keeps it elsewhere), so the one prefix the hub uses is put
    back where the route's regular expression takes the rest of the path."""
    route = scope.get("route")
    pattern = getattr(route, "path_format", None) or getattr(route, "path", None)
    regex = getattr(route, "path_regex", None)
    if not isinstance(pattern, str) or regex is None:
        return "-"
    path = str(scope.get("path", ""))
    for prefix in ("", API_PREFIX):
        if path.startswith(prefix) and regex.fullmatch(path[len(prefix) :]):
            return prefix + pattern
    return "-"


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
