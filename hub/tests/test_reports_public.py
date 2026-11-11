"""docs/api.md §16.8, "The id a stranger sends": anyone signed in reports what a page served now
shows, by the current public name the page shows; a target with no served page stays `not_found`
to a stranger, and a handle a project page lists twice is `ambiguous_handle`."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, select, update

from maity_hub import public_pages
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_public_projects_team import World, pages
from tests.test_public_projects_team import world as world  # noqa: F401  (the fixture)

PROJECT = "maintainer/maity"


def stranger(world: World, make_client: ClientFactory) -> Any:
    """A signed-in human in no project."""
    return flow.human(pages(make_client), world.migrated, "zoe")


def report(who: Any, target: dict[str, Any]) -> Any:
    return who.post("/reports", {"target": target, "reason": "spam"})


def snapshot(world: World, made: Any) -> dict[str, Any]:
    assert made.status_code == 201, made.text
    got = world.owner.get(f"/admin/reports/{made.json()['id']}")
    assert got.status_code == 200, got.text
    shot: dict[str, Any] = got.json()["snapshot"]
    return shot


def bot(world: World) -> dict[str, Any]:
    member: dict[str, Any] = world.bot.get("/me").json()["member"]
    return member


def test_a_stranger_reports_a_served_project_by_its_full_name(
    world: World, make_client: ClientFactory
) -> None:
    zoe = stranger(world, make_client)
    shot = snapshot(world, report(zoe, {"type": "project", "id": PROJECT}))
    assert shot["full_name"] == PROJECT
    assert world.owner.patch(f"/projects/{PROJECT}", {"public_page": "off"}).status_code == 200
    assert report(zoe, {"type": "project", "id": PROJECT}).status_code == 404


def test_a_stranger_reports_an_agent_by_its_global_name_never_by_its_id(
    world: World, make_client: ClientFactory
) -> None:
    zoe = stranger(world, make_client)
    agent = bot(world)
    by_id = report(zoe, {"type": "profile", "id": agent["id"]})
    assert by_id.status_code == 404, by_id.text
    shot = snapshot(world, report(zoe, {"type": "profile", "id": f"maintainer/{agent['handle']}"}))
    assert shot["id"] == agent["id"] and shot["kind"] == "agent"


def test_a_stranger_reports_the_bare_handle_a_project_page_shows_with_its_name(
    world: World, make_client: ClientFactory
) -> None:
    zoe = stranger(world, make_client)
    agent = bot(world)
    target = {"type": "profile", "id": agent["handle"], "project": PROJECT}
    assert snapshot(world, report(zoe, target))["id"] == agent["id"]
    unlisted = {"type": "profile", "id": "nobody-here", "project": PROJECT}
    assert report(zoe, unlisted).status_code == 404
    alone = report(zoe, {"type": "profile", "id": agent["handle"]})  # no project: no person
    assert alone.status_code == 404, alone.text


def test_a_handle_a_project_page_lists_twice_is_ambiguous(
    world: World, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = bot(world)
    other = factory.agent(migrated, world.project_id, world.anna.id, "coder")
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == other.agent_id)
            .values(handle=agent["handle"])
        )
        public_pages.touch(conn, "project", world.project_id)
    zoe = stranger(world, make_client)
    made = report(zoe, {"type": "profile", "id": agent["handle"], "project": PROJECT})
    assert made.status_code == 400, made.text
    assert made.json()["error"]["details"]["reason"] == "ambiguous_handle"
    # Each agent's own global name still names one agent.
    for owner, agent_id in (("maintainer", agent["id"]), ("anna", other.agent_id)):
        name = f"{owner}/{agent['handle']}"
        assert snapshot(world, report(zoe, {"type": "profile", "id": name}))["id"] == agent_id


def test_a_stranger_reports_a_person_by_the_handle_of_their_served_page(
    world: World, make_client: ClientFactory
) -> None:
    zoe = stranger(world, make_client)
    assert world.anna.patch("/me", {"public_profile": True}).status_code == 200
    shot = snapshot(world, report(zoe, {"type": "profile", "id": "anna"}))
    assert shot["id"] == world.anna.id and shot["kind"] == "human"
    assert report(zoe, {"type": "profile", "id": world.anna.id}).status_code == 404


def test_a_former_name_does_not_resolve(world: World, make_client: ClientFactory) -> None:
    zoe = stranger(world, make_client)
    renamed = world.owner.patch(f"/projects/{PROJECT}", {"slug": "maity-new"})
    assert renamed.status_code == 200, renamed.text
    assert report(zoe, {"type": "project", "id": PROJECT}).status_code == 404
    # Not for a member either: an alias must not confirm whose name it was.
    assert report(world.anna, {"type": "project", "id": PROJECT}).status_code == 404
    assert report(zoe, {"type": "project", "id": "maintainer/maity-new"}).status_code == 201


def test_a_card_with_its_own_page_is_reportable_and_one_without_and_a_message_are_not(
    world: World, make_client: ClientFactory, migrated: Engine
) -> None:
    zoe = stranger(world, make_client)
    with migrated.connect() as conn:
        owner_member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == world.owner.id)
        ).scalar_one()
    shown = factory.card(migrated, world.project_id, owner_member, title="buy tokens")
    hidden = factory.card(
        migrated, world.project_id, owner_member, title="a hole", label="security"
    )
    with migrated.begin() as conn:
        for card in (shown, hidden):
            public_pages.touch(conn, "card", card)
    target = {"type": "card", "id": shown, "project": PROJECT}
    assert snapshot(world, report(zoe, target))["title"] == "buy tokens"
    # A security card that is not done has no page: members-only (§16.9).
    secret = {"type": "card", "id": hidden, "project": PROJECT}
    assert report(zoe, secret).status_code == 404
    assert report(world.anna, secret).status_code == 201
    message = {"type": "message", "id": "evt-1", "project": PROJECT}
    assert report(zoe, message).status_code == 404


def mine(who: Any) -> list[dict[str, Any]]:
    got = who.get("/me/reports")
    assert got.status_code == 200, got.text
    return [item["target"] for item in got.json()["items"]]


def test_the_reporters_list_shows_the_current_public_name_or_a_neutral_word(
    world: World, make_client: ClientFactory
) -> None:
    zoe = stranger(world, make_client)
    agent = bot(world)
    assert world.anna.patch("/me", {"public_profile": True}).status_code == 200
    for target in (
        {"type": "project", "id": PROJECT},
        {"type": "profile", "id": agent["handle"], "project": PROJECT},
        {"type": "profile", "id": f"maintainer/{agent['handle']}"},
        {"type": "profile", "id": "anna"},
    ):
        assert report(zoe, target).status_code == 201
    assert mine(zoe) == [
        {"type": "profile", "id": "anna"},
        {"type": "profile", "id": f"maintainer/{agent['handle']}"},
        {"type": "profile", "id": agent["handle"], "project": PROJECT},
        {"type": "project", "id": PROJECT},
    ]
    held = world.owner.post(  # a hold takes the person's page off (§16.8, §16.9)
        "/reports", {"target": {"type": "profile", "id": world.anna.id}, "reason": "spam"}
    )
    assert held.status_code == 201, held.text
    resolve = f"/admin/reports/{held.json()['id']}/resolve"
    assert world.owner.post(resolve, {"action": "hide"}).status_code == 200
    assert world.owner.patch(f"/projects/{PROJECT}", {"public_page": "off"}).status_code == 200
    shown = mine(zoe)
    assert shown[0] == {"type": "profile", "id": None, "label": "person"}
    assert shown[2] == {"type": "profile", "id": None, "label": "agent"}
    assert shown[3] == {"type": "project", "id": None, "label": "project"}
    assert agent["id"] not in str(shown) and world.anna.id not in str(shown)
