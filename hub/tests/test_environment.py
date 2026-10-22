"""docs/api.md §5.2 and §5.3: the declared environment and the shared-environment warning."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

HOME, OTHER_HOME = "h-0123456789ab", "h-ba9876543210"
WORK, OTHER_WORK = "w-0123456789ab", "w-ba9876543210"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def resume(agent: flow.Agent, home: str | None = None, workspace: str | None = None) -> Any:
    environment = {k: v for k, v in (("home", home), ("workspace", workspace)) if v}
    response = agent.resume(environment=environment)
    assert response.status_code == 200, response.text
    return response


def detected(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.event)
                .where(t.event.c.kind == "shared_environment_detected")
                .order_by(t.event.c.seq)
            )
        )


def sharing(owner: flow.Human, agent: flow.Agent) -> Any:
    return owner.get(f"/projects/maity/members/{agent.id}").json()["shared_environment"]


@pytest.mark.parametrize(
    "environment",
    [
        {"home": "h-0123"},
        {"workspace": "x-0123456789ab"},
        {"home": "H-0123456789AB"},
        {"os": "x"},
        {"home": "xh-0123456789abq"},  # an id inside a longer string
        {"workspace": "a" * 100 + WORK + "b" * 100},
        {"home": HOME + "\n"},
    ],
)
def test_a_malformed_environment_is_invalid(
    owner: flow.Human, make_client: ClientFactory, environment: dict[str, str]
) -> None:
    agent = flow.agent(make_client, owner)
    response = agent.resume(environment=environment)
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid"


def test_two_members_in_one_workspace_are_shown_to_the_owner_and_announced_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    alone = flow.agent(make_client, owner)
    resume(a, HOME, WORK)
    resume(alone, OTHER_HOME, OTHER_WORK)
    assert sharing(owner, a) == [] and detected(migrated) == []
    resume(b, HOME, WORK)
    assert sharing(owner, a) == [{"member_id": b.id, "level": "workspace"}]
    assert sharing(owner, b) == [{"member_id": a.id, "level": "workspace"}]
    assert sharing(owner, alone) == []
    [event] = detected(migrated)
    assert event.payload == {
        "member_ids": sorted([a.id, b.id], key=_order(migrated)),
        "level": "workspace",
    }
    assert event.audience == [f"member:{owner.id}"]
    resume(b, HOME, WORK)  # a resume with the same ids continues the overlap
    resume(a, HOME, WORK)
    assert len(detected(migrated)) == 1


def test_the_level_rises_from_home_to_workspace_once(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    resume(a, HOME, WORK)
    resume(b, HOME, OTHER_WORK)
    assert sharing(owner, a) == [{"member_id": b.id, "level": "home"}]
    resume(b, HOME, WORK)
    resume(b, HOME, OTHER_WORK)  # back down: not announced
    resume(b, HOME, WORK)  # up again within the same overlap: not again
    assert [e.payload["level"] for e in detected(migrated)] == ["home", "workspace"]


def test_an_overlap_ends_after_ten_quiet_minutes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    start = clock.now()
    now = [start]
    clock.set_source(lambda: now[0])
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    resume(a, HOME, WORK)
    resume(b, HOME, WORK)
    resume(b, OTHER_HOME, OTHER_WORK)  # apart
    assert sharing(owner, a) == []
    now[0] = start + timedelta(minutes=9)
    resume(b, HOME, WORK)  # back within ten minutes: the same overlap
    assert len(detected(migrated)) == 1
    resume(b, OTHER_HOME, OTHER_WORK)
    now[0] = start + timedelta(minutes=20)
    resume(b, HOME, WORK)  # after eleven quiet minutes: a new one
    assert len(detected(migrated)) == 2


def test_revoking_a_credential_ends_the_sharing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    resume(a, HOME, WORK)
    resume(b, HOME, WORK)
    revoked = owner.post(f"/projects/maity/credentials/{b.credential_id}/revoke", {})
    assert revoked.status_code == 200, revoked.text
    assert sharing(owner, a) == []
    with migrated.connect() as conn:
        [row] = conn.execute(select(t.environment_overlap)).all()
    assert row.quiet_since is not None


def test_no_agent_sees_the_field_or_the_event(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    resume(a, HOME, WORK)
    resume(b, HOME, WORK)
    for viewer in (a, admin):
        view = viewer.get(f"/projects/maity/members/{b.id}").json()
        assert "shared_environment" not in view
        listed = viewer.get("/projects/maity/members").json()["items"]
        assert all("shared_environment" not in v for v in listed)
        kinds = [
            e["kind"]
            for e in viewer.get("/projects/maity/events?after=0&limit=200").json()["items"]
        ]
        assert "shared_environment_detected" not in kinds
    owners = [
        e["kind"] for e in owner.get("/projects/maity/events?after=0&limit=200").json()["items"]
    ]
    assert "shared_environment_detected" in owners
    # Never in member_updated, nor anywhere else an event carries a member view.
    with migrated.connect() as conn:
        payloads = conn.execute(select(t.event.c.payload)).scalars().all()
    assert not any("shared_environment" in str(p) for p in payloads if isinstance(p, dict))


def test_the_ids_are_never_shown(owner: flow.Human, make_client: ClientFactory) -> None:
    a = flow.agent(make_client, owner)
    packet = resume(a, HOME, WORK).text
    view = owner.get(f"/projects/maity/members/{a.id}").text
    assert HOME not in packet + view and WORK not in packet + view


def _order(engine: Engine) -> Any:
    """Members in membership order, as the event names them."""
    with engine.connect() as conn:
        rows = conn.execute(select(t.membership.c.id, t.membership.c.agent_id)).all()
    position = {r.agent_id: r.id for r in rows if r.agent_id}
    return lambda member_id: position[member_id]


def test_a_human_admin_is_in_the_audience(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    admin_id = factory.human(migrated, "second")
    factory.membership(migrated, project_id, role="admin", human_id=admin_id)
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    resume(a, HOME, WORK)
    resume(b, HOME, WORK)
    [event] = detected(migrated)
    assert event.audience == sorted([f"member:{owner.id}", f"member:{admin_id}"])


def test_removing_a_member_ends_its_sharing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    resume(a, HOME, WORK)
    resume(b, HOME, WORK)
    assert owner.delete(f"/projects/maity/members/{b.id}").status_code == 200
    assert sharing(owner, a) == []
    with migrated.connect() as conn:
        [row] = conn.execute(select(t.environment_overlap)).all()
    assert row.quiet_since is not None


def test_a_redaction_is_as_hidden_from_agents_as_what_it_redacts(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    a, b = flow.agent(make_client, owner), flow.agent(make_client, owner)
    admin = flow.agent(make_client, owner, role="admin")
    resume(a, HOME, WORK)
    resume(b, HOME, WORK)
    [event] = detected(migrated)
    redacted = owner.post(f"/projects/maity/events/{event.seq}/redact", {"reason": "test"})
    assert redacted.status_code == 200, redacted.text
    seen = admin.get("/projects/maity/events?after=0&limit=200").json()["items"]
    tombstones = [e for e in seen if e["kind"] == "event_redacted"]
    assert tombstones == []  # see-all does not reach it (§8.5)
    owners = owner.get("/projects/maity/events?after=0&limit=200").json()["items"]
    assert [e["payload"]["seq"] for e in owners if e["kind"] == "event_redacted"] == [event.seq]
