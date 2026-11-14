"""docs/api.md §9.6 on the other paths that address an agent with a member's own text: a request
(§7) and a ticker item's `to` (§17.6) from another side reach an agent only on its owner's yes,
decided when they are written; and an update passes the gate for a card's watcher only by a
watch that watcher set itself (§6.4) (tsk-yy88szfa7sfh)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_work_gate import PROJECT, allow, card, human, seqs, woken


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    found = flow.human(make_client, migrated)
    flow.project(found)
    return found


@pytest.fixture
def sides(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> dict[str, Any]:
    """As in test_work_gate: `other` (admin) owns `theirs`; `writer`, a plain member, writes;
    `mine` is the maintainer's own agent."""
    other = human(make_client, migrated, "other", "admin")
    writer = human(make_client, migrated, "writer", "member")
    return {
        "other": other,
        "writer": writer,
        "theirs": flow.agent(make_client, other),
        "mine": flow.agent(make_client, owner),
    }


# --- requests (§7) ---------------------------------------------------------------------


def ask(who: Any, to: str, title: str = "Which way?") -> dict[str, Any]:
    made = who.post(f"{PROJECT}/requests", {"class": "decision", "title": title, "to": to})
    assert made.status_code == 201, made.text
    found: dict[str, Any] = made.json()
    return found


def created_seq(engine: Engine, request_id: str) -> int:
    with engine.connect() as conn:
        seq: int = conn.execute(
            select(t.event.c.seq).where(
                t.event.c.kind == "request_created", t.event.c.subject_id == request_id
            )
        ).scalar_one()
    return seq


def finds(agent: Any, request_id: str) -> dict[str, bool]:
    """Where the agent meets the request: `to=me`, the resume packet, a read, an answer."""
    inbox = agent.get(f"{PROJECT}/requests?to=me")
    assert inbox.status_code == 200, inbox.text
    packet = agent.resume().json()["requests"]
    read = agent.get(f"{PROJECT}/requests/{request_id}")
    return {
        "inbox": request_id in [r["id"] for r in inbox.json()["items"]],
        "packet": request_id in [r["id"] for r in packet["to_answer"]],
        "read": read.status_code == 200,
    }


def admin_and_role(engine: Engine, agent_id: str) -> str:
    """The agent gets trust `admin` (which also brings `requests:answer`); its role token."""
    with engine.begin() as conn:
        conn.execute(
            update(t.membership).where(t.membership.c.agent_id == agent_id).values(trust="admin")
        )
        role: str = conn.execute(
            select(t.membership.c.role).where(t.membership.c.agent_id == agent_id)
        ).scalar_one()
    return f"role:{role}"


def test_a_request_from_another_side_is_held_for_every_target(
    sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    role = admin_and_role(migrated, theirs.id)
    for to in (theirs.id, f"{theirs.id}#{theirs.instance}", role, "trust:admin"):
        request = ask(writer, to)
        assert theirs.id in request["held"], to  # the asker sees it in the answer
        seq = created_seq(migrated, request["id"])
        with migrated.connect() as conn:
            audience = conn.execute(
                select(t.event.c.audience).where(t.event.c.seq == seq)
            ).scalar_one()
        assert f"held:{theirs.id}" in audience and f"member:{theirs.id}" not in audience, to
        assert finds(theirs, request["id"]) == {"inbox": False, "packet": False, "read": False}
        assert seq not in seqs(theirs) and seq not in woken(migrated, theirs.id), to
        assert seq in seqs(other), to  # its owner reads along
        answered = theirs.post(f"{PROJECT}/requests/{request['id']}/answer", {"text": "no"})
        assert answered.status_code in (403, 404), answered.text
    # Its owner is asked, by the request's event and type, never its text.
    with migrated.connect() as conn:
        proposals = conn.execute(
            select(t.request.c.proposal).where(
                t.request.c.to_human == other.id, t.request.c.filed_by == "hub"
            )
        ).scalars()
        held = [h for p in proposals for h in (p or {}).get("held", [])]
    assert {h["type"] for h in held} == {"request"} and len(held) == 4


def test_a_request_from_the_own_side_or_a_consenting_owner_is_not_held(
    make_client: ClientFactory, sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    peer = flow.agent(make_client, other)
    for who in (other, peer):
        own = ask(who, theirs.id)
        assert own["held"] == []
        assert finds(theirs, own["id"])["inbox"]
        assert created_seq(migrated, own["id"]) in woken(migrated, theirs.id)
    allow(other, agents=[theirs.id], owner_id=writer.id, their_human=True)
    allowed = ask(writer, theirs.id)
    assert allowed["held"] == []
    assert finds(theirs, allowed["id"]) == {"inbox": True, "packet": True, "read": True}


def test_a_held_request_stays_held_after_a_later_yes(
    sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    before = ask(writer, theirs.id)
    assert before["held"] == [theirs.id]
    allow(other, agents=[theirs.id], owner_id=writer.id, their_human=True)
    assert finds(theirs, before["id"]) == {"inbox": False, "packet": False, "read": False}
    again = ask(writer, theirs.id, "Which way, again?")  # the asker asks again
    assert again["held"] == []
    assert finds(theirs, again["id"])["inbox"]
    assert created_seq(migrated, again["id"]) in woken(migrated, theirs.id)


def test_a_held_request_stays_held_when_forwarded_on(
    make_client: ClientFactory, sides: dict[str, Any], migrated: Engine
) -> None:
    """Its later events name the held agent `held:` as its first did."""
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    admin_and_role(migrated, theirs.id)
    request = ask(writer, "trust:admin")
    assert theirs.id in request["held"]
    second = human(make_client, migrated, "second", "admin")
    moved = other.post(f"{PROJECT}/requests/{request['id']}/forward", {"to": second.id})
    assert moved.status_code in (200, 201), moved.text
    with migrated.connect() as conn:
        audiences = (
            conn.execute(
                select(t.event.c.audience).where(
                    t.event.c.subject_id == request["id"], t.event.c.kind == "request_forwarded"
                )
            )
            .scalars()
            .all()
        )
    assert audiences
    for audience in audiences:
        assert f"held:{theirs.id}" in audience


def test_a_forward_to_an_agent_the_gate_holds_it_for_is_refused(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    """Refused with the gate named, never dropped: the request stays with its holder."""
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    admin_and_role(migrated, theirs.id)
    request = ask(writer, owner.id)
    assert request["held"] == []
    path = f"{PROJECT}/requests/{request['id']}"
    refused = owner.post(f"{path}/forward", {"to": theirs.id})
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"reason": "held_by_gate"}
    with migrated.connect() as conn:
        holder = conn.execute(
            select(t.request.c.holder_member).where(t.request.c.id == request["id"])
        ).scalar_one()
    assert holder is None  # it stays with its holder
    # One held for that agent when filed is refused to it even after its owner's later yes.
    pooled = ask(writer, "trust:admin")
    assert theirs.id in pooled["held"]
    allow(other, agents=[theirs.id], owner_id=writer.id, their_human=True)
    again = other.post(f"{PROJECT}/requests/{pooled['id']}/forward", {"to": theirs.id})
    assert again.status_code == 403, again.text
    assert again.json()["error"]["details"]["reason"] == "held_by_gate"


def test_a_forward_to_an_admitted_agent_goes_through(
    owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, other, writer = sides["theirs"], sides["other"], sides["writer"]
    admin_and_role(migrated, theirs.id)
    allow(other, agents=[theirs.id], owner_id=writer.id, their_human=True)
    request = ask(writer, owner.id)
    moved = owner.post(f"{PROJECT}/requests/{request['id']}/forward", {"to": theirs.id})
    assert moved.status_code == 200, moved.text
    assert finds(theirs, request["id"])["read"]


# --- ticker items (§17.6) --------------------------------------------------------------


@pytest.fixture
def poster(make_client: ClientFactory, owner: flow.Human, migrated: Engine) -> flow.Human:
    """A plain member with the ops role, which brings `ticker:post` (§17.6)."""
    return human(make_client, migrated, "poster", "ops")


def post(who: Any, **body: Any) -> dict[str, Any]:
    made = who.post(f"{PROJECT}/ticker", {"type": "note", "text": "Staging is down.", **body})
    assert made.status_code == 201, made.text
    found: dict[str, Any] = made.json()
    return found


def reasons(engine: Engine, item: dict[str, Any]) -> dict[str, list[str]]:
    """Every member's reasons as stored: a plain member's view shows its own only (§17.5)."""
    with engine.connect() as conn:
        payload = conn.execute(
            select(t.event.c.payload).where(t.event.c.seq == item["seq"])
        ).scalar_one()
    return {r["member_id"]: r["why"] for r in payload["reasons"]}


def listed(who: Any) -> list[int]:
    got = who.get(f"{PROJECT}/ticker")
    assert got.status_code == 200, got.text
    return [i["seq"] for i in got.json()["items"]]


def test_a_ticker_item_addressed_or_to_all_is_held_for_another_side(
    poster: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    theirs, mine, other = sides["theirs"], sides["mine"], sides["other"]
    addressed = post(poster, to=[f"member:{theirs.id}"])
    everyone = post(poster, to="all")
    assert addressed["payload"]["held"] == [theirs.id]
    assert {theirs.id, mine.id} <= set(everyone["payload"]["held"])
    for item in (addressed, everyone):
        assert theirs.id not in reasons(migrated, item)
        assert item["seq"] not in listed(theirs) and item["seq"] not in seqs(theirs)
        assert item["seq"] not in woken(migrated, theirs.id)
        assert item["seq"] in seqs(other)  # its owner reads along


def test_computed_reasons_and_a_follow_of_its_own_still_reach(
    make_client: ClientFactory, poster: flow.Human, sides: dict[str, Any], migrated: Engine
) -> None:
    other = sides["other"]
    owns_web = flow.agent(make_client, other, areas=["web/"])
    computed = post(poster, areas=["web/app.ts"])
    assert computed["payload"]["held"] == []
    assert reasons(migrated, computed)[owns_web.id] == ["area_owner:web/"]
    assert computed["seq"] in woken(migrated, owns_web.id)
    follower = flow.agent(make_client, other)
    followed = follower.patch(
        f"{PROJECT}/ticker/subscription", {"add": {"follow": {"types": ["note"]}}}
    )
    assert followed.status_code == 200, followed.text
    addressed = post(poster, to=[f"member:{follower.id}"])
    assert follower.id not in addressed["payload"]["held"]
    assert reasons(migrated, addressed)[follower.id] == [
        "follow:type:note"
    ]  # the gated reason is gone
    assert addressed["seq"] in listed(follower)
    allow(other, agents=[sides["theirs"].id], owner_id=poster.id, their_human=True)
    consented = post(poster, to=[f"member:{sides['theirs'].id}"])
    assert consented["payload"]["held"] == []
    assert consented["seq"] in woken(migrated, sides["theirs"].id)


# --- an update's watchers (§6.4) -------------------------------------------------------


def update_on(who: Any, task_id: str, to: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"kind": "message", "type": "update", "task_id": task_id, "body": "x"}
    if to is not None:
        body["to"] = to
    sent = who.post(f"{PROJECT}/events", body)
    assert sent.status_code == 201, sent.text
    found: dict[str, Any] = sent.json()
    return found


def listed_watcher(engine: Engine, seq: int, agent_id: str) -> bool:
    with engine.connect() as conn:
        return (
            agent_id
            in conn.execute(
                select(t.membership.c.agent_id)
                .join(t.event_watcher, t.event_watcher.c.membership_id == t.membership.c.id)
                .where(t.event_watcher.c.seq == seq)
            )
            .scalars()
            .all()
        )


@pytest.fixture
def depending(
    make_client: ClientFactory, owner: flow.Human, sides: dict[str, Any], migrated: Engine
) -> dict[str, Any]:
    """`target`, another owner's agent owning `web/`, holds a card the writer filed in its
    area that depends on `card`: a watch that came with that card, not one of its own."""
    target = flow.agent(make_client, sides["other"], areas=["web/"])
    watched = card(owner)
    filed = sides["writer"].post(
        f"{PROJECT}/tasks", {"title": "Follows it", "area": "web/app.ts", "depends_on": [watched]}
    )
    assert filed.status_code == 201, filed.text
    with migrated.connect() as conn:
        assigned = conn.execute(
            select(t.membership.c.agent_id)
            .join(t.card, t.card.c.assigned_to == t.membership.c.id)
            .where(t.card.c.id == filed.json()["id"])
        ).scalar_one()
    assert assigned == target.id
    return {"target": target, "card": watched}


def test_a_watch_from_a_dependent_card_does_not_pass_the_gate(
    sides: dict[str, Any], depending: dict[str, Any], migrated: Engine
) -> None:
    target, task_id, writer = depending["target"], depending["card"], sides["writer"]
    for to in (target.id, None):
        news = update_on(writer, task_id, to)
        assert news["payload"]["held"] == [target.id], to
        assert not listed_watcher(migrated, news["seq"], target.id), to
        assert news["seq"] not in seqs(target) and news["seq"] not in woken(migrated, target.id)
        assert news["seq"] in seqs(sides["other"]), to  # its owner reads along


def test_a_dependent_cards_watch_reaches_the_own_side_and_on_a_yes(
    sides: dict[str, Any], depending: dict[str, Any], migrated: Engine
) -> None:
    target, task_id, other, writer = (
        depending["target"],
        depending["card"],
        sides["other"],
        sides["writer"],
    )
    own = update_on(other, task_id)
    assert own["payload"]["held"] == [] and listed_watcher(migrated, own["seq"], target.id)
    assert own["seq"] in seqs(target)
    allow(other, agents=[target.id], owner_id=writer.id, their_human=True)
    allowed = update_on(writer, task_id)
    assert allowed["payload"]["held"] == [] and allowed["seq"] in seqs(target)


def test_a_watch_the_agent_set_itself_passes(
    sides: dict[str, Any], depending: dict[str, Any], migrated: Engine
) -> None:
    target, task_id, writer = depending["target"], depending["card"], sides["writer"]
    watched = target.client.put(f"/api/v1{PROJECT}/tasks/{task_id}/watch", headers=target.auth)
    assert watched.status_code in (200, 201, 204), watched.text
    for to in (target.id, None):
        news = update_on(writer, task_id, to)
        assert news["payload"]["held"] == [], to
        assert listed_watcher(migrated, news["seq"], target.id), to
        assert news["seq"] in seqs(target), to
