"""docs/api.md §6.24, §15.5: a new profile's placement holds its handle under the handle's
lock, against a join, another project's placement and a rename of the same owner (on
PostgreSQL and MariaDB; skipped on SQLite, which serialises the writers)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from sqlalchemy import select

from maity_hub import handles, limits
from maity_hub import tables as t
from maity_hub.routes import placements as placement_routes
from tests import flow
from tests.concurrency import FINISH_WITHIN, finished, meet, race, waiting
from tests.test_account_deletion import paused
from tests.test_join_pickup import NEW_AGENT, pick_up, setup  # noqa: F401  (the fixture)
from tests.test_placements import REPOSITORY, Setup, place
from tests.test_runner_stream import attach
from tests.test_runners import error


def _fields(response: Any) -> Any:
    return response.json()["error"]["details"]["fields"]


def _profiles(s: Setup, handle: str) -> list[str]:
    with s.engine.connect() as conn:
        return list(
            conn.execute(
                select(t.agent_profile.c.id).where(
                    t.agent_profile.c.owner_id == s.owner.id, t.agent_profile.c.handle == handle
                )
            ).scalars()
        )


def _reserving(s: Setup, handle: str) -> list[str]:
    """The active placements that will create a profile of the owner with `handle`."""
    with s.engine.connect() as conn:
        return list(
            conn.execute(
                select(t.placement.c.id).where(
                    t.placement.c.created_by == s.owner.id,
                    t.placement.c.new_handle == handle,
                    t.placement.c.active.is_(True),
                )
            ).scalars()
        )


def _no_agent_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """`max_agents_per_human` off for every account: `create_profile` then does not lock the
    owner's `human` row for its count (`_refuse_over_agents`)."""
    original = limits.for_account

    def for_account(
        conn: Any, name: str, owner_id: str, instance_value: int | None
    ) -> tuple[int | None, str]:
        if name == "max_agents_per_human":
            return None, "instance"
        return original(conn, name, owner_id, instance_value)

    monkeypatch.setattr(limits, "for_account", for_account)


def test_a_join_naming_the_handle_waits_for_a_new_profiles_placement_and_finds_it_reserved(
    setup: Setup,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # §6.24, §15.5: the placement read the handle as free under its lock and holds it; a join
    # that would give the owner a profile with that handle (`create_profile`, which takes the
    # handle's lock first) waits for it and is then refused `taken`, with no deadlock. The
    # handle's lock is its only wait path for this to hold. The agent limit is off, so the
    # join does not lock the owner's `human` row, which the placement's insert key-shares
    # through `created_by`. The join is in another project, so its `join_link` insert does not
    # wait on the placement's project row through the foreign key. Without the placement's
    # handle lock the join then waits for nothing, and both commit.
    caplog.set_level(logging.WARNING, logger="maity_hub.db")
    _no_agent_limit(monkeypatch)
    reached, go = paused(monkeypatch, placement_routes, "_exists")  # right after the handle read
    with race(setup.engine) as r:  # skips on SQLite before any setup
        flow.project(setup.owner, "second", repository={"url": REPOSITORY})
        creating = r.run(r.first, lambda: place(setup, agent=NEW_AGENT))
        try:
            assert reached.wait(FINISH_WITHIN)  # the handle read, the placement not yet made
            joining = r.run(
                r.second,
                lambda: setup.owner.post("/projects/maintainer/second/joins", {"agent": NEW_AGENT}),
            )
            assert waiting(joining)  # on the handle's lock the placement holds
        finally:
            go.set()
        made = finished(creating)
        refused = finished(joining)
    assert made.status_code == 201, made.text
    assert (refused.status_code, error(refused)) == (400, "invalid"), refused.text
    assert _fields(refused) == {"handle": "taken"}
    assert _profiles(setup, NEW_AGENT["handle"]) == []
    assert pick_up(setup, made.json()).status_code == 201
    retries = [x.getMessage() for x in caplog.records if "database retry" in x.getMessage()]
    assert retries == []  # the join waited on the handle's lock alone, no deadlock


def test_two_placements_of_one_new_handle_in_two_projects_give_one_placement(
    setup: Setup, monkeypatch: pytest.MonkeyPatch  # noqa: F811
) -> None:
    # §6.24, §15.5: the project locks differ, so only the handle's lock orders them. Both meet
    # right before it, each holding its own project's lock; one takes the handle, the other
    # waits and then finds it reserved by the first (`taken`). Without the handle lock neither
    # waits and the owner has two placements that would create the same profile.
    meeting = meet(
        monkeypatch,
        handles,
        "lock",
        before=True,
        key=lambda conn, scope, handle: id(conn),
        engine=setup.engine,
    )  # each placement's handle lock, its project's taken; skips on SQLite before any setup
    flow.project(setup.owner, "second", repository={"url": REPOSITORY})  # takes no handle lock
    assert attach(setup.owner, setup.runner, "second").status_code == 201
    body = {"agent": NEW_AGENT, "runner": setup.runner.id, "harness": "claude-code"}
    with race(setup.engine) as r:
        first = r.run(r.first, lambda: place(setup, agent=NEW_AGENT))
        second = r.run(
            r.second,
            lambda: setup.owner.post("/projects/maintainer/second/placements", body),
        )
        answers = [finished(first), finished(second)]
    meeting.check()
    assert sorted(a.status_code for a in answers) == [201, 400], [a.text for a in answers]
    [refused] = [a for a in answers if a.status_code == 400]
    assert _fields(refused) == {"handle": "taken"}, refused.text
    assert len(_reserving(setup, NEW_AGENT["handle"])) == 1


def test_a_rename_and_a_new_profiles_placement_of_one_handle_deadlock_and_one_wins(
    setup: Setup,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # §6.24: a rename takes the handle's lock and then, as its events go out, the lock of the
    # project its profile is a member of; the placement takes the project's lock, then the
    # handle's. The rename is held after its handle lock until the placement waits on it, so
    # each then waits for the other: the database aborts one, `idempotency.run` runs it again,
    # and it finds the handle the other took (`taken`). Without the placement's handle lock
    # the placement does not wait, and the rename gives the profile a handle the committed
    # placement will create too.
    caplog.set_level(logging.WARNING, logger="maity_hub.db")
    reached, go = paused(monkeypatch, handles, "announce")  # the handle locked, no event yet
    with race(setup.engine) as r:
        renaming = r.run(
            r.first,
            lambda: setup.owner.patch(f"/agents/{setup.agent.id}", {"handle": NEW_AGENT["handle"]}),
        )
        try:
            assert reached.wait(FINISH_WITHIN)  # the rename holds the handle's lock
            creating = r.run(r.second, lambda: place(setup, agent=NEW_AGENT))
            assert waiting(creating)  # it holds the project's lock and waits for the handle's
        finally:
            go.set()  # the rename's events reach for the project's lock: a deadlock
        renamed = finished(renaming)
        made = finished(creating)
    retries = [x.getMessage() for x in caplog.records if "database retry" in x.getMessage()]
    assert retries, "the deadlock was not reached"
    outcome = (renamed.status_code, made.status_code)
    assert outcome in {(200, 400), (400, 201)}, (renamed.text, made.text)
    loser = made if made.status_code == 400 else renamed
    assert _fields(loser) == {"handle": "taken"}, loser.text
    profiles = _profiles(setup, NEW_AGENT["handle"])
    reserving = _reserving(setup, NEW_AGENT["handle"])
    if outcome == (200, 400):  # the outcome A2139's probe saw on #2120
        assert (profiles, reserving) == ([setup.agent.id], [])
    else:
        assert (profiles, len(reserving)) == ([], 1)
