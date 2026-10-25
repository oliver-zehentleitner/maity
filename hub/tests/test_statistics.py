"""docs/api.md §16.6: the instance statistics, derived from what the hub holds."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, event, update

from maity_hub import clock, statistics
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import _report, task

PATH = "/admin/statistics"


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    statistics.CACHE.clear()
    yield
    statistics.CACHE.clear()


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)  # the first human: the instance admin
    flow.project(human)
    return human


def at_days_ago(base: Any, days: int) -> None:
    then = base - timedelta(days=days)
    clock.set_source(lambda: then)


def row(answer: dict[str, Any], days_ago: int) -> dict[str, Any]:
    found: dict[str, Any] = answer["days"][days_ago]
    return found


def test_a_week_of_use_in_counts(make_client: ClientFactory, migrated: Engine) -> None:
    """Time only moves forward: an event's `at` never runs backwards in a project (§18.2),
    so the week starts three days ago and the clock moves on from there."""
    base = clock.now()
    at_days_ago(base, 3)
    owner = flow.human(make_client, migrated)  # the first human: the instance admin
    flow.project(owner)
    agent = flow.agent(make_client, owner)  # its first join, three days ago
    reviewed = task(owner)
    assert agent.post(f"/projects/maity/tasks/{reviewed['id']}/claim", {}).status_code == 200
    assert (
        agent.post(f"/projects/maity/tasks/{reviewed['id']}/report", _report()).status_code == 200
    )
    at_days_ago(base, 1)
    done = owner.patch(f"/projects/maity/tasks/{reviewed['id']}", {"status": "done"})
    assert done.json()["status"] == "done"
    clock.reset()
    task(owner)
    with migrated.begin() as conn:  # an account made by registration, today
        conn.execute(update(t.human).values(registered_at=clock.now()))

    answer = owner.get(f"{PATH}?days=7").json()
    assert answer["window_days"] == 7 and len(answer["days"]) == 7
    assert answer["days"][0]["date"] == clock.now().date().isoformat()  # newest first
    three = row(answer, 3)
    assert (three["cards_created"], three["cards_claimed"], three["first_joins"]) == (1, 1, 1)
    assert three["agents_active"] == 1  # it claimed and reported
    assert (row(answer, 1)["cards_done"], row(answer, 1)["reviews"]) == (1, 1)
    assert row(answer, 1)["humans_active"] == 1
    assert (row(answer, 0)["cards_created"], row(answer, 0)["registrations"]) == (1, 1)
    assert row(answer, 2) == {"date": row(answer, 2)["date"], **dict.fromkeys(statistics.SERIES, 0)}
    assert answer["totals"] == {
        "humans": 1,
        "humans_pending": 0,
        "agents": 1,
        "projects": 1,
        "instances_online": answer["totals"]["instances_online"],
        "humans_with_an_agent": 1,
    }
    assert answer["returning"] == {"after_7_days": 0, "after_30_days": 0}  # all new


def test_the_query_count_does_not_grow_with_the_window(owner: flow.Human, migrated: Engine) -> None:
    """One query per series, never one per day: counted on this connection only, so
    the app's own background work on the engine does not count."""
    task(owner)
    counted: list[str] = []
    with migrated.connect() as conn:
        event.listen(
            conn,
            "before_cursor_execute",
            lambda c, cur, stmt, *a: None if stmt.startswith("BEGIN") else counted.append(stmt),
        )
        statistics.compute(conn, 7)
        seven = len(counted)
        counted.clear()
        statistics.compute(conn, 90)
        ninety = len(counted)
    assert seven == ninety and seven < 20


def test_it_is_computed_once_an_hour(owner: flow.Human) -> None:
    first = owner.get(PATH).json()
    task(owner)
    again = owner.get(PATH).json()
    assert again == first  # the kept answer
    later = clock.now() + timedelta(hours=1, seconds=1)
    clock.set_source(lambda: later)
    fresh = owner.get(PATH).json()
    assert fresh["as_of"] != first["as_of"]
    assert fresh["days"][0]["cards_created"] >= 1


def test_only_the_instance_admin_reads_it_and_the_window_is_bounded(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = flow.human(make_client, migrated, "someone")
    assert other.get(PATH).status_code == 403
    for days in (0, 91):
        assert owner.get(f"{PATH}?days={days}").status_code == 400
    assert owner.get(f"{PATH}?days=90").json()["window_days"] == 90
