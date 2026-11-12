"""docs/api.md §9.6 "Free work messages from another side are gated like chat": a `notice`,
`blocker`, `handover`, `interface_change` or `go_request` from another side reaches an agent only
on its owner's yes; a held agent neither reads nor is woken by it, its owner reads it along, and
the work channel (an `update`, a lead's message) stays open."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import chat_gate, events
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def human(make_client: ClientFactory, engine: Engine, handle: str, trust: str) -> flow.Human:
    found = flow.human(make_client, engine, handle)
    factory.membership(engine, project_id(engine), trust, human_id=found.id)
    return found


def send(who: Any, to: str, kind: str = "notice", body: str = "please look") -> dict[str, Any]:
    sent = who.post(f"{PROJECT}/events", {"kind": "message", "type": kind, "to": to, "body": body})
    assert sent.status_code == 201, sent.text
    found: dict[str, Any] = sent.json()
    return found


def seqs(who: Any) -> list[int]:
    got = who.get(f"{PROJECT}/events?after=0&limit=200")
    assert got.status_code == 200, got.text
    return [e["seq"] for e in got.json()["items"]]


def woken(engine: Engine, agent_id: str) -> list[int]:
    with engine.connect() as conn:
        row = conn.execute(select(t.membership).where(t.membership.c.agent_id == agent_id)).one()
        rows, _ = events.read_waking(conn, row.project_id, row, agent_id, 0, 200)
    return [r.seq for r in rows]


def allow(who: flow.Human, **body: Any) -> None:
    got = who.post("/me/chat-access/allow", body)
    assert got.status_code == 201, got.text


@pytest.fixture
def sides(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> dict[str, Any]:
    """`other` (admin) owns `theirs`; `writer`, a plain member, writes; `mine` is the
    maintainer's own agent."""
    other = human(make_client, migrated, "other", "admin")
    writer = human(make_client, migrated, "writer", "member")
    return {
        "other": other,
        "writer": writer,
        "theirs": flow.agent(make_client, other),
        "mine": flow.agent(make_client, owner),
    }


def test_a_notice_from_another_side_is_held_and_the_owner_reads_along(
    sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    sent = send(writer, theirs.id)
    assert sent["payload"]["held"] == [theirs.id]
    with migrated.connect() as conn:
        audience = conn.execute(
            select(t.event.c.audience).where(t.event.c.seq == sent["seq"])
        ).scalar_one()
    assert f"held:{theirs.id}" in audience and f"member:{theirs.id}" not in audience
    assert sent["seq"] not in seqs(theirs)
    assert sent["seq"] not in woken(migrated, theirs.id)
    assert sent["seq"] in seqs(other)  # its owner reads along
    assert sent["seq"] in seqs(writer)  # and the author its own


def test_the_yes_admits_the_messages_after_it_not_the_held_one(
    sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    before = send(writer, theirs.id)
    allow(other, agents=[theirs.id], owner_id=writer.id, their_human=True)
    after = send(writer, theirs.id, "blocker")
    assert after["payload"]["held"] == []
    read = seqs(theirs)
    assert after["seq"] in read and before["seq"] not in read
    assert after["seq"] in woken(migrated, theirs.id)


def test_all_and_a_role_do_not_reach_a_held_agent(sides: dict[str, Any], migrated: Engine) -> None:
    theirs, mine, writer = sides["theirs"], sides["mine"], sides["writer"]
    everyone = send(writer, "all", "handover")
    assert set(everyone["payload"]["held"]) == {theirs.id, mine.id}
    with migrated.connect() as conn:
        role = conn.execute(
            select(t.membership.c.role).where(t.membership.c.agent_id == theirs.id)
        ).scalar_one()
    by_role = send(writer, f"role:{role}", "interface_change")
    assert theirs.id in by_role["payload"]["held"]
    read = seqs(theirs)
    assert everyone["seq"] not in read and by_role["seq"] not in read


def test_the_own_side_and_the_work_channel_stay_open(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, mine, other, writer = sides["theirs"], sides["mine"], sides["other"], sides["writer"]
    own = send(other, theirs.id, "go_request")  # its owner's own side
    assert own["payload"]["held"] == []
    by_admin = send(owner, theirs.id)  # trust owner: a lead
    assert by_admin["payload"]["held"] == []
    card = owner.post(f"{PROJECT}/tasks", {"title": "Ship it"})
    assert card.status_code == 201, card.text
    news = writer.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "update", "task_id": card.json()["id"], "body": "moving"},
    )
    assert news.status_code == 201, news.text
    assert news.json()["payload"]["held"] == []  # an update is the work channel
    chat = theirs.post(
        f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": mine.id, "body": "hi"}
    )
    assert chat.status_code == 201, chat.text
    assert chat.json()["payload"]["held"] == [mine.id]  # an agent of another owner is a side too


def test_a_manager_whose_line_the_agent_is_in_is_a_lead(
    sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, writer = sides["theirs"], sides["writer"]
    with migrated.begin() as conn:
        boss = conn.execute(
            select(t.membership.c.id).where(t.membership.c.human_id == writer.id)
        ).scalar_one()
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == theirs.id).values(reports_to=boss)
        )
    assert send(writer, theirs.id)["payload"]["held"] == []


def test_a_deny_holds_even_beside_an_allow(sides: dict[str, Any]) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    allow(other, agents=[theirs.id], owner_id=writer.id, their_human=True)
    denied = other.post("/me/chat-access/deny", {"agents": [theirs.id], "human_id": writer.id})
    assert denied.status_code == 201, denied.text
    assert send(writer, theirs.id)["payload"]["held"] == [theirs.id]


def test_the_switch_is_one_set_and_the_line_walk_ends() -> None:
    assert {
        "notice",
        "blocker",
        "handover",
        "interface_change",
        "go_request",
    } == chat_gate.GATED_WORK
    assert chat_gate._in_line({1: 2, 2: 3, 3: 1}, 1, 4) is False  # a loop ends the walk
    assert chat_gate._in_line({1: 2, 2: 3}, 1, 3) is True
