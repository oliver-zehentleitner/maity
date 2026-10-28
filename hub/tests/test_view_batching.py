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
    _closed_releases(engine, project_id, owner, n // 3)


_RELEASES = [0]


def _closed_releases(engine: Engine, project_id: str, owner: int, n: int) -> None:
    """n closed releases with their frozen record, every second one with a tag observed."""
    now = clock.now()
    for _ in range(n):
        _RELEASES[0] += 1
        version = f"0.{_RELEASES[0]}.0"
        frozen = {"pull_requests": [], "groups": [], "readiness": {"ready": True, "blocking": []}}
        factory.card(
            engine,
            project_id,
            owner,
            kind="release",
            status="done",
            closed_at=now,
            release_version=version,
            release_data={"version": version, "checklist": [], "frozen": frozen},
        )
        if _RELEASES[0] % 2:
            with engine.begin() as conn:
                conn.execute(
                    insert(t.forge_observation).values(
                        project_id=project_id,
                        kind="tag",
                        ref=f"v{version}",
                        observed_at=now,
                        data={"name": f"v{version}", "sha": "a" * 40, "found": True},
                    )
                )


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
    calls: dict[str, Callable[[], Any]] = {
        "tasks": lambda: owner.get("/projects/maintainer/maity/tasks?status=all&limit=200"),
        "events": lambda: owner.get("/projects/maintainer/maity/events?after=0&limit=200"),
        "members": lambda: owner.get("/projects/maintainer/maity/members"),
        # The packet: claims, events and every peer (§5.2).
        "resume": lambda: resumer.post(
            "/api/v1/me/resume", json={"client": "test", "cursor": 0}, headers=bearer
        ),
    }
    # One open release, the same in both measurements: its readiness is computed live.
    factory.card(
        migrated,
        project_id,
        owner_membership,
        kind="release",
        status="open",
        release_version="1.0.0",
        release_in_flight=True,
        release_data={"version": "1.0.0", "checklist": [], "pull_requests_typed": []},
    )
    # The first resume stores the agent's silent availability baseline. Compare
    # two initialized sessions so that one-time write is not mistaken for row cost.
    warmup = calls["resume"]()
    assert warmup.status_code == 200, warmup.text
    _grow(migrated, project_id, owner_membership, agents, 3)
    small = {name: _statements(migrated, call) for name, call in calls.items()}
    _grow(migrated, project_id, owner_membership, agents, 27)
    large = {name: _statements(migrated, call) for name, call in calls.items()}
    items = calls["tasks"]().json()["items"]
    assert len(items) == 30 + 10 + 1  # cards, closed releases, the open one
    tagged = [i for i in items if i["kind"] == "release" and i["release"]["tag"] is not None]
    assert tagged  # the tag observations were read, in the batch
    assert large == small
