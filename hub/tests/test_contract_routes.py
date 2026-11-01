"""docs/api.md §12: the endpoint index and the hub's API routes name the same endpoints."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CONTRACT = Path(__file__).parents[2] / "docs" / "api.md"
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# In the index without a route of the API, each for a reason. Remove an entry when its route
# comes: the test fails on an entry that no longer applies.
NOT_ROUTED = {
    # The machine form describes the routes, not itself.
    ("GET", "/openapi.json"),
    # Answered ahead of the router, as it carries no credential and no CSRF token (§17.4).
    ("POST", "/projects/{}/{}/forge/webhook"),
    # Contract without a route yet: tsk-4xqfxezvz0dh.
    ("DELETE", "/projects/{}/{}/tasks/{}/objection-hold"),
    # Contract without a route yet: tsk-r97n4e6v4kaz.
    ("PATCH", "/projects/{}/{}/conversations/{}/participants/{}"),
    # Contract without a route yet: tsk-962vfr5m8z7t.
    ("GET", "/public/pages/{}"),
}


def _index() -> set[tuple[str, str]]:
    """Method and path of the rows of §12. A row outside the API says so, and has no route here.
    Every span counts: a shorthand like `…/steps` would name no route, and so fails the test."""
    text = CONTRACT.read_text(encoding="utf-8").split("## 12. Endpoint index", 1)[1]
    rows = set()
    for line in text.split("\n## 13", 1)[0].splitlines():
        cells = line.split(" | ")
        methods = [m.strip() for m in cells[0].strip("| ").split(",")]
        if len(cells) < 3 or not set(methods) <= set(METHODS):
            continue
        if cells[1].endswith("(outside the API)"):
            continue
        for path in re.findall(r"`([^`]*)`", re.sub(r"\([^)]*\)", "", cells[1])):
            rows |= {(method, _plain(path)) for method in methods}
    return rows


def _plain(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path.split("?")[0])


def _routes(openapi: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (method.upper(), _plain(path.removeprefix("/api/v1")))
        for path, operations in openapi["paths"].items()
        if path.startswith("/api/v1/")
        for method in operations
        if method.upper() in METHODS
    }


def test_the_index_and_the_routes_name_the_same_endpoints(client: Any) -> None:
    routes = _routes(client.get("/api/v1/openapi.json").json())
    index = _index()
    assert routes - index == set(), "routes the contract's index does not name"
    assert index - routes == NOT_ROUTED, "index rows without a route, or a stale NOT_ROUTED"
