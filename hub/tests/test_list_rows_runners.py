"""The runners' and placements' lists cost the same statements for 3 rows as for 30
(tests/list_rows.py): the owner's runners and enrollments, a project's runners and placements,
a placement's reports, and what a runner reads (its placements, its events)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.routes import runners as runners_routes
from tests import flow
from tests.conftest import ClientFactory
from tests.list_rows import flat_rows, same_for_3_and_30
from tests.test_auth_agent import signed
from tests.test_placements import REPOSITORY, Setup, allow_instances, placed, report
from tests.test_runner_stream import attach, factory_project_id, hello
from tests.test_runners import Runner, call, enroll, exchange, paired

P = "/projects/maintainer/maity"


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> Setup:
    """A project with a runner that said hello, and an agent that may run 70 instances at once,
    in a project that holds as many placements."""
    owner = flow.human(make_client, migrated)
    flow.project(owner, repository={"url": REPOSITORY})
    runner = paired(make_client, owner)
    assert attach(owner, runner).status_code == 201
    client = make_client()
    assert hello(client, runner).status_code == 200
    agent = flow.agent(make_client, owner, role="member")
    limits = {"max_placements": 70, "max_instances": 70}
    assert owner.patch("/admin/projects/maintainer/maity/limits", limits).status_code == 200
    allow_instances(migrated, agent.id, 70)
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(max_placements=70))
    return Setup(owner, runner, client, agent, migrated)


def _placing(s: Setup) -> Callable[[int], None]:
    def grow(n: int) -> None:
        for _ in range(n):
            placed(s)

    return grow


@flat_rows("/projects/{}/{}/placements")
def test_a_project_s_placements_cost_the_same_for_3_and_for_30(setup: Setup) -> None:
    same_for_3_and_30(
        setup.engine,
        "/projects/{}/{}/placements",
        lambda: setup.owner.get(f"{P}/placements"),
        _placing(setup),
    )


@flat_rows("/runners/{}/placements")
def test_a_runner_s_placements_cost_its_owner_the_same_for_3_and_for_30(setup: Setup) -> None:
    same_for_3_and_30(
        setup.engine,
        "/runners/{}/placements",
        lambda: setup.owner.get(f"/runners/{setup.runner.id}/placements"),
        _placing(setup),
    )


@flat_rows("/runner/placements")
def test_the_runner_s_own_placements_cost_the_same_for_3_and_for_30(setup: Setup) -> None:
    same_for_3_and_30(
        setup.engine,
        "/runner/placements",
        lambda: call(setup.client, setup.runner, "GET", "/api/v1/runner/placements"),
        _placing(setup),
    )


@flat_rows("/projects/{}/{}/placements/{}/reports")
def test_a_placement_s_reports_cost_the_same_for_3_and_for_30(setup: Setup) -> None:
    placement = placed(setup)
    seq = [0]

    def grow(n: int) -> None:
        for _ in range(n):
            seq[0] += 1
            sent = report(setup, placement, seq[0], restarts=seq[0])
            assert sent.status_code == 200, sent.text

    same_for_3_and_30(
        setup.engine,
        "/projects/{}/{}/placements/{}/reports",
        lambda: setup.owner.get(f"{P}/placements/{placement['id']}/reports?limit=50"),
        grow,
    )


@flat_rows("/runner/events")
def test_the_runner_s_events_cost_the_same_for_3_and_for_30(setup: Setup) -> None:
    """Events addressed to the runner, as a placement's are (§15.8), each by another actor;
    read with `wait=0`, so the call answers at once."""
    project_id = factory_project_id(setup.engine)
    path = "/api/v1/runner/events"
    query = "after=0&limit=200&wait=0"

    def grow(n: int) -> None:
        with setup.engine.begin() as conn:
            for _ in range(n):
                conn.execute(
                    insert(t.event).values(
                        project_id=project_id,
                        kind="placement_updated",
                        at=clock.now(),
                        subject_type="placement",
                        subject_id="plc-none",
                        audience=[f"runner:{setup.runner.id}"],
                        payload={"placement": "plc-none"},
                        redacted=False,
                    )
                )

    def read() -> Any:
        return setup.client.get(f"{path}?{query}", headers=signed(setup.runner, "GET", path, query))

    same_for_3_and_30(setup.engine, "/runner/events", read, grow, async_engines=True)


def _runners(make_client: ClientFactory, owner: flow.Human) -> Callable[[int], list[Any]]:
    """n more runners paired, all through one client: each client is an app with pools of its
    own, and 66 of them run PostgreSQL out of connections."""
    client = make_client()
    made = [0]

    def pair(n: int) -> list[Any]:
        runners = []
        for _ in range(n):
            made[0] += 1
            runners_routes.PAIR_BY_ADDRESS.reset()  # pairing is rate-limited per address
            response = exchange(client, enroll(owner, name=f"box-{made[0]:02d}"))
            assert response.status_code == 201, response.text
            runners.append(
                Runner(
                    response.headers["Maity-Runner-Id"],
                    response.headers["Maity-Credential-Id"],
                    response.text,
                )
            )
        return runners

    return pair


@flat_rows("/runners")
def test_the_owner_s_runners_cost_the_same_for_3_and_for_30(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    pair = _runners(make_client, owner)

    def grow(n: int) -> None:
        pair(n)

    same_for_3_and_30(migrated, "/runners", lambda: owner.get("/runners"), grow)


@flat_rows("/projects/{}/{}/runners")
def test_a_project_s_runners_cost_the_same_for_3_and_for_30(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, repository={"url": REPOSITORY})
    pair = _runners(make_client, owner)
    client: TestClient = make_client()

    def grow(n: int) -> None:
        for runner in pair(n):
            assert attach(owner, runner).status_code == 201
            assert hello(client, runner).status_code == 200

    same_for_3_and_30(migrated, "/projects/{}/{}/runners", lambda: owner.get(f"{P}/runners"), grow)


@flat_rows("/runners/enrollments")
def test_the_owner_s_enrollments_cost_the_same_for_3_and_for_30(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    made = [0]

    def grow(n: int) -> None:
        for _ in range(n):
            made[0] += 1
            enroll(owner, name=f"box-{made[0]:02d}")

    same_for_3_and_30(
        migrated,
        "/runners/enrollments",
        lambda: owner.get("/runners/enrollments?limit=200"),
        grow,
    )
