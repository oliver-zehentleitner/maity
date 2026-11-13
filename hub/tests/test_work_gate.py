"""docs/api.md §9.6 "Free work messages from another side are gated like chat": a `notice`,
`blocker`, `handover`, `interface_change` or `go_request` from another side reaches an agent only
on its owner's yes; a held agent neither reads nor is woken by it, its owner reads it along, and
the work channel (a lead's message, the card's own flow) stays open. An `update` and a
`review_result` pass the same gate for every agent they reach beyond that flow: an update's
watchers, a review result's author and two leads (§8.4) (tsk-yy88szfa7sfh)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import chat_gate, events
from maity_hub import tables as t
from maity_hub.routes.events import MESSAGE_TYPES
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
    # A member the chain names but who is no manager is no lead: the message is held.
    assert send(writer, theirs.id)["payload"]["held"] == [theirs.id]
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == boss)
            .values(role="manager", role_base="manager")
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
        "update",
        "review_result",
    } == chat_gate.GATED_WORK
    assert chat_gate._in_line({1: 2, 2: 3, 3: 1}, 1, 4) is False  # a loop ends the walk
    assert chat_gate._in_line({1: 2, 2: 3}, 1, 3) is True


def test_a_redacted_held_message_and_its_notices_stay_held(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    """A redaction replaces the payload, and its `event_redacted` and an `attachment_deleted`
    copy the message's audience: the `held:` token still keeps them from a held agent, even one
    whose trust sees all (fp3y on #1717)."""
    theirs, writer = sides["theirs"], sides["writer"]
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == theirs.id).values(trust="admin")
        )
    sent = send(writer, theirs.id)
    assert sent["payload"]["held"] == [theirs.id]
    redacted = owner.post(f"{PROJECT}/events/{sent['seq']}/redact", {"reason": "oops"})
    assert redacted.status_code == 200, redacted.text
    with migrated.connect() as conn:
        stone = conn.execute(select(t.event).where(t.event.c.seq == sent["seq"])).one()
    project = project_id(migrated)
    with events.transaction(migrated) as conn:
        deleted = events.emit(
            conn,
            project,
            "attachment_deleted",
            list(stone.audience),
            {"message_seq": sent["seq"], "attachment_id": "att-x", "reason": "deleted"},
        )
    with migrated.connect() as conn:
        member = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == theirs.id)
        ).one()
        notice = conn.execute(select(t.event).where(t.event.c.kind == "event_redacted")).one()
        gone = conn.execute(select(t.event).where(t.event.c.seq == deleted)).one()
    assert "held" not in stone.payload  # the tombstone keeps no payload of its own
    for row in (stone, notice, gone):
        assert not events.readable_by(row, member, theirs.id), row.kind
    read = seqs(theirs)
    assert {sent["seq"], notice.seq, deleted} & set(read) == set()
    assert {sent["seq"], notice.seq, deleted} & set(woken(migrated, theirs.id)) == set()


# Every message type that takes a `to`, each with what it needs besides: a card for an update,
# a review object for a review result (without a card: no author, so every target is gated).
HEAD = "7039a4b6fd8b988d71a63338711da188fcd95fba"
REVIEW = {
    "subject": "#7",
    "head": HEAD,
    "verdict": "approve",
    "cites": [{"path": "docs/api.md", "line": 1, "quote": "a line"}],
}
ADDRESSED = sorted(set(MESSAGE_TYPES) - {"chat"})


def card(owner: flow.Human) -> str:
    made = owner.post(f"{PROJECT}/tasks", {"title": "A card"})
    assert made.status_code == 201, made.text
    found: str = made.json()["id"]
    return found


def work(
    who: Any,
    kind: str,
    to: str | None,
    task_id: str,
    body: str = "please look",
    reviewed: bool = False,
) -> Any:
    """`reviewed`: a review result names the card it reviews; otherwise it names none."""
    sent: dict[str, Any] = {"kind": "message", "type": kind, "body": body}
    if to is not None:
        sent["to"] = to
    if kind == "update" or reviewed:
        sent["task_id"] = task_id
    if kind == "review_result":
        sent["review"] = REVIEW
    return who.post(f"{PROJECT}/events", sent)


def held_for(who: Any, kind: str, to: str | None, task_id: str, body: str = "please look") -> Any:
    answer = work(who, kind, to, task_id, body)
    assert answer.status_code == 201, answer.text
    return answer.json()


def test_every_addressed_type_is_gated() -> None:
    """No message type that takes a `to` stays out of the gate by accident: all but `chat`,
    which has a gate of its own (§9.6)."""
    assert "chat" in MESSAGE_TYPES
    assert set(ADDRESSED) <= chat_gate.GATED_WORK
    assert set(MESSAGE_TYPES) >= chat_gate.GATED_WORK


@pytest.mark.parametrize("kind", ADDRESSED)
def test_a_held_side_is_held_for_every_addressed_type_and_target(
    kind: str, owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    task_id = card(owner)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == theirs.id).values(trust="admin")
        )
        role = conn.execute(
            select(t.membership.c.role).where(t.membership.c.agent_id == theirs.id)
        ).scalar_one()
    targets = (theirs.id, f"{theirs.id}#{theirs.instance}", "all", f"role:{role}", "trust:admin")
    sent = [held_for(writer, kind, to, task_id) for to in targets]
    for message in sent:
        assert theirs.id in message["payload"]["held"], message["payload"]["to"]
    read, rung = seqs(theirs), woken(migrated, theirs.id)
    for message in sent:
        assert message["seq"] not in read and message["seq"] not in rung, message["payload"]["to"]
        assert message["seq"] in seqs(other)  # its owner reads along


@pytest.mark.parametrize("kind", ADDRESSED)
def test_a_mention_of_a_held_agent_is_gated(
    kind: str, owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, writer = sides["theirs"], sides["writer"]
    with migrated.connect() as conn:
        handle = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == theirs.id)
        ).scalar_one()
    to = None if kind in ("update", "review_result") else writer.id
    body = f"see @{handle}"
    if kind == "review_result":  # one that reaches nobody but its sender is invalid
        to = f"role:{_role_of(migrated, writer.id)}"
    message = held_for(writer, kind, to, card(owner), body)
    assert theirs.id in message["payload"]["held"]
    assert message["seq"] not in seqs(theirs)


def _role_of(engine: Engine, human_id: str) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.membership.c.role).where(t.membership.c.human_id == human_id)
        ).scalar_one()
    return found


@pytest.mark.parametrize("kind", ADDRESSED)
def test_the_own_side_and_a_consenting_owner_are_not_held(
    kind: str,
    owner: flow.Human,
    make_client: ClientFactory,
    sides: dict[str, Any],
    migrated: Engine,
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    task_id = card(owner)
    peer = flow.agent(make_client, other)  # its owner's own side, no lead
    for who in (other, peer):
        own = held_for(who, kind, theirs.id, task_id)
        assert own["payload"]["held"] == []
        assert own["seq"] in seqs(theirs)
    allow(other, agents=[theirs.id], owner_id=writer.id, their_human=True)
    for to in (theirs.id, "all"):
        allowed = held_for(writer, kind, to, task_id)
        # `all` reaches agents the yes does not name too: they stay held, `theirs` is not.
        assert theirs.id not in allowed["payload"]["held"]
        assert to == "all" or allowed["payload"]["held"] == []
        assert allowed["seq"] in seqs(theirs) and allowed["seq"] in woken(migrated, theirs.id)


def test_an_update_reaches_the_cards_watchers_ungated(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, writer = sides["theirs"], sides["writer"]
    task_id = card(owner)
    watched = theirs.client.put(f"/api/v1{PROJECT}/tasks/{task_id}/watch", headers=theirs.auth)
    assert watched.status_code in (200, 201, 204), watched.text
    for to in (None, theirs.id, "all"):
        news = held_for(writer, "update", to, task_id)
        assert theirs.id not in news["payload"]["held"], to  # the card's own flow
        assert news["seq"] in seqs(theirs)
    # A card the agent does not watch: the same update to it is held.
    other_card = card(owner)
    assert held_for(writer, "update", theirs.id, other_card)["payload"]["held"] == [theirs.id]


def test_a_review_result_reaches_the_author_and_the_leads_ungated(
    owner: flow.Human, make_client: ClientFactory, sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    lead = flow.agent(make_client, other, role="manager")
    bystander = flow.agent(make_client, other)
    task_id = card(owner)
    with migrated.begin() as conn:
        rows = dict(
            conn.execute(
                select(t.membership.c.agent_id, t.membership.c.id).where(
                    t.membership.c.agent_id.in_([theirs.id, lead.id])
                )
            ).all()
        )
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == rows[theirs.id])
            .values(reports_to=rows[lead.id])
        )
        conn.execute(
            update(t.card).where(t.card.c.id == task_id).values(claim_holder=rows[theirs.id])
        )
    for to in (theirs.id, lead.id, "all"):
        message = work(writer, "review_result", to, task_id, reviewed=True)
        assert message.status_code == 201, message.text
        payload = message.json()["payload"]
        assert theirs.id not in payload["held"] and lead.id not in payload["held"], to
        if to == "all":  # anyone else the card's flow does not name is gated
            assert bystander.id in payload["held"]
        assert message.json()["seq"] in seqs(theirs)
    # Without the card, nobody is its author: the same result to that agent is held.
    loose = held_for(writer, "review_result", theirs.id, task_id)
    assert loose["payload"]["held"] == [theirs.id]
