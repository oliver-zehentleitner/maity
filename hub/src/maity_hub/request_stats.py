"""What the hub says about its own load, as plain `key=value` lines (hub/context/serving.md).

Every request is logged by `HubMiddleware` as `METHOD path status ms=<n> route=<pattern>`;
here that same call is also counted, and once a minute one `stats` line says how many requests
the last window had, how many of them were 5xx, the slowest, and the state of the connection
pool. Up to `ROUTE_LINES` `stats_route` lines name the routes that had a slow request in that
window. There is no log stack to read them with (k3s and `kubectl logs`), so the lines are
meant for `grep`, and an alarm built on them needs nothing from the hub.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine

from maity_hub import API_VERSION

log = logging.getLogger("maity_hub.stats")

INTERVAL = 60.0  # seconds between two `stats` lines
API_PREFIX = f"/api/{API_VERSION}"
SLOW_MS = 1000  # a request this long makes its route worth a `stats_route` line
VERY_SLOW_MS = 3000
ROUTE_LINES = 10  # at most this many `stats_route` lines per window
# The server passes any method token on; only these become a key, or a client could grow the
# window without bound and write what it likes into the log.
METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})


@dataclass
class RouteTimes:
    """One method and route pattern in a window. A held long-poll is not counted here: its
    length is how long nothing happened."""

    requests: int = 0
    over_1s: int = 0
    over_3s: int = 0
    total_ms: int = 0
    slowest_ms: int = 0

    def add(self, ms: int) -> None:
        self.requests += 1
        self.over_1s += ms >= SLOW_MS
        self.over_3s += ms >= VERY_SLOW_MS
        self.total_ms += ms
        self.slowest_ms = max(self.slowest_ms, ms)


@dataclass(frozen=True)
class Snapshot:
    requests: int
    errors: int  # 5xx
    slowest_ms: int
    routes: dict[tuple[str, str], RouteTimes] = field(default_factory=dict)


class Window:
    """The requests since the last `stats` line."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests = 0
        self._errors = 0
        self._slowest = 0
        self._routes: dict[tuple[str, str], RouteTimes] = {}

    def record(self, status: int, ms: int, method: str = "", route: str = "") -> None:
        """`route` is left out for a held long-poll, which counts only in the totals."""
        with self._lock:
            self._requests += 1
            if status >= 500:
                self._errors += 1
            self._slowest = max(self._slowest, ms)
            if route:
                key = (method if method in METHODS else "OTHER", route)
                self._routes.setdefault(key, RouteTimes()).add(ms)

    def take(self) -> Snapshot:
        """What the window holds, which then starts again."""
        with self._lock:
            taken = Snapshot(self._requests, self._errors, self._slowest, self._routes)
            self._requests = self._errors = self._slowest = 0
            self._routes = {}
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


def lines(window: Window, engine: Engine, seconds: float) -> list[str]:
    """The `stats` line, then the routes with a slow request, the worst first. `slow_routes` says
    how many there were, so a cut list shows itself."""
    taken = window.take()
    slow = sorted(
        ((key, times) for key, times in taken.routes.items() if times.over_1s),
        key=lambda item: (-item[1].over_1s, -item[1].total_ms, item[0]),
    )
    return [
        f"stats window={seconds:g}s requests={taken.requests} 5xx={taken.errors} "
        f"max_ms={taken.slowest_ms} slow_routes={len(slow)} {pool_fields(engine)}",
        *(
            f"stats_route window={seconds:g}s method={method} route={route} "
            f"requests={times.requests} over_1s={times.over_1s} over_3s={times.over_3s} "
            f"total_ms={times.total_ms} max_ms={times.slowest_ms}"
            for (method, route), times in slow[:ROUTE_LINES]
        ),
    ]


class Reporter:
    """Logs the `stats` lines once a minute."""

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
                for text in lines(self.window, self.engine, self.interval):
                    log.info(text)
            except Exception:
                log.exception("the stats line failed")
