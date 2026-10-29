"""docs/api.md §6.23: the commitment at resume, the confirmation and the member view."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _block(agent: flow.Agent) -> dict[str, Any]:
    response = agent.resume()
    assert response.status_code == 200, response.text
    block: dict[str, Any] = response.json()["keep_the_why"]
    return block


def test_the_first_resume_fixes_the_deadline_for_every_later_one(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    first = _block(agent)
    assert first["commitment"] == "required"
    assert first["acknowledged_at"] is None
    assert first["ack"] == "maity ack keep-the-why"
    assert _block(agent)["acknowledge_by"] == first["acknowledge_by"]


def test_the_deadline_is_thirty_minutes_after_the_first_resume(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    _block(agent)
    with migrated.connect() as conn:
        row = conn.execute(
            select(t.credential).where(t.credential.c.id == agent.credential_id)
        ).one()
        started = conn.execute(
            select(t.agent_session.c.started_at).where(t.agent_session.c.id == row.ktw_session_id)
        ).scalar_one()
    assert row.ktw_acknowledge_by == started + timedelta(minutes=30)


def test_the_confirmation_is_once_and_idempotent(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    _block(agent)
    first = agent.post("/me/keep-the-why/ack")
    assert first.status_code == 200, first.text
    again = agent.post("/me/keep-the-why/ack")
    assert again.json() == first.json()
    assert first.json()["instance"] == agent.instance
    block = _block(agent)
    assert block["acknowledged_at"] == first.json()["acknowledged_at"]
    assert "acknowledge_by" not in block


def test_a_new_instance_confirms_for_itself(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = flow.agent(make_client, owner)
    _block(agent)
    agent.post("/me/keep-the-why/ack")
    sibling = flow.agent(make_client, owner)
    assert _block(sibling)["acknowledged_at"] is None


def test_under_optional_the_hub_checks_nothing(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    owner.patch(BASE, {"policy": {"keep_the_why": "optional"}, "reason": "trial"})
    block = _block(agent)
    assert "skill" in block
    assert not {"commitment", "acknowledged_at", "acknowledge_by", "ack"} & set(block)
    refused = agent.post("/me/keep-the-why/ack")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "keep_the_why_not_required"


def test_the_member_view_carries_the_instance_and_the_mark(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    _block(agent)
    member = owner.get(f"{BASE}/members/{agent.id}").json()
    instance = member["instances"][0]
    assert instance["keep_the_why_acknowledged_at"] is None
    assert instance["keep_the_why_acknowledge_by"] is not None
    assert member["keep_the_why_unconfirmed"] is False
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == agent.credential_id)
            .values(ktw_acknowledge_by=clock.now() - timedelta(minutes=1))
        )
    late = owner.get(f"{BASE}/members/{agent.id}").json()
    assert late["keep_the_why_unconfirmed"] is True
    agent.post("/me/keep-the-why/ack")
    done = owner.get(f"{BASE}/members/{agent.id}").json()
    assert done["keep_the_why_unconfirmed"] is False
    assert done["instances"][0]["keep_the_why_acknowledge_by"] is None
    assert done["instances"][0]["keep_the_why_acknowledged_at"] is not None


def test_humans_and_optional_projects_carry_neither(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    human = owner.get(f"{BASE}/members/{owner.id}").json()
    assert "keep_the_why_unconfirmed" not in human
    owner.patch(BASE, {"policy": {"keep_the_why": "optional"}, "reason": "trial"})
    member = owner.get(f"{BASE}/members/{agent.id}").json()
    assert "keep_the_why_unconfirmed" not in member
    assert "keep_the_why_acknowledge_by" not in member["instances"][0]


# --- the reminder, then the owner ----------------------------------------------------


def _due(engine: Engine, agent: flow.Agent, ago: timedelta) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == agent.credential_id)
            .values(ktw_acknowledge_by=clock.now() - ago)
        )


def _events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def _notices(owner: flow.Human, status: str = "all") -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = owner.get("/requests", params={"status": status}).json()["items"]
    return [r for r in found if r["filed_by"] == "hub"]


def test_the_reminder_goes_to_the_open_session_once(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from maity_hub import commitment

    agent = flow.agent(make_client, owner)
    _block(agent)
    commitment.sweep(migrated)
    assert _events(migrated, "keep_the_why_reminder") == []  # not due yet
    _due(migrated, agent, timedelta(minutes=1))
    commitment.sweep(migrated)
    commitment.sweep(migrated)
    [reminder] = _events(migrated, "keep_the_why_reminder")
    assert reminder.audience == [f"instance:{agent.id}#{agent.instance}"]
    assert reminder.payload["instance"] == agent.instance
    assert reminder.payload["project"] == "maintainer/maity"  # the full name (§6.25)
    assert reminder.payload["acknowledge_by"] is not None
    assert _notices(owner) == []  # the owner hears 30 minutes later


def test_thirty_minutes_later_the_owner_is_asked_once(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from maity_hub import commitment

    agent = flow.agent(make_client, owner)
    _block(agent)
    _due(migrated, agent, timedelta(minutes=31))
    commitment.sweep(migrated)
    commitment.sweep(migrated)
    [notice] = _notices(owner)
    project = owner.get(BASE).json()
    assert notice["title"].endswith(
        f"#{agent.instance} has not confirmed Keep the Why in {project['name']}"
    )
    assert notice["summary"].startswith("The commitment was due at ")
    assert (notice["class"], notice["status"], notice["personal"]) == ("info", "open", True)
    assert [o["id"] for o in notice["options"]] == ["seen"]
    # The owner answering `seen` closes it and files no second one for the same commitment.
    answered = owner.post(f"/requests/{notice['id']}/answer", {"reply_id": "seen"})
    assert answered.status_code == 200, answered.text
    commitment.sweep(migrated)
    assert len(_notices(owner)) == 1


def test_the_confirmation_withdraws_the_owners_request(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from maity_hub import commitment

    agent = flow.agent(make_client, owner)
    _block(agent)
    _due(migrated, agent, timedelta(minutes=31))
    commitment.sweep(migrated)
    assert [n["status"] for n in _notices(owner)] == ["open"]
    agent.post("/me/keep-the-why/ack")
    assert [n["status"] for n in _notices(owner)] == ["withdrawn"]
    commitment.sweep(migrated)
    assert len(_notices(owner)) == 1


def test_optional_ends_what_is_owed_and_a_later_required_starts_afresh(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from maity_hub import commitment

    agent = flow.agent(make_client, owner)
    _block(agent)
    _due(migrated, agent, timedelta(minutes=31))
    commitment.sweep(migrated)
    owner.patch(BASE, {"policy": {"keep_the_why": "optional"}, "reason": "trial"})
    assert [n["status"] for n in _notices(owner)] == ["withdrawn"]
    owner.patch(BASE, {"policy": {"keep_the_why": "required"}, "reason": "again"})
    block = _block(agent)
    assert block["acknowledged_at"] is None and block["acknowledge_by"] is not None
    assert (
        _events(migrated, "keep_the_why_reminder") == []
        or len(_events(migrated, "keep_the_why_reminder")) == 1
    )
    commitment.sweep(migrated)
    assert len(_notices(owner)) == 1  # nothing new: the fresh deadline is ahead


def test_a_paused_agent_is_not_reminded(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from maity_hub import commitment

    agent = flow.agent(make_client, owner)
    _block(agent)
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == agent.credential_id)
            .values(paused_since=clock.now(), paused_by=owner.id)
        )
    _due(migrated, agent, timedelta(minutes=1))
    commitment.sweep(migrated)
    assert _events(migrated, "keep_the_why_reminder") == []


def test_the_acknowledgement_reaches_the_owner_and_the_admins(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    _block(agent)
    assert agent.post("/me/keep-the-why/ack", {}).status_code == 200
    [acknowledged] = _events(migrated, "keep_the_why_acknowledged")
    # The admins by trust since trust x role (§2.3, §8.2), never the retired role token.
    assert acknowledged.audience == [f"member:{owner.id}", "trust:admin"]


def test_a_reminder_missed_without_an_open_session_comes_at_the_next_resume(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from maity_hub import commitment

    agent = flow.agent(make_client, owner)
    _block(agent)
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.credential_id == agent.credential_id)
            .values(live=None)  # an at-most-one marker: ended is null (persistence)
        )
    _due(migrated, agent, timedelta(minutes=1))
    commitment.sweep(migrated)
    assert _events(migrated, "keep_the_why_reminder") == []  # nobody to wake
    _block(agent)  # the next resume
    [reminder] = _events(migrated, "keep_the_why_reminder")
    assert reminder.audience == [f"instance:{agent.id}#{agent.instance}"]
    with migrated.connect() as conn:
        live = conn.execute(
            select(t.agent_session.c.id).where(
                t.agent_session.c.credential_id == agent.credential_id,
                t.agent_session.c.live.is_(True),
            )
        ).scalar()
    assert reminder.payload["session_id"] == live  # the session that just started
    _block(agent)
    commitment.sweep(migrated)
    assert len(_events(migrated, "keep_the_why_reminder")) == 1  # once per commitment


def _credential(engine: Engine, agent: flow.Agent) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.credential).where(t.credential.c.id == agent.credential_id)
        ).one()


@pytest.mark.parametrize("cause", ["revoked", "membership_ended", "profile_deleted"])
def test_an_ended_cause_withdraws_the_request_and_leaves_the_sweep(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine, cause: str
) -> None:
    from maity_hub import commitment

    agent = flow.agent(make_client, owner)
    _block(agent)
    _due(migrated, agent, timedelta(minutes=31))
    commitment.sweep(migrated)
    assert [n["status"] for n in _notices(owner)] == ["open"]
    with migrated.begin() as conn:
        if cause == "revoked":
            conn.execute(
                update(t.credential)
                .where(t.credential.c.id == agent.credential_id)
                .values(revoked_at=clock.now())
            )
        elif cause == "membership_ended":
            conn.execute(
                update(t.membership).where(t.membership.c.agent_id == agent.id).values(active=None)
            )
        else:
            conn.execute(
                update(t.agent_profile)
                .where(t.agent_profile.c.id == agent.id)
                .values(deleted_at=clock.now())
            )
    commitment.sweep(migrated)
    assert [n["status"] for n in _notices(owner)] == ["withdrawn"]
    # Nothing is owed any more, a revoked instance included: it leaves every later sweep.
    assert _credential(migrated, agent).ktw_acknowledge_by is None
    commitment.sweep(migrated)
    assert len(_notices(owner)) == 1


def test_a_new_owner_is_asked_and_the_old_ones_request_is_withdrawn(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from maity_hub import commitment

    agent = flow.agent(make_client, owner)
    _block(agent)
    _due(migrated, agent, timedelta(minutes=31))
    commitment.sweep(migrated)
    [old] = _notices(owner)
    heir = flow.human(make_client, migrated, "heir")
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile).where(t.agent_profile.c.id == agent.id).values(owner_id=heir.id)
        )
    commitment.sweep(migrated)
    assert [n["status"] for n in _notices(owner)] == ["withdrawn"]
    [new] = _notices(heir)
    assert new["status"] == "open" and new["id"] != old["id"]
    assert _credential(migrated, agent).ktw_request_id == new["id"]
    commitment.sweep(migrated)
    assert len(_notices(heir)) == 1
