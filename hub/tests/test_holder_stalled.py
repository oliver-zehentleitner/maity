"""docs/api.md §6.5 "A holder that stops": `holder_stalled` when a limit starts, a revocation
ends the holder's session or an episode starts, and `claim_expired` when leases run out; to the
member the agent reports to, the admins, the owner and the holding instance, which they never
wake. Nothing is released."""

from __future__ import annotations

import time
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, delete, select, update

from maity_hub import clock, events, holder_stalled, not_listening
from maity_hub import tables as t
from maity_hub.auth import leaks
from maity_hub.db import downgrade, migrate
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
    assert set(event.audience) == {  # the admins only without a boss (§8.2)
        f"member:{setup.lead.id}",
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


def test_without_a_boss_the_admins_read_it(setup: Setup) -> None:
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.agent_id == setup.agent.id)
            .values(reports_to=None)
        )
    setup.claim()
    revoked = setup.owner.post(f"{BASE}/credentials/{setup.agent.credential_id}/revoke", {})
    assert revoked.status_code == 200, revoked.text
    [event] = setup.events("holder_stalled")
    assert set(event.audience) == {
        "trust:admin",
        f"member:{setup.owner.id}",
        f"instance:{setup.agent.id}#{setup.agent.instance}",
    }


def test_a_removal_releases_the_cards_and_says_nothing(setup: Setup) -> None:
    card = setup.claim()
    assert setup.owner.delete(f"{BASE}/members/{setup.agent.id}").status_code == 200
    assert setup.events("holder_stalled") == []
    assert setup.holder(card).claim_holder is None


def test_a_second_revocation_says_nothing(setup: Setup) -> None:
    setup.claim()
    revoked = setup.owner.post(f"{BASE}/credentials/{setup.agent.credential_id}/revoke", {})
    assert revoked.status_code == 200, revoked.text
    with transaction(setup.engine) as conn:
        assert not leaks.revoke(conn, setup.agent.credential_id, "lost laptop", by=None)
    assert len(setup.events("holder_stalled")) == 1


def test_a_holder_without_a_session_is_still_session_ended(setup: Setup) -> None:
    """An instance can hold a claim before its first resume: the revocation is still read,
    also by the expiry that follows (§6.5's precedence)."""
    card = setup.claim()
    with setup.engine.begin() as conn:
        conn.execute(
            delete(t.agent_session).where(
                t.agent_session.c.credential_id == setup.agent.credential_id
            )
        )
    with transaction(setup.engine) as conn:
        assert leaks.revoke(conn, setup.agent.credential_id, "lost laptop", by=None)
    [event] = setup.events("holder_stalled")
    assert event.payload["reason"] == "session_ended"
    assert (event.payload["session_id"], event.payload["last_seen_at"]) == (None, None)
    _expire(setup, card, timedelta(minutes=1))
    holder_stalled.expire(setup.engine)
    [expired] = setup.events("claim_expired")
    assert expired.payload["reason"] == "session_ended"


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


def test_the_not_listening_check_reports_a_holder_with_its_episode(setup: Setup) -> None:
    """Through `not_listening.check`: the episode's start and `holder_stalled` together."""
    card = setup.claim()
    start = clock.now()
    response = setup.owner.post(
        f"{BASE}/conversations/{setup.agent.id}/messages", {"body": "are you there?"}
    )
    assert response.status_code == 201, response.text
    later = start + timedelta(minutes=11)
    clock.set_source(lambda: later)
    not_listening.sweep(setup.engine)
    assert len(setup.events("member_not_listening")) == 1
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


def test_the_minute_worker_runs_the_pass(setup: Setup) -> None:
    card = setup.claim()
    _expire(setup, card, timedelta(minutes=2))
    worker = not_listening.Worker(setup.engine, interval=0.05)
    worker.start()
    try:
        deadline = time.monotonic() + 10
        while not setup.events("claim_expired") and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        worker.stop()
    assert len(setup.events("claim_expired")) == 1


def test_the_migration_marks_the_leases_expired_before_it_as_reported(setup: Setup) -> None:
    """The first pass after the deploy reports no old lease; a running one counts later."""
    old, running, closed = setup.claim(), setup.claim(), setup.claim()
    downgrade(setup.engine, "20261103210000_digest_seen")
    with setup.engine.begin() as conn:
        conn.execute(
            update(t.card)
            .where(t.card.c.id.in_([old, closed]))
            .values(lease_until=clock.now() - timedelta(minutes=5))
        )
        conn.execute(update(t.card).where(t.card.c.id == closed).values(status="done"))
    migrate(setup.engine)
    assert setup.holder(old).lease_expiry_reported == setup.holder(old).lease_until
    assert setup.holder(running).lease_expiry_reported is None
    assert setup.holder(closed).lease_expiry_reported is None  # never read by the pass
    holder_stalled.expire(setup.engine)
    assert setup.events("claim_expired") == []
    _expire(setup, running, timedelta(minutes=1))
    holder_stalled.expire(setup.engine)
    [event] = setup.events("claim_expired")
    assert [c["id"] for c in event.payload["tasks"]] == [running]


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
    # A dormant boss is woken by its own instance token only, as for `member_not_listening`.
    assert not events.wakes(event, _reader("agt-boss"), "agt-boss", instance="b055", dormant=True)
