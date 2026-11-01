"""Transient conflicts are run again; everything else surfaces at once."""

from __future__ import annotations

import threading

import pytest
from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import OperationalError

from maity_hub import tables as t
from maity_hub.db import RETRIES, retrying


class _Deadlock(Exception):
    sqlstate = "40001"


class _Gone(Exception):
    args = (2003,)


class _SavepointGone(Exception):
    sqlstate = "42000"
    args = (1305,)


def _failing(errors: list[Exception]) -> object:
    def work() -> str:
        if errors:
            raise OperationalError("stmt", {}, errors.pop(0))
        return "done"

    return work


def test_a_deadlock_is_run_again() -> None:
    assert retrying(_failing([_Deadlock(), _Deadlock()])) == "done"  # type: ignore[arg-type]


def test_a_lasting_deadlock_surfaces_after_the_retries() -> None:
    with pytest.raises(OperationalError):
        retrying(_failing([_Deadlock() for _ in range(RETRIES)]))  # type: ignore[arg-type]


def test_any_other_failure_surfaces_at_once() -> None:
    errors: list[Exception] = [_Gone(), _Deadlock()]
    with pytest.raises(OperationalError):
        retrying(_failing(errors))  # type: ignore[arg-type]
    assert len(errors) == 1  # not retried


def test_a_savepoint_a_deadlock_took_with_it_is_run_again() -> None:
    assert retrying(_failing([_SavepointGone()])) == "done"  # type: ignore[arg-type]


def test_a_real_deadlock_inside_a_savepoint_is_run_again(migrated: Engine) -> None:
    """On InnoDB the driver's answer is the lost savepoint, not the deadlock (seen on
    hub-mariadb): the losing transaction runs again and both end."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite takes one writer and has no such cycle")
    lock = t.handle_lock
    with migrated.begin() as conn:
        conn.execute(insert(lock), [{"scope": "race", "handle": h} for h in ("a", "b")])
    both_hold = threading.Barrier(2, timeout=10)
    results: list[str] = []

    def side(first: str, second: str) -> None:
        met = threading.Event()

        def work() -> str:
            with migrated.begin() as conn:
                conn.execute(
                    select(lock.c.handle)
                    .where(lock.c.scope == "race", lock.c.handle == first)
                    .with_for_update()
                ).first()
                if not met.is_set():
                    met.set()
                    both_hold.wait()
                with conn.begin_nested():
                    conn.execute(
                        update(lock)
                        .where(lock.c.scope == "race", lock.c.handle == second)
                        .values(scope="race")
                    )
            return "done"

        results.append(retrying(work))

    threads = [threading.Thread(target=side, args=pair) for pair in (("a", "b"), ("b", "a"))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert results == ["done", "done"]
