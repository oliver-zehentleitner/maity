"""docs/api.md §9.6 "Rules per side": the `allowed` and `denied` texts of an allow entry reach
the agent it admits, in the resume packet and in the chat's view it reads, and a change wakes it
with `chat_rules_changed`, which only that agent reads."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, delete, insert, select, update

from maity_hub import chat_gate, clock, events
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_chat_gate import BASE, allow, create, item, other_human, view


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def changes(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.event)
                .where(t.event.c.kind == "chat_rules_changed")
                .order_by(t.event.c.seq)
            ).all()
        )


def membership(engine: Engine, member_id: str) -> Any:
    with engine.connect() as conn:
        c = t.membership.c
        return conn.execute(
            select(t.membership).where((c.agent_id == member_id) | (c.human_id == member_id))
        ).one()


def rules_entry(other: flow.Human, agent_id: str, side: str, **body: Any) -> dict[str, Any]:
    entry: dict[str, Any] = allow(
        other,
        agents=[agent_id],
        owner_id=side,
        their_human=True,
        allowed="web and frontend, may work on it",
        denied="nothing about releases",
        **body,
    )
    return entry


def test_the_agent_reads_its_rules_in_the_packet_and_the_chat(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    entry = rules_entry(other, theirs.id, owner.id)
    chat = create(owner, theirs.id).json()
    assert item(chat, theirs.id)["waiting_for"] == []
    expected = {
        "entry_id": entry["id"],
        "owner_id": owner.id,
        "handle": "maintainer",
        "project": None,
        "allowed": "web and frontend, may work on it",
        "denied": "nothing about releases",
        "conversations": [chat["id"]],
    }
    packet = theirs.resume()
    assert packet.status_code == 200, packet.text
    assert packet.json()["chat_rules"] == [expected]
    shown = view(theirs, chat["id"])
    assert shown.status_code == 200, shown.text
    assert shown.json()["chat_rules"] == [expected]
    # Every other reader gets no such field: the other side, and the agent's owner reading along.
    assert "chat_rules" not in view(owner, chat["id"]).json()
    along = view(other, chat["id"]).json()
    assert along["access"] == "observer" and "chat_rules" not in along


def test_a_project_entry_is_named_by_its_project(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    entry = allow(
        other,
        agents="all",
        project={"owner": "maintainer", "slug": "maity"},
        denied="no customer names",
    )
    chat = create(owner, theirs.id).json()
    [rule] = theirs.resume().json()["chat_rules"]
    assert rule == {
        "entry_id": entry["id"],
        "owner_id": None,
        "handle": None,
        "project": {"owner": "maintainer", "slug": "maity"},
        "allowed": None,
        "denied": "no customer names",
        "conversations": [chat["id"]],
    }


def test_no_item_without_a_text_or_without_a_chat_across_the_boundary(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    rules_entry(other, theirs.id, owner.id)
    assert theirs.resume().json()["chat_rules"] == []  # in no chat yet
    second = flow.agent(make_client, other)
    room = create(other, theirs.id, second.id).json()  # its own side only
    assert item(room, theirs.id).get("waiting_for") is None
    assert view(theirs, room["id"]).json()["chat_rules"] == []
    late = other_human(make_client, migrated, "late")
    allow(other, agents=[theirs.id], owner_id=late.id, their_human=True)  # no text
    chat = create(late, theirs.id).json()
    assert item(chat, theirs.id)["waiting_for"] == []
    assert view(theirs, chat["id"]).json()["chat_rules"] == []
    assert theirs.resume().json()["chat_rules"] == []


def test_a_waiting_agent_gets_no_rules(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    late = other_human(make_client, migrated, "late")
    theirs = flow.agent(make_client, other)
    rules_entry(other, theirs.id, owner.id)
    chat = create(owner, theirs.id).json()
    assert view(owner, chat["id"]).status_code == 200
    joined = owner.post(f"{BASE}/{chat['id']}/participants", {"member_id": late.id})
    assert joined.status_code == 200, joined.text
    assert item(view(owner, chat["id"]).json(), theirs.id)["waiting_for"] == [late.id]
    assert theirs.resume().json()["chat_rules"] == []


def test_a_change_wakes_the_agent_and_only_it_reads_the_event(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    entry = allow(other, agents=[theirs.id], owner_id=owner.id, their_human=True)
    chat = create(owner, theirs.id).json()
    assert changes(migrated) == []  # an entry with no text sets no rule
    patched = other.patch(f"/me/chat-access/allow/{entry['id']}", {"denied": "no prices"})
    assert patched.status_code == 200, patched.text
    [event] = changes(migrated)
    assert event.payload == {"entry_id": entry["id"]}
    assert event.audience == [f"member:{theirs.id}"]
    assert event.conversation_id is None
    readers = {
        who: events.readable_by(event, membership(migrated, who), who)
        for who in (theirs.id, owner.id, other.id)
    }
    # The project's owner sees all else, and the agent's owner reads its chats along: not this.
    assert readers == {theirs.id: True, owner.id: False, other.id: False}
    got = theirs.get("/projects/maintainer/maity/events?after=0").json()["items"]
    assert any(e["kind"] == "chat_rules_changed" for e in got)
    # A change that leaves texts and reach as they were sends nothing.
    again = other.patch(f"/me/chat-access/allow/{entry['id']}", {"their_human": True})
    assert again.status_code == 200, again.text
    assert len(changes(migrated)) == 1
    assert view(theirs, chat["id"]).json()["chat_rules"][0]["denied"] == "no prices"


def test_removal_and_a_new_entry_with_a_text_are_changes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    plain = allow(other, agents=[theirs.id], owner_id=owner.id, their_human=True)
    create(owner, theirs.id)
    ruled = allow(other, agents=[theirs.id], owner_id=owner.id, their_human=True, allowed="docs")
    assert [e.payload for e in changes(migrated)] == [{"entry_id": ruled["id"]}]
    gone = other.delete(f"/me/chat-access/allow/{ruled['id']}")
    assert gone.status_code == 204, gone.text
    assert [e.payload for e in changes(migrated)][-1] == {"entry_id": ruled["id"]}
    assert len(changes(migrated)) == 2
    # The plain entry still admits it; there are no rules left.
    assert theirs.resume().json()["chat_rules"] == []
    assert other.get("/me/chat-access").json()["allow"][0]["id"] == plain["id"]


def test_an_entry_whose_until_passes_is_a_change(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    entry = rules_entry(other, theirs.id, owner.id, duration="hour")
    chat = create(owner, theirs.id).json()
    before = len(changes(migrated))
    with migrated.begin() as conn:
        conn.execute(
            update(t.chat_access)
            .where(t.chat_access.c.id == entry["id"])
            .values(until=clock.now() - timedelta(minutes=1))
        )
    assert chat_gate.sweep(migrated) == 1
    assert item(view(owner, chat["id"]).json(), theirs.id)["waiting_for"] == [owner.id]
    after = changes(migrated)
    assert len(after) == before + 1
    assert after[-1].payload == {"entry_id": entry["id"]}
    assert after[-1].audience == [f"member:{theirs.id}"]


@pytest.mark.parametrize("read", ["view", "packet"])
def test_an_entry_retargeted_during_the_read_never_shows_another_agents_rules(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
    read: str,
) -> None:
    """v5vp's hint on #1733: an entry moved from agent A to agent B, with a new text, between the
    statements of A's read. On PostgreSQL each statement sees what was committed when it began
    (READ COMMITTED), so the entries, their agents and their texts are read in one statement and
    the texts are not read again; A then gets the old text or none, never B's."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("a single read sees one snapshot on SQLite and MariaDB")
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    second = flow.agent(make_client, other)
    entry = allow(other, agents=[theirs.id], owner_id=owner.id, their_human=True, allowed="for A")
    chat = create(owner, theirs.id).json()
    original = chat_gate.chats_of_owner
    moved: list[bool] = []

    def retarget_first(conn: Any, who: str) -> Any:
        if not moved:
            moved.append(True)
            g = t.chat_access_agent.c
            with migrated.begin() as other_conn:  # its own connection, committed at once
                other_conn.execute(delete(t.chat_access_agent).where(g.entry_id == entry["id"]))
                other_conn.execute(
                    insert(t.chat_access_agent).values(
                        entry_id=entry["id"], side="own", agent_id=second.id
                    )
                )
                other_conn.execute(
                    update(t.chat_access)
                    .where(t.chat_access.c.id == entry["id"])
                    .values(allowed="for B only")
                )
        return original(conn, who)

    monkeypatch.setattr(chat_gate, "chats_of_owner", retarget_first)
    if read == "view":
        got = view(theirs, chat["id"])
        assert got.status_code == 200, got.text
        rules = got.json()["chat_rules"]
    else:
        rules = theirs.resume().json()["chat_rules"]
    assert moved
    assert "for B only" not in str(rules)
    assert [r["allowed"] for r in rules] in ([], ["for A"])


def test_an_entry_coming_to_admit_or_leaving_a_second_chat_of_a_project_is_a_change(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """9s6p on #1733: what an entry admits is compared per chat, not per project, so a widening
    to a second chat of the same project, and the narrowing back, each send the event."""
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    peer = flow.agent(make_client, owner)
    entry = allow(
        other,
        agents=[theirs.id],
        owner_id=owner.id,
        their_human=False,
        their_agents=[peer.id],
        allowed="docs only",
    )
    first = create(other, peer.id, theirs.id).json()
    assert item(first, theirs.id)["waiting_for"] == []
    second = create(owner, theirs.id).json()
    assert item(second, theirs.id)["waiting_for"] == [owner.id]
    before = len(changes(migrated))
    wide = other.patch(f"/me/chat-access/allow/{entry['id']}", {"their_human": True})
    assert wide.status_code == 200, wide.text
    [rule] = theirs.resume().json()["chat_rules"]
    assert rule["conversations"] == sorted([first["id"], second["id"]])
    after = changes(migrated)
    assert len(after) == before + 1
    assert after[-1].payload == {"entry_id": entry["id"]}
    narrow = other.patch(f"/me/chat-access/allow/{entry['id']}", {"their_human": False})
    assert narrow.status_code == 200, narrow.text
    assert item(view(owner, second["id"]).json(), theirs.id)["waiting_for"] == [owner.id]
    assert theirs.resume().json()["chat_rules"][0]["conversations"] == [first["id"]]
    assert len(changes(migrated)) == before + 2


def test_a_write_between_the_until_and_the_lapse_still_announces(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """9s6p on #1733: an entry whose `until` passed admits until the worker lapses it; an owner
    write in between that removes it is the change, and the lapse after it sends no second."""
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    entry = rules_entry(other, theirs.id, owner.id, duration="hour")
    chat = create(owner, theirs.id).json()
    assert item(chat, theirs.id)["waiting_for"] == []
    before = len(changes(migrated))
    with migrated.begin() as conn:
        conn.execute(
            update(t.chat_access)
            .where(t.chat_access.c.id == entry["id"])
            .values(until=clock.now() - timedelta(minutes=1))
        )
    gone = other.delete(f"/me/chat-access/allow/{entry['id']}")
    assert gone.status_code == 204, gone.text
    after = changes(migrated)
    assert len(after) == before + 1
    assert after[-1].payload == {"entry_id": entry["id"]}
    assert after[-1].audience == [f"member:{theirs.id}"]
    chat_gate.sweep(migrated)
    assert len(changes(migrated)) == before + 1
