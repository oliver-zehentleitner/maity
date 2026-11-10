"""The event loop stays on time under concurrent requests (tsk-v874y63b4z8p, the loop-lag guard).

The async routes run their database work on the event loop (`AsyncConnection.run_sync`), so a
slow body there delays every other request and every held long-poll's wake. This test sends
concurrent requests of the hot families to one hub and fails when the loop's own tick
(`request_stats.watch_load`, the `loop_late_*` of the `stats` line) ran later than the limit.
It also prints the window's fields, the numbers each PR of the series names before and after.

A `load` test: PostgreSQL in CI's `hub-load` job (`pytest -m load`), not the ordinary suite."""

from __future__ import annotations

import os
import threading
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import request_stats
from tests import flow
from tests.conftest import ClientFactory
from tests.test_notifications import bell
from tests.test_notifications_load import inbox_item, owner  # noqa: F401

pytestmark = pytest.mark.load

# The loop's tick may run this much later than due, at most, while the requests run. The tick
# looks every 0.1 s; a late tick is the loop busy (or the GIL held) for that long, and every
# other request on it waited as much. Agreed in PR 1 from runs on main and the branch (the PR's
# body); a PR that moves a family onto the loop must stay under it.
LOOP_LATE_LIMIT_MS = int(os.environ.get("MAITY_LOOP_LATE_LIMIT_MS", "250"))
THREADS = 16
ROUNDS = int(os.environ.get("MAITY_LOOP_ROUNDS", "20"))


def fields(text: str) -> dict[str, float]:
    return {k: float(v) for k, v in (pair.split("=") for pair in text.split())}


def test_the_event_loop_stays_on_time_under_concurrent_requests(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine  # noqa: F811
) -> None:
    inbox_item(make_client, owner)
    paths = [
        "/projects/maintainer/maity",
        "/projects/maintainer/maity/members",
        "/projects/maintainer/maity/tasks",
        "/projects/maintainer/maity/requests",
    ]
    failures: list[Any] = []

    def calls() -> None:
        try:
            for _ in range(ROUNDS):
                bell(owner, limit=20)
                for path in paths:
                    answer = owner.get(path)
                    if answer.status_code != 200:
                        failures.append((path, answer.status_code))
        except Exception as error:  # a thread's failure must fail the test
            failures.append(error)

    request_stats.LOAD.fields()  # the window starts here
    callers = [threading.Thread(target=calls) for _ in range(THREADS)]
    for caller in callers:
        caller.start()
    for caller in callers:
        caller.join(timeout=600)
    seen = fields(request_stats.LOAD.fields())
    print(f"\nloop-lag guard ({THREADS} threads × {ROUNDS} rounds): {seen}")
    assert failures == []
    assert seen["loop_late_max_ms"] <= LOOP_LATE_LIMIT_MS, seen
