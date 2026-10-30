"""Load that grows: the notifications' cost does not rise with the history behind a human, nor
with the number of dashboards they hold open (docs/api.md §18.2, tsk-ryas52q9k53z).

The tests seed a human's bell with many unread requests spread over the notification
window, ask the same thing of a small and of a four times larger history, and fail when the
statements a call sends grow (exact, the same on every machine) or its time grows by more
than a wide factor (soft: a CI runner is noisy). They run on PostgreSQL in the `hub-load` job
and with `pytest -m load`, not in the ordinary suite. `MAITY_LOAD_UNIT` is the number of
unread requests of the small history (1000 by default, as in CI's job)."""

from __future__ import annotations

import os
import statistics
import threading
import time
from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.statements import count_statements
from tests.test_notifications import N, bell
from tests.test_notifications_load import inbox_item, owner  # noqa: F401

pytestmark = pytest.mark.load

UNIT = int(os.environ.get("MAITY_LOAD_UNIT", "1000"))
GROWTH = 4  # the large history is this many times the small one
WINDOW_DAYS = 30  # the notifications' window (notifications/items.py)
REPEATS = 5
# The time may grow by this much between the histories before it fails: the statements
# are the exact check, the clock only catches a statement that got slow without a new one.
TIME_FACTOR = 2.0
TIME_FLOOR = 0.1  # seconds; below this a difference is noise, not growth


def seed(engine: Engine, template: dict[str, Any], count: int, first: int) -> None:
    """`count` more unread requests to the owner, each a copy of a real one (its request
    row and its `request_created` event), spread over the window, oldest first."""
    now = clock.now()
    with engine.begin() as conn:
        request = conn.execute(select(t.request).where(t.request.c.id == template["request"])).one()
        event = conn.execute(
            select(t.event).where(
                t.event.c.kind == "request_created", t.event.c.subject_id == template["request"]
            )
        ).one()
        requests, events = [], []
        for n in range(first, first + count):
            at = now - timedelta(days=WINDOW_DAYS - 1) * (1 - n / (first + count))
            request_id = f"req-load{n:07d}"
            row = {**request._mapping, "id": request_id, "created_at": at}
            payload = {**event.payload, "id": request_id, "created_at": clock.rfc3339(at)}
            values = {k: v for k, v in event._mapping.items() if k != "seq"}
            requests.append(row)
            events.append({**values, "subject_id": request_id, "at": at, "payload": payload})
        conn.execute(insert(t.request), requests)
        conn.execute(insert(t.event), events)


def median_seconds(call: Callable[[], Any]) -> float:
    took = []
    for _ in range(REPEATS):
        began = time.perf_counter()
        call()
        took.append(time.perf_counter() - began)
    return statistics.median(took)


def not_slower(small: float, large: float, what: str) -> None:
    assert large <= max(
        small * TIME_FACTOR, small + TIME_FLOOR
    ), f"{what}: {large:.3f}s with {GROWTH}x the history, {small:.3f}s with 1x"


@pytest.fixture
def histories(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine  # noqa: F811
) -> Callable[[], None]:
    """A bell with `UNIT` unread requests; calling the result grows it to `GROWTH` times."""
    inbox_item(make_client, owner)
    template = {"request": _request_of(migrated)}
    # Joining never replays history (§18.2): the human joined before the window began, so
    # that every seeded event is news to them.
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.human_id == owner.id)
            .values(joined_at=clock.now() - timedelta(days=WINDOW_DAYS + 1))
        )
    seed(migrated, template, UNIT - 1, 1)

    def grow() -> None:
        seed(migrated, template, UNIT * (GROWTH - 1), UNIT)

    return grow


def _request_of(engine: Engine) -> str:
    with engine.connect() as conn:
        return str(conn.execute(select(t.request.c.id)).scalar_one())


def test_a_page_of_the_bell_sends_the_same_statements_whatever_the_history(
    owner: flow.Human, migrated: Engine, histories: Callable[[], None]  # noqa: F811
) -> None:
    def page() -> None:
        assert len(bell(owner, limit=20)["items"]) == 20

    small = count_statements(migrated, page)
    histories()
    assert bell(owner, limit=0)["counts"]["inbox"] >= UNIT * GROWTH
    assert count_statements(migrated, page) == small


@pytest.mark.xfail(
    strict=True,
    reason="tsk-r8f0jm3xs9y6: the page derives every non-chat item of the window, so its "
    "time grows with the unread items (notifications/items.py `derive_page`)",
)
def test_a_page_of_the_bell_takes_the_same_time_whatever_the_history(
    owner: flow.Human, histories: Callable[[], None]  # noqa: F811
) -> None:
    def page() -> None:
        bell(owner, limit=20)

    small = median_seconds(page)
    histories()
    not_slower(small, median_seconds(page), "a page of the bell")


def test_marking_a_page_costs_the_same_whatever_the_history(
    owner: flow.Human, migrated: Engine, histories: Callable[[], None]  # noqa: F811
) -> None:
    def mark() -> None:
        ids = [i["id"] for i in bell(owner, limit=20, unread=True)["items"]]
        assert owner.post(f"{N}/read", {"ids": ids}).status_code == 200

    small_statements = count_statements(migrated, mark)
    histories()
    assert count_statements(migrated, mark) == small_statements


def held_statements(engine: Engine, humans: list[flow.Human], seconds: int) -> float:
    """The statements one held long-poll costs while nothing happens, over `seconds`:
    every human holds one, together."""
    starts = [bell(h, limit=0)["next_after"] for h in humans]

    def hold() -> None:
        pollers = [
            threading.Thread(target=lambda h=h, s=s: bell(h, after=s, wait=seconds))
            for h, s in zip(humans, starts, strict=True)
        ]
        for poller in pollers:
            poller.start()
        for poller in pollers:
            poller.join(timeout=seconds + 15)

    return count_statements(engine, hold) / len(humans)


def test_a_held_long_poll_costs_the_same_whatever_the_history_and_the_tabs(
    make_client: ClientFactory,
    owner: flow.Human,  # noqa: F811
    migrated: Engine,
    histories: Callable[[], None],
) -> None:
    def tabs(n: int) -> list[flow.Human]:
        humans = [owner]
        for k in range(n - 1):
            client = make_client(peer=f"198.51.100.{10 + k}")
            client.post(
                "/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD}
            )
            csrf = client.get("/api/v1/auth/session").json()["csrf_token"]
            humans.append(flow.Human(client, csrf, owner.id))
        return humans

    few, many = tabs(1), tabs(8)
    seconds = 3
    one_tab = held_statements(migrated, few, seconds)
    eight_tabs = held_statements(migrated, many, seconds)
    histories()
    one_tab_large = held_statements(migrated, few, seconds)
    # A held poll looks every half second, so a run's count moves by a look or two; growth
    # is a count that rises with the history or with the tabs, not those few.
    slack = 1.35
    assert one_tab_large <= one_tab * slack + 2, "a held poll costs more with more history"
    assert eight_tabs <= one_tab * slack + 2, "a held poll costs more with more tabs"
