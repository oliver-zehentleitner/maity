"""docs/api.md §9.7: agree and disagree on a chat message, with its event (§8.2), its wake
(§6.18), the resume packet (§5.2) and its redaction (§8.5)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_bridge_calls import Calls, _pair
from tests.test_group_chats import (
    BASE,
    admit,
    create,
    delete,
    event_row,
    field,
    membership_row,
    other_human,
    read,
    reason,
    redact,
    say,
)
from tests.test_group_chats_part2 import outside_owner


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def path(chat_id: str, seq: int) -> str:
    return f"{BASE}/{chat_id}/messages/{seq}/verdict"


def put(who: Any, chat_id: str, seq: int, value: str, sentence: Any = ..., **extra: Any) -> Any:
    body: dict[str, Any] = {"value": value, **extra}
    if sentence is not ...:
        body["sentence"] = sentence
    if isinstance(who, flow.Human):
        return who.client.put(
            f"/api/v1{path(chat_id, seq)}", json=body, headers={"X-CSRF-Token": who.csrf}
        )
    return who.client.put(f"/api/v1{path(chat_id, seq)}", json=body, headers=who.auth | who.key())


def take_back(who: Any, chat_id: str, seq: int) -> Any:
    return delete(who, path(chat_id, seq))


def verdict_events(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(
                select(t.event).where(t.event.c.kind == "chat_verdict").order_by(t.event.c.seq)
            )
        )


def code(response: Any) -> tuple[int, str]:
    return response.status_code, response.json()["error"]["code"]


def message(who: Any, chat_id: str, seq: int) -> dict[str, Any]:
    found: list[dict[str, Any]] = [m for m in read(who, chat_id).json()["items"] if m["seq"] == seq]
    assert len(found) == 1
    return found[0]


# --- giving, replacing, taking back --------------------------------------------------------


def test_a_verdict_is_given_replaced_and_taken_back_one_event_per_change(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    seq = say(agent, agent.id, "Shall I tag v1.2?").json()["seq"]
    given = put(owner, agent.id, seq, "agree")
    assert given.status_code == 200, given.text
    body = given.json()
    assert body["seq"] == seq and body["body"] == "Shall I tag v1.2?"
    [first] = verdict_events(migrated)
    assert body["verdicts"] == [
        {"by": owner.id, "value": "agree", "sentence": None, "at": body["verdicts"][0]["at"],
         "seq": first.seq}
    ]  # fmt: skip
    assert first.payload == {
        "conversation": {"id": agent.id, "kind": "direct", "title": None},
        "message_seq": seq,
        "author": agent.id,
        "value": "agree",
        "previous": None,
        "sentence": None,
    }
    assert sorted(first.audience) == sorted([f"member:{agent.id}", f"member:{owner.id}"])
    assert first.conversation_id == agent.id

    again = put(owner, agent.id, seq, "agree")  # changes nothing: no event
    assert again.status_code == 200 and len(verdict_events(migrated)) == 1
    changed = put(owner, agent.id, seq, "disagree", "  Not before the release.  ")
    assert changed.status_code == 200, changed.text
    second = verdict_events(migrated)[-1]
    assert (second.payload["value"], second.payload["previous"]) == ("disagree", "agree")
    assert second.payload["sentence"] == "Not before the release."
    [shown] = changed.json()["verdicts"]
    assert (shown["value"], shown["sentence"], shown["seq"]) == (
        "disagree",
        "Not before the release.",
        second.seq,
    )
    other_sentence = put(owner, agent.id, seq, "disagree", "After it, then.")
    assert other_sentence.status_code == 200 and len(verdict_events(migrated)) == 3
    assert verdict_events(migrated)[-1].payload["previous"] == "disagree"

    back = take_back(owner, agent.id, seq)
    assert back.status_code == 200, back.text
    assert back.json()["verdicts"] == []
    last = verdict_events(migrated)[-1]
    assert (last.payload["value"], last.payload["previous"], last.payload["sentence"]) == (
        None,
        "disagree",
        None,
    )
    again_back = take_back(owner, agent.id, seq)  # nothing to take back: no event
    assert again_back.status_code == 200 and len(verdict_events(migrated)) == 4
    with migrated.connect() as conn:
        assert conn.execute(select(t.chat_verdict)).all() == []


def test_the_sentence_rules(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    seq = say(agent, agent.id, "Ready?").json()["seq"]
    with_agree = put(owner, agent.id, seq, "agree", "yes indeed")
    assert code(with_agree) == (400, "invalid")
    assert field(with_agree, "sentence") == "agree_has_none"
    assert put(owner, agent.id, seq, "agree", "   ").status_code == 200  # empty: none
    too_long = put(owner, agent.id, seq, "disagree", "x" * 501)
    assert field(too_long, "sentence") == "string_too_long"
    exact = put(owner, agent.id, seq, "disagree", " " + "ü" * 500 + " ")  # code points, trimmed
    assert exact.status_code == 200, exact.text
    assert exact.json()["verdicts"][0]["sentence"] == "ü" * 500
    blank = put(owner, agent.id, seq, "disagree", "")
    assert blank.json()["verdicts"][0]["sentence"] is None
    assert field(put(owner, agent.id, seq, "maybe"), "value") == "literal_error"
    assert code(put(owner, agent.id, seq, "agree", mentions=[])) == (400, "invalid")


def test_a_sentence_resolves_no_mention(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, agent.id, guest.id).json()
    seq = say(agent, chat["id"], "Tag it?").json()["seq"]
    assert put(owner, chat["id"], seq, "disagree", "ask @guest first").status_code == 200
    [row] = verdict_events(migrated)
    assert "mentions" not in row.payload
    assert f"member:{guest.id}" in row.audience  # a participant, not by the mention
    assert not events.wakes(row, membership_row(migrated, guest.id), guest.id)


# --- what takes one ------------------------------------------------------------------------


def test_what_takes_a_verdict(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    mine = say(owner, agent.id, "my own words").json()["seq"]
    own = put(owner, agent.id, mine, "agree")
    assert code(own) == (400, "invalid") and field(own, "seq") == "own_message"
    theirs = say(agent, agent.id, "a secret").json()["seq"]
    redacted = redact(owner, theirs)
    assert redacted.status_code == 200, redacted.text
    gone = put(owner, agent.id, theirs, "agree")
    assert field(gone, "seq") == "redacted"
    assert put(owner, agent.id, 999_999, "agree").status_code == 404
    notice = owner.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "no chat"},
    ).json()["seq"]
    assert put(owner, agent.id, notice, "agree").status_code == 404  # no chat message here
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, agent.id, guest.id).json()
    in_group = say(agent, chat["id"], "in the room").json()["seq"]
    assert put(owner, agent.id, in_group, "agree").status_code == 404  # another chat's
    assert verdict_events(migrated) == []


def test_who_gives_one(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> None:
    agent = flow.agent(make_client, owner)
    other_agent = flow.agent(make_client, owner)
    seq = say(agent, agent.id, "done").json()["seq"]
    by_agent = put(agent, agent.id, seq, "agree")
    assert (by_agent.status_code, reason(by_agent)) == (403, "humans_only")
    by_other_agent = put(other_agent, agent.id, seq, "agree")
    assert reason(by_other_agent) == "humans_only"
    stranger = other_human(make_client, migrated, "stranger", role="admin")
    assert put(stranger, agent.id, seq, "agree").status_code == 404  # not its chat
    assert take_back(stranger, agent.id, seq).status_code == 404
    assert take_back(agent, agent.id, seq).status_code == 403
    assert verdict_events(migrated) == []


def test_a_bridge_gives_none(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    served, bridge, _ = _pair(migrated, owner)
    seq = say(owner, served.agent_id, "hello").json()["seq"]
    replied = Calls(make_client(), bridge).post(f"{BASE}/{served.agent_id}/messages", {"body": "x"})
    assert replied.status_code == 403  # a bridge does not write in the direct chat
    calls = Calls(make_client(), bridge)
    refused = calls.client.put(
        f"/api/v1{path(served.agent_id, seq)}",
        json={"value": "agree"},
        headers=calls.headers(served.agent_id),
    )
    assert (refused.status_code, refused.json()["error"]["details"]["reason"]) == (
        403,
        "humans_only",
    )


def test_an_observer_gives_one_without_becoming_a_participant(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other-owner", role="admin")
    their_agent = flow.agent(make_client, other)
    admit(other, their_agent.id, owner.id)
    chat = create(owner, their_agent.id).json()
    assert chat["observers"] == [other.id]
    seq = say(owner, chat["id"], "Shall your agent take the release?").json()["seq"]
    given = put(other, chat["id"], seq, "disagree", "It is on leave.")
    assert given.status_code == 200, given.text
    assert [v["by"] for v in given.json()["verdicts"]] == [other.id]
    view = other.get(f"{BASE}/{chat['id']}").json()
    assert view["access"] == "observer"
    assert [p["member_id"] for p in view["participants"]] == [owner.id, their_agent.id]
    [row] = verdict_events(migrated)
    assert f"member:{other.id}" not in row.audience and row.actor_human_id is None
    assert sorted(row.audience) == sorted([f"member:{owner.id}", f"member:{their_agent.id}"])
    assert say(other, chat["id"], "hi").status_code == 403  # still writes no message


def test_an_owner_outside_the_project_gives_one_in_a_chat_it_reads_along(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    outside, agent = outside_owner(make_client, migrated)
    chat = create(owner, agent.id).json()
    seq = say(owner, chat["id"], "hello").json()["seq"]
    given = put(outside, chat["id"], seq, "agree")
    assert given.status_code == 200, given.text
    [row] = verdict_events(migrated)
    assert (row.actor_membership, row.actor_human_id) == (None, outside.id)
    assert message(owner, chat["id"], seq)["verdicts"][0]["by"] == outside.id


def test_a_participant_in_a_group_chat_gives_one_and_a_closed_chat_takes_none(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, agent.id, guest.id).json()
    seq = say(agent, chat["id"], "I propose Friday.").json()["seq"]
    assert put(guest, chat["id"], seq, "agree").status_code == 200
    assert put(owner, chat["id"], seq, "disagree").status_code == 200
    [first, second] = message(guest, chat["id"], seq)["verdicts"]  # oldest first
    assert (first["by"], second["by"]) == (guest.id, owner.id)
    row = verdict_events(migrated)[0]
    assert row.payload["conversation"] == {
        "id": chat["id"],
        "kind": "group",
        "title": "Release go/no-go",
    }
    assert sorted(row.audience) == sorted(f"member:{m}" for m in (owner.id, agent.id, guest.id))
    delete(guest, f"{BASE}/{chat['id']}/participants/{guest.id}")
    assert put(guest, chat["id"], seq, "disagree").status_code == 404  # no longer reads it
    delete(owner, f"{BASE}/{chat['id']}/participants/{owner.id}")  # the last human: closed
    closed = take_back(owner, chat["id"], seq)
    assert code(closed) == (409, "conversation_closed")
    assert closed.json()["error"]["details"]["closed_reason"] == "no_human"


def test_a_cross_project_chat_takes_none(owner: flow.Human, make_client: ClientFactory) -> None:
    flow.project(owner, "other")
    home = flow.agent(make_client, owner)
    away = flow.agent(make_client, owner, "other")
    made = owner.post("/me/cross-chats", {"participants": [home.id, away.id]})
    assert made.status_code == 201, made.text
    chat_id = made.json()["id"]
    said = home.post(f"/me/cross-chats/{chat_id}/messages", {"body": "hello"})
    assert said.status_code == 201, said.text
    number = said.json()["seq"]
    assert put(owner, chat_id, number, "agree").status_code == 404  # no chat of the project
    assert take_back(owner, chat_id, number).status_code == 404


# --- the event: audience, wake, packet -----------------------------------------------------


def test_it_wakes_only_the_agent_whose_message_it_names(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    bystander = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, author.id, bystander.id, guest.id).json()
    by_agent = say(author, chat["id"], "Tagging now.").json()["seq"]
    by_human = say(guest, chat["id"], "Wait for me.").json()["seq"]
    put(owner, chat["id"], by_agent, "agree")
    put(owner, chat["id"], by_human, "disagree")
    on_agent, on_human = verdict_events(migrated)
    assert on_agent.payload["author"] == author.id and on_human.payload["author"] == guest.id
    for who in (author, bystander):
        assert f"member:{who.id}" in on_agent.audience
    assert events.wakes(on_agent, membership_row(migrated, author.id), author.id)
    assert not events.wakes(on_agent, membership_row(migrated, bystander.id), bystander.id)
    assert not events.wakes(on_agent, membership_row(migrated, guest.id), guest.id)
    assert not events.wakes(on_agent, membership_row(migrated, owner.id), owner.id)
    for principal in (author.id, guest.id, bystander.id):
        assert not events.wakes(on_human, membership_row(migrated, principal), principal)
    # A direct chat: the agent is woken, as by a reply.
    direct = say(author, author.id, "Merged.").json()["seq"]
    put(owner, author.id, direct, "agree")
    on_direct = verdict_events(migrated)[-1]
    assert events.wakes(on_direct, membership_row(migrated, author.id), author.id)
    assert not events.wakes(on_direct, membership_row(migrated, owner.id), owner.id)


def test_the_author_reads_it_in_wait_and_in_the_packet_others_only_in_wait(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    author = flow.agent(make_client, owner)
    bystander = flow.agent(make_client, owner)
    author.resume()
    bystander.resume()
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, author.id, bystander.id, guest.id).json()
    seq = say(author, chat["id"], "Tagging now.").json()["seq"]
    put(guest, chat["id"], seq, "disagree", "Not yet.")
    [row] = verdict_events(migrated)
    packet = [e["seq"] for e in author.resume(cursor=seq).json()["events"]["items"]]
    assert row.seq in packet
    other_packet = [e["seq"] for e in bystander.resume(cursor=seq).json()["events"]["items"]]
    assert row.seq not in other_packet
    seen = bystander.get(f"/projects/maintainer/maity/events?after={seq}").json()["items"]
    assert row.seq in [e["seq"] for e in seen]  # still a participant's to read
    for_author = author.get(f"/projects/maintainer/maity/events?after={seq}").json()["items"]
    [event] = [e for e in for_author if e["seq"] == row.seq]
    assert event["kind"] == "chat_verdict" and event["payload"]["sentence"] == "Not yet."


def test_a_waiting_agent_reads_no_verdict(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other-owner", role="admin")
    waiting = flow.agent(make_client, other)  # not admitted: it waits (§9.6)
    mine = flow.agent(make_client, owner)
    chat = create(owner, mine.id, waiting.id).json()
    seq = say(mine, chat["id"], "Ship it?").json()["seq"]
    assert put(owner, chat["id"], seq, "agree").status_code == 200
    [row] = verdict_events(migrated)
    assert f"member:{waiting.id}" not in row.audience
    with migrated.connect() as conn:
        hidden = events.hidden_redactions(conn, [row])
    assert not events.readable_by(row, membership_row(migrated, waiting.id), waiting.id, hidden)
    assert put(other, chat["id"], seq, "disagree").status_code == 200  # its owner reads along


# --- redaction -----------------------------------------------------------------------------


def test_a_direct_verdict_is_redacted_by_the_human_party_without_events_admin(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    seq = say(agent, agent.id, "Deploy?").json()["seq"]
    put(owner, agent.id, seq, "disagree", "The key is abc123.")
    [row] = verdict_events(migrated)
    refused = redact(agent, row.seq)
    assert (refused.status_code, reason(refused)) == (403, "humans_only")
    with migrated.begin() as conn:  # the human party holds no events:admin
        conn.execute(
            t.membership.update()
            .where(t.membership.c.human_id == owner.id)
            .values(trust="member", role="coder", role_base="coder")
        )
    done = redact(owner, row.seq)
    assert done.status_code == 200, done.text
    assert event_row(migrated, row.seq).payload["redacted"] is True
    [shown] = message(owner, agent.id, seq)["verdicts"]
    assert (shown["value"], shown["sentence"], shown["seq"]) == ("disagree", None, row.seq)
    with migrated.connect() as conn:
        notice = conn.execute(select(t.event).where(t.event.c.kind == "event_redacted")).one()
    assert sorted(notice.audience) == sorted([f"member:{agent.id}", f"member:{owner.id}"])
    assert notice.conversation_id == agent.id
    for_agent = agent.get(f"/projects/maintainer/maity/events/{row.seq}").json()
    assert for_agent["payload"]["reason"] is None  # an agent never reads the reason
    for_owner = owner.get(f"/projects/maintainer/maity/events/{row.seq}").json()
    assert for_owner["payload"]["reason"] == "a secret"
    assert not events.wakes(
        event_row(migrated, row.seq), membership_row(migrated, agent.id), agent.id
    )
    # A new PUT changes it again, with a sentence of its own.
    put(owner, agent.id, seq, "disagree", "No key here.")
    assert message(owner, agent.id, seq)["verdicts"][0]["sentence"] == "No key here."


def test_a_group_verdict_is_redacted_as_a_message_of_the_chat(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    other = other_human(make_client, migrated, "other-owner", role="admin")
    their_agent = flow.agent(make_client, other)
    admit(other, their_agent.id, owner.id)
    guest = other_human(make_client, migrated, "guest")  # no events:admin
    chat = create(owner, agent.id, their_agent.id, guest.id).json()
    seq = say(agent, chat["id"], "Use this token?").json()["seq"]
    put(owner, chat["id"], seq, "disagree", "token abc is mine")
    [row] = verdict_events(migrated)
    assert reason(redact(agent, row.seq)) == "humans_only"
    assert reason(redact(other, row.seq)) == "not_a_participant"  # reads through its agent
    done = redact(guest, row.seq)
    assert done.status_code == 200, done.text
    [shown] = message(owner, chat["id"], seq)["verdicts"]
    assert (shown["value"], shown["sentence"]) == ("disagree", None)
    as_owner = owner.get(f"/projects/maintainer/maity/events/{row.seq}").json()
    assert as_owner["payload"]["reason"] == "a secret"
    as_agent = agent.get(f"/projects/maintainer/maity/events/{row.seq}").json()
    assert as_agent["payload"]["reason"] is None


def test_a_closed_chats_verdict_is_redacted_by_a_former_human_or_blind(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, agent.id, guest.id).json()
    seq = say(agent, chat["id"], "Done?").json()["seq"]
    put(owner, chat["id"], seq, "disagree", "first secret")
    put(guest, chat["id"], seq, "disagree", "second secret")
    first, second = verdict_events(migrated)
    delete(guest, f"{BASE}/{chat['id']}/participants/{guest.id}")
    delete(owner, f"{BASE}/{chat['id']}/participants/{owner.id}")  # closes it
    assert redact(owner, first.seq, expect="closed_chat_message").status_code == 200
    admin = other_human(make_client, migrated, "admin", role="admin")
    blind = redact(admin, second.seq, expect="closed_chat_message")
    assert (blind.status_code, blind.json()) == (200, {"seq": second.seq, "redacted": True})
    assert event_row(migrated, second.seq).redacted


def test_a_redacted_message_keeps_its_verdict_events_and_reads_none(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    seq = say(agent, agent.id, "the token is abc").json()["seq"]
    put(owner, agent.id, seq, "disagree", "Take it out.")
    [row] = verdict_events(migrated)
    assert redact(owner, seq).status_code == 200
    shown = message(owner, agent.id, seq)
    assert shown["redacted"] is True and shown["verdicts"] == []
    assert not event_row(migrated, row.seq).redacted
    assert field(put(owner, agent.id, seq, "agree"), "seq") == "redacted"


# --- the message shape ----------------------------------------------------------------------


def test_every_message_carries_verdicts_and_the_list_preview_none(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    sent = say(owner, agent.id, "hello")
    assert sent.json()["verdicts"] == []
    reply = say(agent, agent.id, "hi").json()["seq"]
    put(owner, agent.id, reply, "agree")
    items = read(agent, agent.id).json()["items"]
    assert [m["verdicts"] for m in items][0] == []
    [v] = items[1]["verdicts"]
    assert set(v) == {"by", "value", "sentence", "at", "seq"} and v["by"] == owner.id
    [item] = [i for i in owner.get(BASE).json()["items"] if i["id"] == agent.id]
    assert "verdicts" not in item["last_message"]
