"""Timing of the project overview (docs/api.md §6.11, tsk-ybc2ma72dzvq item 3), for the pull
request's numbers before and after (`pytest -m load -s tests/test_load_overview.py`).

On a seeded hub (`MAITY_LOAD_UNIT` cards with a report of about a kilobyte, as many open,
answered and withdrawn requests across priorities and `to` kinds, one in a hundred held,
covered, from a jour fixe round or a bridge consent) it prints, per caller (the owner, a
plain agent, a proxy) and `limit` (10, 50), the statements one call sends, the peak of
Python memory it allocates, and the p50 and p95 of `ROUNDS` calls; then it seeds twice as
much again and prints the same at three times the seed. It runs on a hub without the change
too: it sets nothing the older hub does not know. The checks are what holds on both: every
read answers 200 with the reports in their order and the request counts the listing gives,
and one call sends at most `STATEMENTS_MAX` statements, whatever the seed. The times and the
memory are printed, not checked, since on a shared machine they are noise."""

from __future__ import annotations

import os
import statistics
import time
import tracemalloc
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_overview import (
    jour_fixe_rounds,
    listed_counts,
    person,
    report_order,
    seed_reports,
    seed_requests,
)

pytestmark = pytest.mark.load

UNIT = int(os.environ.get("MAITY_LOAD_UNIT", "1000"))
ROUNDS = int(os.environ.get("MAITY_LOAD_ROUNDS", "20"))
GROWTH = 3  # the second measurement holds this many times the seed
PROJECT = "/projects/maintainer/maity"
# Per overview, whatever UNIT is: 18 for the owner, 23 for an agent, 25 to 26 for a proxy on
# SQLite at 1000 and 3000 (16, 21 and 23 to 24 before the reads went keys first and grouped).
STATEMENTS_MAX = 30


def _statements(engine: Engine, call: Callable[[], Any]) -> int:
    from tests.statements import listening

    sent: list[str] = []
    with listening(engine, lambda *a: sent.append(a[2])):
        response = call()
    assert response.status_code == 200, response.text
    return len(sent)


def _peak_kib(call: Callable[[], Any]) -> int:
    tracemalloc.start()
    try:
        response = call()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert response.status_code == 200, response.text
    return peak // 1024


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


def test_overview_timing(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    proxy = flow.agent(make_client, owner, role="proxy")
    with migrated.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    callers: dict[str, Any] = {"owner": owner, "agent": agent, "proxy": proxy}
    people = {name: person(migrated, who.id) for name, who in callers.items()}
    template = agent.post(
        f"{PROJECT}/requests", {"class": "decision", "title": "Which?", "to": "owner"}
    )
    assert template.status_code == 201, template.text
    rounds = jour_fixe_rounds(migrated, project_id)

    def grow(count: int, first: int) -> None:
        seed_reports(migrated, project_id, people["owner"].membership, agent.id, count, first)
        seed_requests(
            migrated,
            template.json()["id"],
            list(people.values()),
            rounds,
            count,
            first,
            every=100,
        )

    over_budget: list[Any] = []
    for size in (1, GROWTH):
        grown = 0 if size == 1 else UNIT
        grow(UNIT * size - grown, grown)
        order = report_order(migrated, project_id)
        assert len(order) == UNIT * size
        shown: dict[str, Any] = {
            "engine": migrated.dialect.name,
            "cards_and_requests": UNIT * size,
            "rounds": ROUNDS,
        }
        for name, who in callers.items():
            expected = listed_counts(migrated, people[name])
            for limit in (10, 50):
                path = f"{PROJECT}/overview?limit={limit}"
                body = who.get(path).json()
                assert [r["task"]["id"] for r in body["reports"]] == order[:limit], (name, limit)
                assert body["requests"] == expected, (name, limit)

                def call(who: Any = who, path: str = path) -> Any:
                    return who.get(path)

                read: dict[str, Any] = {
                    "statements": _statements(migrated, call),
                    "peak_kib": _peak_kib(call),
                    "p50_p95_ms": _quantiles(_timed(call, ROUNDS)),
                }
                shown[f"{name}_{limit}"] = read
                if read["statements"] > STATEMENTS_MAX:
                    over_budget.append((size, name, limit, read["statements"]))
        print(f"\nLOAD overview at {size}x: {shown}")
    # One overview sends the same statements whatever the seed: the bound leaves headroom.
    assert not over_budget, f"STATEMENTS_MAX {STATEMENTS_MAX} exceeded: {over_budget}"
