"""docs/api.md §16.9, "A project's page": the project's statistics reduced as §6.22 says: the
last 30 days over the agents only, so that no human's contribution appears."""

from __future__ import annotations

import re
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, public_pages, public_projects, swarm
from maity_hub import tables as t
from tests import factory
from tests.conftest import ClientFactory
from tests.test_public_projects_team import World, shown


@pytest.fixture(autouse=True)
def _fresh() -> None:
    swarm.CACHE.clear()


def done_by(engine: Engine, project_id: str, membership_id: int, at: Any | None = None) -> None:
    at = at or clock.now()
    factory.card(
        engine, project_id, membership_id, status="done", claim_holder=membership_id, closed_at=at
    )


def membership_of(engine: Engine, member_id: str) -> int:
    with engine.connect() as conn:
        return int(
            conn.execute(
                select(t.membership.c.id).where(
                    (t.membership.c.human_id == member_id) | (t.membership.c.agent_id == member_id)
                )
            ).scalar_one()
        )


def stat(text: str, label: str) -> str:
    found = re.search(rf"<li>{re.escape(label)}: ([^<]*)</li>", text)
    assert found is not None, label
    return found.group(1)


def test_the_page_counts_only_what_the_agents_did(
    make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated)
    agent = membership_of(migrated, world.bot.get("/me").json()["member"]["id"])
    human = membership_of(migrated, world.owner.get("/me").json()["member"]["id"])
    done_by(migrated, world.project_id, agent)
    done_by(migrated, world.project_id, agent)
    done_by(migrated, world.project_id, human)  # a human's card is nowhere on the page
    swarm.CACHE.clear()  # the window is kept for an hour (§6.22); the page may say so
    with migrated.begin() as conn:
        public_pages.touch(conn, "project", world.project_id)
    text = shown(world.anyone)
    assert "<h2>The agents, last 30 days</h2>" in text
    assert stat(text, "Cards done") == "2"
    assert stat(text, "Handovers") == "0"
    assert stat(text, "Median, claim to done") == "-"  # fewer than three samples: none


def test_a_card_older_than_30_days_is_not_counted(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from datetime import timedelta

    world = World(make_client, migrated)
    agent = membership_of(migrated, world.bot.get("/me").json()["member"]["id"])
    done_by(migrated, world.project_id, agent, clock.now() - timedelta(days=31))
    swarm.CACHE.clear()  # the window is kept for an hour (§6.22); the page may say so
    with migrated.begin() as conn:
        public_pages.touch(conn, "project", world.project_id)
    assert stat(shown(world.anyone), "Cards done") == "0"


def test_the_statistics_name_no_one_and_never_who_is_online(
    make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated)
    text = shown(world.anyone)
    for word in ("online", "last_seen", "presence"):
        assert word not in text


def test_the_statistics_follow_the_agents_the_project_has(
    make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated)
    with migrated.connect() as conn:
        totals = public_projects.agent_statistics(conn, world.project_id)["totals"]
    assert totals["cards_done"] == 0 and totals["handovers"] == 0
    assert set(totals) >= {"cards_done", "reviews_given", "prs_merged", "handovers"}


def test_an_isolated_agent_s_cards_are_not_counted_until_it_is_lifted(
    make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated)
    member = world.bot.get("/me").json()["member"]["id"]
    agent = membership_of(migrated, member)
    done_by(migrated, world.project_id, agent)
    swarm.CACHE.clear()
    with migrated.begin() as conn:
        public_pages.touch(conn, "project", world.project_id)
    assert stat(shown(world.anyone), "Cards done") == "1"
    path = f"/projects/maintainer/maity/members/{member}/isolate"
    assert world.owner.post(path, {"reason": "it rewrote the release notes"}).status_code == 200
    swarm.CACHE.clear()
    with migrated.begin() as conn:
        public_pages.touch(conn, "project", world.project_id)
    assert stat(shown(world.anyone), "Cards done") == "0"
    assert world.owner.delete(path).status_code == 200
    swarm.CACHE.clear()
    with migrated.begin() as conn:
        public_pages.touch(conn, "project", world.project_id)
    assert stat(shown(world.anyone), "Cards done") == "1"


def _refresh(engine: Engine, project_id: str) -> None:
    swarm.CACHE.clear()
    with engine.begin() as conn:
        public_pages.touch(conn, "project", project_id)


def test_a_human_s_review_and_a_pull_request_only_humans_took_part_in_are_not_counted(
    make_client: ClientFactory, migrated: Engine
) -> None:
    from sqlalchemy import insert

    from maity_hub.ids import new_id

    world = World(make_client, migrated)
    agent = membership_of(migrated, world.bot.get("/me").json()["member"]["id"])
    human = membership_of(migrated, world.owner.get("/me").json()["member"]["id"])

    def review(actor: int) -> None:
        card = factory.card(migrated, world.project_id, human, status="done", claim_holder=human)
        with migrated.begin() as conn:
            conn.execute(
                insert(t.card_history).values(
                    id=new_id("history"), card_id=card, at=clock.now(), actor_membership=actor,
                    field="status", before="review", after="done", redacted=False,
                )
            )  # fmt: skip

    def merged(number: int, holder: int) -> None:
        card = factory.card(migrated, world.project_id, human, claim_holder=holder)
        with migrated.begin() as conn:
            conn.execute(
                insert(t.event).values(
                    project_id=world.project_id, kind="link_observed", at=clock.now(),
                    subject_type="task", subject_id=card, audience=["all"], redacted=False,
                    payload={
                        "new": {"found": True, "title": "x", "state": "merged"},
                        "forge_url": f"https://github.com/acme/maity/pull/{number}",
                        "public": True,
                        "task_id": card,
                    },
                )
            )  # fmt: skip

    review(human)
    review(human)
    review(agent)
    merged(1, human)
    merged(2, human)
    merged(3, agent)
    _refresh(migrated, world.project_id)
    text = shown(world.anyone)
    assert stat(text, "Reviews given") == "1"
    assert stat(text, "Pull requests merged") == "1"


def test_the_page_has_a_row_for_each_named_agent_and_the_series_per_day(
    make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated)
    member_id = world.bot.get("/me").json()["member"]["id"]
    agent = membership_of(migrated, member_id)
    done_by(migrated, world.project_id, agent)
    done_by(migrated, world.project_id, agent)
    _refresh(migrated, world.project_id)
    text = shown(world.anyone)
    assert "<h3>Per agent</h3>" not in text  # the owner's profile is private: no name, no row
    assert text.count("<span title=") == 30
    world.owner.patch("/me", {"public_profile": True})
    handle = world.bot.get("/me").json()["member"]["handle"]
    named = shown(world.anyone)
    assert "<h3>Per agent</h3>" in named and f"({handle})</td><td>2</td>" in named
    assert "Human maintainer" not in named.split("<h3>Per agent</h3>")[1]  # no human row
    with migrated.connect() as conn:
        rows = public_projects.agent_statistics(conn, world.project_id)["members"]
    assert [(r["handle"], r["name"], r["display_name"]) for r in rows] == [
        (handle, rows[0]["display_name"], rows[0]["display_name"])
    ]  # `name` is the display name (§6.22)
    today = clock.now().date().isoformat()
    assert f'title="{today}: 2"' in named


def test_an_online_agent_and_a_held_card_leave_no_trace_on_the_page(
    make_client: ClientFactory, migrated: Engine
) -> None:
    world = World(make_client, migrated)
    world.owner.patch("/me", {"public_profile": True})
    agent = membership_of(migrated, world.bot.get("/me").json()["member"]["id"])
    factory.card(
        migrated, world.project_id, agent, title="Held secret title", status="in_progress",
        claim_holder=agent, claim_since=clock.now(), lease_until=clock.now(),
    )  # fmt: skip
    _refresh(migrated, world.project_id)
    text = shown(world.anyone)
    for word in ("Held secret title", "online", "in_progress", "last_seen", "lease"):
        assert word not in text
