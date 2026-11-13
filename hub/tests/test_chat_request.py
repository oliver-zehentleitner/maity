"""docs/api.md §9.6 "The request": the personal request the hub files to an owner whose agents
wait for, or are held for, another side; one per owner pair, kept up to date while open, its
replies (allow for a time, no, block) with the ticks and the reach, the hub's withdrawal, and a
new request when something still waits after an answer or an allow entry ends."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import chat_gate, clock
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
BASE = f"{PROJECT}/conversations"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def project_id(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


def other_human(
    make_client: ClientFactory, engine: Engine, handle: str, trust: str = "admin"
) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, project_id(engine), trust, human_id=human.id)
    return human


def create(who: Any, *participants: str, title: str = "Release") -> dict[str, Any]:
    made = who.post(BASE, {"title": title, "participants": list(participants)})
    assert made.status_code == 201, made.text
    found: dict[str, Any] = made.json()
    return found


def waiting_for(who: Any, chat_id: str, member_id: str) -> Any:
    chat = who.get(f"{BASE}/{chat_id}").json()
    [found] = [p for p in chat["participants"] if p["member_id"] == member_id]
    return found.get("waiting_for")


def here(who: Any, chat_id: str) -> list[str]:
    chat = who.get(f"{BASE}/{chat_id}").json()
    return [p["member_id"] for p in chat["participants"]]


def requests(engine: Engine, human_id: str, status: str | None = "open") -> list[Any]:
    with engine.connect() as conn:
        query = select(t.request).where(t.request.c.to_human == human_id)
        if status is not None:
            query = query.where(t.request.c.status == status)
        rows = conn.execute(query.order_by(t.request.c.created_at, t.request.c.id)).all()
    return [r for r in rows if (r.proposal or {}).get("kind") == "chat_access"]


def the_request(engine: Engine, human_id: str) -> Any:
    [found] = requests(engine, human_id)
    return found


def answer(who: Any, request_id: str, **body: Any) -> Any:
    return who.post(f"/requests/{request_id}/answer", body)


def fields(response: Any) -> Any:
    return response.json()["error"]["details"].get("fields")


def left(engine: Engine, chat_id: str) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.event.c.payload)
            .where(t.event.c.conversation_id == chat_id, t.event.c.kind == "conversation_updated")
            .order_by(t.event.c.seq)
        ).scalars()
        return [r for p in rows for r in p["changed"].get("participants_removed", [])]


def test_one_request_per_owner_pair_names_the_chats(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    first = create(owner, theirs.id, title="Release")
    row = the_request(migrated, other.id)
    assert row.filed_by == "hub" and row.personal and row.project_id is None
    assert row._mapping["class"] == "consent"
    assert row.title == "maintainer and their agents want to chat with your agents"
    assert first["id"] in row.summary and '"Release"' in row.summary
    second = create(owner, theirs.id, title="Docs")
    again = the_request(migrated, other.id)  # the same request, brought up to date
    assert again.id == row.id
    assert first["id"] in again.summary and second["id"] in again.summary
    assert requests(migrated, owner.id) == []  # the side waited for is not asked
    shown = other.get(f"/requests/{row.id}")
    assert shown.status_code == 200, shown.text
    body = shown.json()
    assert [r["id"] for r in body["replies"]] == [
        "allow_hour",
        "allow_day",
        "allow_week",
        "allow_always",
        "no",
        "block",
    ]
    assert body["chat_access_request"] == {
        "side": {"id": owner.id, "handle": "maintainer"},
        "agents": [
            {
                "id": theirs.id,
                "handle": body["chat_access_request"]["agents"][0]["handle"],
                "waiting": True,
                "held": False,
            }
        ],
        "their_human_in_chat": True,
    }
    listed = other.get("/requests").json()["items"]
    assert row.id in [i["id"] for i in listed]


def test_an_allow_with_the_human_ticked_admits_and_closes_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    mine = flow.agent(make_client, owner)
    chat = create(owner, theirs.id, mine.id)
    row = the_request(migrated, other.id)
    got = answer(
        other,
        row.id,
        reply_id="allow_day",
        chat_access={"their_human": True, "allowed": "web only", "denied": "no releases"},
    )
    assert got.status_code == 200, got.text
    assert waiting_for(owner, chat["id"], theirs.id) == []
    [entry] = other.get("/me/chat-access").json()["allow"]
    assert entry["agents"] == [theirs.id] and entry["owner_id"] == owner.id
    assert entry["their_agents"] == [mine.id] and entry["their_human"] is True
    assert entry["duration"] == "day" and entry["until"] is not None
    assert entry["allowed"] == "web only" and entry["denied"] == "no releases"
    assert requests(migrated, other.id) == []  # nothing waits: no new one


def test_without_the_human_the_agent_waits_and_a_new_request_follows(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    mine = flow.agent(make_client, owner)
    chat = create(owner, theirs.id, mine.id)
    row = the_request(migrated, other.id)
    assert answer(other, row.id, reply_id="allow_always").status_code == 200
    [entry] = other.get("/me/chat-access").json()["allow"]
    assert entry["their_agents"] == [mine.id] and entry["their_human"] is False
    assert entry["duration"] is None
    assert waiting_for(owner, chat["id"], theirs.id) == [owner.id]  # the human sits there
    fresh = the_request(migrated, other.id)
    assert fresh.id != row.id


def test_no_lets_the_waiting_agents_leave(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    chat = create(owner, theirs.id)
    row = the_request(migrated, other.id)
    assert answer(other, row.id, reply_id="no").status_code == 200
    assert theirs.id not in here(owner, chat["id"])
    assert left(migrated, chat["id"]) == [
        {"member_id": theirs.id, "by": other.id, "reason": "declined"}
    ]
    assert other.get("/me/chat-access").json() == {"allow": [], "deny": []}
    assert requests(migrated, other.id) == []


def test_block_writes_a_deny_and_the_agents_leave(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    chat = create(owner, theirs.id)
    row = the_request(migrated, other.id)
    assert answer(other, row.id, reply_id="block").status_code == 200
    [deny] = other.get("/me/chat-access").json()["deny"]
    assert deny["agents"] == [theirs.id] and deny["owner_id"] == owner.id
    assert left(migrated, chat["id"])[-1]["reason"] == "denied_participant"
    assert requests(migrated, other.id) == []


def test_the_owners_withdrawal_counts_as_no(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    chat = create(owner, theirs.id)
    row = the_request(migrated, other.id)
    got = other.post(f"/requests/{row.id}/withdraw", {})
    assert got.status_code == 200, got.text
    assert left(migrated, chat["id"])[-1]["reason"] == "declined"
    assert requests(migrated, other.id) == []


def test_the_hub_withdraws_it_when_nothing_waits(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    chat = create(owner, theirs.id)
    row = the_request(migrated, other.id)
    gone = owner.delete(f"{BASE}/{chat['id']}/participants/{theirs.id}")
    assert gone.status_code == 200, gone.text
    [closed] = requests(migrated, other.id, status=None)
    assert closed.id == row.id and closed.status == "withdrawn"
    assert closed.withdraw_reason == "withdrawn"


def test_the_ticks_and_the_reach(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    first = flow.agent(make_client, other)
    second = flow.agent(make_client, other)
    mine = flow.agent(make_client, owner)
    create(owner, first.id, second.id, mine.id)
    row = the_request(migrated, other.id)
    stray = answer(other, row.id, reply_id="allow_hour", chat_access={"agents": [mine.id]})
    assert stray.status_code == 400 and fields(stray) == {
        "chat_access.agents": "not_on_this_request"
    }
    every = answer(other, row.id, reply_id="allow_hour", chat_access={"agents": "all"})
    assert every.status_code in (400, 422)
    with_no = answer(other, row.id, reply_id="no", chat_access={"their_human": True})
    assert with_no.status_code == 400 and fields(with_no) == {"chat_access": "allow_only"}
    text = answer(other, row.id, text="maybe")
    assert text.status_code == 400 and fields(text) == {"reply_id": "required"}
    got = answer(
        other,
        row.id,
        reply_id="allow_hour",
        chat_access={"agents": [first.id], "their_agents": "all", "their_human": True},
    )
    assert got.status_code == 200, got.text
    [entry] = other.get("/me/chat-access").json()["allow"]
    assert entry["agents"] == [first.id] and entry["their_agents"] == "all"
    fresh = the_request(migrated, other.id)  # the unticked one still waits
    assert fresh.id != row.id
    shown = other.get(f"/requests/{fresh.id}").json()["chat_access_request"]
    assert [a["id"] for a in shown["agents"]] == [second.id]


def test_chat_access_belongs_to_this_request_only(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    with migrated.begin() as conn:
        from maity_hub.routes.requests import file_hub_digest

        digest = file_hub_digest(conn, other.id, "away", "nobody", [])
    got = answer(other, digest, reply_id="seen", chat_access={"their_human": True})
    assert got.status_code == 400 and fields(got) == {"chat_access": "not_a_chat_request"}


def test_a_held_work_message_asks_the_owner_without_its_text(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    writer = other_human(make_client, migrated, "writer", "member")
    theirs = flow.agent(make_client, other)
    sent = writer.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "notice", "to": theirs.id, "body": "secret plans"},
    )
    assert sent.status_code == 201, sent.text
    seq = sent.json()["seq"]
    row = the_request(migrated, other.id)
    assert row.title == "writer and their agents want to chat with your agents"
    assert f"message {seq} (notice)" in row.summary and "secret plans" not in row.summary
    shown = other.get(f"/requests/{row.id}").json()["chat_access_request"]
    assert [(a["id"], a["waiting"], a["held"]) for a in shown["agents"]] == [
        (theirs.id, False, True)
    ]
    chat_gate.sweep(migrated)  # a held message keeps it open
    assert the_request(migrated, other.id).id == row.id
    again = writer.post(
        f"{PROJECT}/events",
        {"kind": "message", "type": "blocker", "to": theirs.id, "body": "more"},
    )
    assert again.status_code == 201, again.text
    joined = the_request(migrated, other.id)
    assert joined.id == row.id and f"message {again.json()['seq']} (blocker)" in joined.summary
    got = answer(other, row.id, reply_id="allow_week", chat_access={"their_human": True})
    assert got.status_code == 200, got.text
    [entry] = other.get("/me/chat-access").json()["allow"]
    assert entry["owner_id"] == writer.id and entry["their_human"] is True
    assert entry["their_agents"] == "none"
    assert requests(migrated, other.id) == []  # held before the answer: never asked again


def test_an_allow_that_ends_asks_again(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    chat = create(owner, theirs.id)
    row = the_request(migrated, other.id)
    got = answer(other, row.id, reply_id="allow_hour", chat_access={"their_human": True})
    assert got.status_code == 200, got.text
    assert requests(migrated, other.id) == []
    with migrated.begin() as conn:
        conn.execute(update(t.chat_access).values(until=clock.now() - timedelta(minutes=1)))
    assert chat_gate.sweep(migrated) == 1
    assert waiting_for(owner, chat["id"], theirs.id) == [owner.id]
    assert the_request(migrated, other.id).id != row.id


def test_the_sweep_withdraws_what_ended_out_of_band(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    chat = create(owner, theirs.id)
    row = the_request(migrated, other.id)
    with migrated.begin() as conn:  # as a path that passes no sync would
        conn.execute(
            update(t.conversation)
            .where(t.conversation.c.id == chat["id"])
            .values(closed_at=clock.now(), closed_reason="no_human")
        )
    assert the_request(migrated, other.id).id == row.id
    chat_gate.sweep(migrated)
    [closed] = requests(migrated, other.id, status=None)
    assert closed.status == "withdrawn"


def hold_for(writer: Any, *agents: str) -> None:
    for agent in agents:
        sent = writer.post(
            f"{PROJECT}/events", {"kind": "message", "type": "notice", "to": agent, "body": "hi"}
        )
        assert sent.status_code == 201, sent.text


def held_two(
    make_client: ClientFactory, migrated: Engine
) -> tuple[flow.Human, flow.Human, Any, Any, Any]:
    other = other_human(make_client, migrated, "other")
    writer = other_human(make_client, migrated, "writer", "member")
    gone, kept = flow.agent(make_client, other), flow.agent(make_client, other)
    hold_for(writer, gone.id, kept.id)
    row = the_request(migrated, other.id)
    deleted = other.delete(f"/agents/{gone.id}?cascade=true")
    assert deleted.status_code == 200, deleted.text
    return other, writer, gone, kept, row


def test_a_deleted_agent_is_asked_about_no_more(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """9s6p on #1718 (P2): an agent deleted while its request is open leaves the request, so the
    view no longer offers it and `block` names only the agents that are left."""
    other, writer, gone, kept, row = held_two(make_client, migrated)
    again = the_request(migrated, other.id)
    assert again.id == row.id
    assert [a for h in again.proposal["held"] for a in h["agents"]] == [kept.id]
    shown = other.get(f"/requests/{row.id}").json()["chat_access_request"]
    assert [a["id"] for a in shown["agents"]] == [kept.id]
    got = answer(other, row.id, reply_id="block")
    assert got.status_code == 200, got.text
    [deny] = other.get("/me/chat-access").json()["deny"]
    assert deny["agents"] == [kept.id] and deny["owner_id"] == writer.id


def test_the_default_allow_after_a_deletion_admits_the_agents_left(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other, writer, gone, kept, row = held_two(make_client, migrated)
    got = answer(other, row.id, reply_id="allow_day", chat_access={"their_human": True})
    assert got.status_code == 200, got.text
    [entry] = other.get("/me/chat-access").json()["allow"]
    assert entry["agents"] == [kept.id] and entry["owner_id"] == writer.id


def test_a_request_whose_only_agent_is_deleted_is_withdrawn(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other")
    writer = other_human(make_client, migrated, "writer", "member")
    gone = flow.agent(make_client, other)
    hold_for(writer, gone.id)
    row = the_request(migrated, other.id)
    assert other.delete(f"/agents/{gone.id}?cascade=true").status_code == 200
    [closed] = requests(migrated, other.id, status=None)
    assert closed.id == row.id and closed.status == "withdrawn"
    shown = other.get(f"/requests/{row.id}").json()["chat_access_request"]
    assert shown["agents"] == []


def test_a_chat_change_does_not_wait_for_the_owners_entry_change(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """9s6p on #1718 (P2): a chat change that brings the owner's open request up to date holds
    its project's lock and then only the request's row, so a write under /me/chat-access, which
    holds the owner's human row and then takes the projects', does not meet it in the opposite
    order. (Filing a new request writes the owner's notification record, which locks the
    human's row as every record does: that path still meets it, and is run again.)"""
    if migrated.dialect.name != "postgresql":
        pytest.skip("two writers at once need PostgreSQL; SQLite serialises them already")
    import threading

    from maity_hub import chat_access, events

    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    create(owner, theirs.id, title="Release")
    row = the_request(migrated, other.id)
    outcome: list[int] = []

    def create_chat() -> None:
        made = owner.post(BASE, {"title": "Docs", "participants": [theirs.id]})
        outcome.append(made.status_code)

    with migrated.begin() as conn:  # as /me/chat-access holds it: the owner's human row
        chat_access._lock(conn, other.id)
        racer = threading.Thread(target=create_chat)
        racer.start()
        racer.join(10)
        done = not racer.is_alive()
        if done:
            events.lock_project(conn, project_id(migrated))  # then the project: free again
    racer.join(15)
    assert done, "the chat change waited for the owner's human row"
    assert outcome == [201]
    again = the_request(migrated, other.id)
    assert again.id == row.id and '"Docs"' in again.summary


def test_two_held_messages_at_once_file_one_request(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Two transactions that file for one pair at once collide on the request's id: the second
    waits for the first, then adds its held message to the request the first filed."""
    if migrated.dialect.name != "postgresql":
        pytest.skip("two writers at once need PostgreSQL; SQLite serialises them already")
    import threading

    from maity_hub import chat_request

    other = other_human(make_client, migrated, "other")
    writer = other_human(make_client, migrated, "writer", "member")
    theirs = flow.agent(make_client, other)
    project = project_id(migrated)
    errors: list[BaseException] = []

    def note(seq: int) -> None:
        try:
            with migrated.begin() as conn:
                chat_request.note_held(
                    conn, project, seq, "notice", (writer.id, "human"), writer.id, [theirs.id]
                )
        except BaseException as error:  # pragma: no cover - reported below
            errors.append(error)

    with migrated.begin() as conn:
        chat_request.note_held(
            conn, project, 1, "notice", (writer.id, "human"), writer.id, [theirs.id]
        )
        racer = threading.Thread(target=note, args=(2,))
        racer.start()
        racer.join(1.0)
        assert racer.is_alive()  # its insert waits for this one's
    racer.join(15)
    assert errors == []
    row = the_request(migrated, other.id)
    assert [h["seq"] for h in row.proposal["held"]] == [1, 2]
