"""docs/api.md §6.5 "A holder that stops": `holder_stalled` when a limit starts, a revocation
ends the holder's session or an episode starts, and `claim_expired` when leases run out; to the
member the agent reports to, the admins, the owner and the holding instance, which they never
wake. Nothing is released."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock, events, holder_stalled
from maity_hub import tables as t
from maity_hub.events import transaction
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import task

BASE = "/projects/maintainer/maity"


class Setup:
    def __init__(self, owner: flow.Human, agent: flow.Agent, lead: flow.Agent, engine: Engine):
        self.owner, self.agent, self.lead, self.engine = owner, agent, lead, engine

    def claim(self) -> str:
        card = task(self.owner)
        claimed = self.agent.post(f"{BASE}/tasks/{card['id']}/claim", {})
        assert claimed.status_code == 200, claimed.text
        return str(card["id"])

    def events(self, kind: str) -> list[Any]:
        with self.engine.connect() as conn:
            return list(
                conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
            )

    def holder(self, card_id: str) -> Any:
        with self.engine.connect() as conn:
            return conn.execute(select(t.card).where(t.card.c.id == card_id)).one()


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> Setup:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner, role="member")
    lead = flow.agent(make_client, owner, role="member")
    assert agent.resume().status_code == 200
    with migrated.begin() as conn:
        lead_row = conn.execute(select(t.membership.c.id).where(t.membership.c.agent_id == lead.id))
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == agent.id)
            .values(reports_to=lead_row.scalar_one())
        )
    return Setup(owner, agent, lead, migrated)


def test_a_revocation_reports_the_holder_with_every_card_and_releases_nothing(
    setup: Setup,
) -> None:
    first, second = setup.claim(), setup.claim()
    revoked = setup.owner.post(
        f"{BASE}/credentials/{setup.agent.credential_id}/revoke", {"reason": "lost laptop"}
    )
    assert revoked.status_code == 200, revoked.text
    [event] = setup.events("holder_stalled")
    assert set(event.audience) == {
        f"member:{setup.lead.id}",
        "trust:admin",
        f"member:{setup.owner.id}",
        f"instance:{setup.agent.id}#{setup.agent.instance}",
    }
    payload = event.payload
    assert (payload["member_id"], payload["instance"]) == (setup.agent.id, setup.agent.instance)
    assert payload["reason"] == "session_ended"
    assert [c["id"] for c in payload["tasks"]] == sorted([first, second])
    assert payload["session_id"] and payload["last_seen_at"]
    assert "limit" not in payload
    assert setup.holder(first).claim_holder is not None  # nothing released


def test_a_replacement_says_nothing(setup: Setup) -> None:
    setup.claim()
    with transaction(setup.engine) as conn:
        holder_stalled.revoked(conn, setup.agent.credential_id, "replaced")
    assert setup.events("holder_stalled") == []


def test_a_revocation_without_cards_says_nothing(setup: Setup) -> None:
    revoked = setup.owner.post(f"{BASE}/credentials/{setup.agent.credential_id}/revoke", {})
    assert revoked.status_code == 200, revoked.text
    assert setup.events("holder_stalled") == []


def test_only_the_start_of_a_limit_counts(setup: Setup) -> None:
    setup.claim()
    until = clock.now() + timedelta(hours=2)
    declared = setup.agent.post("/me/limit", {"until": clock.rfc3339(until), "reason": "quota"})
    assert declared.status_code in (200, 201), declared.text
    [event] = setup.events("holder_stalled")
    assert event.payload["reason"] == "limit"
    assert event.payload["limit"] == {"reason": "quota", "until": clock.rfc3339(until)}
    later = clock.rfc3339(until + timedelta(hours=1))
    moved = setup.agent.post("/me/limit", {"until": later, "reason": "quota"})
    assert moved.status_code in (200, 201), moved.text
    assert len(setup.events("holder_stalled")) == 1  # a moved `until` is no new start


def test_an_episode_start_reports_a_holder(setup: Setup) -> None:
    card = setup.claim()
    with transaction(setup.engine) as conn:
        member = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == setup.agent.id)
        ).scalar_one()
        holder_stalled.stalled(conn, member, setup.agent.instance, "not_listening")
    [event] = setup.events("holder_stalled")
    assert event.payload["reason"] == "not_listening"
    assert [c["id"] for c in event.payload["tasks"]] == [card]


def _expire(setup: Setup, card_id: str, ago: timedelta) -> None:
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.card).where(t.card.c.id == card_id).values(lease_until=clock.now() - ago)
        )


def test_an_expired_lease_is_reported_once_per_expiry(setup: Setup) -> None:
    first, second = setup.claim(), setup.claim()
    _expire(setup, first, timedelta(minutes=2))
    _expire(setup, second, timedelta(minutes=1))
    holder_stalled.expire(setup.engine)
    [event] = setup.events("claim_expired")
    assert event.payload["reason"] == "lease_expired"
    assert [c["id"] for c in event.payload["tasks"]] == sorted([first, second])
    holder_stalled.expire(setup.engine)
    assert len(setup.events("claim_expired")) == 1  # once per expiry
    _expire(setup, first, timedelta(seconds=30))  # renewed, and run out again
    holder_stalled.expire(setup.engine)
    expired = setup.events("claim_expired")
    assert len(expired) == 2
    assert [c["id"] for c in expired[-1].payload["tasks"]] == [first]
    assert setup.holder(first).claim_holder is not None  # nothing released


@pytest.mark.parametrize("status", ["done", "cancelled"])
def test_a_closed_card_is_held_by_nobody(setup: Setup, status: str) -> None:
    """A closed card keeps `claim_holder`, `claim_instance` and `lease_until`; it neither
    makes a holder that stops nor a lease that runs out."""
    card = setup.claim()
    with setup.engine.begin() as conn:
        conn.execute(update(t.card).where(t.card.c.id == card).values(status=status))
    _expire(setup, card, timedelta(minutes=2))
    holder_stalled.expire(setup.engine)
    until = clock.rfc3339(clock.now() + timedelta(hours=2))
    assert setup.agent.post("/me/limit", {"until": until, "reason": "quota"}).status_code < 300
    revoked = setup.owner.post(f"{BASE}/credentials/{setup.agent.credential_id}/revoke", {})
    assert revoked.status_code == 200, revoked.text
    assert setup.events("holder_stalled") == [] and setup.events("claim_expired") == []


def _reader(agent_id: str | None, role: str = "member") -> Any:
    return SimpleNamespace(
        id=7, agent_id=agent_id, role=role, lead_instance=None, isolated_since=None
    )


@pytest.mark.parametrize("kind", ["holder_stalled", "claim_expired"])
def test_only_the_member_it_reports_to_is_woken_never_the_holder(kind: str) -> None:
    event = SimpleNamespace(
        kind=kind,
        payload={},
        audience=[
            "member:agt-boss",
            "trust:admin",
            "member:hum-owner",
            "instance:agt-holder#h0ld",
        ],
        wakes=None,
        actor_membership=None,
        actor_credential_id=None,
        conversation_id=None,
    )
    assert events.wakes(event, _reader("agt-boss"), "agt-boss", instance="b055")
    assert not events.wakes(event, _reader("agt-holder"), "agt-holder", instance="h0ld")
    assert not events.wakes(
        event, _reader("agt-holder"), "agt-holder", instance="h0ld", dormant=True
    )
    assert not events.wakes(event, _reader("agt-admin", "admin"), "agt-admin", instance="x")
    assert not events.wakes(event, _reader(None), "hum-owner")
