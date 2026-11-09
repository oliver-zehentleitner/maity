"""The suite's own guard on a server database (tsk-xz3bxa5cwv4v)."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import OperationalError

from maity_hub import tables as t
from tests import conftest


def test_a_connection_left_in_a_transaction_fails_one_cleanup_and_is_ended(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A test that leaves a connection in a transaction holds its locks: the TRUNCATE between
    tests waited for them without end, until CI cancelled the job (dzse at #1256). It now gives
    up after `TRUNCATE_LOCK_TIMEOUT`, names the session that held the locks and ends it: this
    cleanup fails, the next one goes through."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("the lock timeout guards the TRUNCATE on PostgreSQL")
    monkeypatch.setattr(conftest, "TRUNCATE_LOCK_TIMEOUT", "1s")
    leaked = migrated.connect()
    try:
        leaked.execute(select(t.presence_minute).limit(1))  # its lock stays with the transaction
        started = time.monotonic()
        with pytest.raises(conftest.LeakedConnection, match="idle in transaction.*presence_minute"):
            conftest._empty_the_tables(migrated)
        assert time.monotonic() - started < 30
        with pytest.raises(OperationalError):
            leaked.execute(select(1))  # ended
        conftest._empty_the_tables(migrated)  # the next cleanup is not held
    finally:
        leaked.invalidate()
        leaked.close()


def test_a_session_without_a_lock_on_the_emptied_tables_is_not_ended(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the sessions that hold the TRUNCATE up are ended: one in the same database whose
    locks are on a table the cleanup does not empty goes on (dzse at #1264)."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("the lock timeout guards the TRUNCATE on PostgreSQL")
    monkeypatch.setattr(conftest, "TRUNCATE_LOCK_TIMEOUT", "1s")
    leaked, bystander = migrated.connect(), migrated.connect()
    try:
        bystander.execute(text("CREATE TEMPORARY TABLE elsewhere (id int)"))
        bystander.execute(text("LOCK TABLE elsewhere IN ACCESS EXCLUSIVE MODE"))
        leaked.execute(select(t.presence_minute).limit(1))
        with pytest.raises(conftest.LeakedConnection, match="presence_minute") as raised:
            conftest._empty_the_tables(migrated)
        assert "elsewhere" not in str(raised.value)
        assert (
            bystander.execute(select(1)).scalar_one() == 1
        )  # still there, still in its transaction
    finally:
        for conn in (leaked, bystander):
            conn.invalidate()
            conn.close()


def test_a_holder_the_filter_does_not_find_is_said_so_not_claimed_ended(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When none of the suite's own sessions holds a lock on what the cleanup empties (another
    role's, or a lock the filter does not see), the message says so instead of an end, and the
    holder goes on (dzse at #1289)."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("the lock timeout guards the TRUNCATE on PostgreSQL")
    monkeypatch.setattr(conftest, "TRUNCATE_LOCK_TIMEOUT", "1s")
    monkeypatch.setattr(conftest, "_relations", lambda engine, tables: [])  # sees none of them
    leaked = migrated.connect()
    try:
        leaked.execute(select(t.presence_minute).limit(1))
        with pytest.raises(conftest.LeakedConnection, match="no session of this suite holds them"):
            conftest._empty_the_tables(migrated)
        assert leaked.execute(select(1)).scalar_one() == 1  # not ended
    finally:
        leaked.invalidate()
        leaked.close()


def test_a_session_that_only_drew_from_a_sequence_is_ended(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`RESTART IDENTITY` also locks the sequences the tables own: a session whose only lock is
    on one, after a `nextval`, holds the TRUNCATE up and is ended like any other (dzse at #1289:
    "none found", and every later cleanup waited again)."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("the lock timeout guards the TRUNCATE on PostgreSQL")
    monkeypatch.setattr(conftest, "TRUNCATE_LOCK_TIMEOUT", "1s")
    with migrated.connect() as conn:
        sequence = conn.execute(
            text(
                "SELECT s.relname FROM pg_class s JOIN pg_depend d"
                " ON d.classid = 'pg_class'::regclass AND d.objid = s.oid"
                " AND d.deptype IN ('a', 'i')"
                " WHERE s.relkind = 'S' AND s.relnamespace = current_schema()::regnamespace"
                " ORDER BY s.relname LIMIT 1"
            )
        ).scalar_one()
    leaked = migrated.connect()
    try:
        leaked.execute(text("SELECT nextval(CAST(:name AS regclass))"), {"name": sequence})
        held = leaked.execute(
            text(
                "SELECT c.relkind FROM pg_locks l JOIN pg_class c ON c.oid = l.relation"
                " WHERE l.pid = pg_backend_pid()"
                " AND c.relnamespace = current_schema()::regnamespace"
            )
        ).scalars()
        assert set(held) == {"S"}  # a lock on the sequence alone, none on a table
        with pytest.raises(conftest.LeakedConnection, match="ended so the next test runs"):
            conftest._empty_the_tables(migrated)
        with pytest.raises(OperationalError):
            leaked.execute(select(1))  # ended
        conftest._empty_the_tables(migrated)  # the next cleanup is not held
    finally:
        leaked.invalidate()
        leaked.close()


def test_the_relations_are_the_ones_the_truncate_sees_along_the_search_path(
    migrated: Engine,
) -> None:
    """The inspector and the unqualified TRUNCATE see the tables through `search_path`; the lock
    lookup resolves them the same way. With an empty schema ahead of the tables' own one,
    `current_schema()` is that empty schema, and a lookup there found nothing (pmwg at #1289)."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("the lock lookup is PostgreSQL's")
    with migrated.begin() as conn:
        home = conn.execute(text("SELECT current_schema()")).scalar_one()
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS ahead_of_it"))
        expected = conn.execute(text("SELECT 'presence_minute'::regclass::oid")).scalar_one()
    shifted = create_engine(
        migrated.url,
        connect_args={"options": f"-c search_path=ahead_of_it,{home}"},
    )
    try:
        with shifted.connect() as conn:
            assert conn.execute(text("SELECT current_schema()")).scalar_one() == "ahead_of_it"
        assert expected in conftest._relations(shifted, ["presence_minute"])
    finally:
        shifted.dispose()
        with migrated.begin() as conn:
            conn.execute(text("DROP SCHEMA ahead_of_it"))


def test_a_session_in_another_database_is_not_ended(migrated: Engine) -> None:
    """The holders are looked up in this database alone: a session of another database with a
    lock on a relation of the same id is not ended (dzse at #1264)."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("the lock timeout guards the TRUNCATE on PostgreSQL")
    other = create_engine(migrated.url.set(database="postgres"))
    try:
        with other.connect() as conn:
            conn.execute(text("CREATE TEMPORARY TABLE elsewhere (id int)"))
            conn.execute(text("LOCK TABLE elsewhere IN ACCESS EXCLUSIVE MODE"))
            oid = conn.execute(text("SELECT 'elsewhere'::regclass::oid")).scalar_one()
            assert conftest._end_the_lock_holders(migrated, [oid]) == []
            assert conn.execute(select(1)).scalar_one() == 1  # not ended
            conn.rollback()
    finally:
        other.dispose()
