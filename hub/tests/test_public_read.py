"""docs/api.md §16.9, "What visitors read in the dashboard": `GET /public/pages/{path}` answers
what the render stored, the same for everyone, and exactly the keys of the contract's table."""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import public_pages
from maity_hub import tables as t
from tests.conftest import ClientFactory
from tests.test_public_project_views import World

ROUTE = "/api/v1/public/pages"
BASE = "maintainer/maity"
PERSON = {"name", "handle", "page"}


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, settings: Any) -> World:
    public_pages.configure(replace(settings, public_pages=True))
    return World(make_client, migrated)


def read(world: World, path: str) -> dict[str, Any]:
    got = world.anyone.get(f"{ROUTE}/{path}")
    assert got.status_code == 200, got.text
    answer: dict[str, Any] = got.json()
    assert set(answer) == {"path", "kind", "data"} and answer["path"] == f"/{path}"
    return answer


def publish_profile(world: World, who: Any, **more: Any) -> None:
    assert who.patch("/me", {"public_profile": True, **more}).status_code == 200


def test_each_kind_answers_exactly_the_keys_of_the_contract(world: World) -> None:
    publish_profile(world, world.owner, public_bio="I build.")
    world.card(status="open", title="Next up", label="idea")
    world.touch()

    project = read(world, BASE)
    assert project["kind"] == "project"
    assert set(project["data"]) == {
        "name",
        "full_name",
        "about",
        "state",
        "repository_url",
        "links",
        "people",
        "agents",
        "other_agents",
        "statistics",
    }
    assert set(project["data"]["statistics"]) == {"totals", "members"}
    assert [set(p) for p in project["data"]["people"]] == [PERSON]

    board = read(world, f"{BASE}/board")
    assert board["kind"] == "board" and set(board["data"]) == {"columns"}
    cards = [c for col in board["data"]["columns"] for c in col["cards"]]
    assert cards and all(set(c) == {"id", "title", "label", "holder"} for c in cards)

    members = read(world, f"{BASE}/members")
    assert members["kind"] == "members" and set(members["data"]) == {"shown", "others"}
    assert all(set(p) == PERSON | {"trust", "role"} for p in members["data"]["shown"])
    assert all(set(o) == {"role", "count"} for o in members["data"]["others"])

    organisation = read(world, f"{BASE}/organisation")
    assert organisation["kind"] == "organisation" and set(organisation["data"]) == {"nodes"}
    assert all(
        set(n) == {"index", "person", "role", "reports_to"} for n in organisation["data"]["nodes"]
    )

    person = read(world, "maintainer")
    assert person["kind"] == "person"
    assert {"name", "handle", "bio", "projects", "agents"} <= set(person["data"])
    assert set(person["data"]) <= {
        "name",
        "handle",
        "bio",
        "website",
        "social",
        "projects",
        "agents",
    }

    bot = project["data"]["agents"][0]
    agent = read(world, bot["page"].lstrip("/"))
    assert agent["kind"] == "agent"
    assert set(agent["data"]) == {"name", "handle", "owner", "projects", "statistics"}
    assert set(agent["data"]["owner"]) == PERSON


def test_nothing_private_reaches_an_answer(world: World, migrated: Engine) -> None:
    """A marker in every private column a render could reach, and the owner's member id."""
    publish_profile(world, world.owner)
    secret = "CANARY-private"
    done = world.card(status="open", title="Visible", body=f"{secret} body")
    noted = world.owner.post(f"/projects/{BASE}/tasks/{done}/notes", {"body": f"{secret} note"})
    assert noted.status_code in (200, 201), noted.text
    with migrated.begin() as conn:
        conn.execute(
            update(t.human)
            .where(t.human.c.id == world.owner.id)
            .values(limit_reason=f"{secret} limit", password_hash=secret)
        )
    world.card(status="open", title=f"{secret} security", label="security")
    world.touch()
    for path in (BASE, f"{BASE}/board", f"{BASE}/members", f"{BASE}/organisation", "maintainer"):
        text = world.anyone.get(f"{ROUTE}/{path}").text
        assert secret not in text, path
        assert world.owner.id not in text, path
        assert world.bot.id not in text, path


def test_links_appear_only_while_the_person_lets_everyone_see_them(world: World) -> None:
    publish_profile(world, world.owner, website="https://canary.example", links_visible="friends")
    assert not {"website", "social"} & set(read(world, "maintainer")["data"])
    assert "canary.example" not in world.anyone.get(f"{ROUTE}/maintainer").text
    assert world.owner.patch("/me", {"links_visible": "everyone"}).status_code == 200
    assert read(world, "maintainer")["data"]["website"] == "https://canary.example"


def test_a_holder_is_named_only_while_the_page_names_them(world: World) -> None:
    card = world.card(status="in_progress", title="Held", claim_holder=world.owner_member)
    assert card
    world.touch()

    def holder() -> Any:
        columns = read(world, f"{BASE}/board")["data"]["columns"]
        return next(c for col in columns for c in col["cards"] if c["title"] == "Held")["holder"]

    assert holder() == "member"
    publish_profile(world, world.owner)
    assert holder()["handle"] == "maintainer"


def test_the_organisation_numbers_its_nodes_and_never_names_a_member_id(
    world: World, migrated: Engine
) -> None:
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == world.anna_member)
            .values(reports_to=world.owner_member)
        )
    world.touch()
    nodes = read(world, f"{BASE}/organisation")["data"]["nodes"]
    assert [n["index"] for n in nodes] == list(range(len(nodes)))
    assert any(n["reports_to"] is not None for n in nodes)
    assert all(n["reports_to"] in (None, *range(len(nodes))) for n in nodes)


def test_a_session_changes_nothing_and_sets_no_cookie(world: World) -> None:
    anonymous = world.anyone.get(f"{ROUTE}/{BASE}")
    signed_in = world.owner.get(f"/public/pages/{BASE}")
    assert anonymous.status_code == signed_in.status_code == 200
    assert anonymous.content == signed_in.content
    for got in (anonymous, signed_in):
        assert "set-cookie" not in got.headers
        assert got.headers["cache-control"] == "public, max-age=60"
        assert got.headers["content-type"] == "application/json"
        assert "cookie" not in got.headers.get("vary", "").lower()
        assert got.headers["etag"]


def test_a_matching_etag_answers_304(world: World) -> None:
    tag = world.anyone.get(f"{ROUTE}/{BASE}").headers["etag"]
    assert world.anyone.get(f"{ROUTE}/{BASE}", headers={"If-None-Match": tag}).status_code == 304


def test_a_path_with_no_page_is_not_found_and_removal_is_at_once(world: World) -> None:
    for path in (f"{BASE}/why", f"{BASE}/inbox", "nobody", f"{BASE}/board/"):
        assert world.anyone.get(f"{ROUTE}/{path}").status_code == 404, path
    assert world.owner.patch(f"/projects/{BASE}", {"public_page": "off"}).status_code == 200
    for path in (BASE, f"{BASE}/board"):
        assert world.anyone.get(f"{ROUTE}/{path}").status_code == 404, path


def test_a_card_under_no_row_change_refreshes_the_data_without_new_inputs(
    world: World, migrated: Engine
) -> None:
    """Data follows its render even where the digest of the HTML stays the same."""
    with migrated.begin() as conn:
        conn.execute(update(t.public_page).values(data={"stale": True}))
    world.touch()
    assert "columns" in read(world, f"{BASE}/board")["data"]


def test_off_answers_not_found_for_every_path(make_client: ClientFactory) -> None:
    assert make_client(public_pages=False).get(f"{ROUTE}/{BASE}").status_code == 404


def test_the_read_spends_the_page_bucket(world: World, monkeypatch: Any) -> None:
    monkeypatch.setattr(public_pages.BY_ADDRESS, "hit", lambda _: 7)
    got = world.anyone.get(f"{ROUTE}/{BASE}")
    assert got.status_code == 429


def _api_paths(world: World) -> dict[str, Any]:
    paths: dict[str, Any] = world.anyone.get("/api/v1/openapi.json").json()["paths"]
    return paths


def test_the_route_is_the_only_public_read_it_adds(world: World) -> None:
    routes = {p: set(ops) for p, ops in _api_paths(world).items() if "/v1/public" in p}
    assert routes == {"/api/v1/public/pages/{path}": {"get"}}


def test_every_read_of_a_public_project_stays_closed_without_a_session(world: World) -> None:
    """The member routes answer a visitor nothing, however public the project is."""
    prefix = "/api/v1/projects/{owner}/{slug}"
    opened = []
    checked = 0
    for template, operations in _api_paths(world).items():
        if "get" not in operations or not template.startswith(prefix):
            continue
        path = template.replace("{owner}", "maintainer").replace("{slug}", "maity")
        path = re.sub(r"\{[^}]*\}", "x", path)
        checked += 1
        status = world.anyone.get(path).status_code
        if status not in (401, 404):
            opened.append((template, status))
    assert checked > 20 and not opened


def test_explore_lists_only_what_the_pages_show(world: World, migrated: Engine) -> None:
    html = world.anyone.get("/explore").text
    assert "/maintainer/maity" in html
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(name="<b>x</b>"))
    assert "<b>x</b>" not in world.anyone.get("/explore").text
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(state="archived"))
    assert "/maintainer/maity" not in world.anyone.get("/explore").text


def test_explore_is_the_shell_while_pages_are_off(make_client: ClientFactory) -> None:
    got = make_client(public_pages=False).get("/explore")
    assert got.status_code == 200 and "<title>dashboard</title>" in got.text
