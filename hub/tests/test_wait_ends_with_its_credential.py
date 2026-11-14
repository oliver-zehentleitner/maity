"""docs/api.md §8.3, §16.8: an open events wait ends with the credential or the dashboard
session it was opened with, at once in the process that revoked or ended it, and at the
next pass on every other replica, which reads the row; a human's wait also ends with the
human's membership."""

from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import clock, events, longpoll, moderation
from maity_hub import tables as t
from maity_hub.auth import leaks, sessions
from maity_hub.routes import events as events_route
from tests import flow
from tests.conftest import ClientFactory
from tests.test_bridge_reads import PROJECT, _get
from tests.test_event_quiet_passes import _agent, _latest, _until_waiting

FAST = 0.05


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


@pytest.fixture
def pool() -> Iterator[ThreadPoolExecutor]:
    with ThreadPoolExecutor(max_workers=2) as running:
        yield running


def _ended_soon(waiting: Any, began: float) -> None:
    got = waiting.result(timeout=15)
    assert got.status_code == 200, got.text
    assert got.json()["items"] == []
    assert time.monotonic() - began < 8  # well before the wait's own 20 s


@pytest.mark.parametrize("how", ["revoked", "suspended"])
def test_a_revoked_credential_ends_its_open_wait_at_once(
    how: str,
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    pool: ThreadPoolExecutor,
) -> None:
    """The fallback between passes is left at its default: only the registry ends it."""
    reader = _agent(migrated, owner)
    after = _latest(make_client(), reader, f"{PROJECT}/events?")
    began = time.monotonic()
    waiting = pool.submit(_get, make_client(), reader, f"{PROJECT}/events?after={after}&wait=20")
    _until_waiting(reader.credential_id)
    with events.transaction(migrated) as conn:
        if how == "revoked":
            leaks.revoke(conn, reader.credential_id, "test", None)
        else:
            moderation.suspend(conn, owner.id, "rpt-000000000000")
    _ended_soon(waiting, began)


def test_a_dashboard_sign_out_ends_the_sessions_open_wait_at_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, pool: ThreadPoolExecutor
) -> None:
    after = owner.get(f"{PROJECT}/events?after=latest").json()["cursor"]
    began = time.monotonic()
    waiting = pool.submit(owner.get, f"{PROJECT}/events?after={after}&wait=20")
    _until_waiting("session:")
    with events.transaction(migrated) as conn:
        sessions.end_where(conn, t.human_session.c.human_id == owner.id, "test")
    _ended_soon(waiting, began)


@pytest.mark.parametrize("change", ["revoked", "session ended", "human removed"])
def test_another_replica_ends_the_wait_at_its_next_pass(
    change: str,
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    pool: ThreadPoolExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Written in the database without a notice, as another replica would: the next pass
    reads the row and ends the wait, never one that keeps delivering."""
    monkeypatch.setattr(events_route, "FALLBACK_SECONDS", FAST)
    began = time.monotonic()
    if change == "revoked":
        reader = _agent(migrated, owner)
        after = _latest(make_client(), reader, f"{PROJECT}/events?")
        path = f"{PROJECT}/events?after={after}&wait=20"
        waiting = pool.submit(_get, make_client(), reader, path)
        _until_waiting(reader.credential_id)
    else:
        after = owner.get(f"{PROJECT}/events?after=latest").json()["cursor"]
        waiting = pool.submit(owner.get, f"{PROJECT}/events?after={after}&wait=20")
        _until_waiting("session:")
    with migrated.begin() as conn:
        if change == "revoked":
            conn.execute(
                update(t.credential)
                .where(t.credential.c.id == reader.credential_id)
                .values(revoked_at=clock.now(), revoked_reason="elsewhere")
            )
        elif change == "session ended":
            conn.execute(
                update(t.human_session)
                .where(t.human_session.c.human_id == owner.id)
                .values(ended_at=clock.now())
            )
        else:
            conn.execute(
                update(t.membership).where(t.membership.c.human_id == owner.id).values(active=None)
            )
    _ended_soon(waiting, began)


def test_a_wait_that_started_before_the_revoke_reads_nothing_after_it(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The call's caller was loaded before a revoke that commits before its first pass: the
    pass reads the credential as of now and delivers nothing (§8.3)."""
    reader = _agent(migrated, owner)
    assert owner.post(f"{PROJECT}/tasks", {"title": "an event to read"}).status_code == 201
    real = longpoll.registry.enter

    def revoked_meanwhile(waiter: Any) -> None:
        with migrated.begin() as conn:
            conn.execute(
                update(t.credential)
                .where(t.credential.c.id == reader.credential_id)
                .values(revoked_at=clock.now(), revoked_reason="meanwhile")
            )
        real(waiter)

    monkeypatch.setattr(longpoll.registry, "enter", revoked_meanwhile)
    got = _get(make_client(), reader, f"{PROJECT}/events?after=0&wait=1")
    assert got.status_code == 200, got.text
    assert got.json()["items"] == []


def test_end_keys_ends_only_the_named_credentials_and_sessions() -> None:
    import asyncio

    loop = asyncio.new_event_loop()
    made = [
        longpoll.Waiter(key=key, project_id="prj-x", session_id=None, loop=loop)
        for key in ("crd-a", "crd-a|for:agt-1", "crd-b", "session:h1", "session:h2")
    ]
    try:
        for waiter in made:
            longpoll.registry.enter(waiter)
        longpoll.registry.end_keys({"crd-a", "session:h1"})
        assert [w.ended for w in made] == [True, True, False, True, False]
    finally:
        for waiter in made:
            longpoll.registry.leave(waiter)
        loop.close()
