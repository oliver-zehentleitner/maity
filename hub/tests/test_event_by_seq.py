"""docs/api.md §8.9: reading one event by its seq, a hidden one answered as a missing one."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
CHATS = f"{PROJECT}/conversations"
# What may not differ between a hidden and a missing event's answer (§8.9).
COMPARED = ("content-type", "content-length", "cache-control", "etag", "last-modified")


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def project_id(engine: Engine, slug: str = "maity") -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == slug)
        ).scalar_one()
    return found


def other_human(
    make_client: ClientFactory, engine: Engine, handle: str, role: str = "member"
) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, project_id(engine), role, human_id=human.id)
    return human


def say(who: Any, to: str, body: str = "hello", project: str = PROJECT) -> int:
    done = who.post(
        f"{project}/events", {"kind": "message", "type": "notice", "to": to, "body": body}
    )
    assert done.status_code == 201, done.text
    seq: int = done.json()["seq"]
    return seq


def direct(who: Any, agent_id: str, body: str = "psst") -> int:
    done = who.post(f"{CHATS}/{agent_id}/messages", {"body": body})
    assert done.status_code == 201, done.text
    seq: int = done.json()["seq"]
    return seq


def one(who: Any, seq: int | str, project: str = PROJECT) -> Any:
    return who.get(f"{project}/events/{seq}")


def listed(who: Any, seq: int) -> dict[str, Any] | None:
    """What `GET /events?after=<seq − 1>` serves the caller for exactly this seq."""
    answer = who.get(f"{PROJECT}/events?after={seq - 1}&limit=1")
    assert answer.status_code == 200, answer.text
    items = answer.json()["items"]
    return items[0] if items and items[0]["seq"] == seq else None


def head(engine: Engine) -> int:
    with engine.connect() as conn:
        found = conn.execute(select(t.event.c.seq).order_by(t.event.c.seq.desc()).limit(1))
        return int(found.scalar() or 0)


def assert_as_missing(hidden: Any, missing: Any) -> None:
    """The same status, the same bytes and the same headers that could tell them apart."""
    assert hidden.status_code == missing.status_code == 404
    assert hidden.content == missing.content
    assert hidden.json()["error"] == {
        "code": "not_found",
        "message": "no such resource",
        "details": {},
    }
    for name in COMPARED:
        assert hidden.headers.get(name) == missing.headers.get(name), name
    assert "etag" not in hidden.headers and "last-modified" not in hidden.headers
    assert hidden.headers["cache-control"] == "no-store"


def nowhere(who: Any, engine: Engine) -> Any:
    """The answer for a seq no event has: one past the head."""
    return one(who, head(engine) + 1000)


# --- the answer ----------------------------------------------------------------------------


def test_a_readable_event_is_the_event_lists_item_plus_its_conversation(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    seq = say(owner, agent.id, "read me")
    answer = one(agent, seq)
    assert answer.status_code == 200, answer.text
    item = answer.json()
    assert item.pop("conversation_id") is None  # not a conversation's message
    assert item == listed(agent, seq)
    assert item["payload"]["body"] == "read me"
    assert answer.headers["cache-control"] == "no-store" and "etag" not in answer.headers


def test_the_answer_is_exactly_the_event_lists_readable_set(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """For every seq and every caller: `200` exactly when `GET /events` serves it (§8.9)."""
    agent = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    admin = other_human(make_client, migrated, "admin-h", "admin")
    member = other_human(make_client, migrated, "member-h")
    # A human outside the room who owns an agent in it, and a participant added later (§8.9).
    reader = other_human(make_client, migrated, "reader-h", "admin")
    theirs = flow.agent(make_client, reader)
    late = other_human(make_client, migrated, "late-h")
    say(owner, "all")
    say(owner, agent.id)
    say(owner, other.id)
    say(owner, "trust:admin")
    direct(owner, agent.id)
    group = owner.post(CHATS, {"title": "room", "participants": [agent.id, member.id, theirs.id]})
    assert group.status_code == 201, group.text
    chat = group.json()["id"]
    sent = owner.post(f"{CHATS}/{chat}/messages", {"body": "in the room"})
    assert sent.status_code == 201, sent.text
    in_room = sent.json()["seq"]
    added = owner.post(f"{CHATS}/{chat}/participants", {"member_id": late.id})
    assert added.status_code == 200, added.text
    redacted = say(owner, other.id, "gone")
    assert owner.post(f"{PROJECT}/events/{redacted}/redact", {"reason": "x"}).status_code == 200
    last = head(migrated)
    for who in (owner, agent, other, admin, member, reader, late):
        for seq in range(1, last + 2):
            served = listed(who, seq)
            answer = one(who, seq)
            if served is None:
                assert answer.status_code == 404, (who, seq)
            else:
                assert answer.status_code == 200, (who, seq, answer.text)
                item = answer.json()
                item.pop("conversation_id")
                assert item == served, (who, seq)
    # The owner of an agent participant reads the room's message along, and its chat (§9.2).
    along = one(reader, in_room)
    assert along.status_code == 200, along.text
    assert along.json()["conversation_id"] == chat
    # The later participant reads it in the chat's history, but the event list does not
    # serve it to them: the answer of a seq nobody has.
    history = late.get(f"{CHATS}/{chat}/messages?before={in_room + 1}")
    assert history.status_code == 200, history.text
    assert in_room in [m["seq"] for m in history.json()["items"]]
    assert listed(late, in_room) is None
    assert_as_missing(one(late, in_room), nowhere(late, migrated))


# --- a hidden event answers as a missing one -----------------------------------------------


def test_a_direct_chat_between_others_answers_as_missing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    admin = other_human(make_client, migrated, "admin-h", "admin")
    seq = direct(owner, agent.id, "between us")
    # The two parties read it, and are given the chat to open it in.
    for party in (owner, agent):
        answer = one(party, seq)
        assert answer.status_code == 200, answer.text
        assert answer.json()["conversation_id"] == agent.id
    # Another agent, and an admin's see-all, do not (§9.1): the answer of a seq nobody has.
    for outsider in (other, admin):
        assert_as_missing(one(outsider, seq), nowhere(outsider, migrated))


def test_an_event_of_another_project_answers_as_missing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "other")
    elsewhere = say(owner, "all", "over there", project="/projects/maintainer/other")
    # The owner reads it in its own project, but not through this one (§1.3).
    assert one(owner, elsewhere, "/projects/maintainer/other").status_code == 200
    assert_as_missing(one(owner, elsewhere), nowhere(owner, migrated))
    agent = flow.agent(make_client, owner)
    assert_as_missing(one(agent, elsewhere), nowhere(agent, migrated))


def test_a_non_member_gets_not_found_for_every_seq(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    seq = say(owner, "all", "for the members")
    # The positive control: a member reads it, so the route answers this seq at all.
    assert one(owner, seq).status_code == 200
    stranger = flow.human(make_client, migrated, "stranger")
    readable = one(stranger, seq)
    assert_as_missing(readable, one(stranger, head(migrated) + 1000))
    assert readable.content == nowhere(owner, migrated).content


def test_a_redacted_event_is_a_tombstone_to_its_readers_and_missing_to_the_rest(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    seq = say(owner, agent.id, "a secret")
    assert_as_missing(one(other, seq), nowhere(other, migrated))
    done = owner.post(f"{PROJECT}/events/{seq}/redact", {"reason": "said too much"})
    assert done.status_code == 200, done.text
    tomb = one(agent, seq)
    assert tomb.status_code == 200, tomb.text
    assert tomb.json()["redacted"] is True and "a secret" not in tomb.text
    item = tomb.json()
    item.pop("conversation_id")
    assert item == listed(agent, seq)
    # The tombstone widens nothing: still missing to who could not read it (§8.5).
    assert_as_missing(one(other, seq), nowhere(other, migrated))


def test_a_redacted_chat_message_keeps_its_conversation(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    seq = direct(owner, agent.id, "oops")
    assert owner.post(f"{PROJECT}/events/{seq}/redact", {"reason": "typo"}).status_code == 200
    answer = one(agent, seq)
    assert answer.status_code == 200 and answer.json()["redacted"] is True
    assert answer.json()["conversation_id"] == agent.id  # it survives the redaction (§8.9)


def test_a_group_chats_conversation_is_given_to_who_reads_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    admin = other_human(make_client, migrated, "admin-h", "admin")
    created = owner.post(CHATS, {"title": "room", "participants": [agent.id, guest.id]})
    assert created.status_code == 201, created.text
    chat = created.json()["id"]
    sent = owner.post(f"{CHATS}/{chat}/messages", {"body": "in the room"})
    assert sent.status_code == 201, sent.text
    seq = sent.json()["seq"]
    for participant in (owner, agent, guest):
        answer = one(participant, seq)
        assert answer.status_code == 200, answer.text
        assert answer.json()["conversation_id"] == chat
    for outsider in (other, admin):  # neither in it nor its see-all (§9.2)
        assert_as_missing(one(outsider, seq), nowhere(outsider, migrated))


def test_a_former_participant_reads_the_event_but_is_not_given_the_chat(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    created = owner.post(CHATS, {"title": "room", "participants": [agent.id, guest.id]})
    assert created.status_code == 201, created.text
    chat = created.json()["id"]
    sent = owner.post(f"{CHATS}/{chat}/messages", {"body": "while you were here"})
    assert sent.status_code == 201, sent.text
    seq = sent.json()["seq"]
    assert one(guest, seq).json()["conversation_id"] == chat
    removed = owner.delete(f"{CHATS}/{chat}/participants/{guest.id}")
    assert removed.status_code in (200, 204), removed.text
    assert guest.get(f"{CHATS}/{chat}/messages").status_code == 404  # no longer reads the chat
    answer = one(guest, seq)
    assert answer.status_code == 200, answer.text  # the event list still serves it (§8.9)
    assert answer.json()["conversation_id"] is None  # never a chat its reader may not open


@pytest.mark.parametrize("seq", ["0", "1000000", "9223372036854775807"])
def test_zero_and_beyond_the_head_are_not_found(owner: flow.Human, seq: str) -> None:
    readable = say(owner, "all")
    # The positive control: the route answers a readable seq, so the 404 below is its own.
    assert one(owner, readable).status_code == 200
    answer = one(owner, seq)
    assert answer.status_code == 404 and answer.json()["error"]["details"] == {}


@pytest.mark.parametrize(
    "seq", ["068216", "00", "-1", "1.0", "abc", "9223372036854775808", "1" * 30, "٣"]
)
def test_a_seq_that_is_no_number_is_invalid(owner: flow.Human, seq: str) -> None:
    answer = one(owner, seq)
    assert answer.status_code == 400, answer.text
    assert answer.json()["error"]["details"]["fields"] == {"seq": "not_a_seq"}


# --- who calls, and what the read leaves --------------------------------------------------


def test_an_isolated_agent_is_forbidden(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    seq = say(owner, "all")
    isolated = owner.post(f"{PROJECT}/members/{agent.id}/isolate", {"reason": "it broke main"})
    assert isolated.status_code == 200, isolated.text
    refused = one(agent, seq)
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "isolated"


def test_reading_one_event_acknowledges_and_delivers_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    assert agent.resume().status_code == 200
    seq = direct(owner, agent.id, "a chat to the agent")

    def state() -> tuple[Any, Any, int]:
        with migrated.connect() as conn:
            acknowledged = conn.execute(select(t.agent_session.c.acknowledged_seq)).all()
            delivered = conn.execute(
                select(t.message_delivery.c.delivered_at).where(t.message_delivery.c.seq == seq)
            ).scalar()
            count = len(conn.execute(select(t.event.c.seq)).all())
        return acknowledged, delivered, count

    before = state()
    assert before[1] is None
    assert one(agent, seq).status_code == 200
    assert state() == before  # no cursor, no delivery, no event written


def test_reading_one_event_does_not_count_as_listening(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """§8.9 writes nothing: not the `events_at` that `GET /events` sets (§5.3)."""
    agent = factory.agent(migrated, project_id(migrated), owner.id, "coder")
    seq = say(owner, agent.agent_id)
    client = make_client()

    def listening() -> Any:
        with migrated.connect() as conn:
            return conn.execute(
                select(t.agent_session.c.events_at).where(t.agent_session.c.id == agent.session_id)
            ).scalar()

    before = listening()
    assert bearer(client, agent, f"{PROJECT}/events/{seq}").status_code == 200
    assert listening() == before
    # The counter-check: the event list does set it, so the look above can see a change.
    assert bearer(client, agent, f"{PROJECT}/events?after={seq - 1}").status_code == 200
    assert listening() != before


# --- a bridge: `Maity-For`, never `for` (§2.3, §8.9) ---------------------------------------


def bearer(client: Any, agent: factory.Agent, path: str, served: str | None = None) -> Any:
    headers = {"Authorization": f"Bearer {agent.value}"}
    if served is not None:
        headers["Maity-For"] = served
    return client.get(f"/api/v1{path}", headers=headers)


def bridged(engine: Engine, owner: flow.Human) -> tuple[factory.Agent, factory.Agent]:
    """An agent and a bridge that serves it (§2.3, "The bridge")."""
    served = factory.agent(engine, project_id(engine), owner.id, "coder", instance="wk2e")
    bridge = factory.agent(engine, project_id(engine), owner.id, "coder", instance="brg1")
    made = owner.post(
        f"{PROJECT}/members/{served.agent_id}/bridges",
        {"bridge": bridge.agent_id, "purpose": "git for the designer"},
    )
    assert made.status_code == 201, made.text
    return served, bridge


def test_maity_for_reads_what_the_list_serves_the_served_agent(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge = bridged(migrated, owner)
    client = make_client()
    told = say(owner, served.agent_id, "for the served agent")
    chat = direct(owner, served.agent_id, "a chat the bridge reads along")
    for seq in (told, chat):
        answer = bearer(client, bridge, f"{PROJECT}/events/{seq}", served.agent_id)
        assert answer.status_code == 200, answer.text
        item = answer.json()
        conversation = item.pop("conversation_id")
        page = bearer(client, bridge, f"{PROJECT}/events?after={seq - 1}&limit=1", served.agent_id)
        assert page.status_code == 200, page.text
        assert [item] == page.json()["items"]
        # The chat is given exactly when the chat route answers the bridge for the agent.
        messages = bearer(
            client, bridge, f"{CHATS}/{served.agent_id}/messages", served.agent_id
        ).status_code
        assert (conversation == served.agent_id) == (seq == chat and messages == 200)
    # The counter-check: without the header the bridge reads as itself, and the served
    # agent's notice is a hidden event to it, the answer of a seq nobody has.
    own = bearer(client, bridge, f"{PROJECT}/events/{told}")
    assert_as_missing(own, bearer(client, bridge, f"{PROJECT}/events/{head(migrated) + 1000}"))


@pytest.mark.parametrize("value", ["served", "me", ""])
def test_a_for_query_is_invalid_and_never_answered_as_the_bridge(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, value: str
) -> None:
    served, bridge = bridged(migrated, owner)
    client = make_client()
    seq = say(owner, served.agent_id)
    named = served.agent_id if value == "served" else value
    for header in (None, served.agent_id):  # with or without Maity-For beside it
        refused = bearer(client, bridge, f"{PROJECT}/events/{seq}?for={named}", header)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["code"] == "invalid"
        assert refused.json()["error"]["details"]["fields"] == {"for": "not_allowed"}
    # Not a bridge's rule alone: a human's `for` is refused too, and before the seq is parsed.
    for path in (f"{PROJECT}/events/{seq}?for={named}", f"{PROJECT}/events/068216?for={named}"):
        refused = owner.get(path)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["details"]["fields"] == {"for": "not_allowed"}
    # The counter-check: the same read with `Maity-For` and no `for` answers the event.
    assert bearer(client, bridge, f"{PROJECT}/events/{seq}", served.agent_id).status_code == 200
