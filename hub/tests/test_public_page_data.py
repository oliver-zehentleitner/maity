"""docs/api.md §16.9, "What visitors read in the dashboard": what a project's and an agent's
`data` add for the pages' design (tsk-h822960mytm9): each member's picture as their own page
shows it, the role and an agent's harness, the Members figure, the online pictures, the
owner's picture and a merge entry's facts as fields; and the Team tab's pictures by the same
rule, and the Organisation tab's (tsk-9482zxza3gs3)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from maity_hub import avatars, public_snapshot
from maity_hub import tables as t
from tests.test_avatar_public import digest
from tests.test_avatars import image, put_agent, put_human
from tests.test_public_project_views import BASE, TASKS, World
from tests.test_public_snapshot import count_renders, item, merge, seen, snapshot
from tests.test_public_snapshot import hub as hub  # noqa: F401  (the fixture)
from tests.test_public_snapshot import world as world  # noqa: F401  (the fixture)

PUBLIC = "/api/v1/avatars/public"


def _fresh() -> None:
    avatars.CHANGES.reset()


def by_handle(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {e["handle"]: e for e in entries}


def agent_data(world: World) -> Any:
    got = world.anyone.get(f"/api/v1/public/pages/maintainer/agents/{bot_handle(world)}")
    assert got.status_code == 200, got.text
    return got.json()["data"]


def bot_handle(world: World) -> str:
    with world.migrated.connect() as conn:
        return str(
            conn.execute(
                select(t.agent_profile.c.handle).where(t.agent_profile.c.id == world.bot.id)
            ).scalar_one()
        )


def public_address(url: str) -> str:
    return f"{PUBLIC}/{digest(url)}"


def test_each_member_carries_role_and_picture_as_their_own_page_shows_it(world: World) -> None:
    _fresh()
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    assert world.anna.patch("/me", {"public_profile": False}).status_code == 200
    url = put_human(world.owner, "/me/avatar", image()).json()["avatar_url"]
    put_human(world.anna, "/me/avatar", image(size=(90, 90)))
    data = snapshot(world)
    people = by_handle(data["people"])
    assert set(people["maintainer"]) == {"name", "handle", "page", "picture", "role"}
    assert people["maintainer"]["picture"].endswith(digest(url))
    assert people["anna"]["picture"] is None  # her profile is off: her page shows none
    team = world.anyone.get(f"/api/v1/public/pages{BASE}/team").json()["data"]["shown"]
    roles = {p["handle"]: p["role"] for p in team}  # as the Team tab shows them
    assert {h: people[h]["role"] for h in ("anna", "maintainer")} == {
        h: roles[h] for h in ("anna", "maintainer")
    }
    (bot,) = data["agents"]
    assert set(bot) == {"name", "handle", "page", "picture", "role", "harness"}
    assert bot["picture"] and bot["role"] == roles[bot["handle"]] and bot["harness"] is None
    # Every address the data names answers anyone: nothing the page does not show.
    for picture in (people["maintainer"]["picture"], bot["picture"]):
        assert world.anyone.get(picture.split("?")[0]).status_code == 200


def test_the_members_figure_counts_the_team_list(world: World) -> None:
    data = snapshot(world)
    assert data["members"] == len(data["people"]) + len(data["agents"]) == 3
    removed = world.owner.delete(f"/projects/maintainer/maity/members/{world.anna.id}")
    assert removed.status_code in (200, 204), removed.text
    assert snapshot(world)["members"] == 2


def test_an_agent_s_new_harness_renders_its_project_pages_and_the_same_one_none(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert world.bot.resume(model="model-one", harness="claude-code").status_code == 200
    (bot,) = snapshot(world)["agents"]  # at once: no snapshot run in between
    assert bot["harness"] == "claude-code"
    assert "model" not in bot  # the model stays on the agent's own page
    rendered = count_renders(monkeypatch)
    assert world.bot.resume(model="model-two", harness="claude-code").status_code == 200
    assert ("project", world.project_id) not in rendered  # agents resume often
    assert world.bot.resume(harness="codex").status_code == 200
    assert ("project", world.project_id) in rendered
    assert snapshot(world)["agents"][0]["harness"] == "codex"


def test_the_online_names_carry_the_picture_their_page_shows(world: World, hub: Any) -> None:
    _fresh()
    from maity_hub import clock

    url = put_human(world.anna, "/me/avatar", image()).json()["avatar_url"]
    assert world.anna.patch("/me", {"public_profile": False}).status_code == 200
    seen(world, world.anna_member, clock.now())
    worker = public_snapshot.Worker(world.migrated, hub)
    worker.run_once()
    (anna,) = [p for p in snapshot(world)["online"]["named"] if p["handle"] == "anna"]
    assert set(anna) == {"name", "handle", "page", "picture"} and anna["picture"] is None
    assert world.anna.patch("/me", {"public_profile": True}).status_code == 200
    worker.run_once()
    (anna,) = [p for p in snapshot(world)["online"]["named"] if p["handle"] == "anna"]
    assert anna["picture"].endswith(digest(url))


def test_an_agent_s_page_names_its_owner_with_the_owner_s_picture(world: World) -> None:
    _fresh()
    assert world.owner.patch("/me", {"public_profile": False}).status_code == 200
    put_human(world.owner, "/me/avatar", image())
    owner = agent_data(world)["owner"]
    assert set(owner) == {"name", "handle", "page", "picture"} and owner["picture"] is None
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    assert agent_data(world)["owner"]["picture"] is not None


def test_a_new_picture_reaches_every_page_that_names_it_at_once(world: World) -> None:
    """The old address answers `not_found` from the change on: no stored `data` may keep it,
    whatever `MAITY_PUBLIC_PAGES_RENDER` says (§16.9, "The picture")."""
    _fresh()
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    first = put_human(world.owner, "/me/avatar", image()).json()["avatar_url"]
    assert by_handle(snapshot(world)["people"])["maintainer"]["picture"].endswith(digest(first))
    second = put_human(world.owner, "/me/avatar", image(size=(90, 90))).json()["avatar_url"]
    assert digest(first) != digest(second)
    assert by_handle(snapshot(world)["people"])["maintainer"]["picture"].endswith(digest(second))
    assert agent_data(world)["owner"]["picture"].endswith(digest(second))
    old_bot = snapshot(world)["agents"][0]["picture"]
    new_bot = put_agent(world.bot, image(size=(80, 80))).json()["avatar_url"]
    (bot,) = snapshot(world)["agents"]
    assert bot["picture"] != old_bot and bot["picture"].endswith(digest(new_bot))


def team_tab(world: World) -> dict[str, dict[str, Any]]:
    got = world.anyone.get(f"/api/v1/public/pages{BASE}/team")
    assert got.status_code == 200, got.text
    return by_handle(got.json()["data"]["shown"])


def test_the_team_tab_names_each_one_with_the_picture_their_page_shows(world: World) -> None:
    """The project page's rule (`public_projects.member_pictures`): a person's picture only while
    their `public_profile` is on, an agent's always (§16.9, `team`)."""
    _fresh()
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    assert world.anna.patch("/me", {"public_profile": False}).status_code == 200
    url = put_human(world.owner, "/me/avatar", image()).json()["avatar_url"]
    put_human(world.anna, "/me/avatar", image(size=(90, 90)))
    team = team_tab(world)
    assert set(team["maintainer"]) == {"name", "handle", "page", "picture", "trust", "role"}
    assert team["maintainer"]["picture"].endswith(digest(url))
    assert team["anna"]["picture"] is None  # her profile is off: her page shows none
    bot = team[bot_handle(world)]
    assert bot["picture"] and bot["picture"] == snapshot(world)["agents"][0]["picture"]
    people = by_handle(snapshot(world)["people"])
    assert {h: team[h]["picture"] for h in people} == {h: people[h]["picture"] for h in people}
    for picture in (team["maintainer"]["picture"], bot["picture"]):
        assert world.anyone.get(picture.split("?")[0]).status_code == 200
    # Turning the profile off takes the picture off the Team tab at once.
    assert world.owner.patch("/me", {"public_profile": False}).status_code == 200
    assert team_tab(world)["maintainer"]["picture"] is None


def test_a_new_picture_renders_the_team_tab_at_once(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Team tab names the picture's public address, which answers `not_found` from a change
    on: the change renders it again at once, as it does the project page (§16.9, "The picture")."""
    _fresh()
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    first = put_human(world.owner, "/me/avatar", image()).json()["avatar_url"]
    assert team_tab(world)["maintainer"]["picture"].endswith(digest(first))
    rendered = count_renders(monkeypatch)
    second = put_human(world.owner, "/me/avatar", image(size=(90, 90))).json()["avatar_url"]
    assert ("project_views", world.project_id) in rendered
    assert team_tab(world)["maintainer"]["picture"].endswith(digest(second))
    rendered.clear()
    new_bot = put_agent(world.bot, image(size=(80, 80))).json()["avatar_url"]
    assert ("project_views", world.project_id) in rendered
    assert team_tab(world)[bot_handle(world)]["picture"].endswith(digest(new_bot))


def organisation_tab(world: World) -> dict[str, dict[str, Any]]:
    got = world.anyone.get(f"/api/v1/public/pages{BASE}/organisation")
    assert got.status_code == 200, got.text
    return by_handle([n["person"] for n in got.json()["data"]["nodes"] if n["person"]])


def test_the_organisation_tab_names_each_one_with_the_team_tabs_picture(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A named node's `person` carries the picture as the Team tab does: a person's only while
    their `public_profile` is on, an agent's always (§16.9, `organisation`); a new one renders
    the tab again at once."""
    _fresh()
    assert world.owner.patch("/me", {"public_profile": True}).status_code == 200
    assert world.anna.patch("/me", {"public_profile": False}).status_code == 200
    put_human(world.owner, "/me/avatar", image())
    put_human(world.anna, "/me/avatar", image(size=(90, 90)))
    org = organisation_tab(world)
    team = team_tab(world)
    assert set(org["maintainer"]) == {"name", "handle", "page", "picture"}
    assert org["maintainer"]["picture"] and org["anna"]["picture"] is None
    assert {h: p["picture"] for h, p in org.items()} == {h: team[h]["picture"] for h in org}
    assert org[bot_handle(world)]["picture"]
    rendered = count_renders(monkeypatch)
    second = put_human(world.owner, "/me/avatar", image(size=(80, 80))).json()["avatar_url"]
    assert ("project_views", world.project_id) in rendered
    assert organisation_tab(world)["maintainer"]["picture"].endswith(digest(second))
    assert world.owner.patch("/me", {"public_profile": False}).status_code == 200
    assert organisation_tab(world)["maintainer"]["picture"] is None


def test_a_merge_entry_carries_its_facts_as_fields(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Public card"}).json()["id"]
    item(
        world,
        {
            **merge("#7 Title by someone — merged into main; touches hub/", card_id),
            "merge": {
                "public": True,
                "pr": 7,
                "title": "Title",
                "author": "someone",
                "merge_sha": "a" * 40,
            },
            "areas": ["hub/", "web/"],
        },
    )
    (entry,) = snapshot(world)["ticker"]
    assert set(entry) == {"type", "text", "url", "at", "merge"}
    assert entry["merge"] == {
        "pr": 7,
        "title": "Title",
        "author": "someone",
        "areas": ["hub/", "web/"],
    }
    raw = world.anyone.get(f"/api/v1/public/pages{BASE}").text
    assert "a" * 40 not in raw  # never the sha


def test_a_merge_without_its_facts_names_none_and_parses_nothing(world: World) -> None:
    card_id = world.owner.post(TASKS, {"title": "Public card"}).json()["id"]
    item(
        world,
        {
            **merge("#8 merged", card_id),
            "merge": {"public": True, "pr": True, "title": 3, "author": None},
            "areas": "hub/",
        },
    )
    (entry,) = snapshot(world)["ticker"]
    assert entry["merge"] == {"pr": None, "title": None, "author": None, "areas": []}


def test_a_project_that_leaves_the_public_set_takes_its_harness_off_the_other_pages(
    world: World,
) -> None:
    """The harness an agent's entry names comes from its latest session in any public project;
    a project leaving that set renders the other pages that copied it, at once (§16.9)."""
    from datetime import timedelta

    from sqlalchemy import insert

    from maity_hub import clock, public_pages
    from tests import factory

    assert world.bot.resume(harness="x-harness").status_code == 200
    second = world.owner.post("/projects", {"slug": "second", "name": "Second"})
    assert second.status_code == 201, second.text
    on = world.owner.patch("/projects/maintainer/second", {"public_page": "on"})
    assert on.status_code == 200, on.text
    with world.migrated.connect() as conn:
        second_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "second")
        ).scalar_one()
    in_second = factory.membership(world.migrated, second_id, "member", agent_id=world.bot.id)
    with world.migrated.begin() as conn:
        s = t.agent_session.c
        latest = conn.execute(
            select(t.agent_session).order_by(s.started_at.desc(), s.id.desc()).limit(1)
        ).one()
        row = dict(latest._mapping)
        row |= {
            "id": "ses-in-second",
            "membership_id": in_second,
            "harness": "y-harness",
            "started_at": latest.started_at + timedelta(seconds=1),
            "live": None,
            "ended_at": clock.now(),
        }
        conn.execute(insert(t.agent_session).values(**row))
        public_pages.touch(conn, "project", world.project_id, dependents=False)
    assert snapshot(world)["agents"][0]["harness"] == "y-harness"  # the latest, from Second
    off = world.owner.patch("/projects/maintainer/second", {"public_page": "off"})
    assert off.status_code == 200, off.text
    assert snapshot(world)["agents"][0]["harness"] == "x-harness"  # at once, no snapshot run
