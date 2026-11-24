"""Timing of the reads per credential (docs/api.md §1.7, tsk-ybc2ma72dzvq item 7), for the
pull request's numbers before and after (`pytest -m load -s tests/test_load_read_limits.py`).

On a seeded hub (`CARDS` cards, `AGENTS` agents) it prints the statements of `GET /me` (a
dashboard session and an agent's credential) and of the card list; the p50 and p95 of
`GET /me` for a session and for an agent; and the p50 and p95 of a second credential's
`GET /me` while a first one reads `FLOOD` times without a pause (more than 2000 a minute on
any machine this runs on), with the statuses the flood got. It runs on a hub without the
limit too: it sets nothing the older hub does not know. The checks are what holds on both:
every timed read answers 200, and the statements are counted per call; the numbers are
printed, not checked, since on a shared machine they are noise."""

from __future__ import annotations

import os
import statistics
import threading
import time
from collections import Counter
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

pytestmark = pytest.mark.load

CARDS = int(os.environ.get("MAITY_LOAD_UNIT", "1000"))
AGENTS = 10
ROUNDS = int(os.environ.get("MAITY_LOAD_ROUNDS", "300"))
FLOOD = 2000
PROJECT = "/projects/maintainer/maity"


def _statements(engine: Engine, call: Callable[[], Any]) -> int:
    from tests.statements import listening

    sent: list[str] = []
    with listening(engine, lambda *a: sent.append(a[2])):
        response = call()
    assert response.status_code == 200, response.text
    return len(sent)


def _quantiles(times: list[float]) -> tuple[float, float]:
    ordered = sorted(times)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)]
    return round(statistics.median(ordered) * 1000, 2), round(p95 * 1000, 2)


def _timed(call: Callable[[], Any], rounds: int) -> list[float]:
    times = []
    for _ in range(rounds):
        began = time.perf_counter()
        response = call()
        times.append(time.perf_counter() - began)
        assert response.status_code == 200, response.text
    return times


def test_reads_per_credential_timing(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    with migrated.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
        owner_membership: int = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == owner.id)
        ).scalar_one()
    agents = [factory.agent(migrated, project_id, owner.id) for _ in range(AGENTS)]
    for n in range(CARDS):
        factory.card(migrated, project_id, owner_membership, title=f"Card {n}")
    client = make_client()

    def bearer(agent: factory.Agent, path: str) -> Callable[[], Any]:
        headers = {"Authorization": f"Bearer {agent.value}"}
        return lambda: client.get(f"/api/v1{path}", headers=headers)

    statements = {
        "me_session": _statements(migrated, lambda: owner.get("/me")),
        "me_agent": _statements(migrated, bearer(agents[0], "/me")),
        "tasks_session": _statements(migrated, lambda: owner.get(f"{PROJECT}/tasks?limit=50")),
        "tasks_agent": _statements(migrated, bearer(agents[0], f"{PROJECT}/tasks?limit=50")),
    }
    # One credential each, under the default limit: ROUNDS stays below it.
    session_times = _timed(lambda: owner.get("/me"), ROUNDS)
    agent_times = _timed(bearer(agents[1], "/me"), ROUNDS)

    flood_statuses: Counter[int] = Counter()
    raised: list[BaseException] = []
    flooding = bearer(agents[2], "/me")

    def flood() -> None:
        try:
            for _ in range(FLOOD):
                flood_statuses[flooding().status_code] += 1
        except BaseException as error:  # noqa: BLE001 - asserted in the main thread
            raised.append(error)

    flooder = threading.Thread(target=flood)
    began = time.perf_counter()
    flooder.start()
    beside: list[float] = []
    second = bearer(agents[3], "/me")
    while flooder.is_alive() and len(beside) < ROUNDS:
        beside.extend(_timed(second, 1))
    flooder.join(300)
    flood_seconds = time.perf_counter() - began
    shown: dict[str, Any] = {
        "engine": migrated.dialect.name,
        "cards": CARDS,
        "agents": AGENTS,
        "statements": statements,
        "me_session_p50_p95_ms": _quantiles(session_times),
        "me_agent_p50_p95_ms": _quantiles(agent_times),
        "flood_reads": FLOOD,
        "flood_seconds": round(flood_seconds, 1),
        "flood_per_minute": round(FLOOD / flood_seconds * 60),
        "flood_statuses": dict(flood_statuses),
        "second_credential_reads": len(beside),
        "second_credential_p50_p95_ms": _quantiles(beside) if beside else None,
    }
    print(f"\nLOAD reads per credential: {shown}")
    assert not raised, shown
    assert not flooder.is_alive(), shown
    assert beside, shown  # the second credential read beside the flood, every read 200
