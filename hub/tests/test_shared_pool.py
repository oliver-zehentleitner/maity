"""Counter transactions must make progress while the serving pool is held by requests."""

from __future__ import annotations

import time
from dataclasses import replace

import pytest
from sqlalchemy import Engine, create_engine, func, select

from maity_hub import db, ratelimit, shared_budget, shared_counts
from maity_hub.app import create_app
from maity_hub.config import Settings


def test_non_postgres_does_not_gain_an_engine(migrated: Engine) -> None:
    if migrated.dialect.name == "postgresql":
        pytest.skip("the single-process database path")
    assert db.make_shared_engine(migrated) is None


@pytest.mark.parametrize("operation", ["counts", "budget"])
def test_counters_progress_while_a_request_holds_the_entire_pool(
    migrated: Engine, settings: Settings, operation: str
) -> None:
    if migrated.dialect.name != "postgresql":
        pytest.skip("shared counters run on PostgreSQL")
    serving = create_engine(migrated.url, pool_size=1, max_overflow=0, pool_timeout=0.1)
    app = create_app(replace(settings, db_statement_timeout=2), serving)
    extra = app.state.shared_engine
    try:
        with serving.begin() as request:
            request.execute(select(func.pg_advisory_xact_lock(4467)))
            # One connection is the whole serving pool. The count commits separately,
            # while this request still holds its transaction and lock.
            if operation == "counts":
                limit = ratelimit.Limiter(2, 60, name="test.shared.pool")
                assert limit.hit("caller") == 0
                assert limit.hit("caller") == 0
                assert limit.hit("caller") > 0
            else:
                shared_budget.write("pool-test", 5000, 1234, time.time() + 3600, 0)
                row = shared_budget.read("pool-test")
                assert row is not None and row.remaining == 1234
            assert request.in_transaction()
            with extra.connect() as counter:
                assert counter.exec_driver_sql("SHOW statement_timeout").scalar_one() == "2s"
        assert extra is not serving and extra.pool is not serving.pool
        assert extra.pool.size() == 2 and extra.pool._max_overflow == 0
    finally:
        shared_counts.configure(None)
        shared_budget.configure(None)
        if extra is not None:
            extra.dispose()
        app.state.health_engine.dispose()
        serving.dispose()
