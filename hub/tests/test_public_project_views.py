"""docs/api.md §16.9, "The public views of a project": Board, Members and Organisation, pages
of their own that follow the project's page and what it shows of its people and cards."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, public_pages
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_reports import report

BASE = "/maintainer/maity"
TASKS = "/projects/maintainer/maity/tasks"


def pages(make_client: ClientFactory) -> ClientFactory:
    return lambda **kw: make_client(public_pages=True, **kw)


def view(client: Any, name: str) -> str | None:
    got = client.get(f"{BASE}/{name}")
    assert got.status_code == 200
    return None if "<title>dashboard</title>" in got.text else str(got.text)


class World:
    def __init__(self, make_client: ClientFactory, migrated: Engine) -> None:
        make = pages(make_client)
        self.migrated = migrated
        self.owner = flow.human(make, migrated)
        flow.project(self.owner)
        self.anna = flow.human(make, migrated, "anna")
        with migrated.connect() as conn:
            self.project_id = conn.execute(select(t.project.c.id)).scalar_one()
            self.owner_member = conn.execute(select(t.membership.c.id)).scalars().first()
        self.anna_member = factory.membership(
            migrated, self.project_id, "member", human_id=self.anna.id
        )
        self.bot = flow.agent(make, self.owner, role="coder")
        self.anyone = make_client(public_pages=True)
        assert (
            self.owner.patch("/projects/maintainer/maity", {"public_page": "on"}).status_code == 200
        )

    def card(self, **values: Any) -> str:
        assert self.owner_member is not None
        return factory.card(self.migrated, self.project_id, self.owner_member, **values)

    def touch(self) -> None:
        """What a write of a card does, for rows the test put in directly."""
        with self.migrated.begin() as conn:
            public_pages.touch(conn, "project_views", self.project_id)


@pytest.fixture
def world(make_client: ClientFactory, migrated: Engine, settings: Any) -> World:
    public_pages.configure(replace(settings, public_pages=True))
    return World(make_client, migrated)


def test_the_views_are_served_exactly_while_the_page_is(world: World) -> None:
    for name in ("board", "members", "organisation"):
        text = view(world.anyone, name)
        assert text is not None and "<script" not in text
        assert f'<link rel="canonical" href="https://hub.example{BASE}/{name}">' in text
    assert view(world.anyone, "why") is None and view(world.anyone, "inbox") is None
    world.owner.patch("/projects/maintainer/maity", {"public_page": "off"})
    assert [view(world.anyone, n) for n in ("board", "members", "organisation")] == [None] * 3


def test_the_board_shows_id_title_status_and_label_and_never_a_body(world: World) -> None:
    done = world.card(status="done", title="Shipped", closed_at=clock.now(), label="bug")
    world.card(status="open", title="Next up", body="a secret body", label="idea")
    world.card(status="proposed", title="Maybe")
    world.touch()
    text = view(world.anyone, "board") or ""
    assert "Shipped" in text and "Next up" in text and "Maybe" in text and done in text
    assert "secret body" not in text and "bug" in text
    assert "<a href" not in text.split("<h1>")[1]  # the ids are text, not links
    assert text.index("proposed") < text.index("open") < text.index("done")


def test_done_and_cancelled_cards_stay_for_30_days(world: World) -> None:
    old = clock.now() - timedelta(days=31)
    world.card(status="done", title="Long ago", closed_at=old)
    world.card(status="cancelled", title="Dropped long ago", closed_at=old)
    world.card(status="cancelled", title="Dropped lately", closed_at=clock.now())
    world.touch()
    text = view(world.anyone, "board") or ""
    assert "Long ago" not in text and "Dropped long ago" not in text
    assert "Dropped lately" in text


def test_an_open_column_holds_at_most_200_cards_newest_first(
    world: World, migrated: Engine
) -> None:
    start = clock.now() - timedelta(days=1)
    for n in range(201):
        world.card(title=f"card {n:03}", created_at=start + timedelta(seconds=n))
    world.touch()
    text = view(world.anyone, "board") or ""
    assert "card 200" in text and "card 001" in text
    assert "card 000" not in text and "open (200)" in text


def test_a_card_change_renders_the_board_at_once(world: World) -> None:
    made = world.owner.post(TASKS, {"title": "First title"})
    assert made.status_code == 201, made.text
    card_id = made.json()["id"]
    assert "First title" in (view(world.anyone, "board") or "")
    patched = world.owner.patch(f"{TASKS}/{card_id}", {"title": "Second title"})
    assert patched.status_code == 200, patched.text
    text = view(world.anyone, "board") or ""
    assert "Second title" in text and "First title" not in text
    world.owner.patch(f"{TASKS}/{card_id}", {"status": "cancelled"})
    assert "cancelled (1)" in (view(world.anyone, "board") or "")


def test_a_holder_is_named_only_when_shown_otherwise_a_member_or_an_agent(world: World) -> None:
    with world.migrated.begin() as conn:
        bot_member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id.is_not(None))
        ).scalar_one()
    world.card(title="By anna", claim_holder=world.anna_member)
    world.card(title="By the bot", claim_holder=bot_member)
    world.touch()
    text = view(world.anyone, "board") or ""
    assert "a member" in text and "an agent" in text and "(anna)" not in text
    world.anna.patch("/me", {"public_profile": True})
    assert "Human anna (anna)" in (view(world.anyone, "board") or "")
    world.anna.patch("/me", {"public_profile": False})
    assert "(anna)" not in (view(world.anyone, "board") or "")


def test_members_shows_the_public_ones_with_trust_and_role_and_counts_the_rest(
    world: World,
) -> None:
    text = view(world.anyone, "members") or ""
    assert "Human anna" not in text and "<h2>Others</h2>" in text
    world.anna.patch("/me", {"public_profile": True})
    text = view(world.anyone, "members") or ""
    assert '<a href="/anna">Human anna</a> (anna)' in text
    assert "× coder</li>" in text
    assert "presence" not in text and "<img" not in text


def test_organisation_shows_the_lines_and_hides_the_names_of_the_others(
    world: World, migrated: Engine
) -> None:
    world.anna.patch("/me", {"public_profile": True})
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == world.anna_member)
            .values(reports_to=world.owner_member)
        )
    world.anna.patch("/me", {"public_profile": False})
    world.anna.patch("/me", {"public_profile": True})
    text = view(world.anyone, "organisation") or ""
    assert "Human anna" in text and "<ul><li>" in text
    world.anna.patch("/me", {"public_profile": False})
    text = view(world.anyone, "organisation") or ""
    assert "(anna)" not in text and '<span class="tag">coder</span>' in text


def test_a_card_under_a_hold_is_on_no_board_and_comes_back_when_it_is_dismissed(
    world: World,
) -> None:
    made = world.owner.post(TASKS, {"title": "Spammy title"})
    assert made.status_code == 201, made.text
    got = report(
        world.anna,
        {"type": "card", "id": made.json()["id"], "project": "maintainer/maity"},
        "spam",
    )
    assert got.status_code == 201, got.text
    assert "Spammy title" in (view(world.anyone, "board") or "")

    def resolved(action: str) -> None:
        done = world.owner.post(f"/admin/reports/{got.json()['id']}/resolve", {"action": action})
        assert done.status_code == 200, done.text

    resolved("hide")
    assert "Spammy title" not in (view(world.anyone, "board") or "")
    resolved("dismiss")
    assert "Spammy title" in (view(world.anyone, "board") or "")


def test_a_card_removed_by_moderation_never_shows_its_title_on_the_board(world: World) -> None:
    made = world.owner.post(TASKS, {"title": "Abusive title"})
    got = report(
        world.anna,
        {"type": "card", "id": made.json()["id"], "project": "maintainer/maity"},
        "abuse",
    )
    assert got.status_code == 201, got.text
    done = world.owner.post(f"/admin/reports/{got.json()['id']}/resolve", {"action": "remove"})
    assert done.status_code == 200, done.text
    text = view(world.anyone, "board") or ""
    assert "Abusive title" not in text and "cancelled (0)" in text


def test_the_views_are_in_the_sitemap(world: World) -> None:
    sitemap = world.anyone.get("/sitemap.xml").text
    for name in ("board", "members", "organisation"):
        assert f"https://hub.example{BASE}/{name}" in sitemap


def test_an_isolated_agent_is_on_no_view_and_a_held_agent_has_no_name(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    agent = world.bot.get("/me").json()["member"]
    assert f"({agent['handle']})" in (view(world.anyone, "members") or "")
    made = world.anna.post(
        "/reports", {"target": {"type": "profile", "id": agent["id"]}, "reason": "spam"}
    )
    assert made.status_code == 201, made.text
    path = f"/admin/reports/{made.json()['id']}/resolve"
    assert world.owner.post(path, {"action": "hide"}).status_code == 200
    members = view(world.anyone, "members") or ""
    assert f"({agent['handle']})" not in members and "× coder" in members  # a count, no name
    assert world.owner.post(path, {"action": "dismiss"}).status_code == 200
    boxes = (view(world.anyone, "organisation") or "").count("<li>")
    isolate = f"/projects/maintainer/maity/members/{agent['id']}/isolate"
    assert world.owner.post(isolate, {"reason": "it rewrote the release notes"}).status_code == 200
    members = view(world.anyone, "members") or ""
    assert f"({agent['handle']})" not in members and "1 × coder" in members  # anna alone
    assert (view(world.anyone, "organisation") or "").count("<li>") == boxes - 1  # no box


def test_an_agent_on_members_links_to_its_page_under_its_owner(world: World) -> None:
    world.owner.patch("/me", {"public_profile": True})
    handle = world.bot.get("/me").json()["member"]["handle"]
    members = view(world.anyone, "members") or ""
    assert f'<a href="/maintainer/agents/{handle}">' in members
    page = world.anyone.get(f"/maintainer/agents/{handle}")
    assert page.status_code == 200 and "<title>dashboard</title>" not in page.text


def test_the_holder_of_a_done_card_is_still_an_agent_when_it_was_isolated(world: World) -> None:
    agent = world.bot.get("/me").json()["member"]
    with world.migrated.connect() as conn:
        bot_member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent["id"])
        ).scalar_one()
    world.card(
        title="Shipped by the bot", status="done", closed_at=clock.now(), claim_holder=bot_member
    )
    world.card(
        title="Shipped by anna",
        status="done",
        closed_at=clock.now(),
        claim_holder=world.anna_member,
    )
    isolate = f"/projects/maintainer/maity/members/{agent['id']}/isolate"
    assert world.owner.post(isolate, {"reason": "it rewrote the release notes"}).status_code == 200
    world.touch()
    text = view(world.anyone, "board") or ""
    assert "Shipped by the bot" in text and "an agent" in text and "a member" in text
    assert agent["handle"] not in text


def test_the_limit_of_a_column_counts_the_cards_the_hold_leaves(
    world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity_hub import public_project_views

    monkeypatch.setattr(public_project_views, "BOARD_LIMIT", 3)
    start = clock.now() - timedelta(days=1)
    ids = [world.card(title=f"card {n}", created_at=start + timedelta(seconds=n)) for n in range(5)]
    report_id = world.owner.post(
        "/reports",
        {"target": {"type": "card", "id": ids[4], "project": "maintainer/maity"}, "reason": "spam"},
    )
    assert report_id.status_code == 201, report_id.text
    resolved = world.owner.post(
        f"/admin/reports/{report_id.json()['id']}/resolve", {"action": "hide"}
    )
    assert resolved.status_code == 200, resolved.text
    world.touch()
    text = view(world.anyone, "board") or ""
    # the newest card is held: the three shown are the next three, not two
    assert "card 4" not in text and all(f"card {n}<" in text for n in (3, 2, 1))
    assert "open (3)" in text
