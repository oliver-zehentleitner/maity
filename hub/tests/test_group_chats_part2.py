"""docs/api.md §9.2 (the owner outside the project), §5.2 (conversations in the packet)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, update

from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_group_chats import BASE, create, handle, other_human, read, reason, redact, say


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def outside_owner(make_client: ClientFactory, migrated: Engine) -> tuple[flow.Human, Any]:
    """A human whose agent is a member of the project and who no longer is."""
    human = other_human(make_client, migrated, "outside", role="admin")
    agent = flow.agent(make_client, human)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.human_id == human.id)
            .values(active=None, removed_at=t.membership.c.joined_at)
        )
    return human, agent


def test_an_owner_outside_reads_its_agents_chats_and_nothing_else(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    outside, agent = outside_owner(make_client, migrated)
    guest = other_human(make_client, migrated, "guest")
    with_agent = create(owner, agent.id).json()
    without = create(owner, guest.id).json()
    said = say(owner, with_agent["id"], "hello").json()
    assert outside.get(BASE).json() == {"items": [], "next_cursor": None}
    [item] = outside.get(f"{BASE}?observed=true").json()["items"]
    assert (item["id"], item["access"], item["unread"]) == (with_agent["id"], "observer", None)
    assert outside.get(f"{BASE}/{with_agent['id']}").json()["access"] == "observer"
    assert [m["seq"] for m in read(outside, with_agent["id"]).json()["items"]] == [said["seq"]]
    assert outside.get(f"{BASE}/{without['id']}").status_code == 404
    assert outside.get(f"{BASE}/{agent.id}/messages").status_code == 404  # no direct chat here
    assert outside.get("/projects/maintainer/maity/events").status_code == 404  # nothing else of it
    posted = say(outside, with_agent["id"], "hi")
    assert (posted.status_code, reason(posted)) == (403, "observer")
    renamed = outside.patch(f"{BASE}/{with_agent['id']}", {"title": "x"})
    assert reason(renamed) == "observer"
    assert reason(redact(outside, said["seq"])) == "observer"
    # Outside a chat it reads along, a write stays not_found, like every other read.
    assert outside.post(BASE, {"participants": [agent.id]}).status_code == 404
    notice = {"kind": "message", "type": "notice", "to": "all", "body": "hi"}
    assert outside.post("/projects/maintainer/maity/events", notice).status_code == 404
    assert outside.post("/projects/maintainer/maity/tasks", {"title": "x"}).status_code == 404


def test_an_outsider_without_an_agent_learns_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    stranger = flow.human(make_client, migrated, "stranger")
    for path in (BASE, f"{BASE}?observed=true"):
        assert stranger.get(path).status_code == 404


def test_the_packet_counts_chats_and_carries_only_mentions(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    # The instance's first session starts at the head (§5.2): it is open before the chat.
    agent.resume()
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, agent.id, guest.id).json()
    plain = say(guest, chat["id"], "just talking").json()["seq"]
    pinged = say(guest, chat["id"], f"@{handle(migrated, agent.id)} please look").json()["seq"]
    packet = agent.resume().json()
    seqs = [e["seq"] for e in packet["events"]["items"]]
    assert pinged in seqs and plain not in seqs
    [group] = [c for c in packet["conversations"] if c["id"] == chat["id"]]
    assert group == {
        "id": chat["id"],
        "kind": "group",
        "title": chat["title"],
        "unread": 2,
        "mentions_unread": 1,
        "last_message_at": group["last_message_at"],
        "closed_at": None,
        "meat_proxy": [],  # no human in it has the mode on (§9.3)
    }
    assert any(c["kind"] == "direct" and c["id"] == agent.id for c in packet["conversations"])


def test_an_agent_whose_owner_is_outside_resumes_with_its_chats(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The reviewer's probe: no direct conversation without its human party, so the
    packet and the list carry the group chats only, never a 404."""
    _, agent = outside_owner(make_client, migrated)
    chat = create(owner, agent.id).json()
    resumed = agent.resume()
    assert resumed.status_code == 200, resumed.text
    assert [c["id"] for c in resumed.json()["conversations"]] == [chat["id"]]
    listed = agent.get(BASE)
    assert listed.status_code == 200, listed.text
    assert [c["id"] for c in listed.json()["items"]] == [chat["id"]]


def test_an_outsider_posting_through_events_is_an_observer(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    outside, agent = outside_owner(make_client, migrated)
    chat = create(owner, agent.id).json()
    posted = outside.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "chat", "body": "hi", "conversation_id": chat["id"]},
    )
    assert (posted.status_code, reason(posted)) == (403, "observer")


def test_the_packet_keeps_only_the_current_stays_mentions(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The reviewer's probe: mentioned, removed, added again, resumed from an old cursor;
    the old mention is outside the window and stays out, as in `unread`."""
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, agent.id, guest.id).json()
    old = say(guest, chat["id"], f"@{handle(migrated, agent.id)} first").json()["seq"]
    url = f"{BASE}/{chat['id']}/participants"
    assert owner.delete(f"{url}/{agent.id}").status_code == 200
    assert owner.post(url, {"member_id": agent.id}).status_code == 200
    new = say(guest, chat["id"], f"@{handle(migrated, agent.id)} again").json()["seq"]
    packet = agent.resume(cursor=old - 1).json()
    seqs = [e["seq"] for e in packet["events"]["items"]]
    assert new in seqs and old not in seqs
    [group] = [c for c in packet["conversations"] if c["id"] == chat["id"]]
    assert (group["unread"], group["mentions_unread"]) == (1, 1)


def test_observer_only_where_the_outsider_reads_along(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """The reviewer's probe: outside a chat it reads along, an outsider's write is
    not_found, whatever it names."""
    outside, agent = outside_owner(make_client, migrated)
    guest = other_human(make_client, migrated, "guest")
    without = create(owner, guest.id).json()  # none of its agents in it
    notice = owner.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "x"},
    ).json()["seq"]
    assert redact(outside, notice).status_code == 404  # a project event
    assert redact(outside, 10**9).status_code == 404  # no such seq
    hidden_post = outside.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "chat", "body": "hi", "conversation_id": without["id"]},
    )
    assert hidden_post.status_code == 404
    assert say(outside, without["id"], "hi").status_code == 404
    assert outside.patch(f"{BASE}/{without['id']}", {"title": "x"}).status_code == 404
    assert outside.patch(f"{BASE}/cnv-nonexistent", {"title": "x"}).status_code == 404
    mine = create(owner, agent.id).json()
    said = say(owner, mine["id"], "hello").json()["seq"]
    assert reason(redact(outside, said)) == "observer"  # its agent's chat: observer
