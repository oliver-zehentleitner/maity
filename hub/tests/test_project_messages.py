"""docs/api.md §8.8: listing the project's messages."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def say(who: Any, to: str, body: str = "hello", type_: str = "notice") -> int:
    done = who.post(
        "/projects/maity/events", {"kind": "message", "type": type_, "to": to, "body": body}
    )
    assert done.status_code == 201, done.text
    seq: int = done.json()["seq"]
    return seq


def listed(who: Any, query: str = "") -> Any:
    return who.get(f"/projects/maity/messages{query}")


def seqs(answer: Any) -> list[int]:
    assert answer.status_code == 200, answer.text
    return [item["seq"] for item in answer.json()["items"]]


def test_the_listing_is_newest_first_and_an_item_has_the_reading_shape(owner: flow.Human) -> None:
    first = say(owner, "all", "one")
    second = say(owner, "all", "two", "blocker")
    answer = listed(owner)
    assert seqs(answer) == [second, first]
    assert answer.json()["next_cursor"] is None
    item = answer.json()["items"][0]
    assert set(item) == {
        "id",
        "seq",
        "type",
        "from",
        "to",
        "task_id",
        "body",
        "sent_at",
        "mentions",
        "attachments",
        "redacted",
        "redaction",
    }
    assert item["id"] == f"evt-{second}" and item["type"] == "blocker" and item["to"] == "all"
    assert item["from"] == owner.id and item["body"] == "two"
    assert item["attachments"] == [] and item["redacted"] is False and item["redaction"] is None


def test_a_member_lists_what_it_can_read_through_events(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    other = flow.agent(make_client, owner)
    to_all = say(owner, "all")
    to_agent = say(owner, agent.id)
    say(owner, other.id)  # another member's
    say(owner, "role:admin")  # not the agent's role
    sent = say(agent, owner.id)
    assert seqs(listed(agent)) == [sent, to_agent, to_all]
    on_events = agent.get("/projects/maity/events?after=0").json()["items"]
    assert sorted(
        e["seq"] for e in on_events if e["kind"] == "message" and e["seq"] in (to_all, to_agent)
    ) == [to_all, to_agent]
    assert len(seqs(listed(owner))) == 5  # an owner reads every project message


def test_type_filters_as_a_set_and_chat_or_unknown_is_refused(owner: flow.Human) -> None:
    note = say(owner, "all", "n")
    blocker = say(owner, "all", "b", "blocker")
    handover = say(owner, "all", "h", "handover")
    both = seqs(listed(owner, "?type=blocker&type=notice"))
    assert both == seqs(listed(owner, "?type=notice,blocker")) == [blocker, note]
    assert seqs(listed(owner, "?type=handover")) == [handover]
    for bad in ("chat", "nonsense"):
        refused = listed(owner, f"?type={bad}")
        assert refused.status_code == 400
        assert refused.json()["error"]["details"]["fields"] == {"type": "unknown"}


def test_before_pages_down_and_after_catches_up(owner: flow.Human) -> None:
    made = [say(owner, "all", str(n)) for n in range(5)]
    assert seqs(listed(owner, f"?before={made[3]}")) == [made[2], made[1], made[0]]
    assert seqs(listed(owner, f"?after={made[1]}")) == [made[2], made[3], made[4]]  # oldest first
    assert seqs(listed(owner, "?after=0&limit=2")) == [made[0], made[1]]


def test_a_cursor_continues_in_its_direction_and_only_with_its_own_query(
    owner: flow.Human,
) -> None:
    made = [say(owner, "all", str(n)) for n in range(5)]
    page = listed(owner, "?limit=2").json()
    assert [i["seq"] for i in page["items"]] == [made[4], made[3]]
    more = listed(owner, f"?limit=2&cursor={page['next_cursor']}").json()
    assert [i["seq"] for i in more["items"]] == [made[2], made[1]]
    last = listed(owner, f"?limit=2&cursor={more['next_cursor']}").json()
    assert [i["seq"] for i in last["items"]] == [made[0]] and last["next_cursor"] is None
    up = listed(owner, "?after=0&limit=2").json()
    onward = listed(owner, f"?after=0&limit=2&cursor={up['next_cursor']}").json()
    assert [i["seq"] for i in onward["items"]] == [made[2], made[3]]
    for changed in (
        f"?limit=2&type=notice&cursor={page['next_cursor']}",  # type added
        f"?limit=2&before={made[4]}&cursor={page['next_cursor']}",  # before added
        f"?limit=2&cursor={up['next_cursor']}",  # after left out
        "?limit=2&cursor=garbage",
    ):
        refused = listed(owner, changed)
        assert refused.status_code == 400
        assert refused.json()["error"]["details"]["fields"] == {"cursor": "invalid"}


def test_after_and_before_are_integers_and_never_together(owner: flow.Human) -> None:
    for query, field in (
        ("?after=latest", "after"),
        ("?before=x", "before"),
        ("?after=-1", "after"),
    ):
        refused = listed(owner, query)
        assert refused.status_code == 400
        assert field in refused.json()["error"]["details"]["fields"]
    both = listed(owner, "?after=1&before=9")
    assert both.status_code == 400 and "before" in both.json()["error"]["details"]["fields"]
    assert listed(owner, "?limit=0").status_code == 400
    assert listed(owner, "?limit=201").status_code == 400


def test_a_chat_is_never_listed(owner: flow.Human, make_client: ClientFactory) -> None:
    agent = flow.agent(make_client, owner)
    note = say(owner, "all")
    chat = owner.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "private"})
    assert chat.status_code == 201, chat.text
    assert seqs(listed(owner)) == [note]
    assert seqs(listed(agent)) == [note]


def test_a_redacted_message_keeps_its_place_as_a_tombstone(owner: flow.Human) -> None:
    kept = say(owner, "all", "kept")
    gone = say(owner, "all", "secret", "blocker")
    assert (
        owner.post(f"/projects/maity/events/{gone}/redact", {"reason": "a secret"}).status_code
        == 200
    )
    items = listed(owner).json()["items"]
    tomb = next(i for i in items if i["seq"] == gone)
    assert tomb["redacted"] is True and tomb["body"] is None and tomb["mentions"] == []
    assert (tomb["type"], tomb["to"], tomb["task_id"], tomb["attachments"]) == (
        None,
        None,
        None,
        [],
    )
    assert tomb["from"] == owner.id and tomb["sent_at"]
    assert tomb["redaction"]["by"] == owner.id and tomb["redaction"]["reason"] == "a secret"
    assert gone not in seqs(listed(owner, "?type=blocker"))  # a tombstone has no type
    assert seqs(listed(owner, "?type=notice")) == [kept]


def test_a_redacted_chat_message_is_not_listed_either(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    sent = owner.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "private"})
    seq = sent.json()["seq"]
    done = owner.post(f"/projects/maity/events/{seq}/redact", {"reason": "x"})
    assert done.status_code == 200, done.text
    assert seq not in seqs(listed(owner))


def test_a_stranger_gets_not_found(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    say(owner, "all")
    stranger = flow.human(make_client, migrated, "stranger")
    refused = listed(stranger)
    assert refused.status_code == 404
