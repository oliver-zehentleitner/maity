"""Timing of the card list and the card search (docs/api.md §6.4, tsk-ybc2ma72dzvq item 2),
for the pull request's numbers before and after
(`pytest -m load -s tests/test_load_card_paging.py`).

On a seeded hub (`CARDS` cards with a body of about a kilobyte, two notes each) it prints,
per read, the statements one call sends, the peak of Python memory it allocates, and the
p50 and p95 of `ROUNDS` calls: the first page of the default list and of the open column,
the second page of the open column, `order=updated`, a search that finds one card and a
search that finds every card. It runs on a hub without the change too: it sets nothing the
older hub does not know. The checks are what holds on both: every read answers 200 with
the page it asked for, and a read without a search sends at most `STATEMENTS_MAX`
statements, whatever the card count. The times and the memory are printed, not checked,
since on a shared machine they are noise."""

from __future__ import annotations

import os
import statistics
import time
import tracemalloc
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.ids import new_id
from tests import factory, flow
from tests.conftest import ClientFactory

pytestmark = pytest.mark.load

CARDS = int(os.environ.get("MAITY_LOAD_UNIT", "1000"))
ROUNDS = int(os.environ.get("MAITY_LOAD_ROUNDS", "20"))
PROJECT = "/projects/maintainer/maity"
BODY = "Steps, acceptance and pointers for this card. " * 22  # about a kilobyte
STATEMENTS_MAX = 25  # per page of a read without a search, whatever CARDS is


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


def _seed(engine: Engine, owner: flow.Human) -> None:
    with engine.connect() as conn:
        project_id: str = conn.execute(select(t.project.c.id)).scalar_one()
        author: int = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == owner.id)
        ).scalar_one()
    statuses = ("open", "open", "in_progress", "review", "done")
    ids = [
        factory.card(
            engine,
            project_id,
            author,
            title=f"Card {n}" + (" needle" if n == CARDS // 2 else ""),
            body=BODY,
            status=statuses[n % len(statuses)],
            closed_at=clock.now() if statuses[n % len(statuses)] == "done" else None,
        )
        for n in range(CARDS)
    ]
    now = clock.now()
    with engine.begin() as conn:
        conn.execute(
            insert(t.card_note),
            [
                {
                    "id": new_id("note"),
                    "card_id": card_id,
                    "author": author,
                    "author_kind": "human",
                    "body": f"Remark {k} on this card: " + "a plain remark. " * 30,
                    "state": "open",
                    "created_at": now,
                    "redacted": False,
                }
                for card_id in ids
                for k in range(2)
            ],
        )


def test_card_list_and_search_timing(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    _seed(migrated, owner)
    first_open = owner.get(f"{PROJECT}/tasks?status=open&limit=200").json()
    assert len(first_open["items"]) == min(200, 2 * CARDS // 5)
    reads: dict[str, Callable[[], Any]] = {
        "list_all_50": lambda: owner.get(f"{PROJECT}/tasks?limit=50"),
        "open_200": lambda: owner.get(f"{PROJECT}/tasks?status=open&limit=200"),
        "open_200_page_2": lambda: owner.get(
            f"{PROJECT}/tasks",
            params={"status": "open", "limit": 200, "cursor": first_open["next_cursor"]},
        ),
        "updated_50": lambda: owner.get(f"{PROJECT}/tasks?order=updated&limit=50"),
        "search_one_hit": lambda: owner.get(f"{PROJECT}/tasks?q=needle&status=all"),
        "search_every_card_50": lambda: owner.get(f"{PROJECT}/tasks?q=remark&limit=50"),
    }
    found = owner.get(f"{PROJECT}/tasks?q=needle&status=all").json()["items"]
    assert [c["title"] for c in found] == [f"Card {CARDS // 2} needle"]
    assert len(owner.get(f"{PROJECT}/tasks?q=remark&limit=50").json()["items"]) == 50
    shown: dict[str, Any] = {"engine": migrated.dialect.name, "cards": CARDS, "rounds": ROUNDS}
    for name, call in reads.items():
        shown[name] = {
            "statements": _statements(migrated, call),
            "peak_kib": _peak_kib(call),
            "p50_p95_ms": _quantiles(_timed(call, ROUNDS)),
        }
    print(f"\nLOAD card list and search: {shown}")
    # A read without a search sends the same statements per page whatever the card count
    # (21 on SQLite and 19 on PostgreSQL at 1000 and 3000 cards): the bound leaves headroom.
    for name in ("list_all_50", "open_200", "open_200_page_2", "updated_50"):
        assert shown[name]["statements"] <= STATEMENTS_MAX, (name, shown[name])
