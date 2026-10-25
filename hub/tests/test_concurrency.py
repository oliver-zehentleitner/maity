"""The race helper itself (tests/concurrency.py), on any database."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from maity_hub import events
from tests.concurrency import _end


def test_a_connection_goes_back_to_the_pool_without_the_event_lists() -> None:
    """`info` belongs to the pooled connection and outlives `close`: a later caller on the
    same connection must not believe it is inside `events.transaction`."""
    engine = create_engine("sqlite://", poolclass=QueuePool, pool_size=1, max_overflow=0)
    conn = engine.connect()
    conn.begin()
    conn.info[events._PENDING] = []
    conn.info[events._UNDO] = []
    _end(conn)
    recycled = engine.connect()
    assert events._PENDING not in recycled.info and events._UNDO not in recycled.info
    recycled.close()
    engine.dispose()
