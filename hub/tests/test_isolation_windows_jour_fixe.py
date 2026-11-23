"""docs/api.md §6.2, "Isolation", and §20.9: a lift with `hide_isolation_events` keeps what
a jour fixe round did in the hidden window out of what the agent reads on the jour fixe
routes, as on every other listing; its owner and the humans read the round as before
(tsk-z0rwa30vgns5)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, idempotency, listening
from maity_hub import tables as t
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


def test_a_statement_made_in_the_window_is_left_out_of_an_earlier_round(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime]
) -> None:
    """The round opened before the isolation and stays readable; only its statement, which
    came in the window, drops out for the hiding reader, on all three routes. The human admin
    and an agent isolated over the same window but lifted plainly still read it."""
    watcher = flow.agent(make_client, owner, role="admin")
    plain = flow.agent(make_client, owner, role="admin")
    watcher.resume()
    plain.resume()
    held = Round(owner, make_client, migrated, now)
    isolate(owner, watcher.id)
    isolate(owner, plain.id)
    assert held.statement().status_code == 201  # inside the window
    assert lift(owner, watcher, hide=True).status_code == 200
    assert lift(owner, plain).status_code == 200
    mine = _reads(watcher, held.id)
    for who in (owner, plain):
        theirs = _reads(who, held.id)
        for route in ("listed", "got", "overview"):
            assert theirs[route]["statement"] is not None, (who, route)
    for route in ("listed", "got", "overview"):
        assert mine[route] is not None and mine[route]["id"] == held.id, route
        assert mine[route]["statement"] is None, route


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


# --- a replay's read gate (§1.5) holds the round to the same windows ----------------------------


def _held_round(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, now: list[datetime], hide: bool
) -> tuple[Any, Round, dict[str, str]]:
    """`watcher` isolated while a round opens, gets a statement, a post and a report, then
    lifted (`hide` or not). The ids each round-shaped replay type names for that round."""
    watcher = flow.agent(make_client, owner, role="admin")
    watcher.resume()
    isolate(owner, watcher.id)
    held = Round(owner, make_client, migrated, now)
    assert held.statement().status_code == 201
    posted = held.post(held.lead, "response")
    assert posted.status_code == 201, posted.text
    held.tick()
    assert report(held).status_code == 200
    assert lift(owner, watcher, hide=hide).status_code == 200
    with migrated.connect() as conn:
        answer_id = conn.execute(
            select(t.jour_fixe_answer.c.id).where(
                t.jour_fixe_answer.c.round_id == held.id, t.jour_fixe_answer.c.anonymous.is_(False)
            )
        ).scalar_one()
    refs = {
        "jour_fixe_round": held.id,
        "jour_fixe_report": held.id,
        "jour_fixe_answer": answer_id,
        "jour_fixe_post": f"{held.id}/{posted.json()['id']}",
    }
    return watcher, held, refs


def _agent_caller(migrated: Engine, owner: flow.Human, agent: Any) -> Any:
    from maity_hub.auth.caller import Caller

    with migrated.connect() as conn:
        row = conn.execute(
            select(t.membership.c.id, t.membership.c.project_id).where(
                t.membership.c.agent_id == agent.id
            )
        ).one()
    return Caller(
        kind="agent",
        via="bearer",
        agent_id=agent.id,
        owner_id=owner.id,
        membership_id=row.id,
        project_id=row.project_id,
    )


def test_every_round_shaped_replay_type_has_a_window_case(make_client: ClientFactory) -> None:
    make_client()
    rounds = {"jour_fixe_round", "jour_fixe_report", "jour_fixe_answer", "jour_fixe_post"}
    assert {n for n in idempotency.LOADERS if n.startswith("jour_fixe_")} - rounds == {
        "jour_fixe_series",
        "jour_fixe_grant",
    }


@pytest.mark.parametrize("hide", [True, False])
def test_a_replay_of_a_round_in_the_hidden_window_is_not_found_to_the_agent(
    hide: bool,
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    now: list[datetime],
) -> None:
    """The replay gates of the round, its report, an answer and a post pass the same read as
    `GET …/rounds/{id}`: a round that opened in a hidden window is `not_found` to the agent,
    while the human admin still passes. After a plain lift the agent passes as well."""
    from maity_hub.auth.caller import Caller

    watcher, held, refs = _held_round(owner, make_client, migrated, now, hide)
    agent = _agent_caller(migrated, owner, watcher)
    admin = Caller(kind="human", via="cookie", human_id=owner.id)
    assert watcher.get(rounds_path(held.id)).status_code == (404 if hide else 200)
    with migrated.connect() as conn:
        seen = {
            kind: (
                idempotency.LOADERS[kind].may_see(conn, ref, admin),
                idempotency.LOADERS[kind].may_see(conn, ref, agent),
            )
            for kind, ref in refs.items()
        }
    assert seen == {kind: (True, not hide) for kind in refs}
