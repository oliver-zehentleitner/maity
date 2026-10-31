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


# --- superseding a wait across replicas (point 3) ------------------------------------------


def test_a_newer_wait_on_another_replica_supersedes_this_one(
    postgres: Engine, listener: wakeups.Listener, heard: list[tuple[str, int]]
) -> None:
    ended: list[str] = []
    closed = asyncio.run(
        wakeups.opened(postgres, "events", "cred-1", lambda: ended.append("cred-1"))
    )
    other = asyncio.run(wakeups.opened(postgres, "bell", "cred-1", lambda: ended.append("bell")))
    _notify(postgres, "prj-marker:1")  # after both announcements, in commit order
    assert _until(lambda: ("prj-marker", 1) in heard)
    assert ended == []  # its own announcement ends nothing
    elsewhere = wakeups._digest("events", "cred-1")
    with postgres.begin() as conn:  # what the other replica's `opened` sends, a moment later
        conn.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": wakeups.SUPERSEDE, "payload": f"{elsewhere}:{2**62}"},
        )
    assert _until(lambda: ended == ["cred-1"])  # the bell's wait of that key is another kind
    closed()
    other()


def test_only_a_wait_that_started_earlier_is_superseded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two waits opening at almost the same moment on two replicas: each announcement may
    arrive after the other wait opened; only the older one ends, never both."""
    monkeypatch.setattr(wakeups, "_held", {})
    digest = wakeups._digest("events", "cred-1")
    ended: list[str] = []
    wakeups._held[digest] = {
        object(): (100, lambda: ended.append("older")),
        object(): (300, lambda: ended.append("newer")),
    }
    wakeups.supersede(f"{digest}:200")
    wakeups.supersede(f"{digest}:200")  # told twice: ended once
    wakeups.supersede("not a notice")
    assert ended == ["older"]


def test_a_wait_without_postgresql_announces_nothing(migrated: Engine) -> None:
    if migrated.dialect.name == "postgresql":
        pytest.skip("the announcement is PostgreSQL's")
    closed = asyncio.run(wakeups.opened(migrated, "events", "cred-1", lambda: None))
    assert wakeups._held == {}
    closed()


def test_the_listener_notices_a_dead_connection(postgres: Engine) -> None:
    """c47w at #869: without keepalives a connection dropped silently would leave the listener
    waiting for good, and its session would hold the server's notice queue."""
    from maity_hub.db import make_listener_engine

    engine = make_listener_engine(_url(postgres))
    try:
        raw = engine.raw_connection()
        try:
            assert raw.driver_connection is not None
            parameters = raw.driver_connection.info.get_parameters()
        finally:
            raw.close()
    finally:
        engine.dispose()
    assert parameters["keepalives"] == "1"
    assert parameters["keepalives_idle"] == "30"


def test_a_newer_notice_right_after_the_commit_finds_the_wait(
    postgres: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """c47w at #877: the wait is held before its announcement commits, so a newer wait's
    notice arriving before `opened` has returned still ends it; else both stayed open."""
    monkeypatch.setattr(wakeups, "_held", {})
    digest, ended = wakeups._digest("events", "cred-2"), []
    wakeups._announce(postgres, digest, object(), lambda: ended.append("older"))
    ((started, _),) = wakeups._held[digest].values()
    wakeups.supersede(f"{digest}:{started}")  # its own notice: not older, nothing ends
    assert ended == []
    wakeups.supersede(f"{digest}:{started + 1}")  # a newer wait elsewhere, at once
    assert ended == ["older"]


def test_a_failed_announcement_holds_nothing(
    postgres: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(wakeups, "_held", {})
    monkeypatch.setattr(wakeups, "SUPERSEDE", "")  # PostgreSQL refuses an empty channel
    with pytest.raises(Exception, match="channel"):
        wakeups._announce(postgres, wakeups._digest("events", "x"), object(), lambda: None)
    assert wakeups._held == {}


# --- the bell and the device codes (point 5) -----------------------------------------------


def test_a_ring_on_another_replica_wakes_a_held_bell(
    postgres: Engine, listener: wakeups.Listener
) -> None:
    async def hold_and_wait() -> float:
        hold = wakeups.held(postgres, "bell", wait_key="s-1", ring_key="hum-1", poll=0.5)
        try:
            began = time.monotonic()

            def other_replica() -> None:
                with postgres.begin() as conn:
                    wakeups.ring(conn, "bell", "hum-1")

            threading.Timer(0.1, other_replica).start()
            await hold.pause(5)
            return time.monotonic() - began
        finally:
            hold.close()

    assert asyncio.run(hold_and_wait()) < wakeups.FALLBACK_SECONDS  # the ring, not the fallback


def test_an_event_in_its_projects_wakes_a_held_bell(
    postgres: Engine, listener: wakeups.Listener
) -> None:
    async def hold_and_wait() -> float:
        hold = wakeups.held(
            postgres,
            "bell",
            wait_key="s-2",
            ring_key="hum-2",
            poll=0.5,
            project_ids=frozenset({"prj-bell"}),
        )
        try:
            began = time.monotonic()
            threading.Timer(0.1, _notify, args=(postgres, "prj-bell:9")).start()
            await hold.pause(5)
            return time.monotonic() - began
        finally:
            hold.close()

    assert asyncio.run(hold_and_wait()) < wakeups.FALLBACK_SECONDS


def test_a_ring_names_only_a_hash_and_comes_at_commit(postgres: Engine) -> None:
    with psycopg.connect(_url(postgres).replace("+psycopg", ""), autocommit=True) as watch:
        watch.execute(f"LISTEN {wakeups.RINGS['device']}")
        with pytest.raises(RuntimeError, match="abort"), postgres.begin() as conn:
            wakeups.ring(conn, "device", "code:rolled-back")
            raise RuntimeError("abort")
        with postgres.begin() as conn:
            wakeups.ring(conn, "device", "code:abc")
        payloads = [n.payload for n in watch.notifies(timeout=2, stop_after=2)]
    assert payloads == [wakeups._digest("device", "code:abc")]


def test_without_postgresql_a_held_wait_polls(migrated: Engine) -> None:
    if migrated.dialect.name == "postgresql":
        pytest.skip("PostgreSQL rings")

    async def hold_and_wait() -> float:
        hold = wakeups.held(migrated, "bell", wait_key="s-3", ring_key="hum-3", poll=0.05)
        began = time.monotonic()
        await hold.pause(5)
        hold.close()
        return time.monotonic() - began

    assert asyncio.run(hold_and_wait()) < 0.5
