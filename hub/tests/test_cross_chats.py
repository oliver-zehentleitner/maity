"""docs/api.md §9.5: cross-project group chats, the hub routes and their fields."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, cross_chats, mentions
from maity_hub import tables as t
from maity_hub.db import current_revision, downgrade, migrate
from maity_hub.ids import new_id
from maity_hub.ratelimit import Limiter
from tests import factory, flow
from tests.conftest import ClientFactory

DETAIL = {
    "id",
    "kind",
    "title",
    "created_by",
    "created_at",
    "participants",
    "observers",
    "closed_at",
    "closed_reason",
    "access",
}
HUMAN = {"member_id", "kind", "handle", "owner_id", "joined_at"}
AGENT = HUMAN | {"name", "projects"}
LIST_ITEM = {
    "id",
    "kind",
    "title",
    "created_at",
    "participants",
    "observers",
    "access",
    "closed_at",
    "last_message_at",
    "unread",
    "mentions_unread",
    "last_message",
}
LIST_HUMAN = {"member_id", "kind", "handle"}
LIST_AGENT = LIST_HUMAN | {"name"}
MESSAGE = {
    "id",
    "seq",
    "conversation_id",
    "from",
    "to",
    "body",
    "sent_at",
    "mentions",
    "from_instance",
    "to_instance",
    "redacted",
    "redaction",
}
MENTION = {"member_id", "handle", "name", "instance", "field", "offset", "length"}
PREVIEW = {"seq", "from", "body", "sent_at", "redacted"}
STAY = {"conversation_id", "member_id", "joined_at", "left_at", "by", "reason"}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def project_id(engine: Engine, slug: str = "maity") -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == slug)
        ).scalar_one()
    return found


def other_human(make_client: ClientFactory, engine: Engine, handle: str) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, project_id(engine), "admin", human_id=human.id)
    return human


def create(who: flow.Human, *participants: str, title: str | None = "Across") -> Any:
    return who.post("/me/cross-chats", {"title": title, "participants": list(participants)})


def field(response: Any, name: str) -> Any:
    return response.json()["error"]["details"]["fields"][name]


def test_the_owner_creates_a_room_and_the_view_pins_its_fields(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.project(owner, "other")
    first = flow.agent(make_client, owner, "maity")
    second = flow.agent(make_client, owner, "other")
    created = create(owner, second.id, first.id, owner.id, first.id)
    assert created.status_code == 201, created.text
    chat = created.json()
    assert chat["id"].startswith("xch-") and chat["kind"] == "cross"
    assert set(chat) == DETAIL
    assert chat["created_by"] == owner.id and chat["title"] == "Across"
    assert chat["access"] == "participant" and chat["observers"] == []
    assert chat["closed_at"] is None and chat["closed_reason"] is None
    assert [p["member_id"] for p in chat["participants"]] == [owner.id, second.id, first.id]
    human, away, home = chat["participants"]
    assert set(human) == HUMAN and human["kind"] == "human" and human["owner_id"] is None
    assert set(away) == AGENT and set(home) == AGENT
    assert away["projects"] == ["maintainer/other"]
    assert home["projects"] == ["maintainer/maity"]
    assert away["owner_id"] == owner.id and "/" in away["name"]
    assert owner.get(f"/me/cross-chats/{chat['id']}").json() == chat


def test_an_agent_sees_only_projects_it_shares(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.project(owner, "other")
    home = flow.agent(make_client, owner, "maity")
    away = flow.agent(make_client, owner, "other")
    chat = create(owner, home.id, away.id).json()
    seen = home.get(f"/me/cross-chats/{chat['id']}").json()
    assert seen["access"] == "participant"
    by_id = {p["member_id"]: p for p in seen["participants"]}
    assert by_id[home.id]["projects"] == ["maintainer/maity"]
    assert by_id[away.id]["projects"] == []
    assert "projects" not in by_id[owner.id]


def test_who_may_create_and_the_check_order(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    stranger = flow.human(make_client, migrated, "stranger")
    flow.project(stranger, "theirs")
    theirs = flow.agent(make_client, stranger, "stranger/theirs")
    lone = owner.post("/agents", {"handle": "idle", "display_name": "Idle"}).json()
    refused = agent.post("/me/cross-chats", {"participants": [agent.id, theirs.id]})
    assert (
        refused.status_code == 403 and refused.json()["error"]["details"]["reason"] == "humans_only"
    )
    both = create(owner, stranger.id, "no-such")
    assert both.status_code == 400 and field(both, "participants") == "agents_only"
    missing = create(owner, agent.id, "no-such")
    assert missing.status_code == 404
    foreign = create(owner, agent.id, theirs.id)
    assert foreign.status_code == 404
    gone = owner.delete(f"/agents/{lone['id']}")
    assert gone.status_code == 200, gone.text
    deleted = create(owner, agent.id, lone["id"])
    assert deleted.status_code == 400 and field(deleted, "participants") == "deleted"
    idle = owner.post("/agents", {"handle": "idle", "display_name": "Idle"}).json()
    nowhere = create(owner, agent.id, idle["id"])
    assert nowhere.status_code == 400 and field(nowhere, "participants") == "no_membership"
    assert nowhere.json()["error"]["details"]["member_id"] == idle["id"]
    few = create(owner, agent.id)
    assert few.status_code == 400 and field(few, "participants") == "too_few"


def test_use_group_when_the_owner_can_open_the_project_chat(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    one = flow.agent(make_client, owner)
    two = flow.agent(make_client, owner)
    shared = create(owner, one.id, two.id)
    assert shared.status_code == 400 and field(shared, "participants") == "use_group"
    flow.project(owner, "other")
    other = flow.agent(make_client, owner, "other")
    opened = create(owner, one.id, other.id)
    assert opened.status_code == 201, opened.text


def test_a_guest_membership_does_not_offer_use_group(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A project the owner is only a guest of does not count, even when it holds both agents."""
    host = flow.human(make_client, migrated, "host")
    flow.project(host, "room")
    one = flow.agent(make_client, owner, "maity")
    flow.project(owner, "side")
    two = flow.agent(make_client, owner, "side")
    room = project_id(migrated, "room")
    factory.membership(migrated, room, "guest", human_id=owner.id)
    factory.membership(migrated, room, "coder", agent_id=one.id)
    factory.membership(migrated, room, "coder", agent_id=two.id)
    opened = create(owner, one.id, two.id)
    assert opened.status_code == 201, opened.text


def test_the_quota_names_the_owner(
    owner: flow.Human, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cross_chats, "OPEN_PER_OWNER", 1)
    one = flow.agent(make_client, owner, "maity")
    flow.project(owner, "other")
    two = flow.agent(make_client, owner, "other")
    assert create(owner, one.id, two.id).status_code == 201
    flow.project(owner, "third")
    three = flow.agent(make_client, owner, "third")
    again = create(owner, one.id, three.id)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "conversation_quota"
    assert again.json()["error"]["details"] == {"max": 1, "scope": "owner"}


def test_the_list_pins_its_fields_and_pages(owner: flow.Human, make_client: ClientFactory) -> None:
    flow.project(owner, "other")
    one = flow.agent(make_client, owner)
    two = flow.agent(make_client, owner, "other")
    first = create(owner, one.id, two.id, title="First").json()
    said = owner.post(
        f"/me/cross-chats/{first['id']}/messages", {"body": "@" + owner.handle + " hi"}
    )
    assert said.status_code == 201, said.text
    second = create(owner, one.id, two.id, title="Second").json()
    listed = owner.get("/me/cross-chats?limit=1")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert set(body) == {"items", "next_cursor"} and body["next_cursor"]
    item = body["items"][0]
    assert set(item) == LIST_ITEM and item["id"] == second["id"]
    assert item["unread"] == 0 and item["last_message"] is None
    page = owner.get("/me/cross-chats", params={"limit": 1, "cursor": body["next_cursor"]}).json()
    assert page["next_cursor"] is None and page["items"][0]["id"] == first["id"]
    preview = page["items"][0]["last_message"]
    assert set(preview) == PREVIEW and preview["from"] == owner.id and preview["redacted"] is False
    short = page["items"][0]["participants"]
    assert set(short[0]) == LIST_HUMAN and set(short[1]) == LIST_AGENT
    agent_list = one.get("/me/cross-chats").json()
    assert [i["id"] for i in agent_list["items"]] == [second["id"], first["id"]]
    assert agent_list["items"][1]["unread"] == 1
    assert agent_list["items"][1]["mentions_unread"] == 0


def test_a_message_pins_its_fields_and_the_window(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    flow.project(owner, "other")
    home = flow.agent(make_client, owner)
    away = flow.agent(make_client, owner, "other")
    chat = create(owner, home.id, away.id).json()
    handle = next(p["handle"] for p in chat["participants"] if p["member_id"] == home.id)
    posted = home.post(f"/me/cross-chats/{chat['id']}/messages", {"body": f"@{handle} go"})
    assert posted.status_code == 201, posted.text
    message = posted.json()
    assert set(message) == MESSAGE
    assert message["id"].startswith("xmsg-") and message["seq"] == 1
    assert message["to"] == chat["id"] and message["from"] == home.id
    assert message["from_instance"] == home.instance and message["to_instance"] is None
    assert message["redacted"] is False and message["redaction"] is None
    assert message["mentions"] and set(message["mentions"][0]) == MENTION
    assert message["mentions"][0]["member_id"] == home.id
    assert message["mentions"][0]["instance"] is None
    stranger = owner.post(
        f"/me/cross-chats/{chat['id']}/messages", {"body": "hello @not-in-the-room"}
    )
    assert stranger.status_code == 201 and stranger.json()["mentions"] == []
    files = owner.post(
        f"/me/cross-chats/{chat['id']}/messages", {"body": "x", "attachments": ["att-1"]}
    )
    assert files.status_code == 400 and field(files, "attachments") == "not_in_cross_chat"
    named = owner.post(
        f"/me/cross-chats/{chat['id']}/messages", {"body": "x", "to_instance": "wqe2"}
    )
    assert named.status_code == 400 and field(named, "to_instance") == "direct_chat_only"
    supplied = owner.post(f"/me/cross-chats/{chat['id']}/messages", {"body": "x", "mentions": []})
    assert supplied.status_code == 400 and field(supplied, "mentions") == "read_only"
    both = owner.get(f"/me/cross-chats/{chat['id']}/messages?after=0&before=2")
    assert both.status_code == 400 and field(both, "before") == "with_after"
    page = away.get(f"/me/cross-chats/{chat['id']}/messages")
    assert page.status_code == 200, page.text
    assert set(page.json()) == {"items", "cursor", "earlier"}
    assert page.json()["cursor"] == 2 and page.json()["items"][0]["seq"] == 1
    again = away.get(f"/me/cross-chats/{chat['id']}/messages?after=2")
    assert again.json()["items"] == []
    history = away.get(f"/me/cross-chats/{chat['id']}/messages?before=2")
    assert [m["seq"] for m in history.json()["items"]] == [1]
    # `before` marks nothing read: the cursor stayed at 2, so nothing new is unread.
    assert away.get("/me/cross-chats").json()["items"][0]["unread"] == 0


def test_a_mention_wakes_the_agent_once_and_an_admin_does_not_read_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    home = flow.agent(make_client, owner)
    flow.project(owner, "other")
    away = flow.agent(make_client, owner, "other")
    created = create(owner, home.id, away.id)
    assert created.status_code == 201, created.text
    chat = created.json()
    # The same profile in a second project must still be one event.
    flow.agent(make_client, owner, "other", agent={"id": home.id})
    handle = next(p["handle"] for p in chat["participants"] if p["member_id"] == home.id)
    posted = away.post(
        f"/me/cross-chats/{chat['id']}/messages", {"body": f"@{handle} and @{handle}"}
    )
    assert posted.status_code == 201, posted.text
    admin = other_human(make_client, migrated, "auditor")
    admin_events = admin.get("/projects/maintainer/maity/events").json()["items"]
    assert [i for i in admin_events if i["kind"] == "cross_chat_mention"] == []
    found = home.get("/projects/maintainer/maity/events")
    assert found.status_code == 200, found.text
    home_events = [i for i in found.json()["items"] if i["kind"] == "cross_chat_mention"]
    assert len(home_events) == 1
    event = home_events[0]
    assert event["audience"] == [f"member:{home.id}"]
    assert set(event["payload"]) == {"conversation", "message_id", "seq"}
    assert "body" not in event["payload"]
    assert event["payload"]["conversation"] == {
        "id": chat["id"],
        "kind": "cross",
        "title": "Across",
    }
    assert event["actor"]["kind"] == "agent" and event["actor"]["id"] == away.id
    assert event["actor"]["instance"] == away.instance
    packet = home.resume().json()
    assert packet["cross_chats"]
    assert set(packet["cross_chats"][0]) == {"id", "kind", "title", "unread", "mentions_unread"}
    assert packet["cross_chats"][0]["kind"] == "cross"
    assert packet["cross_chats"][0]["mentions_unread"] == 1
    assert all(i["kind"] != "cross" for i in packet["conversations"])


def test_closing_redaction_and_leaving(owner: flow.Human, make_client: ClientFactory) -> None:
    flow.project(owner, "other")
    home = flow.agent(make_client, owner)
    away = flow.agent(make_client, owner, "other")
    chat = create(owner, home.id, away.id).json()
    posted = owner.post(f"/me/cross-chats/{chat['id']}/messages", {"body": "a secret"})
    message = posted.json()
    refused = home.client.request(
        "DELETE",
        f"/api/v1/me/cross-chats/{chat['id']}/participants/{owner.id}",
        headers=home.auth | home.key(),
    )
    assert refused.status_code == 403
    assert refused.json()["error"]["details"]["reason"] == "humans_only"
    added = owner.post(f"/me/cross-chats/{chat['id']}/participants", {"member_id": home.id})
    assert added.status_code == 200
    assert [p["member_id"] for p in added.json()["participants"]] == [
        p["member_id"] for p in chat["participants"]
    ]
    left = home.client.request(
        "DELETE",
        f"/api/v1/me/cross-chats/{chat['id']}/participants/{home.id}",
        headers=home.auth | home.key(),
    )
    assert left.status_code == 200, left.text
    assert set(left.json()) == STAY and left.json()["reason"] == "left"
    assert left.json()["member_id"] == home.id and left.json()["left_at"]
    assert home.get(f"/me/cross-chats/{chat['id']}").status_code == 404
    again = owner.delete(f"/me/cross-chats/{chat['id']}/participants/{home.id}")
    assert again.status_code == 200 and again.json()["reason"] == "left"
    missing = owner.delete(f"/me/cross-chats/{chat['id']}/participants/agt-missing")
    assert missing.status_code == 404
    owner_left = owner.delete(f"/me/cross-chats/{chat['id']}/participants/{owner.id}")
    assert owner_left.status_code == 200 and owner_left.json()["reason"] == "left"
    closed = owner.get(f"/me/cross-chats/{chat['id']}").json()
    assert closed["access"] == "owner" and closed["closed_reason"] == "no_human"
    assert owner.id not in [p["member_id"] for p in closed["participants"]]
    blocked = away.post(f"/me/cross-chats/{chat['id']}/messages", {"body": "too late"})
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "conversation_closed"
    assert blocked.json()["error"]["details"]["closed_reason"] == "no_human"
    redacted = owner.post(
        f"/me/cross-chats/{chat['id']}/messages/{message['id']}/redact", {"reason": "secret"}
    )
    assert redacted.status_code == 200, redacted.text
    tomb = redacted.json()
    assert tomb["body"] is None and tomb["mentions"] == [] and tomb["redacted"] is True
    assert set(tomb["redaction"]) == {"at", "by", "reason"}
    assert tomb["redaction"]["by"] == owner.id and tomb["redaction"]["reason"] == "secret"
    seen = away.get(f"/me/cross-chats/{chat['id']}/messages").json()["items"][0]
    assert seen["redaction"]["reason"] is None and seen["redaction"]["by"] == owner.id
    twice = owner.post(
        f"/me/cross-chats/{chat['id']}/messages/{message['id']}/redact", {"reason": "again"}
    )
    assert twice.status_code == 400
    assert twice.json()["error"]["details"]["reason"] == "already_redacted"


def test_the_owner_pays_mentions_from_the_account(
    owner: flow.Human, make_client: ClientFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cross_chats, "OWNER_PINGS", Limiter(1, 600, name="test-owner-pings"))
    flow.project(owner, "other")
    one = flow.agent(make_client, owner)
    two = flow.agent(make_client, owner, "other")
    chat = create(owner, one.id, two.id).json()
    handle = next(p["handle"] for p in chat["participants"] if p["member_id"] == one.id)
    assert (
        owner.post(f"/me/cross-chats/{chat['id']}/messages", {"body": f"@{handle} one"}).status_code
        == 201
    )
    limited = owner.post(f"/me/cross-chats/{chat['id']}/messages", {"body": f"@{handle} two"})
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "rate_limited"
    # The agent's own budget is a different counter, so one ping of it still fits.
    monkeypatch.setattr(mentions, "PINGS", Limiter(1, 600, name="test-agent-pings"))
    other = next(p["handle"] for p in chat["participants"] if p["member_id"] == two.id)
    assert (
        one.post(
            f"/me/cross-chats/{chat['id']}/messages", {"body": f"@{other} from me"}
        ).status_code
        == 201
    )


def test_the_last_membership_and_isolation_and_an_owner_change(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    flow.project(owner, "other")
    home = flow.agent(make_client, owner)
    away = flow.agent(make_client, owner, "other")
    created = create(owner, home.id, away.id)
    assert created.status_code == 201, created.text
    chat = created.json()
    flow.agent(make_client, owner, "other", agent={"id": home.id})
    removed = owner.delete(f"/projects/maintainer/maity/members/{home.id}")
    assert removed.status_code == 200, removed.text
    still = owner.get(f"/me/cross-chats/{chat['id']}").json()
    assert home.id in [p["member_id"] for p in still["participants"]]
    removed_other = owner.delete(f"/projects/maintainer/other/members/{home.id}")
    assert removed_other.status_code == 200, removed_other.text
    gone = owner.get(f"/me/cross-chats/{chat['id']}").json()
    assert home.id not in [p["member_id"] for p in gone["participants"]]
    # Isolation of every active membership leaves; one does not. A fresh pair.
    first = flow.agent(make_client, owner)
    second = flow.agent(make_client, owner, "other")
    room = create(owner, first.id, second.id).json()
    flow.agent(make_client, owner, "other", agent={"id": first.id})
    isolated = owner.post(
        f"/projects/maintainer/maity/members/{first.id}/isolate", {"reason": "hold"}
    )
    assert isolated.status_code == 200, isolated.text
    kept = owner.get(f"/me/cross-chats/{room['id']}").json()
    assert first.id in [p["member_id"] for p in kept["participants"]]
    other = owner.post(f"/projects/maintainer/other/members/{first.id}/isolate", {"reason": "hold"})
    assert other.status_code == 200, other.text
    left = owner.get(f"/me/cross-chats/{room['id']}").json()
    assert first.id not in [p["member_id"] for p in left["participants"]]
    heir = flow.human(make_client, migrated, "heir")
    with migrated.begin() as conn:
        cross_chats.owner_changed(conn, second.id, owner.id)
        conn.execute(
            update(t.agent_profile)
            .where(t.agent_profile.c.id == second.id)
            .values(owner_id=heir.id)
        )
    handed = owner.get(f"/me/cross-chats/{room['id']}").json()
    assert second.id not in [p["member_id"] for p in handed["participants"]]


def test_the_export_includes_the_chat_and_deletion_removes_it(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from maity_hub.routes import me

    flow.project(owner, "other")
    one = flow.agent(make_client, owner)
    two = flow.agent(make_client, owner, "other")
    chat = create(owner, one.id, two.id).json()
    assert (
        owner.post(f"/me/cross-chats/{chat['id']}/messages", {"body": "keep me"}).status_code == 201
    )
    me.EXPORTS.reset()
    document = owner.get("/me/export")
    assert document.status_code == 200, document.text
    body = document.json()
    assert len(body["cross_chats"]) == 1
    exported = body["cross_chats"][0]
    assert set(exported) == {"id", "title", "created_at", "closed_at", "closed_reason", "messages"}
    assert exported["id"] == chat["id"]
    assert exported["messages"][0]["body"] == "keep me"
    assert set(exported["messages"][0]) == MESSAGE
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(state="archived"))
        cross_chats.remove_owned(conn, owner.id)
    with migrated.connect() as conn:
        assert conn.execute(select(t.cross_chat.c.id)).all() == []
        assert conn.execute(select(t.cross_chat_message.c.id)).all() == []
        assert conn.execute(select(t.cross_chat_mention_for.c.seq)).all() == []


def test_not_found_comes_before_deleted(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A deleted profile named beside an id the caller does not own is not_found (§9.5)."""
    agent = flow.agent(make_client, owner)
    lone = owner.post("/agents", {"handle": "gone", "display_name": "Gone"}).json()
    assert owner.delete(f"/agents/{lone['id']}").status_code == 200
    stranger = flow.human(make_client, migrated, "outsider")
    flow.project(stranger, "theirs")
    theirs = flow.agent(make_client, stranger, "outsider/theirs")
    deleted_first = create(owner, lone["id"], "no-such")
    assert deleted_first.status_code == 404, deleted_first.text
    foreign_second = create(owner, lone["id"], theirs.id)
    assert foreign_second.status_code == 404, foreign_second.text
    # The deleted id alone, with a real agent, is still deleted.
    only_deleted = create(owner, agent.id, lone["id"])
    assert only_deleted.status_code == 400 and field(only_deleted, "participants") == "deleted"


def test_removing_the_last_open_membership_drops_the_isolated_one(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Isolate A, remove the membership that was not isolated, lift A: the agent is out (§9.5)."""
    home = flow.agent(make_client, owner)
    flow.project(owner, "other")
    away = flow.agent(make_client, owner, "other")
    chat = create(owner, home.id, away.id).json()
    flow.agent(make_client, owner, "other", agent={"id": home.id})
    isolated = owner.post(
        f"/projects/maintainer/maity/members/{home.id}/isolate", {"reason": "hold"}
    )
    assert isolated.status_code == 200, isolated.text
    removed = owner.delete(f"/projects/maintainer/other/members/{home.id}")
    assert removed.status_code == 200, removed.text
    with migrated.connect() as conn:
        reason = conn.execute(
            select(t.cross_chat_participant.c.reason).where(
                t.cross_chat_participant.c.conversation_id == chat["id"],
                t.cross_chat_participant.c.member_id == home.id,
                t.cross_chat_participant.c.here.is_(None),
            )
        ).scalar_one()
    assert reason == "membership_isolated"
    lifted = owner.delete(f"/projects/maintainer/maity/members/{home.id}/isolate")
    assert lifted.status_code == 200, lifted.text
    assert home.get(f"/me/cross-chats/{chat['id']}").status_code == 404
    assert home.get(f"/me/cross-chats/{chat['id']}/messages").status_code == 404
    still = owner.get(f"/me/cross-chats/{chat['id']}").json()
    assert home.id not in [p["member_id"] for p in still["participants"]]


def test_an_instance_mention_skips_an_isolated_membership(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    home = flow.agent(make_client, owner)
    flow.project(owner, "other")
    away = flow.agent(make_client, owner, "other")
    chat = create(owner, home.id, away.id).json()
    flow.agent(make_client, owner, "other", agent={"id": home.id})
    assert (
        owner.post(
            f"/projects/maintainer/maity/members/{home.id}/isolate", {"reason": "hold"}
        ).status_code
        == 200
    )
    handle = next(p["handle"] for p in chat["participants"] if p["member_id"] == home.id)
    posted = away.post(
        f"/me/cross-chats/{chat['id']}/messages",
        {"body": f"@{handle}#{home.instance} over here"},
    )
    assert posted.status_code == 201, posted.text
    maity = project_id(migrated, "maity")
    other = project_id(migrated, "other")
    with migrated.connect() as conn:
        places = conn.execute(
            select(t.event.c.project_id, t.event.c.audience).where(
                t.event.c.kind == "cross_chat_mention"
            )
        ).all()
    assert places
    assert all(row.project_id != maity for row in places)
    assert any(row.project_id == other and f"member:{home.id}" in row.audience for row in places)


def _quiet(engine: Engine, chat_id: str, author: str, count: int) -> None:
    """Messages that mention nobody, written past the hub's mention index."""
    with engine.begin() as conn:
        start = int(
            conn.execute(
                select(t.cross_chat.c.next_seq).where(t.cross_chat.c.id == chat_id)
            ).scalar_one()
        )
        now = clock.now()
        conn.execute(
            insert(t.cross_chat_message),
            [
                {
                    "id": new_id("cross_message"),
                    "conversation_id": chat_id,
                    "seq": start + i,
                    "author_id": author,
                    "body": "quiet",
                    "sent_at": now,
                    "mentions": [],
                    "redacted": False,
                }
                for i in range(count)
            ],
        )
        conn.execute(
            update(t.cross_chat)
            .where(t.cross_chat.c.id == chat_id)
            .values(next_seq=start + count, last_message_at=now)
        )


class _CountingCursor:
    """A cursor SQLAlchemy fetches from. psycopg's and sqlite's own fetch methods are
    read-only, so the count has to live on a wrapper the dialect is handed."""

    def __init__(self, inner: Any, counted: dict[str, int]) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_counted", counted)
        object.__setattr__(self, "_statement", "")

    def _remember(self, statement: Any) -> None:
        text = statement if isinstance(statement, str) else str(statement)
        object.__setattr__(self, "_statement", text)

    def _note(self, rows: int) -> None:
        if "cross_chat_message" in object.__getattribute__(self, "_statement").lower():
            object.__getattribute__(self, "_counted")["n"] += rows

    def execute(self, statement: Any, parameters: Any = None, /, **kwargs: Any) -> Any:
        self._remember(statement)
        inner = object.__getattribute__(self, "_inner")
        if parameters is None and not kwargs:
            return inner.execute(statement)
        if parameters is None:
            return inner.execute(statement, **kwargs)
        return inner.execute(statement, parameters, **kwargs)

    def executemany(self, statement: Any, parameters: Any, /) -> Any:
        self._remember(statement)
        return object.__getattribute__(self, "_inner").executemany(statement, parameters)

    def fetchall(self) -> Any:
        rows = object.__getattribute__(self, "_inner").fetchall()
        self._note(len(rows))
        return rows

    def fetchmany(self, size: int | None = None) -> Any:
        inner = object.__getattribute__(self, "_inner")
        rows = inner.fetchmany() if size is None else inner.fetchmany(size)
        self._note(len(rows))
        return rows

    def fetchone(self) -> Any:
        row = object.__getattribute__(self, "_inner").fetchone()
        if row is not None:
            self._note(1)
        return row

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_inner"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_inner"), name, value)


def _message_rows_fetched(engine: Engine, call: Any) -> int:
    """Rows a SELECT of `cross_chat_message` returned to the hub during `call`.

    The call's response has to be 200: an error that returns no rows must not count
    as a small fetch."""
    counted = {"n": 0}
    cls = engine.dialect.execution_ctx_cls
    defined = "create_cursor" in cls.__dict__
    original = cls.create_cursor

    def create_cursor(self: Any) -> _CountingCursor:
        return _CountingCursor(original(self), counted)

    cls.create_cursor = create_cursor  # type: ignore[assignment]
    try:
        response = call()
    finally:
        if defined:
            cls.create_cursor = original  # type: ignore[method-assign]
        else:
            del cls.create_cursor
    assert response.status_code == 200, response.text
    return counted["n"]


def test_mention_unread_does_not_read_the_quiet_history(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """Ten quiet messages and ten thousand return the same message rows to the list."""
    flow.project(owner, "other")
    home = flow.agent(make_client, owner)
    away = flow.agent(make_client, owner, "other")
    chat = create(owner, home.id, away.id).json()
    _quiet(migrated, chat["id"], owner.id, 10)
    small = _message_rows_fetched(migrated, lambda: home.get("/me/cross-chats"))
    _quiet(migrated, chat["id"], owner.id, 9_990)
    large = _message_rows_fetched(migrated, lambda: home.get("/me/cross-chats"))
    assert small > 0
    assert small == large
    assert large < 20
    listed = home.get("/me/cross-chats").json()["items"][0]
    assert listed["unread"] == 10_000
    assert listed["mentions_unread"] == 0


def test_the_cross_chat_migration_downgrades_and_returns(engine: Engine) -> None:
    migrate(engine)
    assert current_revision(engine) == "20261105073000_cross_chats"
    downgrade(engine, "20261104150000_report_request")
    assert current_revision(engine) == "20261104150000_report_request"
    migrate(engine)
    assert current_revision(engine) == "20261105073000_cross_chats"
