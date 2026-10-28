"""docs/api.md §8.8: listing the project's messages."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import paging
from maity_hub.errors import ApiError
from maity_hub.routes import project_messages
from tests import flow
from tests.conftest import ClientFactory


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def say(who: Any, to: str, body: str = "hello", type_: str = "notice") -> int:
    done = who.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": type_, "to": to, "body": body},
    )
    assert done.status_code == 201, done.text
    seq: int = done.json()["seq"]
    return seq


def listed(who: Any, query: str = "") -> Any:
    return who.get(f"/projects/maintainer/maity/messages{query}")


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
    say(owner, "trust:admin")  # not the agent's role
    sent = say(agent, owner.id)
    assert seqs(listed(agent)) == [sent, to_agent, to_all]
    on_events = agent.get("/projects/maintainer/maity/events?after=0").json()["items"]
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
    chat = owner.post(
        f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "private"}
    )
    assert chat.status_code == 201, chat.text
    assert seqs(listed(owner)) == [note]
    assert seqs(listed(agent)) == [note]


def test_a_redacted_message_keeps_its_place_as_a_tombstone(owner: flow.Human) -> None:
    kept = say(owner, "all", "kept")
    gone = say(owner, "all", "secret", "blocker")
    assert (
        owner.post(
            f"/projects/maintainer/maity/events/{gone}/redact", {"reason": "a secret"}
        ).status_code
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
    sent = owner.post(
        f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "private"}
    )
    seq = sent.json()["seq"]
    done = owner.post(f"/projects/maintainer/maity/events/{seq}/redact", {"reason": "x"})
    assert done.status_code == 200, done.text
    assert seq not in seqs(listed(owner))


def test_a_stranger_gets_not_found(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    say(owner, "all")
    stranger = flow.human(make_client, migrated, "stranger")
    refused = listed(stranger)
    assert refused.status_code == 404


def test_a_sparse_filter_costs_a_bounded_page_and_continues_without_skipping(
    owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(project_messages, "SCAN_BUDGET", 3)
    monkeypatch.setattr(project_messages, "BATCH", 2)
    wanted = say(owner, "all", "the one", "blocker")
    for n in range(8):
        say(owner, "all", f"note {n}")
    found: list[int] = []
    pages = 0
    answer = listed(owner, "?type=blocker&limit=1").json()
    while True:
        pages += 1
        found += [i["seq"] for i in answer["items"]]
        if answer["next_cursor"] is None:
            break
        assert pages < 20
        answer = listed(owner, f"?type=blocker&limit=1&cursor={answer['next_cursor']}").json()
    assert found == [wanted]
    assert pages > 1  # short or empty pages carried a cursor on the way
    everything = [i["seq"] for p in _all_pages(owner, "?limit=2") for i in p["items"]]
    assert len(everything) == 9 and everything == sorted(everything, reverse=True)


def _all_pages(who: Any, query: str) -> list[dict[str, Any]]:
    pages = [listed(who, query).json()]
    while pages[-1]["next_cursor"] is not None:
        pages.append(listed(who, f"{query}&cursor={pages[-1]['next_cursor']}").json())
        assert len(pages) < 50
    return pages


@pytest.mark.parametrize("seq", [-1, 2**63, 2**100, True, "5", 1.5, None])
def test_a_cursor_with_a_seq_outside_the_bigint_range_is_invalid(seq: Any) -> None:
    bound = paging.scope(after=None, before=None, type=[])
    with pytest.raises(ApiError) as refused:
        paging.unseq(paging.seq_cursor(seq, bound), bound)
    assert refused.value.details["fields"] == {"cursor": "invalid"}


def test_the_edge_seqs_are_valid_cursors_and_a_huge_one_is_refused_over_http(
    owner: flow.Human,
) -> None:
    say(owner, "all")
    bound = paging.scope(after=None, before=None, type=[])
    for seq in (0, 2**63 - 1):
        assert paging.unseq(paging.seq_cursor(seq, bound), bound) == seq
        assert listed(owner, f"?cursor={paging.seq_cursor(seq, bound)}").status_code == 200
    huge = listed(owner, f"?cursor={paging.seq_cursor(2**100, bound)}")
    assert huge.status_code == 400
    assert huge.json()["error"]["details"]["fields"] == {"cursor": "invalid"}


def test_a_message_lists_the_attachments_it_names_and_a_tombstone_none(
    make_client: ClientFactory, migrated: Engine, tmp_path: Any
) -> None:
    store = tmp_path / "blobs"
    store.mkdir()
    owner = flow.human(lambda **kw: make_client(attachment_dir=store, **kw), migrated)
    flow.project(owner, "maity")
    agent = flow.agent(lambda **kw: make_client(attachment_dir=store, **kw), owner)
    sent = agent.client.post(
        "/api/v1/projects/maintainer/maity/attachments?name=log.txt",
        content=b"log",
        headers={"Content-Type": "text/plain", **agent.auth, **agent.key()},
    ).json()
    done = agent.post(
        "/projects/maintainer/maity/events",
        {
            "kind": "message",
            "type": "notice",
            "to": "all",
            "body": "see",
            "attachments": [sent["id"]],
        },
    )
    assert done.status_code == 201, done.text
    item = listed(owner).json()["items"][0]
    assert [a["id"] for a in item["attachments"]] == [sent["id"]]
    assert set(item["attachments"][0]) == {"id", "name", "size", "type", "kind", "width", "height"}
    redacted = owner.post(
        f"/projects/maintainer/maity/events/{done.json()['seq']}/redact", {"reason": "x"}
    )
    assert redacted.status_code == 200
    assert listed(owner).json()["items"][0]["attachments"] == []
