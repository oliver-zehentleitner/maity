"""docs/api.md §6.2, "Isolation", and §20.9: a lift with `hide_isolation_events` keeps what
a jour fixe round did in the hidden window out of what the agent reads on the jour fixe
routes, as on every other listing; its owner and the humans read the round as before
(tsk-z0rwa30vgns5)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import clock, listening
from tests import flow
from tests.conftest import ClientFactory
from tests.test_isolation import isolate
from tests.test_isolation_windows import lift
from tests.test_jour_fixe_exchange import Round, rounds_path
from tests.test_jour_fixe_triage import report

BASE = "/projects/maintainer/maity/jour-fixe"


@pytest.fixture(autouse=True)
def _no_listeners() -> Iterator[None]:
    yield
    listening.reset()


@pytest.fixture
def now() -> list[datetime]:
    moment = [datetime.now(UTC).replace(microsecond=0)]
    clock.set_source(lambda: moment[0])
    return moment


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine, now: list[datetime]) -> flow.Human:
    """Made on the test's clock: an event's `at` never runs back behind the one before it, so
    events made on the real clock first would put the window after the round's times."""
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _reads(who: Any, round_id: str) -> dict[str, Any]:
    """The round on each jour fixe route that serves it: the list, the round, the overview."""
    listed = {r["id"]: r for r in who.get(f"{BASE}/rounds").json()["items"]}
    got = who.get(rounds_path(round_id))
    [series] = who.get(BASE).json()["series"]
    overview = [series["current_round"], series["last_round"]]
    return {
        "listed": listed.get(round_id),
        "got": got.json() if got.status_code == 200 else got.status_code,
        "overview": next((r for r in overview if r and r["id"] == round_id), None),
    }


def test_a_round_held_in_the_hidden_window_is_gone_for_the_agent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    watcher = flow.agent(make_client, owner, role="admin")  # admin trust reads everything else
    watcher.resume()
    isolate(owner, watcher.id)
    held = Round(owner, make_client, migrated, now)
    assert held.statement().status_code == 201
    held.tick()
    assert report(held).status_code == 200
    assert lift(owner, watcher, hide=True).status_code == 200
    mine, ours = _reads(watcher, held.id), _reads(owner, held.id)
    assert mine == {"listed": None, "got": 404, "overview": None}
    assert ours["listed"]["statement"] and ours["got"]["report"]
    assert ours["overview"]["id"] == held.id
    assert watcher.get(rounds_path(held.id, "/answers?mine=true")).status_code == 404


def test_the_parts_of_an_earlier_round_made_in_the_window_are_left_out(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    watcher = flow.agent(make_client, owner, role="admin")
    watcher.resume()
    held = Round(owner, make_client, migrated, now)
    assert held.statement().status_code == 201  # before the isolation: it stays readable
    isolate(owner, watcher.id)
    assert held.post(held.lead, "response").status_code == 201
    held.tick()
    assert report(held).status_code == 200
    assert lift(owner, watcher, hide=True).status_code == 200
    mine, ours = _reads(watcher, held.id), _reads(owner, held.id)
    for route in ("listed", "got", "overview"):
        assert mine[route]["statement"] == ours[route]["statement"] is not None, route
        assert mine[route]["posts"] == [] and len(ours[route]["posts"]) == 1, route
        assert mine[route]["report"] is None and ours[route]["report"] is not None, route
        assert mine[route]["status"] == "reported", route  # the state it finds


def test_a_plain_lift_leaves_the_round_readable(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    watcher = flow.agent(make_client, owner, role="admin")
    watcher.resume()
    isolate(owner, watcher.id)
    held = Round(owner, make_client, migrated, now)
    assert held.statement().status_code == 201
    assert lift(owner, watcher).status_code == 200
    assert _reads(watcher, held.id)["got"]["statement"] is not None
