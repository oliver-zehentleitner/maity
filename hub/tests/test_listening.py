"""Who listens, across replicas on PostgreSQL (hub/context/replicas.md 387c2409, point 4)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, delete, insert, select

from maity_hub import listening
from maity_hub import tables as t


def _until(check: Callable[[], bool], seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.02)
    return check()


@pytest.fixture
def shared(migrated: Engine) -> Iterator[Engine]:
    """The registry in the database, as `create_app` starts it on PostgreSQL."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("SQLite and MariaDB keep the registry in the process")
    listening.start(migrated)
    yield migrated
    listening.stop(every=True)


def _rows(engine: Engine, key: str) -> list[str]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.long_poll.c.pod).where(t.long_poll.c.listening_key == key)
            ).scalars()
        )


def _other_pod(engine: Engine, pod: str, key: str, seen: datetime) -> None:
    """A wait held by another replica, whose heartbeat was last seen at `seen`."""
    with engine.begin() as conn:
        conn.execute(insert(t.hub_pod).values(pod=pod, seen_at=seen))
        conn.execute(
            insert(t.long_poll).values(
                wait_id=f"w-{pod}", listening_key=key, pod=pod, opened_at=seen
            )
        )


def test_a_wait_on_another_replica_counts_while_its_pod_lives(shared: Engine) -> None:
    now = datetime.now(UTC)
    _other_pod(shared, "pod-live", "ses-elsewhere", now)
    _other_pod(shared, "pod-gone", "ses-stale", now - timedelta(minutes=5))
    assert listening.is_listening("ses-elsewhere")
    assert not listening.is_listening("ses-stale")  # its pod missed three heartbeats
    with shared.connect() as conn:  # one read for many, inside the caller's connection
        assert listening.which(["ses-elsewhere", "ses-stale", "ses-none"], conn) == {
            "ses-elsewhere"
        }


def test_two_waits_of_one_key_never_remove_each_others_row(shared: Engine) -> None:
    first, second = listening.opened("ses-twice"), listening.opened("ses-twice")
    assert listening.is_listening("ses-twice")  # at once, from memory
    assert _until(lambda: _rows(shared, "ses-twice") == [listening.POD] * 2)
    listening.closed("ses-twice", first)
    assert _until(lambda: _rows(shared, "ses-twice") == [listening.POD])
    assert listening.is_listening("ses-twice")
    listening.closed("ses-twice", second)
    assert _until(lambda: _rows(shared, "ses-twice") == [])
    assert not listening.is_listening("ses-twice")


def test_the_heartbeat_writes_rows_again_after_the_table_emptied(shared: Engine) -> None:
    """UNLOGGED: a crash or a failover empties the table while the waits go on."""
    wait = listening.opened("ses-crash")
    assert _until(lambda: _rows(shared, "ses-crash") == [listening.POD])
    with shared.begin() as conn:
        conn.execute(delete(t.long_poll))
        conn.execute(delete(t.hub_pod))
    listening._heartbeat(shared)
    assert _rows(shared, "ses-crash") == [listening.POD]
    listening.closed("ses-crash", wait)


def test_the_heartbeat_sweeps_the_waits_of_a_gone_pod(shared: Engine) -> None:
    _other_pod(shared, "pod-crashed", "ses-orphan", datetime.now(UTC) - timedelta(minutes=5))
    listening._heartbeat(shared)
    assert _rows(shared, "ses-orphan") == []
    with shared.connect() as conn:
        pods = set(conn.execute(select(t.hub_pod.c.pod)).scalars())
    assert pods == {listening.POD}


def test_stopping_removes_this_process_from_the_registry(shared: Engine) -> None:
    listening.opened("ses-leaving")
    assert _until(lambda: _rows(shared, "ses-leaving") == [listening.POD])
    listening.stop()
    assert _rows(shared, "ses-leaving") == []
    with shared.connect() as conn:
        assert conn.execute(select(t.hub_pod.c.pod)).scalars().all() == []
    listening.reset()


def test_without_postgresql_the_registry_stays_in_the_process(migrated: Engine) -> None:
    if migrated.dialect.name == "postgresql":
        pytest.skip("PostgreSQL shares it")
    listening.start(migrated)  # a no-op here
    wait = listening.opened("ses-local")
    assert listening.which(["ses-local", "ses-other"]) == {"ses-local"}
    listening.closed("ses-local", wait)
    assert not listening.is_listening("ses-local")
    with migrated.connect() as conn:
        assert conn.execute(select(t.long_poll.c.wait_id)).all() == []


def test_one_writer_however_many_apps_start_it(shared: Engine) -> None:
    """The tests start an app per client: a writer per start leaked threads and connections,
    and a stop could end the wrong one."""
    import threading

    listening.start(shared)  # a second app in this process
    writer = listening._thread[0]
    assert [th.name for th in threading.enumerate()].count("maity-listening") == 1
    listening.stop()  # that app ends; the first still holds the registry
    assert listening._engine[0] is shared and writer is not None and writer.is_alive()


def test_a_failing_heartbeat_waits_its_interval_instead_of_spinning(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """c47w at #903: with the database gone (a failover) a failed beat was retried at once, in
    a loop without a pause, on every pod."""
    import threading

    beats: list[float] = []

    def failing(_engine: Engine) -> None:
        beats.append(time.monotonic())
        raise RuntimeError("the database is gone")

    monkeypatch.setattr(listening, "_heartbeat", failing)
    monkeypatch.setattr(listening, "HEARTBEAT", timedelta(seconds=0.2))
    writer = threading.Thread(target=listening._write, args=(migrated,), daemon=True)
    writer.start()
    time.sleep(1.0)
    listening._writes.put(None)
    writer.join(timeout=5)
    assert not writer.is_alive()
    assert 2 <= len(beats) <= 7  # one per interval, not thousands


# --- a writer that never ran or is gone (tsk-xz3bxa5cwv4v) ----------------------------------


class _PgLike:
    """Enough of an engine for `start` to take the PostgreSQL path; writes are stubbed."""

    class dialect:  # noqa: N801
        name = "postgresql"

    def begin(self) -> None:
        raise RuntimeError("no database here")


def _broken(engine: object) -> None:
    raise RuntimeError("the database went away")


def test_a_start_whose_heartbeat_fails_leaves_no_registry_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Way C: the first heartbeat fails; nothing stays started, so nothing waits for a writer."""
    monkeypatch.setattr(listening, "_heartbeat", _broken)
    with pytest.raises(RuntimeError):
        listening.start(_PgLike())  # type: ignore[arg-type]
    assert listening._engine[0] is None and listening._starts[0] == 0
    listening.stop(every=True)
    assert listening._writes.empty() and listening._writes.unfinished_tasks == 0


def test_the_next_writer_runs_after_a_failed_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Way D: a stop while no writer ran (a failed start, a writer that died) left the
    sentinel, which ended the next writer at once; `reset` then waited for ever. The next
    writer now runs and handles the queue."""
    listening._engine[0] = _PgLike()  # type: ignore[call-overload]
    listening._thread[0] = None
    listening.stop(every=True)
    assert listening._writes.empty()
    handled: list[str] = []
    monkeypatch.setattr(listening, "_heartbeat", lambda engine: None)
    monkeypatch.setattr(
        listening, "_apply", lambda engine, kind, wait_id, key: handled.append(kind)
    )
    listening.start(_PgLike())  # type: ignore[arg-type]
    try:
        wait = listening.opened("ses-next")
        listening.closed("ses-next", wait)
        listening._drained(5)
        assert handled == ["open", "close"]
        assert listening._thread[0] is not None and listening._thread[0].is_alive()
    finally:
        listening.stop(every=True)


def test_a_wait_for_a_gone_writer_fails_instead_of_hanging(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Way E (a writer that died): the wait for the queue ends with an error, not never."""
    monkeypatch.setattr(listening, "_engine", [_PgLike()])
    monkeypatch.setattr(listening, "_thread", [None])
    listening.opened("ses-gone")
    try:
        with pytest.raises(TimeoutError, match="1 write"):
            listening._drained(0.2)
    finally:
        listening._discard_queued()
        listening._open.clear()
        listening._rows.clear()
