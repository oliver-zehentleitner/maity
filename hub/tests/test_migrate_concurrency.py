"""`maity-hub migrate` while the hub serves (tsk-cvxtjnep4bqj): on PostgreSQL the chain is one
transaction, and a hub transaction that holds a table the chain wants next and then touches one it
already holds closes a cycle. The chain is the victim and is run again from the start; a lock it
cannot have within the timeout ends the attempt the same way."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from alembic import command
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import OperationalError

from maity_hub import db
from maity_hub.db import current_revision, make_engine, migrate

KNOWN_SOURCE = "20261105120000_known_source"
PUBLIC_STATS = "20261106180000_public_stats"
JOIN_SUBAGENTS = "20261106210000_join_subagents"


def _down(engine: Engine, revision: str) -> str:
    from alembic.script import ScriptDirectory

    down = (
        ScriptDirectory.from_config(db.alembic_config(engine)).get_revision(revision).down_revision
    )
    assert isinstance(down, str)
    return down


@pytest.fixture
def postgres(engine: Engine) -> Engine:
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL's lock manager")
    return engine


@contextmanager
def _engine_named(engine: Engine, name: str) -> Iterator[Engine]:
    named = make_engine(engine.url.render_as_string(hide_password=False), application_name=name)
    try:
        yield named
    finally:
        named.dispose()


def _locks(watch: Engine, application: str, relation: str, granted: bool) -> bool:
    with watch.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT 1 FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
                    " WHERE a.application_name = :application AND l.granted = :granted"
                    " AND l.relation = CAST(:relation AS regclass)"
                ),
                {"application": application, "relation": relation, "granted": granted},
            ).first()
            is not None
        )


def _until(condition: Callable[[], bool], what: str) -> None:
    deadline = time.monotonic() + 30
    while not condition():
        assert time.monotonic() < deadline, what
        time.sleep(0.02)


def _migrate_beside(
    postgres: Engine, target: str, first: str, held: str, second: Callable[[Connection], object]
) -> tuple[BaseException | None, BaseException | None]:
    """Migrate to `target` in a thread while a hub transaction reads `first`, waits until the
    migration holds `held` and waits for `first`, then runs `second`. The errors of both."""
    outcome: dict[str, BaseException | None] = {}
    with (
        _engine_named(postgres, "test-migrate") as runner,
        _engine_named(postgres, "test-hub") as hub,
        _engine_named(postgres, "test-watch") as watch,
    ):

        def run() -> None:
            try:
                migrate(runner, target)
                outcome["migrate"] = None
            except BaseException as error:  # noqa: BLE001 - handed to the test
                outcome["migrate"] = error

        with hub.connect() as conn:
            transaction = conn.begin()
            conn.execute(text(f"SELECT count(*) FROM {first}"))
            thread = threading.Thread(target=run)
            thread.start()
            _until(lambda: _locks(watch, "test-migrate", held, True), f"migrate holds {held}")
            _until(lambda: _locks(watch, "test-migrate", first, False), f"migrate waits: {first}")
            try:
                second(conn)
                transaction.commit()
                outcome["hub"] = None
            except OperationalError as error:
                transaction.rollback()
                outcome["hub"] = error
            thread.join(60)
            assert not thread.is_alive()
    return outcome["migrate"], outcome["hub"]


def test_a_hub_transaction_that_reads_a_later_table_then_human_does_not_fail_the_chain(
    postgres: Engine,
) -> None:
    # known_source and public_stats lock `human`, join_subagents then wants `membership`: the
    # hub holds membership and reads human (prod deploy 2026-11-08, first attempt).
    migrate(postgres, _down(postgres, KNOWN_SOURCE))
    failed, hub_failed = _migrate_beside(
        postgres,
        JOIN_SUBAGENTS,
        "membership",
        "human",
        lambda conn: conn.execute(text("SELECT count(*) FROM human")),
    )
    assert failed is None
    assert hub_failed is None
    assert current_revision(postgres) == JOIN_SUBAGENTS


def test_a_deadlock_inside_one_migration_does_not_fail_the_chain(postgres: Engine) -> None:
    # join_subagents alone takes join_link, then membership: one migration meets the hub too.
    migrate(postgres, PUBLIC_STATS)
    failed, hub_failed = _migrate_beside(
        postgres,
        JOIN_SUBAGENTS,
        "membership",
        "join_link",
        lambda conn: conn.execute(text("SELECT count(*) FROM join_link")),
    )
    assert failed is None
    assert hub_failed is None
    assert current_revision(postgres) == JOIN_SUBAGENTS


def test_a_lock_not_had_in_time_rolls_the_whole_chain_back(postgres: Engine) -> None:
    # No half state: a run that gives up leaves the revision the running hub expects (its
    # /health answers schema_outdated for any other), not the migrations before the one it lost.
    start = _down(postgres, KNOWN_SOURCE)
    migrate(postgres, start)
    with _engine_named(postgres, "test-hub") as hub, hub.connect() as conn:
        conn.begin()
        conn.execute(text("SELECT count(*) FROM membership"))  # held until the end
        began = time.monotonic()
        with pytest.raises(OperationalError) as raised:
            migrate(postgres, JOIN_SUBAGENTS, lock_timeout=0.2, attempts=2, pause=0.05)
        assert getattr(raised.value.orig, "sqlstate", None) == "55P03"
        assert time.monotonic() - began < 10
        conn.rollback()
    assert current_revision(postgres) == start
    with postgres.connect() as conn:
        assert conn.execute(text("SELECT to_regclass('known_source')")).scalar() is None


def test_the_lock_timeout_does_not_stay_on_the_pooled_connection(postgres: Engine) -> None:
    migrate(postgres, _down(postgres, KNOWN_SOURCE), lock_timeout=3)
    with postgres.connect() as conn:
        assert conn.execute(text("SHOW lock_timeout")).scalar() == "0"


class _Driver(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _failing(monkeypatch: pytest.MonkeyPatch, sqlstate: str) -> list[str]:
    calls: list[str] = []

    def upgrade(_config: object, revision: str) -> None:
        calls.append(revision)
        raise OperationalError("ALTER TABLE", {}, _Driver(sqlstate))

    monkeypatch.setattr(command, "upgrade", upgrade)
    return calls


@pytest.mark.parametrize("sqlstate", ["40P01", "55P03"])
def test_the_chain_is_run_again_a_bounded_number_of_times(
    postgres: Engine, monkeypatch: pytest.MonkeyPatch, sqlstate: str
) -> None:
    calls = _failing(monkeypatch, sqlstate)
    with pytest.raises(OperationalError):
        migrate(postgres, attempts=3, pause=0)
    assert calls == ["head", "head", "head"]


def test_any_other_error_is_not_run_again(
    postgres: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _failing(monkeypatch, "42P01")
    with pytest.raises(OperationalError):
        migrate(postgres, attempts=3, pause=0)
    assert calls == ["head"]


def test_other_databases_are_not_run_again(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    # MariaDB commits per step, so an attempt from the start would redo committed DDL; SQLite
    # has one writer.
    if engine.dialect.name == "postgresql":
        pytest.skip("the other engines")
    calls = _failing(monkeypatch, "40P01")
    with pytest.raises(OperationalError):
        migrate(engine, attempts=3, pause=0)
    assert calls == ["head"]
