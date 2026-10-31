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
        totals = public_projects.agent_statistics(conn, world.project_id)
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
