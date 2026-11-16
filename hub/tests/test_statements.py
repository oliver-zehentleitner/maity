"""The statement counter of the cost tests (`tests/statements.py`) counts a call's own
statements, in every thread the call's request hands work to, and none of a thread that was
running before it (the app's background workers): tsk-dbnh1nhcjrc4."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Any

import anyio.to_thread
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from starlette.concurrency import run_in_threadpool

from tests import flow
from tests.conftest import ClientFactory
from tests.statements import count_statements


def _one(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


class _Worker:
    """A thread that sends statements on its own, as the app's workers do on each tick."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sent = 0
        self.stop = threading.Event()
        self.ticked = threading.Condition()
        self.thread = threading.Thread(target=self._run, name="test-worker", daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            _one(self.engine)
            with self.ticked:
                self.sent += 1
                self.ticked.notify_all()

    def ticks(self, n: int) -> None:
        """Wait until the worker has sent `n` more statements."""
        with self.ticked:
            until = self.sent + n
            assert self.ticked.wait_for(lambda: self.sent >= until, timeout=30)


@pytest.fixture
def worker(migrated: Engine) -> Iterator[_Worker]:
    running = _Worker(migrated)
    running.thread.start()
    try:
        yield running
    finally:
        running.stop.set()
        running.thread.join(timeout=30)


@pytest.fixture
def app_client(migrated: Engine) -> Iterator[TestClient]:
    app = FastAPI()

    @app.get("/sync")
    def in_the_threadpool() -> dict[str, Any]:  # FastAPI runs a sync route in a worker thread
        _one(migrated)
        return {}

    @app.get("/handed")
    async def handed_to_threads() -> dict[str, Any]:
        await run_in_threadpool(_one, migrated)
        await anyio.to_thread.run_sync(_one, migrated)
        return {}

    with TestClient(app) as client:
        yield client


def test_a_call_counts_its_request_in_every_thread_it_uses_and_no_worker_tick(
    migrated: Engine, app_client: TestClient, worker: _Worker
) -> None:
    def call() -> None:
        worker.ticks(3)  # the worker sends while the call is counted
        _one(migrated)  # in the test's own thread
        assert app_client.get("/sync").status_code == 200
        assert app_client.get("/handed").status_code == 200
        worker.ticks(3)

    one = count_statements(migrated, lambda: _one(migrated))  # with what a connection adds
    assert one >= 1
    assert count_statements(migrated, call) == (1 + 1 + 2) * one


def test_a_request_of_the_app_counts_its_route_and_its_authentication(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """Not zero: a context that no longer reached the app's request would count nothing, and
    every "the same for more rows" test would pass whatever the route sends."""
    owner = flow.human(make_client, migrated)

    def read() -> None:
        assert owner.get("/me/notifications").status_code == 200

    read()  # the session's first read does one-time work
    route = count_statements(migrated, read, async_engines=False)
    assert route > 0
    assert count_statements(migrated, read) > route  # and the authentication on the async engine
