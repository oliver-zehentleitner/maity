"""docs/api.md §16.9, "An agent's page" and "A person's page": `GET /{owner}/agents/{handle}`
while the owner's profile is public and the agent is a member of a public project, and the
projects and agents on the person's page."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import Engine, select

from maity_hub import clock, public_pages, swarm
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_public_projects_team import World, shown
from tests.test_public_projects_team import world as world  # noqa: F401  (the fixture)


def handle_of(world: World) -> str:
    return str(world.bot.get("/me").json()["member"]["handle"])


def agent_page(world: World, handle: str | None = None, owner: str = "maintainer") -> str | None:
    got = world.anyone.get(f"/{owner}/agents/{handle or handle_of(world)}")
    assert got.status_code == 200
    return None if "<title>dashboard</title>" in got.text else str(got.text)


def person_page(world: World, handle: str = "maintainer") -> str:
    got = world.anyone.get(f"/{handle}")
    assert got.status_code == 200
    return str(got.text)


def stat(text: str, label: str) -> str:
    found = re.search(rf"<li>{re.escape(label)}: ([^<]*)</li>", text)
    assert found is not None, label
    return found.group(1)


def test_an_agent_has_a_page_while_its_owner_s_profile_is_public(world: World) -> None:
    assert agent_page(world) is None
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    text = agent_page(world)
    assert text is not None
    me = world.bot.get("/me").json()["member"]
    assert f"<h1>{me['display_name']}</h1>" in text
    assert '<a href="/maintainer">Human maintainer</a>' in text
    assert '<a href="/maintainer/maity">Maity</a>' in text
    assert '<link rel="canonical" href="https://hub.example/maintainer/agents/' in text
    for word in ("online", "briefing", "instance", "harness", "model"):
        assert word not in text.split("<main")[1]
    world.owner.patch("/me", {"public_profile": False})
    assert agent_page(world) is None


def test_the_page_goes_with_the_last_public_project_and_comes_back(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    assert agent_page(world) is not None
    assert (
        world.owner.patch("/projects/maintainer/maity", {"public_page": "off"}).status_code == 200
    )
    assert agent_page(world) is None
    assert world.owner.patch("/projects/maintainer/maity", {"public_page": "on"}).status_code == 200
    assert agent_page(world) is not None


def test_a_new_name_is_on_the_page_at_once(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    agent = world.bot.get("/me").json()["member"]
    renamed = world.owner.patch(f"/agents/{agent['id']}", {"display_name": "Renamed Agent"})
    assert renamed.status_code == 200, renamed.text
    text = agent_page(world) or ""
    assert "<h1>Renamed Agent</h1>" in text and f"<h1>{agent['display_name']}</h1>" not in text
    moved = world.owner.patch("/projects/maintainer/maity", {"name": "Maity Two"})
    assert moved.status_code == 200, moved.text
    assert ">Maity Two</a>" in (agent_page(world) or "")


def test_an_isolated_agent_and_an_agent_under_a_hold_have_no_page(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    agent = world.bot.get("/me").json()["member"]
    isolate = f"/projects/maintainer/maity/members/{agent['id']}/isolate"
    assert world.owner.post(isolate, {"reason": "it rewrote the release notes"}).status_code == 200
    assert agent_page(world) is None
    assert world.owner.delete(isolate).status_code == 200
    assert agent_page(world) is not None
    made = world.anna.post(
        "/reports", {"target": {"type": "profile", "id": agent["id"]}, "reason": "spam"}
    )
    assert made.status_code == 201, made.text
    path = f"/admin/reports/{made.json()['id']}/resolve"
    assert world.owner.post(path, {"action": "hide"}).status_code == 200
    assert agent_page(world) is None
    assert world.owner.post(path, {"action": "dismiss"}).status_code == 200
    assert agent_page(world) is not None


def test_a_handle_that_changes_moves_the_page(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    old = handle_of(world)
    agent_id = world.bot.get("/me").json()["member"]["id"]
    renamed = world.owner.patch(f"/agents/{agent_id}", {"handle": "swift-fox"})
    assert renamed.status_code == 200, renamed.text
    assert agent_page(world, old) is None
    assert agent_page(world, "swift-fox") is not None


def test_the_statistics_are_the_agent_s_alone_over_its_public_projects(
    world: World, migrated: Engine
) -> None:
    world.owner.patch("/me", {"public_profile": True})
    agent_id = world.bot.get("/me").json()["member"]["id"]
    with migrated.connect() as conn:
        mine = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent_id)
        ).scalar_one()
        owner_member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == world.owner.id)
        ).scalar_one()
    for _ in range(2):
        factory.card(
            migrated,
            world.project_id,
            mine,
            status="done",
            claim_holder=mine,
            closed_at=clock.now(),
        )
    factory.card(  # a human's card is nowhere on an agent's page
        migrated,
        world.project_id,
        owner_member,
        status="done",
        claim_holder=owner_member,
        closed_at=clock.now(),
    )
    second = world.owner.post("/projects", {"slug": "second", "name": "Second"})
    assert second.status_code == 201, second.text
    assert (
        world.owner.patch("/projects/maintainer/second", {"public_page": "on"}).status_code == 200
    )
    with migrated.connect() as conn:
        second_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "second")
        ).scalar_one()
    in_second = factory.membership(migrated, second_id, "member", agent_id=agent_id)
    factory.card(
        migrated, second_id, in_second, status="done", claim_holder=in_second, closed_at=clock.now()
    )
    swarm.CACHE.clear()
    with migrated.begin() as conn:
        public_pages.touch(conn, "project", second_id)
    text = agent_page(world) or ""
    assert stat(text, "Cards done") == "3"
    assert '<a href="/maintainer/second">Second</a>' in text
    assert stat(text, "Handovers") == "0" and stat(text, "Median, claim to done") == "-"


def test_the_person_page_lists_their_projects_and_the_agents_with_a_page(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    handle = handle_of(world)
    text = person_page(world)
    assert "<h2>Projects</h2>" in text and '<a href="/maintainer/maity">Maity</a>' in text
    assert f'<a href="/maintainer/agents/{handle}">' in text
    # a project whose page goes off leaves the person's page, and so does the agent
    world.owner.patch("/projects/maintainer/maity", {"public_page": "off"})
    text = person_page(world)
    assert "<h2>Projects</h2>" not in text and "<h2>Agents</h2>" not in text


def test_a_member_s_person_page_lists_the_project(world: World) -> None:
    world.anna.patch("/me", {"public_profile": True})
    assert '<a href="/maintainer/maity">Maity</a>' in person_page(world, "anna")
    world.owner.patch("/projects/maintainer/maity", {"name": "Renamed Project"})
    assert ">Renamed Project</a>" in person_page(world, "anna")
    assert shown(world.anyone)  # the project's own page is unaffected


def test_the_agent_page_is_in_the_sitemap(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    sitemap: Any = world.anyone.get("/sitemap.xml").text
    assert f"https://hub.example/maintainer/agents/{handle_of(world)}" in sitemap


def test_a_person_page_follows_an_agent_in_a_project_its_owner_is_no_member_of(
    make_client: ClientFactory, migrated: Engine, world: World
) -> None:
    carol = flow.human(lambda **kw: make_client(public_pages=True, **kw), migrated, "carol")
    assert carol.patch("/me", {"public_profile": True}).status_code == 200
    bot = factory.agent(migrated, world.project_id, carol.id, "coder")
    handle = bot.agent_id
    # the join: the owner's page lists the agent, the agent has its page
    with migrated.begin() as conn:
        public_pages.touch(conn, "project", world.project_id)
    assert f'<a href="/carol/agents/{handle}">' in person_page(world, "carol")
    assert agent_page(world, handle, "carol") is not None
    # a new name is on both at once
    with migrated.begin() as conn:
        conn.execute(
            t.agent_profile.update()
            .where(t.agent_profile.c.id == bot.agent_id)
            .values(display_name="Carol Bot")
        )
        from maity_hub import public_projects

        public_projects.touch_of_agent(conn, bot.agent_id)
    assert ">Carol Bot</a>" in person_page(world, "carol")
    # the isolation takes the link away at once, though carol is no member
    isolate = f"/projects/maintainer/maity/members/{bot.agent_id}/isolate"
    assert world.owner.post(isolate, {"reason": "it rewrote the release notes"}).status_code == 200
    assert f"/carol/agents/{handle}" not in person_page(world, "carol")
    assert agent_page(world, handle, "carol") is None


def _window(as_of: Any, **facts: Any) -> swarm.Window:
    return swarm.Window(as_of=as_of, reviews_since=swarm.utc_day(as_of), **facts)


def test_the_medians_are_pooled_over_the_projects_and_the_counters_summed(
    world: World, migrated: Engine, monkeypatch: Any
) -> None:
    world.owner.patch("/me", {"public_profile": True})
    agent_id = world.bot.get("/me").json()["member"]["id"]
    second = world.owner.post("/projects", {"slug": "second", "name": "Second"})
    assert second.status_code == 201, second.text
    assert (
        world.owner.patch("/projects/maintainer/second", {"public_page": "on"}).status_code == 200
    )
    with migrated.connect() as conn:
        second_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "second")
        ).scalar_one()
        first_member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent_id)
        ).scalar_one()
    second_member = factory.membership(migrated, second_id, "member", agent_id=agent_id)
    now = clock.now()
    day = swarm.utc_day(now)
    windows = {
        world.project_id: _window(
            now,
            claim_to_done=[(first_member, s, day) for s in (100, 200, 300)],
            reviews=[(first_member, day)] * 2,
            prs=[({first_member}, day)],
        ),
        second_id: _window(
            now,
            claim_to_done=[(second_member, s, day) for s in (1000, 2000, 3000)],
            reviews=[(second_member, day)] * 3,
            prs=[({second_member}, day)] * 2,
        ),
    }
    monkeypatch.setattr(swarm.CACHE, "get", lambda conn, project_id: windows[project_id])
    with migrated.begin() as conn:
        public_pages.touch(conn, "project", second_id)
    text = agent_page(world) or ""
    # the six samples pooled have the median 650 s (10 min); the medians of the two projects, 200 s
    # and 2000 s, would average 1100 s (18 min)
    assert stat(text, "Median, claim to done") == "10 min"
    assert stat(text, "Reviews given") == "5" and stat(text, "Pull requests merged") == "3"
