"""The notifications answer under load (docs/api.md §18.2, §18.3): a held long-poll derives
again only when something it reads moved, full answers run a few at a time, and two
marks of the same items at once never fail on the key."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any

import anyio
import pytest
from sqlalchemy import Engine, insert

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.config import ConfigError, Settings
from maity_hub.db import make_engine
from maity_hub.notifications import listing
from maity_hub.routes import notifications as routes
from tests import flow
from tests.conftest import ClientFactory
from tests.test_notifications import N, bell


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity")
    return human


@pytest.fixture
def answers(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """When each full answer started."""
    started: list[float] = []
    real = routes._answer

    def counted(*args: Any, **kwargs: Any) -> Any:
        started.append(time.monotonic())
        return real(*args, **kwargs)

    monkeypatch.setattr(routes, "_answer", counted)
    return started


def card_item(make_client: ClientFactory, owner: flow.Human) -> dict[str, Any]:
    """One unread card item of the owner's: an agent claims the owner's card."""
    agent = flow.agent(make_client, owner)
    card = owner.post("/projects/maity/tasks", {"title": "Mine"}).json()
    assert agent.post(f"/projects/maity/tasks/{card['id']}/claim", {}).status_code == 200
    [item] = [i for i in bell(owner)["items"] if i["kind"] == "card" and not i["read"]]
    return dict(item)


def test_a_held_long_poll_derives_again_only_when_something_moved(
    make_client: ClientFactory, owner: flow.Human, answers: list[float]
) -> None:
    item = card_item(make_client, owner)
    start = bell(owner, limit=0)["next_after"]
    answers.clear()
    quiet = bell(owner, after=start, wait=2)
    assert quiet["items"] == []
    assert len(answers) == 2  # the first look and the last, none in between

    answers.clear()
    held: list[dict[str, Any]] = []
    waiter = threading.Thread(target=lambda: held.append(bell(owner, after=start, wait=3)))
    waiter.start()
    time.sleep(0.8)
    assert owner.post(f"{N}/read", {"ids": [item["id"]]}).status_code == 200
    waiter.join(timeout=10)
    assert held and held[0]["items"] == []
    assert len(answers) == 3  # a read mark is movement: one more answer, then the last


def test_the_stamp_moves_with_events_and_read_marks(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    def stamp() -> tuple[Any, ...]:
        with migrated.connect() as conn:
            return listing.stamp(conn, owner.id)

    item = card_item(make_client, owner)
    before = stamp()
    assert stamp() == before  # nothing moved, nothing differs
    owner.post(f"{N}/read", {"ids": [item["id"]]})
    marked = stamp()
    assert marked != before
    owner.post("/projects/maity/tasks", {"title": "Another"})
    assert stamp() != marked


def test_two_marks_of_the_same_item_at_once_both_succeed(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """The second waits for the first's row and skips it, where it failed on the key.
    SQLite serialises every writer anyway, so this runs on PostgreSQL and MariaDB; the
    first transaction is released before the worker is joined."""
    if migrated.dialect.name == "sqlite":
        pytest.skip("SQLite serialises writers; the race is the server databases'")
    item = card_item(make_client, owner)
    first = migrated.connect()
    started, answered = threading.Event(), threading.Event()

    def mark() -> int:
        started.set()
        status = int(owner.post(f"{N}/read", {"ids": [item["id"]]}).status_code)
        answered.set()
        return status

    pool = ThreadPoolExecutor(max_workers=1)
    first_tx = first.begin()
    try:
        first.execute(
            insert(t.notification_read).values(human_id=owner.id, seq=item["seq"], at=clock.now())
        )
        waiting = pool.submit(mark)
        assert started.wait(timeout=10)
        assert not answered.wait(timeout=1.0)  # waits for the first's row
        first_tx.commit()
        assert waiting.result(timeout=20) == 200
    finally:
        if first_tx.is_active:
            first_tx.rollback()
        first.close()
        pool.shutdown(wait=True, cancel_futures=True)
    assert [i["read"] for i in bell(owner)["items"] if i["id"] == item["id"]] == [True]


def test_marking_what_is_read_already_is_a_no_op(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    item = card_item(make_client, owner)
    for _ in range(2):
        assert owner.post(f"{N}/read", {"ids": [item["id"]]}).status_code == 200


def test_full_answers_run_a_few_at_a_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """Six at once, two at a time: the app's semaphore, made at first use (SQLite takes
    its write lock at BEGIN, so overlapping answers show on the semaphore, not the API)."""
    monkeypatch.setattr(routes, "AT_ONCE", 2)
    request: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))
    running, most = [0], [0]
    lock = threading.Lock()

    def work() -> int:
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        time.sleep(0.1)
        with lock:
            running[0] -= 1
        return 1

    async def main() -> list[int]:
        found: list[int] = []

        async def one() -> None:
            found.append(await routes._limited(request, work))

        async with anyio.create_task_group() as group:
            for _ in range(6):
                group.start_soon(one)
        return found

    assert anyio.run(main) == [1] * 6
    assert most[0] == 2
    assert routes._limit(request) is request.app.state.notifications_at_once  # one per app


def test_the_pool_size_comes_from_the_environment() -> None:
    base = {"MAITY_DATABASE_URL": "sqlite://"}
    found = Settings.from_env({**base, "MAITY_DB_POOL_SIZE": "8", "MAITY_DB_MAX_OVERFLOW": "0"})
    assert (found.db_pool_size, found.db_max_overflow) == (8, 0)
    default = Settings.from_env(base)
    assert (default.db_pool_size, default.db_max_overflow) == (5, 10)  # SQLAlchemy's
    with pytest.raises(ConfigError):
        Settings.from_env({**base, "MAITY_DB_POOL_SIZE": "0"})
    engine = make_engine("postgresql+psycopg://hub@db.invalid/maity", 8, 2)
    assert engine.pool.size() == 8  # type: ignore[attr-defined]
    engine.dispose()
