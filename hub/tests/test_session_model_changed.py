"""docs/api.md §5.3 "A model change is a new session": `session_model_changed` to the member the
agent reports to, the admins and the owner when a member; only the first is woken."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import events
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory


class Setup:
    def __init__(self, owner: flow.Human, agent: flow.Agent, engine: Engine) -> None:
        self.owner, self.agent, self.engine = owner, agent, engine

    def resume(self, **body: Any) -> dict[str, Any]:
        response = self.agent.resume(**body)
        assert response.status_code == 200, response.text
        return dict(response.json())

    def changes(self) -> list[Any]:
        with self.engine.connect() as conn:
            return list(
                conn.execute(
                    select(t.event)
                    .where(t.event.c.kind == "session_model_changed")
                    .order_by(t.event.c.seq)
                )
            )


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> Setup:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    return Setup(owner, flow.agent(make_client, owner, role="member"), migrated)


def test_a_first_session_is_no_change(setup: Setup) -> None:
    setup.resume(harness="Claude Code", model="m1")
    assert setup.changes() == []


def test_the_same_model_is_no_change(setup: Setup) -> None:
    setup.resume(harness="Claude Code", model="m1")
    setup.resume(harness="Claude Code", model="m1")
    assert setup.changes() == []


def test_a_new_model_is_announced_with_both_sides(setup: Setup) -> None:
    setup.resume(harness="Claude Code", model="m1")
    packet = setup.resume(harness="Claude Code", model="m2")
    [event] = setup.changes()
    assert event.payload == {
        "member_id": setup.agent.id,
        "instance": setup.agent.instance,
        "from": {"harness": "Claude Code", "model": "m1"},
        "to": {"harness": "Claude Code", "model": "m2"},
        "session_id": packet["session"]["id"],
    }


def test_a_new_harness_is_announced(setup: Setup) -> None:
    setup.resume(harness="Claude Code", model="m1")
    setup.resume(harness="Codex", model="m1")
    [event] = setup.changes()
    assert (event.payload["from"]["harness"], event.payload["to"]["harness"]) == (
        "Claude Code",
        "Codex",
    )


def test_an_omitted_model_keeps_the_previous_one_without_an_event(setup: Setup) -> None:
    setup.resume(harness="Claude Code", model="m1")
    assert setup.resume(harness="Claude Code")["session"]["model"] == "m1"
    assert setup.changes() == []
    with setup.engine.connect() as conn:
        stored = conn.execute(
            select(t.agent_session.c.model).where(t.agent_session.c.live.is_(True))
        ).scalar()
    assert stored == "m1"


def test_an_omitted_harness_is_kept_and_a_switch_across_it_is_seen(setup: Setup) -> None:
    """A resume without `harness` keeps the previous one, like `model`: otherwise the session in
    between holds none, and a switch from one harness to another over it is never announced."""
    setup.resume(harness="Claude Code", model="m1")
    kept = setup.resume(model="m1")
    assert kept["session"]["harness"] == "Claude Code" and setup.changes() == []
    setup.resume(harness="Codex", model="m1")
    (event,) = setup.changes()
    assert (event.payload["from"]["harness"], event.payload["to"]["harness"]) == (
        "Claude Code",
        "Codex",
    )


def test_a_first_declared_model_is_no_change(setup: Setup) -> None:
    setup.resume(harness="Claude Code")
    setup.resume(harness="Claude Code", model="m1")
    assert setup.changes() == []


def test_the_audience_is_the_lead_the_admins_and_the_owner(
    make_client: ClientFactory, setup: Setup
) -> None:
    lead = flow.agent(make_client, setup.owner, role="member")
    with setup.engine.begin() as conn:
        lead_row = conn.execute(select(t.membership.c.id).where(t.membership.c.agent_id == lead.id))
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == setup.agent.id)
            .values(reports_to=lead_row.scalar_one())
        )
    setup.resume(harness="Claude Code", model="m1")
    setup.resume(harness="Claude Code", model="m2")
    [event] = setup.changes()
    assert set(event.audience) == {
        f"member:{lead.id}",
        "trust:admin",
        f"member:{setup.owner.id}",
    }


def _reader(agent_id: str | None, role: str = "member") -> Any:
    return SimpleNamespace(
        id=7, agent_id=agent_id, role=role, lead_instance=None, isolated_since=None
    )


def test_only_the_member_it_reports_to_is_woken() -> None:
    event = SimpleNamespace(
        kind="session_model_changed",
        payload={},
        audience=["member:agt-boss", "trust:admin", "member:hum-owner"],
        wakes={"agt-boss": ["lead"]},
        actor_membership=None,
        actor_credential_id=None,
        conversation_id=None,
    )
    assert events.wakes(event, _reader("agt-boss"), "agt-boss", instance="lead")
    assert not events.wakes(event, _reader("agt-boss"), "agt-boss", instance="other")
    assert not events.wakes(event, _reader("agt-admin", "admin"), "agt-admin", instance="x")
    assert not events.wakes(event, _reader(None), "hum-owner")
