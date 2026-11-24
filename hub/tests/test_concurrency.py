"""The race helper itself (tests/concurrency.py), on any database."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import QueuePool

from maity_hub import events
from tests.concurrency import _end, meet


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


def test_a_caller_after_the_meeting_passes_straight_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The barrier is cyclic: once two callers met, a third distinct caller must not wait on
    it (it would start a meeting nobody joins, time out and mark the first one broken)."""
    module = SimpleNamespace(hold=lambda who: who)
    meeting = meet(monkeypatch, module, "hold", key=lambda who: who, timeout=2.0)
    threads = [threading.Thread(target=module.hold, args=(who,)) for who in ("anna", "ben")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5.0)
    start = time.monotonic()
    assert module.hold("carl") == "carl"
    assert time.monotonic() - start < 1.0, "the third caller waited on the barrier"
    meeting.check()
    assert sorted(meeting.arrived) == ["anna", "ben"]
