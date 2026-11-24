"""Timing of a project's request list (docs/api.md §7, tsk-ybc2ma72dzvq item 4), for the pull
request's numbers before and after (`pytest -m load -s tests/test_load_request_paging.py`).

On a seeded hub (`MAITY_LOAD_UNIT` open, answered and withdrawn requests across priorities and
`to` kinds, one in a hundred held, covered, from a jour fixe round or carrying a proposal) it
prints, per sort, the statements one call sends, the peak of Python memory it allocates and the
p50 and p95 of `ROUNDS` calls: the first and the second page of the owner's `to=all` and of an
agent's `to=me`, then a walk through every page of the owner's `to=all` at `limit=200`. It runs
on a hub without the change too: it sets nothing the older hub does not know. The checks are
what holds on both: every read answers 200 with the pages the listing's own rule gives, and one
page sends at most `STATEMENTS_MAX` statements, whatever the seed. The times and the memory are
printed, not checked, since on a shared machine they are noise."""

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
from tests.test_overview import jour_fixe_rounds, listed_open, person, seed_requests

pytestmark = pytest.mark.load

UNIT = int(os.environ.get("MAITY_LOAD_UNIT", "1000"))
ROUNDS = int(os.environ.get("MAITY_LOAD_ROUNDS", "20"))
PROJECT = "/projects/maintainer/maity"
SORTS = ("priority", "date", "agent")
PAGE = 50
# Per page, whatever UNIT is; the walk at 200 sends this per page it reads.
STATEMENTS_MAX = 25


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


def _read(who: Any, params: dict[str, Any]) -> Callable[[], Any]:
    return lambda: who.get(f"{PROJECT}/requests", params=params)


class _Walk:
    """Every page of a list, one call after the other; `pages` counts the last walk's."""

    def __init__(self, who: Any, params: dict[str, Any]) -> None:
        self.who, self.params, self.pages = who, params, 0
        self.ids: list[str] = []

    def __call__(self) -> Any:
        cursor, self.pages, self.ids = None, 0, []
        while True:
            params = {**self.params, **({"cursor": cursor} if cursor else {})}
            response = self.who.get(f"{PROJECT}/requests", params=params)
            if response.status_code != 200:
                return response
            body = response.json()
            self.pages += 1
            self.ids += [item["id"] for item in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                return response


def test_request_list_timing(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    reviewer = flow.agent(make_client, owner, role="reviewer")
    proxy = flow.agent(make_client, owner, role="proxy")
    with migrated.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
    callers: dict[str, Any] = {"owner": owner, "agent": agent, "reviewer": reviewer, "proxy": proxy}
    people = {name: person(migrated, who.id) for name, who in callers.items()}
    template = agent.post(
        f"{PROJECT}/requests", {"class": "decision", "title": "Which?", "to": "owner"}
    )
    assert template.status_code == 201, template.text
    seed_requests(
        migrated,
        template.json()["id"],
        list(people.values()),
        jour_fixe_rounds(migrated, project_id),
        UNIT,
        every=100,
    )
    listed = {
        "owner_all": {r.id for r in listed_open(migrated, people["owner"], "all")},
        "agent_me": {r.id for r in listed_open(migrated, people["agent"], "me")},
    }
    assert len(listed["owner_all"]) > 2 * PAGE and len(listed["agent_me"]) > 2 * PAGE
    reads: dict[str, Callable[[], Any]] = {}
    for sort in SORTS:
        for name, who, to in (("owner_all", owner, "all"), ("agent_me", agent, "me")):
            params = {"to": to, "sort": sort, "limit": PAGE}
            first = who.get(f"{PROJECT}/requests", params=params).json()
            assert len(first["items"]) == PAGE and first["next_cursor"], (sort, name)
            second = {**params, "cursor": first["next_cursor"]}
            reads[f"{name}_{sort}_p1"] = _read(who, params)
            reads[f"{name}_{sort}_p2"] = _read(who, second)
    walk = _Walk(owner, {"to": "all", "limit": 200})
    walk()
    assert set(walk.ids) == listed["owner_all"] and len(walk.ids) == len(listed["owner_all"])
    shown: dict[str, Any] = {"engine": migrated.dialect.name, "requests": UNIT, "rounds": ROUNDS}
    over_budget = []
    for name, call in reads.items():
        sent = _statements(migrated, call)
        shown[name] = {
            "statements": sent,
            "peak_kib": _peak_kib(call),
            "p50_p95_ms": _quantiles(_timed(call, ROUNDS)),
        }
        if sent > STATEMENTS_MAX:
            over_budget.append((name, sent))
    statements = _statements(migrated, walk)
    shown["owner_all_walk_200"] = {
        "pages": walk.pages,
        "statements": statements,
        "peak_kib": _peak_kib(walk),
        "p50_p95_ms": _quantiles(_timed(walk, max(1, ROUNDS // 4))),
    }
    if statements > STATEMENTS_MAX * walk.pages:
        over_budget.append(("owner_all_walk_200", statements))
    print(f"\nLOAD request list: {shown}")
    assert not over_budget, f"STATEMENTS_MAX {STATEMENTS_MAX} exceeded: {over_budget}"
