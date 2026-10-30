"""docs/api.md §16.9, "A project's page": the human members whose own profile is public, the
agents whose owner's is, and the number of the other agents; the page follows them."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PATH = "/maintainer/maity"


def pages(make_client: ClientFactory, **overrides: Any) -> ClientFactory:
    return lambda **kw: make_client(public_pages=True, **overrides, **kw)


def shown(client: Any) -> str:
    got = client.get(PATH)
    assert got.status_code == 200
    assert "<title>dashboard</title>" not in got.text, "the address is the app shell"
    return str(got.text)


class World:
    def __init__(self, make_client: ClientFactory, migrated: Engine, **overrides: Any) -> None:
        factory_ = pages(make_client, **overrides)
        self.migrated = migrated
        self.owner = flow.human(factory_, migrated)
        flow.project(self.owner)
        self.anna = flow.human(factory_, migrated, "anna")
        self.ben = flow.human(factory_, migrated, "ben")
        with migrated.connect() as conn:
            self.project_id = conn.execute(select(t.project.c.id)).scalar_one()
        for human in (self.anna, self.ben):
            factory.membership(migrated, self.project_id, "member", human_id=human.id)
        self.bot = flow.agent(factory_, self.owner, role="coder")
        self.anyone = make_client(public_pages=True, **overrides)
        assert (
            self.owner.patch("/projects/maintainer/maity", {"public_page": "on"}).status_code == 200
        )


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine) -> World:
    return World(make_client, migrated)


def test_a_member_with_a_private_profile_is_not_on_the_page(world: World) -> None:
    text = shown(world.anyone)
    assert "Human anna" not in text and "Human ben" not in text and "Human maintainer" not in text
    assert "<h2>People</h2>" not in text


def test_a_member_appears_with_a_link_to_their_page_when_their_profile_is_public(
    world: World,
) -> None:
    assert world.anna.patch("/me", {"public_profile": True}).status_code == 200
    text = shown(world.anyone)
    assert '<li><a href="/anna">Human anna</a></li>' in text
    assert "Human ben" not in text
    # and goes again the moment it turns private
    assert world.anna.patch("/me", {"public_profile": False}).status_code == 200
    assert "Human anna" not in shown(world.anyone)


def test_an_agent_is_shown_only_where_its_owner_s_profile_is_public(world: World) -> None:
    text = shown(world.anyone)
    assert "<h2>Agents</h2>" not in text and "and 1 more agent</p>" in text
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    text = shown(world.anyone)
    agent = world.bot.get("/me").json()["member"]
    assert f"<li>{agent['display_name']} ({agent['handle']})</li>" in text
    assert "more agent" not in text
    assert world.owner.patch("/me", {"public_profile": False}).status_code == 200
    again = shown(world.anyone)
    assert agent["handle"] not in again and "and 1 more agent</p>" in again


def test_the_count_of_the_others_is_plural_for_several(
    make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated)
    flow.agent(pages(make_client), world.owner, "maity", role="reviewer")
    assert "and 2 more agents</p>" in shown(world.anyone)


def test_a_member_who_is_removed_is_off_the_page_at_once(world: World) -> None:
    world.anna.patch("/me", {"public_profile": True})
    assert "Human anna" in shown(world.anyone)
    removed = world.owner.delete(f"/projects/maintainer/maity/members/{world.anna.id}")
    assert removed.status_code in (200, 204), removed.text
    assert "Human anna" not in shown(world.anyone)


def test_an_agent_that_joins_or_whose_profile_is_deleted_changes_the_page_at_once(
    make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated)
    world.owner.patch("/me", {"public_profile": True})
    joined = flow.agent(pages(make_client), world.owner, "maity", role="reviewer")
    handle = joined.get("/me").json()["member"]["handle"]
    assert f"({handle})" in shown(world.anyone)
    agent_id = joined.get("/me").json()["member"]["id"]
    deleted = world.owner.delete(f"/agents/{agent_id}?cascade=true")
    assert deleted.status_code in (200, 204), deleted.text
    assert f"({handle})" not in shown(world.anyone)


def test_under_interval_a_removal_is_at_once_and_a_new_entry_waits(
    make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated, public_pages_render="interval")
    world.anna.patch("/me", {"public_profile": True})
    assert "Human anna" not in shown(world.anyone)  # a new entry waits for the run
    from maity_hub import public_pages
    from maity_hub.config import Settings

    hub = Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite://",
            "MAITY_PUBLIC_URL": "https://hub.example",
            "MAITY_PUBLIC_PAGES": "on",
            "MAITY_PUBLIC_PAGES_RENDER": "interval",
        }
    )
    public_pages.render_all(migrated, hub)
    assert "Human anna" in shown(world.anyone)
    world.anna.patch("/me", {"public_profile": False})
    assert "Human anna" not in shown(world.anyone)  # taken off at once, whatever the mode
