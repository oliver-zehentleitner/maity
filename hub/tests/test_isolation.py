"""docs/api.md §6.2, "Isolation": a human with `members:admin` stops an agent member at
once and lifts that again (tsk-8c6vdjpw82b1)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import availability, events, longpoll, views
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_tasks import task

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def isolate(who: Any, member_id: str, reason: str = "it rewrote the release notes") -> Any:
    return who.post(f"{PROJECT}/members/{member_id}/isolate", {"reason": reason})


def lift(who: Any, member_id: str) -> Any:
    path = f"{PROJECT}/members/{member_id}/isolate"
    if isinstance(who, flow.Human):
        return who.delete(path)
    return who.client.request("DELETE", f"/api/v1{path}", headers=who.auth | who.key())


def say(who: Any, to: str, body: str = "are you there") -> Any:
    return who.post(
        f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": to, "body": body}
    )


def _row(engine: Engine, principal: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership).where(
                (t.membership.c.agent_id == principal) | (t.membership.c.human_id == principal)
            )
        ).one()


def _code(response: Any) -> dict[str, Any]:
    error: dict[str, Any] = response.json()["error"]
    return error


# --- who isolates -------------------------------------------------------------------------


def test_a_human_with_members_admin_isolates_and_lifts(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    done = isolate(owner, agent.id)
    assert done.status_code == 200, done.text
    shown = done.json()["isolated"]
    assert shown["reason"] == "it rewrote the release notes" and shown["by"] == owner.id
    assert shown["since"]
    assert owner.get(f"{PROJECT}/members/{agent.id}").json()["isolated"] == shown
    # Isolating an isolated member answers 200 and changes nothing.
    again = isolate(owner, agent.id, "another reason")
    assert again.status_code == 200 and again.json()["isolated"] == shown
    freed = lift(owner, agent.id)
    assert freed.status_code == 200 and freed.json()["isolated"] is None
    assert lift(owner, agent.id).json()["isolated"] is None  # a free member stays free


def test_an_agent_never_isolates_and_a_human_cannot_be_isolated(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    admin = flow.agent(make_client, owner, role="admin")
    victim = flow.agent(make_client, owner)
    refused = isolate(admin, victim.id)
    assert refused.status_code == 403 and _code(refused)["details"] == {"reason": "humans_only"}
    assert lift(admin, victim.id).status_code == 403
    human = isolate(owner, owner.id)
    assert human.status_code == 400
    assert _code(human)["details"]["fields"] == {"member": "not_an_agent"}


def test_a_member_without_members_admin_does_not_isolate(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    friend = flow.human(make_client, migrated, "friend")
    factory.membership(migrated, _project(migrated), "coder", human_id=friend.id)
    assert isolate(friend, agent.id).status_code == 403
    assert _row(migrated, agent.id).isolated_since is None


def test_the_reason_is_one_to_five_hundred_characters(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    assert isolate(owner, agent.id, "").status_code == 400
    assert isolate(owner, agent.id, "x" * 501).status_code == 400
    assert isolate(owner, agent.id, "x" * 500).status_code == 200


def _project(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


# --- what an isolated agent can still do --------------------------------------------------


def test_every_call_of_an_isolated_agent_is_refused_but_me_and_resume(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    isolate(owner, agent.id)
    refused = agent.get(f"{PROJECT}/members")
    assert refused.status_code == 403
    error = _code(refused)
    assert error["code"] == "forbidden" and error["details"]["reason"] == "isolated"
    assert error["details"]["isolated"]["reason"] == "it rewrote the release notes"
    assert agent.get(f"{PROJECT}/events?after=latest").status_code == 403
    assert agent.post(f"{PROJECT}/tasks", {"title": "x"}).status_code == 403
    me = agent.get("/me")
    assert me.status_code == 200 and me.json()["membership"]["isolated"]["by"] == owner.id
    resumed = agent.resume()
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["membership"]["isolated"]["by"] == owner.id
    lift(owner, agent.id)
    assert agent.get(f"{PROJECT}/members").status_code == 200
    assert agent.get("/me").json()["membership"]["isolated"] is None
    assert agent.resume().json()["membership"]["isolated"] is None


# --- what the isolation lets go of --------------------------------------------------------


def test_the_claims_are_released_and_stay_released(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    card = task(owner)
    assert agent.post(f"{PROJECT}/tasks/{card['id']}/claim", {}).status_code == 200
    isolate(owner, agent.id)
    shown = owner.get(f"{PROJECT}/tasks/{card['id']}").json()
    assert shown["status"] == "open" and shown["claim"] is None
    lift(owner, agent.id)
    assert owner.get(f"{PROJECT}/tasks/{card['id']}").json()["claim"] is None


def test_the_agent_leaves_its_group_chats_and_is_not_put_back(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    chat = owner.post(
        f"{PROJECT}/conversations", {"title": "release", "participants": [agent.id, other.id]}
    ).json()
    isolate(owner, agent.id)
    left = owner.get(f"{PROJECT}/conversations/{chat['id']}").json()
    assert agent.id not in [p["member_id"] for p in left["participants"]]
    lift(owner, agent.id)
    again = owner.get(f"{PROJECT}/conversations/{chat['id']}").json()
    assert agent.id not in [p["member_id"] for p in again["participants"]]


def test_the_change_is_announced_and_the_owner_gets_a_notice_each_time(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    isolate(owner, agent.id)
    lift(owner, agent.id)
    with migrated.connect() as conn:
        updates = [
            e.payload
            for e in conn.execute(select(t.event).where(t.event.c.kind == "member_updated"))
            if e.payload.get("changed") == ["isolated"]
        ]
        notices = list(conn.execute(select(t.request).where(t.request.c.filed_by == "hub")).all())
    assert [u["isolated"] is not None for u in updates] == [True, False]
    assert len(notices) == 2
    first, second = sorted(notices, key=lambda r: r.created_at)
    assert (
        first.personal is True and first.to_human == owner.id and first._mapping["class"] == "info"
    )
    assert "it rewrote the release notes" in first.summary and "maintainer/maity" in first.summary
    assert "lifted" in second.title


# --- nothing reaches it -------------------------------------------------------------------


def test_a_message_or_request_to_an_isolated_agent_is_invalid(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    isolate(owner, agent.id)
    message = say(other, agent.id)
    assert message.status_code == 400
    assert _code(message)["details"]["fields"] == {"to": "isolated"}
    request = other.post(
        f"{PROJECT}/requests",
        {"class": "decision", "title": "q", "summary": "s", "to": agent.id},
    )
    assert request.status_code == 400
    assert _code(request)["details"]["fields"] == {"to": "isolated"}
    chat = owner.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "chat", "conversation_id": agent.id, "body": "hello"},
    )
    assert chat.status_code == 400 and _code(chat)["details"]["fields"] == {"to": "isolated"}
    lift(owner, agent.id)
    assert say(other, agent.id).status_code == 201


def test_an_isolated_agent_reads_no_event_and_no_event_wakes_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    agent.resume()
    assert say(owner, "all", "to everybody").status_code == 201
    with migrated.connect() as conn:
        row = conn.execute(
            select(t.event).where(t.event.c.kind == "message").order_by(t.event.c.seq.desc())
        ).first()
    assert row is not None
    free = _row(migrated, agent.id)
    assert events.readable_by(row, free, agent.id) and events.wakes(row, free, agent.id)
    isolate(owner, agent.id)
    shut = _row(migrated, agent.id)
    assert not events.readable_by(row, shut, agent.id)
    assert not events.wakes(row, shut, agent.id)


def test_isolating_ends_the_open_waits_of_the_agent() -> None:
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        waiter = longpoll.Waiter(
            key="cred", project_id="prj-x", session_id=None, loop=loop, membership_id=7
        )
        other = longpoll.Waiter(
            key="cred2", project_id="prj-x", session_id=None, loop=loop, membership_id=8
        )
        longpoll.registry.enter(waiter)
        longpoll.registry.enter(other)
        longpoll.registry.end(7)
        assert waiter.ended is True and other.ended is False
    finally:
        longpoll.registry.leave(waiter)
        longpoll.registry.leave(other)
        loop.close()


# --- seats ---------------------------------------------------------------------------------


def test_a_seat_that_names_an_isolated_agent_is_routed_past_and_stays(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    coordinator = flow.agent(make_client, owner, role="admin")
    boss = flow.agent(make_client, owner, role="manager", reports_to=owner.id)
    report = flow.agent(make_client, owner, reports_to=boss.id)
    set_seat = owner.patch(
        f"{PROJECT}", {"policy": {"coordinator": coordinator.id}, "reason": "a named coordinator"}
    )
    assert set_seat.status_code == 200, set_seat.text
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        assert availability.coordinator_token(conn, project) == f"member:{coordinator.id}"
        member = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == report.id)
        ).one()
        assert views.routing_boss(conn, member.reports_to) == boss.id
    isolate(owner, coordinator.id)
    isolate(owner, boss.id)
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        assert project.coordinator == coordinator.id  # the seat stays as it is
        assert availability.coordinator_token(conn, project) == "trust:admin"
        member = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == report.id)
        ).one()
        assert member.reports_to is not None  # so does the edge
        assert views.routing_boss(conn, member.reports_to) is None
    lift(owner, coordinator.id)
    with migrated.connect() as conn:
        project = conn.execute(select(t.project)).one()
        assert availability.coordinator_token(conn, project) == f"member:{coordinator.id}"
