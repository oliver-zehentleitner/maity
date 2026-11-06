"""docs/api.md §16.9, the maintainer's decisions of 2026-11-05: role, member since and online on
a person's and an agent's page, an agent's model and harness, and a person's numbers behind
their own `public_stats`."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, public_pages, public_snapshot, swarm
from maity_hub import tables as t
from maity_hub.ids import new_id
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_public_project_views import World

ROUTE = "/api/v1/public/pages"


@pytest.fixture
def hub(settings: Any) -> Any:
    return replace(settings, public_pages=True)


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, hub: Any) -> World:
    public_pages.configure(hub)
    return World(make_client, migrated)


def data(world: World, path: str) -> dict[str, Any]:
    got = world.anyone.get(f"{ROUTE}/{path}")
    assert got.status_code == 200, got.text
    found: dict[str, Any] = got.json()["data"]
    return found


def html(world: World, path: str) -> str:
    got = world.anyone.get(f"/{path}")
    assert got.status_code == 200
    return str(got.text).split("<main")[1]


def month(migrated: Engine, table: Any, row_id: str) -> str:
    with migrated.connect() as conn:
        created = conn.execute(select(table.c.created_at).where(table.c.id == row_id)).scalar_one()
    return str(created.strftime("%Y-%m"))


def bot_page(world: World) -> str:
    return f"maintainer/agents/{world.bot.get('/me').json()['member']['handle']}"


def seen(world: World, membership_id: int) -> None:
    with world.migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == membership_id)
            .values(last_seen_at=clock.now())
        )


def bot_membership(world: World) -> int:
    agent_id = world.bot.get("/me").json()["member"]["id"]
    with world.migrated.connect() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.agent_id == agent_id, t.membership.c.project_id == world.project_id
            )
        ).scalar_one()
    return found


def test_a_person_page_shows_role_and_member_since_and_no_numbers_until_chosen(
    world: World,
) -> None:
    anna = data(world, "anna")
    # The fixture's "member" is the single role of old: trust member, role coder (§2.3).
    assert anna["projects"] == [{"name": "Maity", "full_name": "maintainer/maity", "role": "coder"}]
    since = month(world.migrated, t.human, world.anna.id)
    assert anna["member_since"] == since and len(since) == 7  # never the day
    assert anna["online"] is False and anna["statistics"] is None
    page = html(world, "anna")
    assert f"Member since {since}" in page and '<span class="tag">coder</span>' in page
    assert "Statistics" not in page and "Online" not in page


def test_with_the_profile_off_none_of_the_four_appear_the_numbers_switch_included(
    world: World,
) -> None:
    switched = world.anna.patch("/me", {"public_profile": False, "public_stats": True})
    assert switched.status_code == 200, switched.text
    assert switched.json()["member"]["public_stats"] is True
    anna = data(world, "anna")
    assert (anna["projects"], anna["member_since"], anna["online"], anna["statistics"]) == (
        [],
        None,
        None,
        None,
    )
    page = html(world, "anna")
    assert "Member since" not in page and "Statistics" not in page


def test_public_stats_shows_the_person_s_three_counts_at_once_never_an_agent_s_others(
    world: World, hub: Any
) -> None:
    for _ in range(2):
        factory.card(
            world.migrated,
            world.project_id,
            world.anna_member,
            status="done",
            claim_holder=world.anna_member,
            closed_at=clock.now(),
        )
    swarm.CACHE.clear()
    public_pages.configure(replace(hub, public_pages_render="interval"))  # at once even so
    assert world.anna.patch("/me", {"public_stats": True}).status_code == 200
    numbers = data(world, "anna")["statistics"]
    assert set(numbers) == {"cards_done", "reviews_given", "prs_merged"}
    assert numbers["cards_done"] == 2
    page = html(world, "anna")
    assert "<li>Cards done: 2</li>" in page
    assert "Handovers" not in page and "Median" not in page
    assert world.anna.patch("/me", {"public_stats": False}).status_code == 200
    assert data(world, "anna")["statistics"] is None
    assert "Cards done" not in html(world, "anna")


def test_online_follows_the_snapshot_and_public_presence_at_once(world: World, hub: Any) -> None:
    worker = public_snapshot.Worker(world.migrated, hub)
    seen(world, world.anna_member)
    assert data(world, "anna")["online"] is False  # not before the snapshot
    worker.run_once()
    assert data(world, "anna")["online"] is True
    assert "<li>Online</li>" in html(world, "anna")
    public_pages.configure(replace(hub, public_pages_render="interval"))
    assert world.anna.patch("/me", {"public_presence": False}).status_code == 200
    assert data(world, "anna")["online"] is None  # the page does not show it
    assert world.anna.patch("/me", {"public_presence": True}).status_code == 200
    assert data(world, "anna")["online"] is True  # their own page follows at once either way


def test_an_agent_page_shows_role_member_since_and_online(world: World, hub: Any) -> None:
    agent = data(world, bot_page(world))
    assert agent["projects"] == [
        {"name": "Maity", "full_name": "maintainer/maity", "role": "coder"}
    ]
    agent_id = world.bot.get("/me").json()["member"]["id"]
    assert agent["member_since"] == month(world.migrated, t.agent_profile, agent_id)
    assert agent["online"] is False
    assert world.bot.resume().status_code == 200  # an agent is online through a session (§5.3)
    seen(world, bot_membership(world))
    public_snapshot.Worker(world.migrated, hub).run_once()
    assert data(world, bot_page(world))["online"] is True
    page = html(world, bot_page(world))
    assert "<li>Online</li>" in page and "Member since" in page
    assert '<span class="tag">coder</span>' in page


def test_model_and_harness_come_from_the_latest_session_in_a_public_project(
    world: World, hub: Any, make_client: ClientFactory
) -> None:
    before = data(world, bot_page(world))
    assert (before["model"], before["harness"]) == (None, None)  # no session yet
    page = html(world, bot_page(world))
    assert "Model:" not in page and "Harness:" not in page
    resumed = world.bot.resume(model="model-one", harness="claude-code", harness_version="9.9")
    assert resumed.status_code == 200, resumed.text
    after = data(world, bot_page(world))  # at once, with the session's start
    assert (after["model"], after["harness"]) == ("model-one", "claude-code")
    page = html(world, bot_page(world))
    assert "<li>Model: model-one</li>" in page and "<li>Harness: claude-code</li>" in page
    assert "9.9" not in page and "test" not in page.split("<li>Model")[0][-200:]
    # A later session in a project without a page never counts.
    private = world.owner.post("/projects", {"slug": "private", "name": "Private"})
    assert private.status_code == 201, private.text
    off = world.owner.patch("/projects/maintainer/private", {"public_page": "off"})
    assert off.status_code == 200, off.text
    agent_id = world.bot.get("/me").json()["member"]["id"]
    with world.migrated.connect() as conn:
        private_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "private")
        ).scalar_one()
    elsewhere = factory.membership(world.migrated, private_id, "member", agent_id=agent_id)
    with world.migrated.begin() as conn:
        conn.execute(
            insert(t.agent_session).values(
                id=new_id("session"),
                credential_id=world.bot.credential_id,
                membership_id=elsewhere,
                harness="secret-harness",
                model="secret-model",
                started_at=clock.now(),
                last_seen_at=clock.now(),
                acknowledged_seq=0,
            )
        )
    public_snapshot.Worker(world.migrated, hub).run_once()
    later = data(world, bot_page(world))
    assert (later["model"], later["harness"]) == ("model-one", "claude-code")
    assert "secret" not in html(world, bot_page(world))


def test_a_session_that_names_no_model_leaves_it_out(
    world: World, make_client: ClientFactory
) -> None:
    membership_id = bot_membership(world)
    agent_id = world.bot.get("/me").json()["member"]["id"]
    with world.migrated.begin() as conn:
        conn.execute(
            insert(t.agent_session).values(
                id=new_id("session"),
                credential_id=world.bot.credential_id,
                membership_id=membership_id,
                harness="codex",
                model=None,
                started_at=clock.now(),
                last_seen_at=clock.now(),
                acknowledged_seq=0,
            )
        )
        public_pages.touch(conn, "agent", agent_id)
    agent = data(world, bot_page(world))
    assert (agent["model"], agent["harness"]) == (None, "codex")
    page = html(world, bot_page(world))
    assert "Model:" not in page and "<li>Harness: codex</li>" in page


def test_a_new_account_starts_with_public_stats_off(
    make_client: ClientFactory, migrated: Engine
) -> None:
    who = flow.human(make_client, migrated)
    assert who.get("/me").json()["member"]["public_stats"] is False


def test_an_agent_present_only_through_its_bridge_is_not_online_on_its_page(
    world: World, hub: Any, make_client: ClientFactory
) -> None:
    """§16.9 counts the agent's own instances; the bridges' presence (§2.3) is not its own."""
    from tests.test_bridge_reads import _get

    served = factory.agent(
        world.migrated, world.project_id, world.owner.id, "coder", with_session=False
    )
    bridge = factory.agent(world.migrated, world.project_id, world.owner.id, "coder")
    made = world.owner.post(
        f"/projects/maintainer/maity/members/{served.agent_id}/bridges",
        {"bridge": bridge.agent_id, "purpose": "git for the designer"},
    )
    assert made.status_code == 201, made.text
    assert _get(make_client(), bridge, "/me").status_code == 200  # the bridge is seen now
    view = world.owner.get(f"/projects/maintainer/maity/members/{served.agent_id}").json()
    assert view["presence"] == "online"  # the member view keeps the carried presence
    public_snapshot.Worker(world.migrated, hub).run_once()
    with world.migrated.connect() as conn:
        handles = dict(
            conn.execute(
                select(t.agent_profile.c.id, t.agent_profile.c.handle).where(
                    t.agent_profile.c.id.in_([served.agent_id, bridge.agent_id])
                )
            ).all()
        )
    assert data(world, f"maintainer/agents/{handles[served.agent_id]}")["online"] is False
    assert "<li>Online</li>" not in html(world, f"maintainer/agents/{handles[served.agent_id]}")
    assert data(world, f"maintainer/agents/{handles[bridge.agent_id]}")["online"] is True
