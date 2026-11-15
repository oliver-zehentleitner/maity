"""docs/api.md: every GET answer carries the top-level keys the contract names for it.

The contract gives an answer's shape in three forms: a JSON example, braces in a sentence, or
a table. A parser would have to guess which of them is the answer of which route, so the keys
are listed here by hand. Each entry is anchored to the contract: its anchor is a line that must
still be in docs/api.md, and every key must be named between that line and the next heading.
Only the top-level keys are checked: their content, and keys the hub sends beyond the
contract, are not modelled (hub/context/testing.md).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import iter_route_contexts
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory

CONTRACT = Path(__file__).parents[2] / "docs" / "api.md"

# The paging answer of every list (§1.4).
PAGE = ('{ "items": [ ... ], "next_cursor": "..." }', {"items", "next_cursor"})

# The routes checked, as "/path with {}": (anchor, keys). The anchor is a line, or part of one,
# of docs/api.md; each key must be named after it, before the next heading.
SHAPES: dict[str, tuple[str, set[str]]] = {
    "/me": ("### 5.1 `GET /me`", {"member", "projects", "maintenance", "server_time"}),
    "/bootstrap": ("### 5.4 `GET /bootstrap`", {"maintenance", "session", "me"}),
    "/me/chat-access": ("| `GET /me/chat-access` | human |", {"allow", "deny"}),
    "/me/contact-of": PAGE,
    "/me/contacts": PAGE,
    "/projects/{}/{}": (
        "### 6.1 Project",
        {
            "id", "slug", "owner", "full_name", "aliases", "name", "state", "released_at",
            "state_note", "state_changed_at", "repository", "links", "logo", "banner", "memory",
            "setup", "keep_the_why_export", "policy", "absence", "settings", "attachments",
            "rules_version", "created_at", "public_page", "public_about",
        },
    ),  # fmt: skip
    "/projects/{}/{}/members": PAGE,
    "/projects/{}/{}/requests": PAGE,
    "/projects/{}/{}/roles": (
        '`GET` with `project:read` answers `{"builtin": [{name, description, guide, scopes}], '
        '"custom": […]}`',
        {"builtin", "custom"},
    ),
    "/projects/{}/{}/tasks": PAGE,
}

# Keys the contract names that the hub does not send yet, each with the card that adds them.
# The test fails on an entry the hub now sends: remove it in that card's pull request.
KNOWN_GAPS: dict[str, set[str]] = {}

# GET routes under /api/v1/ that answer no contract shape, each with its reason.
OUTSIDE = {
    "/openapi.json",  # the machine form of the routes, not an answer the contract shapes (§12)
}

# GET routes whose shape is not checked yet (tsk-x4c4v639trrv moves them in batches), one per
# line. Move a route to SHAPES with its anchor; the test fails on an entry that is no longer a
# GET route or is in SHAPES too.
PENDING = {
    "/admin/maintenance",
    "/admin/maintenance/changes",
    "/admin/orgs",
    "/admin/registrations",
    "/admin/reports",
    "/admin/reports/{}",
    "/admin/settings/auth-pages",
    "/admin/settings/landing",
    "/admin/settings/landing/preview/{}",
    "/admin/settings/legal",
    "/admin/settings/legal/preview/{}",
    "/admin/settings/limits",
    "/admin/settings/mail",
    "/admin/settings/registration",
    "/admin/settings/sign-in",
    "/admin/settings/site-values",
    "/admin/statistics",
    "/admin/statistics/campaigns",
    "/admin/users",
    "/agents",
    "/agents/{}",
    "/agents/{}/soul",
    "/agents/{}/soul/versions",
    "/auth/device-codes/{}",
    "/auth/device-login",
    "/auth/methods",
    "/auth/pages/{}",
    "/auth/second-factor",
    "/auth/session",
    "/auth/sessions",
    "/avatars/motifs",
    "/avatars/public/{}",
    "/avatars/{}",
    "/forge/github/setup",
    "/health",
    "/help",
    "/invitations/{}",
    "/join/{}",
    "/landing",
    "/languages",
    "/legal",
    "/maintenance",
    "/me/broadcasts",
    "/me/conversations",
    "/me/cross-chats",
    "/me/cross-chats/{}",
    "/me/cross-chats/{}/messages",
    "/me/export",
    "/me/forge",
    "/me/notification-settings",
    "/me/notifications",
    "/me/preferences",
    "/me/preferences/versions",
    "/me/reports",
    "/me/soul",
    "/orgs",
    "/orgs/{}",
    "/orgs/{}/members",
    "/orgs/{}/members/invitations",
    "/people/{}",
    "/projects",
    "/projects/{}/{}/attachments",
    "/projects/{}/{}/attachments/{}",
    "/projects/{}/{}/attachments/{}/content",
    "/projects/{}/{}/banner",
    "/projects/{}/{}/contract",
    "/projects/{}/{}/conversations",
    "/projects/{}/{}/conversations/{}",
    "/projects/{}/{}/conversations/{}/messages",
    "/projects/{}/{}/events",
    "/projects/{}/{}/events/{}",
    "/projects/{}/{}/forge/webhook",
    "/projects/{}/{}/invitations",
    "/projects/{}/{}/joins",
    "/projects/{}/{}/jour-fixe",
    "/projects/{}/{}/jour-fixe/rounds",
    "/projects/{}/{}/jour-fixe/rounds/{}",
    "/projects/{}/{}/jour-fixe/rounds/{}/answers",
    "/projects/{}/{}/jour-fixe/series",
    "/projects/{}/{}/keep-the-why",
    "/projects/{}/{}/keep-the-why/bodies",
    "/projects/{}/{}/keep-the-why/export",
    "/projects/{}/{}/logo",
    "/projects/{}/{}/me/settings",
    "/projects/{}/{}/members/{}",
    "/projects/{}/{}/members/{}/briefing",
    "/projects/{}/{}/members/{}/briefings",
    "/projects/{}/{}/members/{}/credentials",
    "/projects/{}/{}/members/{}/preferences",
    "/projects/{}/{}/memory",
    "/projects/{}/{}/messages",
    "/projects/{}/{}/overview",
    "/projects/{}/{}/placements",
    "/projects/{}/{}/placements/{}",
    "/projects/{}/{}/placements/{}/reports",
    "/projects/{}/{}/probe",
    "/projects/{}/{}/requests/{}",
    "/projects/{}/{}/rules",
    "/projects/{}/{}/runners",
    "/projects/{}/{}/swarm",
    "/projects/{}/{}/takeovers",
    "/projects/{}/{}/takeovers/{}",
    "/projects/{}/{}/tasks/{}",
    "/projects/{}/{}/tasks/{}/contract",
    "/projects/{}/{}/tasks/{}/history",
    "/projects/{}/{}/tasks/{}/notes",
    "/projects/{}/{}/tasks/{}/restricted",
    "/projects/{}/{}/ticker",
    "/projects/{}/{}/ticker/subscription",
    "/public/pages/{}",
    "/requests",
    "/requests/{}",
    "/runner",  # the runner's credential only, like its siblings; the owner fixture gets 403
    "/runner/events",
    "/runner/placements",
    "/runners",
    "/runners/enrollments",
    "/runners/{}",
    "/site/chrome",
}


def _plain(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path.split("?")[0])


def _get_routes(app_routes: Any) -> set[str]:
    """Every GET route of the API: the app's router with its included routers and their
    prefixes walked, those left out of the OpenAPI document (`include_in_schema=False`) too."""
    paths = {
        route.path_format
        for route in iter_route_contexts(list(app_routes))
        if route.methods and "GET" in route.methods and route.path_format is not None
    }
    return {_plain(p.removeprefix("/api/v1")) for p in paths if p.startswith("/api/v1/")}


def _named_after(anchor: str) -> str:
    """The contract's text from the line holding `anchor` to the next heading."""
    lines = CONTRACT.read_text(encoding="utf-8").splitlines()
    at = [i for i, line in enumerate(lines) if anchor in line]
    assert len(at) == 1, f"the anchor is in {len(at)} lines of docs/api.md, not one: {anchor}"
    end = next((i for i in range(at[0] + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    return "\n".join(lines[at[0] : end])


def _names(text: str, key: str) -> bool:
    """`key` is named as a JSON key, a code span, or a word in braces."""
    return bool(re.search(rf'"{key}"|`{key}`|[{{,]\s*{key}\b', text))


def test_every_get_route_is_checked_or_pending(client: Any) -> None:
    routes = _get_routes(client.app.routes)
    shaped, pending = set(SHAPES), PENDING
    for a, b in ((shaped, pending), (shaped, OUTSIDE), (pending, OUTSIDE)):
        assert not a & b, f"in two lists: {sorted(a & b)}"
    listed = shaped | pending | OUTSIDE
    assert routes - listed == set(), "GET routes in none of SHAPES, PENDING and OUTSIDE"
    assert listed - routes == set(), "entries that are no GET route (any more)"
    assert set(KNOWN_GAPS) <= shaped, "a KNOWN_GAPS entry for a route SHAPES does not check"


@pytest.mark.parametrize("path", sorted(SHAPES))
def test_the_contract_names_each_listed_key_after_its_anchor(path: str) -> None:
    anchor, keys = SHAPES[path]
    text = _named_after(anchor)
    unnamed = {key for key in keys if not _names(text, key)}
    assert not unnamed, f"{path}: docs/api.md does not name {sorted(unnamed)} after its anchor"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _answer(owner: flow.Human, path: str) -> dict[str, Any]:
    concrete = path.replace("/projects/{}/{}", "/projects/maintainer/maity", 1)
    assert "{}" not in concrete, f"{path}: say here which ids the test calls it with"
    response = owner.get(concrete)
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def _check(path: str, sent: set[str]) -> None:
    missing = SHAPES[path][1] - sent
    gaps = KNOWN_GAPS.get(path, set())
    assert missing == gaps, (
        f"{path}: missing {sorted(missing - gaps)}; "
        f"KNOWN_GAPS entries now sent, remove them: {sorted(gaps - missing)}"
    )


@pytest.mark.parametrize("path", sorted(SHAPES))
def test_the_answer_carries_the_keys_the_contract_names(path: str, owner: flow.Human) -> None:
    _check(path, set(_answer(owner, path)))


def test_a_route_left_out_of_the_schema_is_still_counted() -> None:
    # #1499 review: a GET with `include_in_schema=False` answers like any other.
    router = APIRouter()
    router.add_api_route("/hidden", lambda: {}, methods=["GET"], include_in_schema=False)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    assert "/hidden" in _get_routes(app.routes)


def test_a_key_named_below_the_example_is_checked_too(owner: flow.Human) -> None:
    # #1499 review: `public_page` and `public_about` are named after §6.1's JSON example.
    sent = set(_answer(owner, "/projects/{}/{}")) - {"public_page", "public_about"}
    with pytest.raises(AssertionError, match="missing \\['public_about', 'public_page'\\]"):
        _check("/projects/{}/{}", sent)
