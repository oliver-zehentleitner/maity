"""docs/api.md §16.9, "A person's agents" (cards tsk-b9kp7tfsf0yn, tsk-2t7efzj1p8zt): a person's
agents on their one page, by their own `public_agents`, and the same list in the visitors' route
and in `GET /people/{handle}` (§6.27). `/{handle}/agents` is no page (the maintainer's request
req-xkxaq2c3cjjq): it names nothing, with no redirect."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import avatar_generated, avatars, images, public_pages, public_snapshot
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


def listed(world: World, handle: str) -> list[dict[str, Any]]:
    """The agents the person's page lists, as the visitors' route answers them."""
    agents: list[dict[str, Any]] = data(world, handle)["data"]["agents"]
    return agents


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


def generated(agent_id: str) -> str:
    """The public address of an agent's generated picture (§6.10)."""
    return avatars.public_url(images.etag(avatar_generated.draw(agent_id)))


def bot_id(world: World) -> str:
    member_id: str = world.bot.get("/me").json()["member"]["id"]
    return member_id


def entry(
    handle: str, name: str, page: str | None, roles: list[str], picture: str
) -> dict[str, Any]:
    return {
        "name": name,
        "handle": handle,
        "picture": picture,
        "page": page,
        "roles": roles,
        "model": None,
        "harness": None,
    }


def test_the_page_lists_the_agents_that_have_a_page_by_default(
    world: World, make_client: ClientFactory
) -> None:
    private_agent(world, make_client)
    bot = bot_handle(world)
    picture = generated(bot_id(world))
    shown = [entry(bot, "An agent", f"/maintainer/agents/{bot}", ["coder"], picture)]
    answer = data(world, "maintainer")
    assert answer["kind"] == "person"
    assert answer["data"]["agents"] == shown
    page = main(world, "maintainer")
    assert (
        f'href="/maintainer/agents/{bot}"' in page
        and '<span class="chip role">Coder</span>' in page
    )
    assert f'src="{picture}?s=128"' in page  # each agent's picture, on the one page
    assert "hidden-bot" not in page and "Hidden Bot" not in page
    # One page: no tabs, no link to an agents page.
    assert "aria-current" not in page and 'href="/maintainer/agents"' not in page
    people = world.owner.get("/people/maintainer").json()["agents"]
    assert people == [
        {
            "handle": bot,
            "display_name": "An agent",
            # its owner reads the picture at its id address (§6.10)
            "avatar_url": avatars.url_of(bot_id(world), picture.rsplit("/", 1)[1]),
            "page": f"/maintainer/agents/{bot}",
            "roles": ["coder"],
            "model": None,
            "harness": None,
        }
    ]
    # A member of a shared project reads the same address (§6.10).
    assert world.anna.get("/people/maintainer").json()["agents"] == people


def test_the_old_agents_address_names_nothing(world: World) -> None:
    """`/{handle}/agents` answers the app shell, its visitors' route `not_found`, and neither
    redirects (§16.9, "A person's agents"; §16.11)."""
    assert world.anyone.get(f"{ROUTE}/maintainer/agents").status_code == 404
    got = world.anyone.get("/maintainer/agents", follow_redirects=False)
    assert got.status_code == 200 and "<title>dashboard</title>" in got.text
    assert "location" not in got.headers
    slashed = world.anyone.get("/maintainer/agents/", follow_redirects=False)
    assert slashed.status_code == 200 and "location" not in slashed.headers  # no 308 either
    assert "/maintainer/agents</loc>" not in world.anyone.get("/sitemap.xml").text
    with world.migrated.connect() as conn:
        stored = conn.execute(
            select(t.public_page.c.path).where(t.public_page.c.path == "/maintainer/agents")
        ).all()
    assert stored == []


def test_all_lists_an_agent_without_a_page_with_nothing_of_its_private_project(
    world: World, make_client: ClientFactory
) -> None:
    agent, hidden = private_agent(world, make_client)
    switched = world.owner.patch("/me", {"public_agents": "all"})
    assert switched.status_code == 200, switched.text
    assert switched.json()["member"]["public_agents"] == "all"
    agents = listed(world, "maintainer")
    assert [a["handle"] for a in agents] == sorted([bot_handle(world), hidden])  # by handle
    assert entry(hidden, "Hidden Bot", None, [], generated(agent.id)) in agents
    page = main(world, "maintainer")
    assert "Hidden Bot" in page and f"/maintainer/agents/{hidden}" not in page
    assert "secret" not in page.lower() and "reviewer" not in page  # nothing of where it works
    # Back to `public_projects`: off at once.
    assert world.owner.patch("/me", {"public_agents": "public_projects"}).status_code == 200
    assert hidden not in [a["handle"] for a in listed(world, "maintainer")]


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


def test_a_person_without_an_agent_gets_no_agents_part(world: World) -> None:
    assert listed(world, "anna") == []
    assert "<h2>Agents</h2>" not in main(world, "anna")


def test_with_the_profile_off_the_agents_stay_on_the_page(world: World) -> None:
    assert world.owner.patch("/me", {"public_profile": False}).status_code == 200
    got = world.anyone.get("/maintainer")
    assert got.headers["x-robots-tag"] == "noindex"
    assert bot_handle(world) in got.text  # still listed, whatever `public_profile`
    assert [a["handle"] for a in listed(world, "maintainer")] == [bot_handle(world)]


def test_under_all_a_private_membership_changes_the_page_at_once(
    world: World, make_client: ClientFactory
) -> None:
    assert world.owner.patch("/me", {"public_agents": "all"}).status_code == 200
    _, hidden = private_agent(world, make_client)  # a join in a private project
    assert hidden in [a["handle"] for a in listed(world, "maintainer")]
    with world.migrated.connect() as conn:
        agent_id = conn.execute(
            select(t.agent_profile.c.id).where(t.agent_profile.c.handle == hidden)
        ).scalar_one()
    renamed = world.owner.patch(f"/agents/{agent_id}", {"display_name": "Quiet Bot"})
    assert renamed.status_code == 200, renamed.text
    assert "Quiet Bot" in main(world, "maintainer")
    removed = world.owner.delete(f"/agents/{agent_id}?cascade=true")
    assert removed.status_code == 200, removed.text
    assert hidden not in [a["handle"] for a in listed(world, "maintainer")]


def test_the_snapshot_brings_an_agent_s_model_and_harness_to_the_page(
    world: World, hub: Any
) -> None:
    assert world.bot.resume(model="model-one", harness="claude-code").status_code == 200
    public_snapshot.Worker(world.migrated, hub).run_once()
    (agent,) = listed(world, "maintainer")
    assert (agent["model"], agent["harness"]) == ("model-one", "claude-code")
    # The page draws an agent's card as the dashboard does: the harness on it, the model in
    # `data` only (public_design.agent_cards, visitor.js agentCards).
    page = main(world, "maintainer")
    assert '<span class="h">claude-code</span>' in page and "model-one" not in page


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
    assert hidden not in [a["handle"] for a in listed(world, "maintainer")]
    assert world.owner.post(path, {"action": "dismiss"}).status_code == 200
    with world.migrated.begin() as conn:
        public_pages.touch(conn, "person", world.owner.id)
    assert hidden in [a["handle"] for a in listed(world, "maintainer")]


def test_the_snapshot_renders_the_page_of_an_owner_who_is_no_member(world: World, hub: Any) -> None:
    olga = factory.human(world.migrated, "olga")  # owns an agent in the project, no member
    bot = factory.agent(world.migrated, world.project_id, olga, role="coder")
    with world.migrated.begin() as conn:
        public_pages.touch(conn, "person", olga)
    (agent,) = listed(world, "olga")
    assert agent["model"] == "claude-opus-5-5"
    with world.migrated.begin() as conn:
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.id == bot.session_id)
            .values(model="model-two")
        )
    public_snapshot.Worker(world.migrated, hub).run_once()
    (agent,) = listed(world, "olga")
    assert agent["model"] == "model-two"
