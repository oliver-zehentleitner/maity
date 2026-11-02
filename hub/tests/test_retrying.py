"""Transient conflicts are run again; everything else surfaces at once."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import OperationalError

from maity_hub import errors as hub_errors
from maity_hub import tables as t
from maity_hub.db import RETRIES, retrying


class _Deadlock(Exception):
    sqlstate = "40001"


class _Gone(Exception):
    args = (2003,)


class _LockWait(Exception):
    sqlstate = "HY000"
    args = (1205,)


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


def _gone_after(earlier: Exception) -> OperationalError:
    """What a failed `ROLLBACK TO SAVEPOINT` raises while `earlier` is being handled."""
    gone = OperationalError("ROLLBACK TO SAVEPOINT", {}, _SavepointGone())
    gone.__context__ = OperationalError("stmt", {}, earlier)
    return gone


def _raising(errors: list[OperationalError]) -> Callable[[], str]:
    def work() -> str:
        if errors:
            raise errors.pop(0)
        return "done"

    return work


def test_a_savepoint_a_deadlock_took_with_it_is_run_again() -> None:
    assert retrying(_raising([_gone_after(_Deadlock())])) == "done"


def test_a_lost_savepoint_without_a_deadlock_behind_it_surfaces_at_once() -> None:
    errors = [OperationalError("stmt", {}, _SavepointGone()), _gone_after(_Gone())]
    with pytest.raises(OperationalError):
        retrying(_raising(errors))
    assert len(errors) == 1
    with pytest.raises(OperationalError):
        retrying(_raising(errors))
    assert errors == []


def test_a_lock_wait_timeout_surfaces_at_once() -> None:
    """The whole lock timeout again on each attempt is no help to anyone waiting."""
    errors = [OperationalError("stmt", {}, _LockWait()), _gone_after(_Deadlock())]
    with pytest.raises(OperationalError):
        retrying(_raising(errors))
    assert len(errors) == 1


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


def test_each_repeat_logs_a_line_with_the_codes_and_no_statement(
    caplog: pytest.LogCaptureFixture,
) -> None:
    deadlock = OperationalError("SELECT secret FROM t", {"p": "secret"}, _Deadlock())
    with caplog.at_level(logging.WARNING, logger="maity_hub.db"):
        assert retrying(_raising([deadlock, _gone_after(_Deadlock())])) == "done"
    assert [r.getMessage() for r in caplog.records if r.name == "maity_hub.db"] == [
        "database retry: attempt=1 of=4 code=40001 number=- behind=-",
        "database retry: attempt=2 of=4 code=42000 number=1305 behind=40001",
    ]


@pytest.mark.parametrize(
    ("error", "fields"),
    [
        (_gone_after(_Deadlock()), "code=42000 number=1305 behind=40001"),
        (OperationalError("s", {}, _SavepointGone()), "code=42000 number=1305 behind=-"),
    ],
)
def test_the_failure_line_gives_the_codes(
    error: OperationalError, fields: str, caplog: pytest.LogCaptureFixture
) -> None:
    app = FastAPI()
    hub_errors.install(app)

    @app.get("/")
    def fail() -> None:
        raise error

    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/").status_code == 503
    assert any(fields in r.getMessage() for r in caplog.records)
