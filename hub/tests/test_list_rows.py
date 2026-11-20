"""Every GET route under /api/v1/ that answers a list (`items`) has a test that shows it costs
the same statements for 3 rows as for 30 (`@flat_rows`, tests/list_rows.py), or is listed here
as no list.

The routes come from the app's router, as in `test_contract_shapes`. The claims come from the
`@flat_rows("/route")` decorators in tests/test_*.py, read from the source. A GET route in none
of the claims, `NOT_LISTS`, `ITEMS_INSIDE` and `CATALOGS` fails, and so does an entry that is no
route any more. A route in `NOT_LISTS` whose code names `"items"` fails too, and so does one
whose answer, read on a small project, holds a list at the top under a key `LIST_KEYS` does
not name for it: that is how a new list route put there by mistake is found
(hub/context/testing.md)."""

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
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow, list_rows
from tests.conftest import ClientFactory
from tests.test_contract_shapes import _get_routes, _plain

TESTS = Path(__file__).parent

# GET routes that answer no list of rows: an object, a file, a page, each with what it is. One
# per line, sorted. A route whose code names "items" cannot be here
# (`test_no_route_of_not_lists_names_items`), and its answer may hold a list at the top only
# under a key `LIST_KEYS` names for it (`test_a_route_of_not_lists_answers_no_list_unnamed`).
NOT_LISTS = {
    "/admin/instance": "the instance's settings; `settings`: its own",
    "/admin/maintenance": "the one maintenance window",
    "/admin/projects/{}/{}/limits": "one project's ceilings",
    "/admin/reports/{}": "one report",
    "/admin/settings/auth-pages": "a setting",
    "/admin/settings/landing": "a setting; `campaigns`: the landing's own, set by the admin",
    "/admin/settings/legal": "a setting",
    "/admin/settings/limits": "a setting",
    "/admin/settings/mail": "a setting; `missing`, `warnings`: of the setting itself",
    "/admin/settings/registration": "a setting; `missing`: of the setting itself",
    "/admin/settings/sign-in": "a setting; `missing`, `password_reset_missing`: of the setting",
    "/admin/settings/site-values": "a setting",
    "/admin/statistics": "counts; `days`: a fixed window of days",
    "/admin/statistics/campaigns": "counts per campaign and variant the admin set up",
    "/admin/users/{}/limits": "one account's ceilings",
    "/agents/{}": "one agent; `aliases`, `memberships`: its own",
    "/agents/{}/soul": "one text",
    "/auth/device-codes/{}": "one code",
    "/auth/device-login": "one code's state",
    "/auth/methods": "the sign-in methods, from the settings",
    "/auth/pages/{}": "one page",
    "/auth/second-factor": "the caller's factor",
    "/auth/session": "the caller's session",
    "/avatars/motifs": "`motifs`: the catalog, from the code",
    "/avatars/public/{}": "a picture",
    "/avatars/{}": "a picture",
    "/forge/github/setup": "a redirect",
    "/health": "the probe",
    "/help": "a text",
    "/invitations/{}": "one invitation",
    "/join/{}": "one join",
    "/legal": "a page",
    "/maintenance": "the one window",
    "/me/cross-chats/{}": "one chat",
    "/me/forge": "`links`: one per forge account the caller linked, at most a few",
    "/me/notification-settings": "a setting; `kinds`: the catalog",
    "/me/soul": "one text",
    "/openapi.json": "the schema",
    "/orgs/{}": "one org",
    "/projects/{}/{}": "one project; `aliases`: its own",
    "/projects/{}/{}/attachments/{}": "one attachment",
    "/projects/{}/{}/attachments/{}/content": "a file",
    "/projects/{}/{}/banner": "a picture",
    "/projects/{}/{}/contract": "a text",
    "/projects/{}/{}/conversations/{}": "one chat; `participants`: its own",
    "/projects/{}/{}/events/{}": "one event",
    "/projects/{}/{}/forge/webhook": "a setting",
    "/projects/{}/{}/jour-fixe/rounds/{}": "one round",
    "/projects/{}/{}/keep-the-why": "the project's Keep the Why state, read from a stored export",
    "/projects/{}/{}/keep-the-why/bodies": "stored texts, read from the export",
    "/projects/{}/{}/keep-the-why/export": "a file",
    "/projects/{}/{}/logo": "a picture",
    "/projects/{}/{}/me/settings": "the caller's settings",
    "/projects/{}/{}/members/{}": "one member; its lists are its own parts",
    "/projects/{}/{}/members/{}/preferences": "one member's settings",
    "/projects/{}/{}/placements/{}": "one placement",
    "/projects/{}/{}/probe": "the forge's state",
    "/projects/{}/{}/requests/{}": "one request",
    "/projects/{}/{}/roles": "`builtin`: the catalog; `custom`: the project's own few",
    "/projects/{}/{}/rules": "a text",
    "/projects/{}/{}/takeovers/{}": "one takeover",
    "/projects/{}/{}/tasks/{}": "one card; its edges, links and mentions are its own",
    "/projects/{}/{}/tasks/{}/contract": "a text",
    "/projects/{}/{}/tasks/{}/restricted": "a text",
    "/projects/{}/{}/ticker/subscription": "the caller's subscription",
    "/public/pages/{}": "a page",
    "/requests/{}": "one request",
    "/runner": "`update_requests`: the runner's open ones, at most one per placement",
    "/runners/{}": "one runner",
}

# The top-level keys under which a NOT_LISTS answer holds a list, each bounded by something
# other than the rows of a table (its reason is the route's in NOT_LISTS): a catalog, one
# object's own parts, a setting. A list of rows under any other key is measured instead.
LIST_KEYS: dict[str, set[str]] = {
    "/admin/instance": {"settings"},
    "/admin/settings/landing": {"campaigns"},
    "/admin/settings/mail": {"missing", "warnings"},
    "/admin/settings/registration": {"missing"},
    "/admin/settings/sign-in": {"missing", "password_reset_missing"},
    "/admin/statistics": {"days"},
    "/admin/statistics/campaigns": {"campaigns", "rows", "variants"},
    "/agents/{}": {"aliases", "memberships"},
    "/avatars/motifs": {"motifs"},
    "/me/forge": {"links"},
    "/me/notification-settings": {"kinds"},
    "/projects/{}/{}": {"aliases"},
    "/projects/{}/{}/conversations/{}": {"participants"},
    "/projects/{}/{}/members/{}": {
        "aliases",
        "areas",
        "bridges",
        "bridging_for",
        "capabilities",
        "covering",
        "expert_sources",
        "instances",
        "isolation_windows",
        "placements",
        "shared_environment",
    },
    "/projects/{}/{}/roles": {"builtin", "custom"},
    "/projects/{}/{}/tasks/{}": {"depends_on", "links", "mentions", "related", "ships_with"},
    "/runner": {"update_requests"},
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
    lists = (claimed, set(NOT_LISTS), set(ITEMS_INSIDE), set(CATALOGS))
    listed = set().union(*lists)
    twice = {r for i, a in enumerate(lists) for b in lists[i + 1 :] for r in a & b}
    problems = {
        "GET routes in no @flat_rows test and in none of NOT_LISTS, ITEMS_INSIDE, CATALOGS": (
            routes - listed
        ),
        "entries that are no GET route (any more)": listed - routes,
        "routes in two of them": twice,
        "GROWING entries no @flat_rows test claims": set(list_rows.GROWING) - claimed,
        "LIST_KEYS entries for a route not in NOT_LISTS": set(LIST_KEYS) - set(NOT_LISTS),
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
    assert set(NOT_LISTS) & naming == set(), "lists in NOT_LISTS: give them a @flat_rows test"
    assert set(ITEMS_INSIDE) - naming == set(), "ITEMS_INSIDE entries that name no items now"


def test_the_catalogs_answer_a_list(client: Any) -> None:
    for route in CATALOGS:
        response = client.get(f"/api/v1{route}")
        assert response.status_code == 200, response.text
        assert isinstance(response.json()["items"], list)


def _lists_unnamed(
    app_routes: Any, ids: dict[str, str], callers: Iterable[Any]
) -> dict[str, set[str]]:
    """Route -> the top-level keys of its answers that hold a list and that `LIST_KEYS` does not
    name, for every NOT_LISTS route each caller reads with 200 when every path parameter is
    taken from `ids` (an unknown one as `none`)."""
    found: dict[str, set[str]] = {}
    for route in iter_route_contexts(list(app_routes)):
        if not route.methods or "GET" not in route.methods or route.path_format is None:
            continue
        plain = _plain(route.path_format.removeprefix("/api/v1"))
        if plain not in NOT_LISTS:
            continue
        path = re.sub(r"\{(\w+)\}", lambda m: ids.get(m.group(1), "none"), route.path_format)
        for caller in callers:
            answer = caller.get(path.removeprefix("/api/v1"))
            if answer.status_code != 200 or "json" not in answer.headers.get("content-type", ""):
                continue
            body = answer.json()
            keys = (
                {k for k, v in body.items() if isinstance(v, list)}
                if isinstance(body, dict)
                else {"<the answer>"} if isinstance(body, list) else set()
            )
            unnamed = keys - LIST_KEYS.get(plain, set())
            if unnamed:
                found.setdefault(plain, set()).update(unnamed)
    return found


def test_a_route_of_not_lists_answers_no_list_unnamed(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """Every NOT_LISTS route, read by a project's owner and by its agent on a small project
    (a card, the agent's chat): a route the two cannot read with 200 is not checked here."""
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        mine = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == owner.id)
        ).scalar_one()
    ids = {
        "owner": "maintainer",
        "slug": "maity",
        "org": "maintainer",
        "handle": "maintainer",
        "human_id": owner.id,
        "agent_id": agent.id,
        "member_id": agent.id,
        "conversation_id": agent.id,
        "card_id": factory.card(migrated, project_id, mine),
    }
    app: Any = owner.client.app
    assert _lists_unnamed(app.routes, ids, (owner, agent)) == {}


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
