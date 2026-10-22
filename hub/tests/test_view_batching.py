"""A page of cards, events or members costs the same statements for 3 rows as
for 30: the views are built in batches, never with a lookup per row."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import Engine, event, insert, select

from maity_hub import clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory


def _statements(engine: Engine, call: Callable[[], Any]) -> int:
    seen = [0]

    def count(*_args: Any) -> None:
        seen[0] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        response = call()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert response.status_code == 200, response.text
    return seen[0]


def _grow(engine: Engine, project_id: str, owner: int, agents: list[factory.Agent], n: int) -> None:
    """n more cards with claims, assignments and edges, n events, n // 3 agents."""
    agents += [factory.agent(engine, project_id, agents[0].owner_id) for _ in range(n // 3)]
    now = clock.now()
    previous = None
    for i in range(n):
        holder = agents[i % len(agents)]
        card = factory.card(
            engine,
            project_id,
            agents[(i + 1) % len(agents)].membership_id,
            status="claimed",
            assigned_to=owner,
            claim_holder=holder.membership_id,
            claim_session_id=holder.session_id,
            claim_since=now,
            lease_until=now + timedelta(hours=1),
        )
        with engine.begin() as conn:
            if previous:
                conn.execute(
                    insert(t.card_edge).values(from_card=card, to_card=previous, kind="depends_on")
                )
            conn.execute(
                insert(t.event).values(
                    project_id=project_id,
                    kind="task_updated",
                    at=now,
                    actor_membership=holder.membership_id,
                    subject_type="task",
                    subject_id=card,
                    audience=["all"],
                    payload={"task": card},
                    redacted=False,
                )
            )
        previous = card


def test_lists_cost_the_same_for_3_rows_and_for_30(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
        owner_membership = conn.execute(
            select(t.membership.c.id).where(t.membership.c.project_id == project_id)
        ).scalar_one()
    agents = [factory.agent(migrated, project_id, owner.id)]
    resumer = make_client()
    bearer = {"Authorization": f"Bearer {agents[0].value}"}
    calls = {
        "tasks": lambda: owner.get("/projects/maity/tasks?status=all&limit=200"),
        "events": lambda: owner.get("/projects/maity/events?after=0&limit=200"),
        "members": lambda: owner.get("/projects/maity/members"),
        # The packet: claims, events and every peer (§5.2).
        "resume": lambda: resumer.post(
            "/api/v1/me/resume", json={"client": "test", "cursor": 0}, headers=bearer
        ),
    }
    _grow(migrated, project_id, owner_membership, agents, 3)
    small = {name: _statements(migrated, call) for name, call in calls.items()}
    _grow(migrated, project_id, owner_membership, agents, 27)
    large = {name: _statements(migrated, call) for name, call in calls.items()}
    assert len(calls["tasks"]().json()["items"]) == 30
    assert large == small
