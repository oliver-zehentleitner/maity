"""docs/api.md §16.9, "A person's agents" (card tsk-b9kp7tfsf0yn): `GET /{handle}/agents`, the
tab of a person's agents, by their own `public_agents`, and the same list on their page, in the
visitors' route and in `GET /people/{handle}` (§6.27)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import public_pages, public_snapshot
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_public_project_views import World, pages

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
    answer: dict[str, Any] = got.json()
    return answer


def main(world: World, path: str) -> str:
    got = world.anyone.get(f"/{path}")
    assert got.status_code == 200
    assert "<title>dashboard</title>" not in got.text, f"/{path} answered the app shell"
    return str(got.text).split("<main")[1]


def bot_handle(world: World) -> str:
    handle: str = world.bot.get("/me").json()["member"]["handle"]
    return handle


def private_agent(world: World, make_client: ClientFactory) -> tuple[flow.Agent, str]:
    """An agent of the owner that is a member of a private project only: it has no page."""
    flow.project(world.owner, "secret")
    agent = flow.agent(
        pages(make_client),
        world.owner,
        "secret",
        role="reviewer",
        agent={"handle": "hidden-bot", "display_name": "Hidden Bot"},
    )
    return agent, "hidden-bot"


def entry(handle: str, name: str, page: str | None, roles: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "handle": handle,
        "picture": None,
        "page": page,
        "roles": roles,
        "model": None,
        "harness": None,
    }


def test_the_tab_lists_the_agents_that_have_a_page_by_default(
    world: World, make_client: ClientFactory
) -> None:
    private_agent(world, make_client)
    bot = bot_handle(world)
    answer = data(world, "maintainer/agents")
    assert answer["kind"] == "person_agents"
    assert answer["data"]["owner"] == {
        "name": answer["data"]["owner"]["name"],
        "handle": "maintainer",
        "page": "/maintainer",
    }
    shown = [entry(bot, "An agent", f"/maintainer/agents/{bot}", ["coder"])]
    assert answer["data"]["agents"] == shown
    page = main(world, "maintainer/agents")
    assert f'href="/maintainer/agents/{bot}"' in page and '<span class="tag">coder</span>' in page
    assert "hidden-bot" not in page and "Hidden Bot" not in page
    # Both pages carry the two tabs, the current one marked.
    assert '<a href="/maintainer">Profile</a>' in page
    assert '<a href="/maintainer/agents" aria-current="page">Agents</a>' in page
    profile = main(world, "maintainer")
    assert '<a href="/maintainer" aria-current="page">Profile</a>' in profile
    assert '<a href="/maintainer/agents">All agents</a>' in profile
    # The person's page and the dashboard read the same list.
    assert data(world, "maintainer")["data"]["agents"] == shown
    people = world.owner.get("/people/maintainer").json()["agents"]
    assert people == [
        {
            "handle": bot,
            "display_name": "An agent",
            "avatar_url": None,
            "page": f"/maintainer/agents/{bot}",
            "roles": ["coder"],
            "model": None,
            "harness": None,
        }
    ]
    assert world.anna.get("/people/maintainer").json()["agents"] == people


def test_all_lists_an_agent_without_a_page_with_nothing_of_its_private_project(
    world: World, make_client: ClientFactory
) -> None:
    _, hidden = private_agent(world, make_client)
    switched = world.owner.patch("/me", {"public_agents": "all"})
    assert switched.status_code == 200, switched.text
    assert switched.json()["member"]["public_agents"] == "all"
    listed = data(world, "maintainer/agents")["data"]["agents"]
    assert [a["handle"] for a in listed] == sorted([bot_handle(world), hidden])  # by handle
    assert entry(hidden, "Hidden Bot", None, []) in listed
    page = main(world, "maintainer/agents")
    assert "Hidden Bot" in page and f"/maintainer/agents/{hidden}" not in page
    assert "secret" not in page.lower() and "reviewer" not in page  # nothing of where it works
    # Back to `public_projects`: off at once.
    assert world.owner.patch("/me", {"public_agents": "public_projects"}).status_code == 200
    assert hidden not in [a["handle"] for a in data(world, "maintainer/agents")["data"]["agents"]]


@pytest.mark.parametrize(
    ("value", "reason"), [(None, "required"), ("everyone", "unknown"), (True, "string_type")]
)
def test_any_other_value_is_invalid(world: World, value: Any, reason: str) -> None:
    refused = world.owner.patch("/me", {"public_agents": value})
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {"public_agents": reason}
    assert world.owner.get("/me").json()["member"]["public_agents"] == "public_projects"


def test_an_agent_may_not_set_it(world: World) -> None:
    refused = world.bot.patch("/me", {"public_agents": "all"})
    assert refused.status_code == 403, refused.text


def test_a_person_without_an_agent_gets_the_page_with_a_sentence(world: World) -> None:
    answer = data(world, "anna/agents")
    assert answer["data"]["agents"] == []
    assert "No agents are listed here." in main(world, "anna/agents")


def test_with_the_profile_off_the_tab_stays_out_of_search(world: World) -> None:
    assert (
        "<loc>https://hub.example/maintainer/agents</loc>" in world.anyone.get("/sitemap.xml").text
    )
    assert world.owner.patch("/me", {"public_profile": False}).status_code == 200
    got = world.anyone.get("/maintainer/agents")
    assert got.headers["x-robots-tag"] == "noindex"
    assert '<meta name="robots" content="noindex">' in got.text
    assert bot_handle(world) in got.text  # still served, whatever `public_profile`
    assert "/maintainer/agents</loc>" not in world.anyone.get("/sitemap.xml").text


def test_the_address_with_a_slash_at_the_end_is_a_308(world: World) -> None:
    got = world.anyone.get("/maintainer/agents/", follow_redirects=False)
    assert got.status_code == 308 and got.headers["location"] == "/maintainer/agents"


def test_under_all_a_private_membership_changes_the_tab_at_once(
    world: World, make_client: ClientFactory
) -> None:
    assert world.owner.patch("/me", {"public_agents": "all"}).status_code == 200
    _, hidden = private_agent(world, make_client)  # a join in a private project
    assert hidden in [a["handle"] for a in data(world, "maintainer/agents")["data"]["agents"]]
    with world.migrated.connect() as conn:
        agent_id = conn.execute(
            select(t.agent_profile.c.id).where(t.agent_profile.c.handle == hidden)
        ).scalar_one()
    renamed = world.owner.patch(f"/agents/{agent_id}", {"display_name": "Quiet Bot"})
    assert renamed.status_code == 200, renamed.text
    assert "Quiet Bot" in main(world, "maintainer/agents")
    removed = world.owner.delete(f"/agents/{agent_id}?cascade=true")
    assert removed.status_code == 200, removed.text
    assert hidden not in [a["handle"] for a in data(world, "maintainer/agents")["data"]["agents"]]


def test_the_snapshot_brings_an_agent_s_model_and_harness_to_the_tab(
    world: World, hub: Any
) -> None:
    assert world.bot.resume(model="model-one", harness="claude-code").status_code == 200
    public_snapshot.Worker(world.migrated, hub).run_once()
    (listed,) = data(world, "maintainer/agents")["data"]["agents"]
    assert (listed["model"], listed["harness"]) == ("model-one", "claude-code")
    page = main(world, "maintainer/agents")
    assert "Model: model-one" in page and "Harness: claude-code" in page
    assert "Model:" not in main(world, "maintainer")  # the profile lists names only


def test_under_all_an_agent_held_by_moderation_is_not_listed(
    world: World, make_client: ClientFactory
) -> None:
    assert world.owner.patch("/me", {"public_agents": "all"}).status_code == 200
    _, hidden = private_agent(world, make_client)
    with world.migrated.connect() as conn:
        agent_id = conn.execute(
            select(t.agent_profile.c.id).where(t.agent_profile.c.handle == hidden)
        ).scalar_one()
    # The agent shares no project with anyone but its owner: the instance admin reports it.
    target = {"target": {"type": "profile", "id": agent_id}, "reason": "spam"}
    made = world.owner.post("/reports", target)
    assert made.status_code == 201, made.text
    path = f"/admin/reports/{made.json()['id']}/resolve"
    assert world.owner.post(path, {"action": "hide"}).status_code == 200
    with world.migrated.begin() as conn:  # what the owner's next render reads
        public_pages.touch(conn, "person", world.owner.id)
    assert hidden not in [a["handle"] for a in data(world, "maintainer/agents")["data"]["agents"]]
    assert world.owner.post(path, {"action": "dismiss"}).status_code == 200
    with world.migrated.begin() as conn:
        public_pages.touch(conn, "person", world.owner.id)
    assert hidden in [a["handle"] for a in data(world, "maintainer/agents")["data"]["agents"]]


def test_the_snapshot_renders_the_tab_of_an_owner_who_is_no_member(world: World, hub: Any) -> None:
    olga = factory.human(world.migrated, "olga")  # owns an agent in the project, no member
    bot = factory.agent(world.migrated, world.project_id, olga, role="coder")
    with world.migrated.begin() as conn:
        public_pages.touch(conn, "person", olga)
    (listed,) = data(world, "olga/agents")["data"]["agents"]
    assert listed["model"] == "claude-opus-5-5"
    with world.migrated.begin() as conn:
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.id == bot.session_id)
            .values(model="model-two")
        )
    public_snapshot.Worker(world.migrated, hub).run_once()
    (listed,) = data(world, "olga/agents")["data"]["agents"]
    assert listed["model"] == "model-two"
