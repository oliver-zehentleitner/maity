"""A transaction that only reads takes no write lock on SQLite (hub/context/persistence.md,
`db.read_transaction`): it neither waits for the one writer nor holds it up, and it cannot
write. The server engines lock no row for a read; there the helper is `engine.begin()`."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.exc import OperationalError

from maity_hub import tables as t
from maity_hub import views
from maity_hub.db import read_transaction
from maity_hub.routes import tasks as task_routes
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import task

# The busy timeout is five seconds (db.py): a transaction that waited for the lock takes
# at least that long, one that did not takes a small part of it.
QUICK = 1.5


@pytest.fixture
def sqlite(migrated: Engine) -> Engine:
    if migrated.dialect.name != "sqlite":
        pytest.skip("SQLite only: the server engines take no lock for a read")
    return migrated


@pytest.fixture
def owner(make_client: ClientFactory, sqlite: Engine) -> flow.Human:
    human = flow.human(make_client, sqlite)
    flow.project(human)
    return human


def _write(engine: Engine, card_id: str, title: str) -> float:
    """The seconds one write of a card's title takes, its commit included."""
    started = time.monotonic()
    with engine.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card_id).values(title=title))
    return time.monotonic() - started


def test_a_read_transaction_does_not_wait_for_the_writer(sqlite: Engine) -> None:
    with sqlite.begin() as writer:  # BEGIN IMMEDIATE: holds the write lock
        writer.execute(update(t.project).values(name="held"))
        started = time.monotonic()
        with read_transaction(sqlite) as reader:
            # The snapshot before the writer's change: nothing of it is committed yet.
            names = reader.execute(select(t.project.c.name)).scalars().all()
        assert time.monotonic() - started < QUICK
        assert "held" not in names


def test_a_writer_does_not_wait_for_a_read_transaction(sqlite: Engine) -> None:
    with read_transaction(sqlite) as reader:
        reader.execute(select(t.project.c.id)).all()
        started = time.monotonic()
        with sqlite.begin() as writer:
            writer.execute(update(t.project).values(name="written"))
        assert time.monotonic() - started < QUICK


def test_a_read_transaction_cannot_write(sqlite: Engine) -> None:
    with pytest.raises(OperationalError, match="readonly"), read_transaction(sqlite) as reader:
        reader.execute(update(t.project).values(name="never"))


def test_the_connection_writes_again_after_a_read_transaction(sqlite: Engine) -> None:
    """`query_only` belongs to the pooled connection: the next transaction on it that is
    not a read writes as before."""
    with read_transaction(sqlite) as reader:
        reader.execute(select(t.project.c.id)).all()
    with sqlite.begin() as writer:
        writer.execute(update(t.project).values(name="written"))


def test_a_slow_card_list_does_not_hold_up_a_write(
    owner: flow.Human, sqlite: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET …/tasks reads in a read transaction: while it builds its answer, a write of the
    same project commits at once instead of waiting for the read to end."""
    card = task(owner)
    inside, release = threading.Event(), threading.Event()
    shown = views.task_views

    def slow_views(*args: Any, **kwargs: Any) -> Any:
        inside.set()
        release.wait(10)
        return shown(*args, **kwargs)

    monkeypatch.setattr(task_routes, "task_views", slow_views)
    answers: list[int] = []
    reading = threading.Thread(
        target=lambda: answers.append(owner.get("/projects/maintainer/maity/tasks").status_code)
    )
    reading.start()
    try:
        assert inside.wait(10), "the list never reached its views"
        took = _write(sqlite, card["id"], "written while the list is read")
    finally:
        release.set()
        reading.join(15)
    assert answers == [200]
    assert took < QUICK, f"the write waited {took:.2f} s for the read"


@pytest.mark.parametrize(
    "path",
    [
        "/projects/maintainer/maity/tasks",
        "/projects/maintainer/maity/tasks/{card}",
        "/projects/maintainer/maity/tasks/{card}/history",
        "/projects/maintainer/maity/tasks/{card}/notes",
        "/projects/maintainer/maity/overview",
        "/projects/maintainer/maity/swarm",
        "/projects/maintainer/maity/requests?to=all&status=all",
        "/requests?to=all&status=all",
    ],
)
def test_the_read_routes_answer_under_query_only(owner: flow.Human, path: str) -> None:
    """Each route moved to a read transaction answers as before: none of them writes in it
    (a write there would fail with `readonly`)."""
    card = task(owner)
    owner.post(f"/projects/maintainer/maity/tasks/{card['id']}/notes", {"body": "a note"})
    response = owner.get(path.format(card=card["id"]))
    assert response.status_code == 200, response.text
