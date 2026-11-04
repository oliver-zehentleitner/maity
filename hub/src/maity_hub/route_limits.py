"""Limits on single routes that the operator sets in an emergency (MAITY_ROUTE_LIMITS, §1.7).

The general limit per client is the ingress's (hub/context/kubernetes.md); the hub limits no
route by default beyond what the route limits itself. An entry names a route of the API as
the hub's OpenAPI document lists it (`/api/v1/openapi.json`) and is resolved against that
document when the app is built: a route the document does not list with that method stops
the hub, so a typo never leaves the operator believing a limit holds. The routes are read
from the app's router, in the order it matches in, each named by its path as the document
lists it (`path_format`) and matched by the router's own pattern, so a path converter
(`{path:path}`, listed as `{path}`) matches as many segments as the route does. A request
counts against the first route whose method and pattern it fits; that is the route that
serves it. Counted per client
address in this process only (`Limiter(local=True)`): no database write per request, so
with several replicas each counts its own share.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from fastapi.routing import iter_route_contexts
from starlette.routing import compile_path
from starlette.types import Scope

from maity_hub.config import ConfigError, RouteLimit
from maity_hub.ratelimit import Limiter

# The methods a route of the OpenAPI document is listed under.
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")


@dataclass(frozen=True)
class Table:
    # Every route of the API in the router's order, as (method, pattern, template); empty
    # when no limit is set, so nothing is matched at all.
    routes: tuple[tuple[str, re.Pattern[str], str], ...] = ()
    limiters: dict[tuple[str, str], Limiter] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.limiters)


def resolve(app_routes: Iterable[Any], limits: tuple[RouteLimit, ...]) -> Table:
    """The table for `limits`, or ConfigError for an entry the API does not have.
    `app_routes` are the app's routes in the router's order, included routers walked with
    their prefixes (`iter_route_contexts`); those the OpenAPI document lists
    (`include_in_schema`) are the ones a limit may name. A route's pattern is compiled from
    its declared path, converters kept."""
    if not limits:
        return Table()
    routes: list[tuple[str, re.Pattern[str], str]] = []
    for route in iter_route_contexts(list(app_routes)):
        if not getattr(route, "include_in_schema", False) or not route.methods:
            continue
        if route.path is None or route.path_format is None:
            continue  # for the type checker: a route with methods always has both
        pattern = compile_path(route.path)[0]
        for method in _METHODS:
            if method in route.methods:
                routes.append((method, pattern, route.path_format))
    listed = {(method, template) for method, _, template in routes}
    limiters: dict[tuple[str, str], Limiter] = {}
    for limit in limits:
        if (limit.method, limit.template) not in listed:
            raise ConfigError(
                f"MAITY_ROUTE_LIMITS: the hub has no route {limit.method} {limit.template}"
                " (write it as /api/v1/openapi.json lists it,"
                " e.g. /api/v1/projects/{owner}/{slug}/events)"
            )
        limiters[(limit.method, limit.template)] = Limiter(
            limit.count,
            limit.seconds,
            name=f"route_limits.{limit.method} {limit.template}",
            local=True,
        )
    return Table(tuple(routes), limiters)


def wait(scope: Scope, table: Table, key: str) -> int:
    """Count this request against the limit of the route that serves it: 0 when it may go
    on, else the seconds until it may. A request whose route has no limit counts nowhere."""
    if not table:
        return 0
    method = str(scope.get("method", ""))
    path = str(scope.get("path", ""))
    if all(m != method for m, _ in table.limiters):
        return 0  # no limit for this method: no route needs matching
    for route_method, pattern, template in table.routes:
        if route_method == method and pattern.match(path):
            limiter = table.limiters.get((method, template))
            return limiter.hit(key) if limiter is not None else 0
    return 0
