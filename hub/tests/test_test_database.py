"""The suite's own guard on a server database (tsk-xz3bxa5cwv4v)."""

from __future__ import annotations

import time

import pytest
from sqlalchemy import Engine, select
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
