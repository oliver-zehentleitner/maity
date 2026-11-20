"""Every GET route under /api/v1/ that answers a list (`items`) has a test that shows it costs
the same statements for 3 rows as for 30 (`@flat_rows`, tests/list_rows.py), or is listed here
as no list.

The routes come from the app's router, as in `test_contract_shapes`. The claims come from the
`@flat_rows("/route")` decorators in tests/test_*.py, read from the source. A GET route in none
of the claims, `NOT_LISTS`, `ITEMS_INSIDE` and `CATALOGS` fails, and so does an entry that is no
route any more. A route in `NOT_LISTS` whose code names `"items"` fails too: that is how a new
list route put there by mistake is found (hub/context/testing.md)."""

from __future__ import annotations

import ast
import inspect
import re
import types
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.routing import iter_route_contexts

from tests import list_rows
from tests.test_contract_shapes import _get_routes, _plain

TESTS = Path(__file__).parent

# GET routes that answer no list: an object, a file, a page. One per line, sorted. A route whose
# code names "items" cannot be here (`test_no_route_of_not_lists_names_items`).
NOT_LISTS = {
    "/admin/instance",
    "/admin/maintenance",
    "/admin/projects/{}/{}/limits",
    "/admin/reports/{}",
    "/admin/settings/auth-pages",
    "/admin/settings/landing",
    "/admin/settings/legal",
    "/admin/settings/limits",
    "/admin/settings/mail",
    "/admin/settings/registration",
    "/admin/settings/sign-in",
    "/admin/settings/site-values",
    "/admin/statistics",
    "/admin/statistics/campaigns",
    "/admin/users/{}/limits",
    "/agents/{}",
    "/agents/{}/soul",
    "/auth/device-codes/{}",
    "/auth/device-login",
    "/auth/methods",
    "/auth/pages/{}",
    "/auth/second-factor",
    "/auth/session",
    "/avatars/motifs",  # the motif catalog as `motifs`, from the code
    "/avatars/public/{}",
    "/avatars/{}",
    "/forge/github/setup",
    "/health",
    "/help",
    "/invitations/{}",
    "/join/{}",
    "/legal",
    "/maintenance",
    "/me",
    "/me/broadcasts",  # `agents`: the caller's own agents, a setting each
    "/me/chat-access",
    "/me/cross-chats/{}",
    "/me/forge",  # `links`: one per forge account the caller linked, at most a few
    "/me/notification-settings",
    "/me/preferences",
    "/me/soul",
    "/openapi.json",
    "/orgs/{}",
    "/people/{}",
    "/projects/{}/{}",
    "/projects/{}/{}/attachments/{}",
    "/projects/{}/{}/attachments/{}/content",
    "/projects/{}/{}/banner",
    "/projects/{}/{}/contract",
    "/projects/{}/{}/conversations/{}",
    "/projects/{}/{}/events/{}",
    "/projects/{}/{}/forge/webhook",
    "/projects/{}/{}/jour-fixe",
    "/projects/{}/{}/jour-fixe/rounds/{}",
    "/projects/{}/{}/keep-the-why",
    "/projects/{}/{}/keep-the-why/bodies",
    "/projects/{}/{}/keep-the-why/export",
    "/projects/{}/{}/limits",
    "/projects/{}/{}/logo",
    "/projects/{}/{}/me/settings",
    "/projects/{}/{}/members/{}",
    "/projects/{}/{}/members/{}/preferences",
    "/projects/{}/{}/overview",
    "/projects/{}/{}/placements/{}",
    "/projects/{}/{}/probe",
    "/projects/{}/{}/requests/{}",
    "/projects/{}/{}/roles",
    "/projects/{}/{}/rules",
    "/projects/{}/{}/swarm",
    "/projects/{}/{}/takeovers/{}",
    "/projects/{}/{}/tasks/{}",
    "/projects/{}/{}/tasks/{}/contract",
    "/projects/{}/{}/tasks/{}/restricted",
    "/projects/{}/{}/ticker/subscription",
    "/public/pages/{}",
    "/requests/{}",
    "/runner",  # `update_requests`: the runner's open ones, at most one per placement
    "/runners/{}",
}

# GET routes whose code names "items" but whose answer is no list at the top: the name is in a
# part of it, or in what it reads. Each with its reason; the test fails on an entry whose code no
# longer names it.
ITEMS_INSIDE = {
    "/admin/settings/landing/preview/{}": "a landing page's sections, which have `items`",
    "/admin/settings/legal/preview/{}": "a page drawn from the landing's sections",
    "/bootstrap": "its parts, `members` among them, are the single routes' answers (§5.4)",
    "/landing": "the landing page's sections, which have `items`",
    "/me/export": "the export carries the lists of the caller's data, read once",
    "/projects/{}/{}/members/{}/briefing": "the briefing names the memory's `items`",
    "/site/chrome": "the site's menus, from the landing's sections",
}

# GET routes that answer a list from the hub's own code, not from rows: nothing to grow.
CATALOGS = {
    "/languages": "the interface languages the hub ships (§16.12)",
}

# How deep `_names_items` follows the calls of a route's function into the hub's code.
DEPTH = 4


def claims(files: Iterable[Path]) -> dict[str, list[str]]:
    """Route -> the tests that claim it, from the `@flat_rows(...)` decorators in `files`."""
    found: dict[str, list[str]] = {}
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                name = decorator.func
                called = name.id if isinstance(name, ast.Name) else getattr(name, "attr", "")
                if called != "flat_rows":
                    continue
                for arg in decorator.args:
                    assert isinstance(arg, ast.Constant) and isinstance(
                        arg.value, str
                    ), f"{path.name}::{node.name}: a @flat_rows route that is no string literal"
                    found.setdefault(arg.value, []).append(f"{path.name}::{node.name}")
    return found


def unaccounted(routes: set[str], claimed: set[str]) -> dict[str, set[str]]:
    """What the guard fails on, by kind; empty when every GET route is accounted for."""
    lists = (claimed, NOT_LISTS, set(ITEMS_INSIDE), set(CATALOGS))
    listed = set().union(*lists)
    twice = {r for i, a in enumerate(lists) for b in lists[i + 1 :] for r in a & b}
    problems = {
        "GET routes in no @flat_rows test and in none of NOT_LISTS, ITEMS_INSIDE, CATALOGS": (
            routes - listed
        ),
        "entries that are no GET route (any more)": listed - routes,
        "routes in two of them": twice,
        "GROWING entries no @flat_rows test claims": set(list_rows.GROWING) - claimed,
    }
    return {kind: found for kind, found in problems.items() if found}


def _names_items(function: Callable[..., Any], depth: int, seen: set[Any]) -> bool:
    """`"items"` is in the source of `function`, or of a function of the hub it calls, to
    `depth` calls deep: by the names it calls, looked up in its module's globals."""
    if depth < 0 or function in seen:
        return False
    seen.add(function)
    try:
        source = inspect.getsource(function)
    except (OSError, TypeError):
        return False
    if re.search(r"""["']items["']""", source):
        return True
    names = getattr(function, "__globals__", {})
    for called in set(re.findall(r"\b([A-Za-z_][\w.]*)\s*\(", source)):
        head, *rest = called.split(".")
        found: Any = names.get(head)
        for part in rest:
            found = getattr(found, part, None)
        if (
            isinstance(found, types.FunctionType)
            and found.__module__.startswith("maity_hub")
            and _names_items(found, depth - 1, seen)
        ):
            return True
    return False


def naming_items(app_routes: Any) -> set[str]:
    """The GET routes under /api/v1/ whose function, or what it calls, names `"items"`."""
    return {
        _plain(route.path_format.removeprefix("/api/v1"))
        for route in iter_route_contexts(list(app_routes))
        if route.methods
        and "GET" in route.methods
        and route.path_format is not None
        and route.path_format.startswith("/api/v1/")
        and route.endpoint is not None
        and _names_items(route.endpoint, DEPTH, set())
    }


def test_every_get_route_is_a_measured_list_or_listed_as_none(client: Any) -> None:
    claimed = claims(sorted(TESTS.glob("test_*.py")))
    assert unaccounted(_get_routes(client.app.routes), set(claimed)) == {}


def test_no_route_of_not_lists_names_items(client: Any) -> None:
    naming = naming_items(client.app.routes)
    assert NOT_LISTS & naming == set(), "lists in NOT_LISTS: give them a @flat_rows test"
    assert set(ITEMS_INSIDE) - naming == set(), "ITEMS_INSIDE entries that name no items now"


def test_the_catalogs_answer_a_list(client: Any) -> None:
    for route in CATALOGS:
        response = client.get(f"/api/v1{route}")
        assert response.status_code == 200, response.text
        assert isinstance(response.json()["items"], list)


def test_a_new_list_route_without_a_test_fails_the_guard(tmp_path: Path) -> None:
    """The counter-check: an app with one more list route, and a test file that measures
    another route than it."""
    app = FastAPI()
    app.add_api_route("/api/v1/projects/{owner}/{slug}/tasks", lambda: {"items": []})
    app.add_api_route("/api/v1/new-list", lambda: {"items": []})
    measured = tmp_path / "test_measured.py"
    measured.write_text(
        "@flat_rows('/projects/{}/{}/tasks')\ndef test_it():\n    pass\n", encoding="utf-8"
    )
    claimed = set(claims([measured]))
    assert claimed == {"/projects/{}/{}/tasks"}
    problems = unaccounted(_get_routes(app.routes), claimed)
    missing = "GET routes in no @flat_rows test and in none of NOT_LISTS, ITEMS_INSIDE, CATALOGS"
    assert problems[missing] == {"/new-list"}
    assert naming_items(app.routes) == {"/projects/{}/{}/tasks", "/new-list"}
