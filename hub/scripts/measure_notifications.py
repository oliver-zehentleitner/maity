"""Measure what `GET /me/notifications` derives for one human: every item of 30 days
(`items.derive`, what an answer cost before) against a page cut from `items.derive_page`.

    python scripts/measure_notifications.py [--projects 10] [--chats 3000] [--others 3000]

Run from hub/ with the dev dependencies installed. Each project gets the human as owner,
five of their agents, `--chats` messages from those agents in direct chats (one item each)
and `--others` events that make no item, spread over the 30 days. SQLite in a temporary
directory; the times are the hub's own work, the statement counts are what a database across
a network would add a round trip to.
"""

from __future__ import annotations

import argparse
import random
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tests.factory

from sqlalchemy import Engine, event, insert  # noqa: E402

from maity_hub import clock  # noqa: E402
from maity_hub import tables as t  # noqa: E402
from maity_hub.db import make_engine, migrate  # noqa: E402
from maity_hub.notifications import items, listing  # noqa: E402
from tests import factory  # noqa: E402

PAGE = 20
ROUNDS = 5


def seed(engine: Engine, projects: int, chats: int, others: int) -> str:
    rng = random.Random(1)
    human = factory.human(engine, "owner")
    now = clock.now()
    minutes = 30 * 24 * 60 - 1
    for n in range(projects):
        project_id = factory.project(engine, f"p{n}")
        mine = factory.membership(engine, project_id, "owner", human_id=human)
        with engine.begin() as conn:  # joined long ago, so that the history is the human's
            conn.execute(
                t.membership.update()
                .where(t.membership.c.id == mine)
                .values(joined_at=now - timedelta(days=90))
            )
        agents = [factory.agent(engine, project_id, human) for _ in range(5)]
        rows: list[dict[str, Any]] = []
        for _ in range(chats):
            agent = rng.choice(agents)
            rows.append(
                {
                    "project_id": project_id,
                    "kind": "message",
                    "at": now - timedelta(minutes=rng.randint(1, minutes)),
                    "actor_membership": agent.membership_id,
                    "subject_type": "conversation",
                    "subject_id": agent.agent_id,
                    "conversation_id": agent.agent_id,
                    "audience": [f"member:{human}", f"member:{agent.agent_id}"],
                    "payload": {"type": "chat", "to": human, "body": "hi", "mentions": []},
                    "redacted": False,
                }
            )
        for _ in range(others):
            rows.append(
                {
                    "project_id": project_id,
                    "kind": "task_updated",
                    "at": now - timedelta(minutes=rng.randint(1, minutes)),
                    "actor_membership": rng.choice(agents).membership_id,
                    "subject_type": "task",
                    "subject_id": "tsk-x",
                    "conversation_id": None,
                    "audience": ["all"],
                    "payload": {},
                    "redacted": False,
                }
            )
        with engine.begin() as conn:
            conn.execute(insert(t.event), rows)
    return human


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--projects", type=int, default=10)
    parser.add_argument("--chats", type=int, default=3000, help="chat messages per project")
    parser.add_argument("--others", type=int, default=3000, help="events making no item")
    args = parser.parse_args()
    engine = make_engine(f"sqlite:///{tempfile.mkdtemp()}/measure.db")
    migrate(engine)
    human = seed(engine, args.projects, args.chats, args.others)
    statements = [0]

    @event.listens_for(engine, "before_cursor_execute")
    def count(*_: Any) -> None:
        statements[0] += 1

    print(f"{args.projects} projects x {args.chats} chat items = {args.projects * args.chats}")
    with engine.connect() as conn, conn.begin():

        def answer(derive: Callable[[Any], list[items.Item]]) -> None:
            where = items.scope(conn, human, "https://hub.example")
            found = derive(where)
            listing.counts(conn, where, found)
            shared: dict[Any, Any] = {}
            for item in listing.select_items(found, kinds=None, projects=None, unread=False)[:PAGE]:
                items.view(conn, where, item, shared)

        cases: list[tuple[str, Callable[[Any], list[items.Item]]]] = [
            ("derive (before)", lambda where: items.derive(conn, where)),
            (
                "derive_page",
                lambda where: items.derive_page(
                    conn, where, count=PAGE + 1, newest_first=True, wanted=lambda item: True
                ),
            ),
        ]
        for name, derive in cases:
            times = []
            for _ in range(ROUNDS):
                statements[0] = 0
                started = time.perf_counter()
                answer(derive)
                times.append(1000 * (time.perf_counter() - started))
            median = sorted(times)[ROUNDS // 2]
            print(f"{name:22s} median {median:8.1f} ms {statements[0]:5d} statements")


if __name__ == "__main__":
    main()
