"""docs/api.md §12: the endpoint index and the hub's API routes name the same endpoints."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CONTRACT = Path(__file__).parents[2] / "docs" / "api.md"
METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# In the index without a route of the API, each for a reason. Remove an entry when its route
# comes: the test fails on an entry that no longer applies. One entry per line, sorted by method
# and path, its reason on the same line: a pull request adding or removing an entry touches only
# its own line, so parallel ones conflict here only when they change neighbouring lines.
NOT_ROUTED = {
    ("DELETE", "/me/cross-chats/{}/participants/{}"),  # §9.5, not built: tsk-fvh80q02772c
    ("DELETE", "/projects/{}/{}/tasks/{}/objection-hold"),  # no route yet: tsk-4xqfxezvz0dh
    ("DELETE", "/projects/{}/{}/tasks/{}/restricted"),  # contract first: tsk-g8ts5vxhj1md
    ("GET", "/avatars/public/{}"),  # contract first: tsk-q155psrk6tzz, the hub PR adds it
    ("GET", "/me/briefings"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("GET", "/me/briefings/versions"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("GET", "/me/cross-chats"),  # contract only, §9.5, not built: tsk-fvh80q02772c
    ("GET", "/me/cross-chats/{}"),  # contract only, §9.5, not built: tsk-fvh80q02772c
    ("GET", "/me/cross-chats/{}/messages"),  # contract only, §9.5, not built: tsk-fvh80q02772c
    ("GET", "/me/soul/versions"),  # no route yet: tsk-k0k3jzrkpza2, the agent's soul
    ("GET", "/openapi.json"),  # the machine form describes the routes, not itself
    ("GET", "/projects/{}/{}/briefings"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("GET", "/projects/{}/{}/briefings/versions"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("GET", "/projects/{}/{}/tasks/{}/restricted"),  # contract first: tsk-g8ts5vxhj1md
    ("PATCH", "/me/briefings"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("PATCH", "/me/cross-chats/{}"),  # contract only, §9.5, not built: tsk-fvh80q02772c
    ("PATCH", "/me/preferences"),  # no route yet: tsk-k0k3jzrkpza2, "discuss first"
    ("PATCH", "/projects/{}/{}/briefings"),  # no route yet: tsk-k0k3jzrkpza2, briefings
    ("PATCH", "/projects/{}/{}/conversations/{}/participants/{}"),  # no route yet: tsk-r97n4e6v4kaz
    ("POST", "/agents/{}/soul/rollback"),  # no route yet: tsk-k0k3jzrkpza2, the agent's soul
    ("POST", "/me/cross-chats"),  # contract only, §9.5, not built: tsk-fvh80q02772c
    ("POST", "/me/cross-chats/{}/messages"),  # contract only, §9.5, not built: tsk-fvh80q02772c
    ("POST", "/me/cross-chats/{}/messages/{}/redact"),  # §9.5, not built: tsk-fvh80q02772c
    ("POST", "/me/cross-chats/{}/participants"),  # contract only, §9.5, not built: tsk-fvh80q02772c
    ("POST", "/projects/{}/{}/forge/webhook"),  # before the router: no credential, no CSRF (§17.4)
    ("PUT", "/me/soul"),  # no route yet: tsk-k0k3jzrkpza2, the agent's soul
    ("PUT", "/projects/{}/{}/tasks/{}/restricted"),  # contract first: tsk-g8ts5vxhj1md
}

# Routes the contract no longer names, removed with the hub change of the same card. Remove an
# entry when its route goes: the test fails on an entry that no longer applies.
UNLISTED = {
    # The agent writes its soul itself now (§19.1): tsk-k0k3jzrkpza2.
    ("POST", "/me/soul/proposals"),
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
    assert (
        routes - index == UNLISTED
    ), "routes the contract's index does not name, or a stale UNLISTED"
    assert index - routes == NOT_ROUTED, "index rows without a route, or a stale NOT_ROUTED"
