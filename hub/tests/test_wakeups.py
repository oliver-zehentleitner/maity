"""Wake-ups across replicas on PostgreSQL (hub/context/replicas.md 387c2409)."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterator

import psycopg
import pytest
from sqlalchemy import Engine, text

from maity_hub import events, longpoll, wakeups
from maity_hub.db import APPLICATION_LISTENER
from tests import factory


def _url(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def _until(check: Callable[[], bool], seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return check()


@pytest.fixture
def postgres(migrated: Engine) -> Engine:
    if migrated.dialect.name != "postgresql":
        pytest.skip("SQLite and MariaDB run one replica: no listener")
    return migrated


@pytest.fixture
def heard() -> Iterator[list[tuple[str, int]]]:
    received: list[tuple[str, int]] = []
    unsubscribe = events.notifier.subscribe(lambda p, s: received.append((p, s)))
    yield received
    unsubscribe()


@pytest.fixture
def listener(postgres: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[wakeups.Listener]:
    monkeypatch.setattr(wakeups, "BACKOFF_FIRST", 0.05)
    running = wakeups.Listener(_url(postgres))
    running.start()
    assert running.listening.wait(10)
    yield running
    running.stop()


def _notify(engine: Engine, payload: str) -> None:
    """What another replica's commit sends."""
    with engine.begin() as conn:
        conn.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {
                "channel": events.CHANNEL,
                "payload": payload,
            },
        )


def test_an_event_another_replica_commits_wakes_this_one(
    postgres: Engine, listener: wakeups.Listener, heard: list[tuple[str, int]]
) -> None:
    _notify(postgres, "prj-elsewhere:42")
    assert _until(lambda: heard == [("prj-elsewhere", 42)])


def test_emit_announces_at_commit_and_never_for_a_rollback(postgres: Engine) -> None:
    project_id = factory.project(postgres)
    with psycopg.connect(_url(postgres).replace("+psycopg", ""), autocommit=True) as watch:
        watch.execute(f"LISTEN {events.CHANNEL}")
        with pytest.raises(RuntimeError, match="abort"), events.transaction(postgres) as conn:
            events.emit(conn, project_id, "state_changed", ["all"], {})
            raise RuntimeError("abort")
        with events.transaction(postgres) as conn:
            seq = events.emit(conn, project_id, "state_changed", ["all"], {"old": "build"})
        payloads = [n.payload for n in watch.notifies(timeout=2, stop_after=2)]
    assert payloads == [f"{project_id}:{seq}"]  # where to look, never what happened


def test_an_event_of_this_process_wakes_its_waiters_once(
    postgres: Engine, listener: wakeups.Listener, heard: list[tuple[str, int]]
) -> None:
    project_id = factory.project(postgres)
    with events.transaction(postgres) as conn:
        seq = events.emit(conn, project_id, "state_changed", ["all"], {})
    _notify(postgres, "prj-marker:1")  # delivered after the event's own, in commit order
    assert _until(lambda: ("prj-marker", 1) in heard)
    assert heard == [(project_id, seq), ("prj-marker", 1)]


def test_a_lost_connection_wakes_every_waiter_and_listens_again(
    postgres: Engine,
    listener: wakeups.Listener,
    heard: list[tuple[str, int]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spreads: list[float] = []
    monkeypatch.setattr(longpoll.registry, "wake_all", lambda spread=0.0: spreads.append(spread))
    with postgres.begin() as conn:
        ended = (
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
                    " WHERE application_name = :name AND datname = current_database()"
                ),
                {"name": APPLICATION_LISTENER},
            )
            .scalars()
            .all()
        )
    assert ended == [True]
    assert _until(lambda: spreads == [wakeups.RESPREAD_SECONDS] and listener.listening.is_set())
    _notify(postgres, "prj-after:7")
    assert _until(lambda: heard == [("prj-after", 7)])


def test_a_wake_up_that_is_no_project_and_seq_is_ignored(heard: list[tuple[str, int]]) -> None:
    wakeups.handle("no seq here")
    wakeups.handle("prj:")
    assert heard == []


def test_a_spread_wake_reaches_every_waiter_within_the_spread() -> None:
    async def waiting() -> list[bool]:
        loop = asyncio.get_running_loop()
        registry = longpoll.Registry()
        waiters = [
            longpoll.Waiter(key=f"k{i}", project_id="p", session_id=None, loop=loop)
            for i in range(3)
        ]
        for waiter in waiters:
            registry.enter(waiter)
        threading.Thread(target=registry.wake_all, kwargs={"spread": 0.2}).start()
        woken = await asyncio.wait_for(
            asyncio.gather(*(w.event.wait() for w in waiters)), timeout=2
        )
        return [bool(w) for w in woken]

    assert asyncio.run(waiting()) == [True, True, True]
