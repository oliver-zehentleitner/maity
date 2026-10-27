"""docs/api.md §9.2–§9.4, §8.2, §8.5, §8.6: group chats."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import events
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory

BASE = "/projects/maintainer/maity/conversations"


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
    make_client: ClientFactory, engine: Engine, handle: str, role: str = "member"
) -> flow.Human:
    human = flow.human(make_client, engine, handle)
    factory.membership(engine, project_id(engine), role, human_id=human.id)
    return human


def create(who: Any, *participants: str, title: str | None = "Release go/no-go") -> Any:
    return who.post(BASE, {"title": title, "participants": list(participants)})


def say(who: Any, chat_id: str, body: str) -> Any:
    return who.post(f"{BASE}/{chat_id}/messages", {"body": body})


def read(who: Any, chat_id: str, query: str = "") -> Any:
    return who.get(f"{BASE}/{chat_id}/messages{query}")


def delete(who: Any, path: str) -> Any:
    if isinstance(who, flow.Human):
        return who.delete(path)
    return who.client.request("DELETE", f"/api/v1{path}", headers=who.auth | who.key())


def reason(response: Any) -> Any:
    return response.json()["error"]["details"].get("reason")


def field(response: Any, name: str) -> Any:
    return response.json()["error"]["details"]["fields"][name]


def event_row(engine: Engine, seq: int) -> Any:
    with engine.connect() as conn:
        return conn.execute(select(t.event).where(t.event.c.seq == seq)).one()


def membership_row(engine: Engine, principal: str) -> Any:
    with engine.connect() as conn:
        return conn.execute(
            select(t.membership).where(
                (t.membership.c.agent_id == principal) | (t.membership.c.human_id == principal),
                t.membership.c.active.is_(True),
            )
        ).one()


# --- creating ------------------------------------------------------------------------------


def test_a_human_creates_a_room_it_is_in(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    created = create(owner, agent.id, guest.id)
    assert created.status_code == 201, created.text
    chat = created.json()
    assert chat["id"].startswith("cnv-") and chat["kind"] == "group"
    assert chat["created_by"] == owner.id and chat["access"] == "participant"
    assert [p["member_id"] for p in chat["participants"]] == [owner.id, agent.id, guest.id]
    assert chat["participants"][1]["owner_id"] == owner.id
    assert chat["observers"] == [] and chat["closed_at"] is None
    assert owner.get(f"{BASE}/{chat['id']}").json() == chat
    assert guest.get(f"{BASE}/{chat['id']}").json()["access"] == "participant"


def test_who_may_create_and_with_whom(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    refused = create(agent, owner.id, guest.id)
    assert (refused.status_code, reason(refused)) == (403, "humans_only")
    assert field(create(owner), "participants") == "too_few"
    assert field(create(owner, owner.id), "participants") == "too_few"
    assert field(create(owner, agent.id), "participants") == "use_direct"
    assert field(create(owner, guest.id, "hum-nobody"), "participants") == "not_a_member"
    crowd = []
    for i in range(12):  # members by the factory: no login needed to be named
        crowd.append(factory.human(migrated, f"crowd-{i}"))
        factory.membership(migrated, project_id(migrated), "member", human_id=crowd[-1])
    assert field(create(owner, *crowd), "participants") == "too_many"
    assert create(owner, *crowd[:11]).status_code == 201  # twelve with the creator


def test_a_closed_project_refuses_a_new_room(owner: flow.Human, migrated: Engine) -> None:
    with migrated.begin() as conn:
        conn.execute(update(t.project).values(state="accepted"))
    refused = create(owner, "hum-anyone", "hum-else")
    assert refused.json()["error"]["code"] == "project_closed"


# --- talking -----------------------------------------------------------------------------


def test_a_message_reaches_the_room_and_wakes_an_agent_only_when_mentioned(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    outsider = flow.agent(make_client, owner)  # a member, not in the chat
    chat = create(owner, agent.id, guest.id).json()
    plain = say(owner, chat["id"], "the build is green")
    assert plain.status_code == 201, plain.text
    assert "delivered_at" not in plain.json()
    pinged = say(
        guest,
        chat["id"],
        f"@{handle(migrated, agent.id)} can we tag? @{handle(migrated, outsider.id)} stays text",
    )
    assert [m["member_id"] for m in pinged.json()["mentions"]] == [agent.id]
    for seq, wakes_agent in ((plain.json()["seq"], False), (pinged.json()["seq"], True)):
        row = event_row(migrated, seq)
        assert sorted(row.audience) == sorted(f"member:{m}" for m in (owner.id, agent.id, guest.id))
        assert row.payload["conversation"] == {
            "id": chat["id"],
            "kind": "group",
            "title": "Release go/no-go",
        }
        agent_row = membership_row(migrated, agent.id)
        assert events.wakes(row, agent_row, agent.id) is wakes_agent
        assert events.wakes(row, membership_row(migrated, owner.id), owner.id) is (
            seq != plain.json()["seq"]
        )
    created = conn_events(migrated, "conversation_created")[0]
    assert not events.wakes(created, membership_row(migrated, agent.id), agent.id)
    assert say(outsider, chat["id"], "me too").status_code == 404
    via_events = agent.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "chat", "body": "on it", "conversation_id": chat["id"]},
    )
    assert via_events.status_code == 201, via_events.text  # the same write (§9.2)


def handle(engine: Engine, agent_id: str) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == agent_id)
        ).scalar_one()
    return found


def conn_events(engine: Engine, kind: str) -> list[Any]:
    with engine.connect() as conn:
        return list(
            conn.execute(select(t.event).where(t.event.c.kind == kind).order_by(t.event.c.seq))
        )


def test_a_newcomer_starts_fresh_and_reads_the_history_on_demand(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    guest = other_human(make_client, migrated, "guest")
    late = other_human(make_client, migrated, "late")
    chat = create(owner, guest.id).json()
    first = say(owner, chat["id"], "before you came").json()["seq"]
    added = owner.post(f"{BASE}/{chat['id']}/participants", {"member_id": late.id})
    assert added.status_code == 200, added.text
    after = say(guest, chat["id"], "welcome").json()["seq"]
    fresh = read(late, chat["id"]).json()
    assert [m["seq"] for m in fresh["items"]] == [after]
    assert fresh["earlier"] == after  # older messages exist
    history = read(late, chat["id"], f"?before={after}").json()
    assert [m["seq"] for m in history["items"]] == [first]
    assert history["earlier"] is None
    both = read(late, chat["id"], f"?after=0&before={after}")
    assert field(both, "before") == "with_after"


def test_unread_counts_the_others_in_the_window_and_mentions(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, guest.id).json()
    say(guest, chat["id"], "one")
    say(guest, chat["id"], "@maintainer two")

    def item(who: Any) -> Any:
        [found] = [i for i in who.get(BASE).json()["items"] if i["id"] == chat["id"]]
        return found

    mine = item(owner)
    assert (mine["unread"], mine["mentions_unread"]) == (2, 1)
    assert mine["last_message"]["body"] == "@maintainer two"
    assert (item(guest)["unread"], item(guest)["mentions_unread"]) == (0, 0)
    read(owner, chat["id"])
    assert item(owner)["unread"] == 0
    say(guest, chat["id"], "three")
    say(owner, chat["id"], "I've read up to here")  # speaking reads up to there
    assert item(owner)["unread"] == 0


def test_the_list_mixes_both_kinds_newest_first_and_pages(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    older = create(owner, guest.id, title="older").json()
    newer = create(owner, guest.id, title="newer").json()
    owner.post(f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "hi"})
    say(owner, older["id"], "now the older one is the newest")
    items = owner.get(BASE).json()["items"]
    assert [i["id"] for i in items] == [older["id"], agent.id, newer["id"]]
    direct = items[1]
    assert (direct["kind"], direct["access"], direct["title"], direct["mentions_unread"]) == (
        "direct",
        "party",
        None,
        0,
    )
    first = owner.get(f"{BASE}?limit=2").json()
    assert [i["id"] for i in first["items"]] == [older["id"], agent.id]
    rest = owner.get(f"{BASE}?limit=2&cursor={first['next_cursor']}").json()
    assert [i["id"] for i in rest["items"]] == [newer["id"]] and rest["next_cursor"] is None


# --- managing and closing ----------------------------------------------------------------


def test_who_manages_and_how_the_room_closes(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, agent.id, guest.id).json()
    url = f"{BASE}/{chat['id']}"
    assert guest.patch(url, {"title": "mine"}).status_code == 403  # neither creator nor admin
    assert agent.patch(url, {"title": "mine"}).status_code == 403
    renamed = owner.patch(url, {"title": None})
    assert (renamed.status_code, renamed.json()["title"]) == (200, None)
    left = delete(guest, f"{url}/participants/{guest.id}")
    assert left.status_code == 200, left.text
    assert (left.json()["reason"], left.json()["by"]) == ("left", guest.id)
    assert guest.get(url).status_code == 404  # a former participant no longer reads it
    again = delete(owner, f"{url}/participants/{guest.id}")
    assert (again.status_code, again.json()["left_at"]) == (200, left.json()["left_at"])
    gone = delete(owner, f"{url}/participants/{owner.id}")  # the last human leaves
    assert gone.status_code == 200
    closed = conn_events(migrated, "conversation_updated")[-1]
    assert closed.payload["changed"]["closed"] == {"closed_reason": "no_human"}
    agent_view = agent.get(url).json()
    assert (agent_view["closed_reason"], agent_view["access"]) == ("no_human", "participant")
    refused = say(agent, chat["id"], "anyone?")
    assert refused.json()["error"]["code"] == "conversation_closed"


def test_a_direct_conversation_does_not_change(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    refused = owner.patch(f"{BASE}/{agent.id}", {"title": "x"})
    assert field(refused, "conversation") == "direct"
    item = owner.get(f"{BASE}/{agent.id}").json()
    assert (item["id"], item["kind"], item["agent_id"]) == (agent.id, "direct", agent.id)


def test_removal_from_the_project_leaves_every_room(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, guest.id, agent.id).json()
    assert owner.delete(f"/projects/maintainer/maity/members/{guest.id}").status_code == 200
    view = owner.get(f"{BASE}/{chat['id']}").json()
    assert [p["member_id"] for p in view["participants"]] == [owner.id, agent.id]
    removed = conn_events(migrated, "conversation_updated")[-1]
    assert removed.payload["changed"]["participants_removed"][0]["reason"] == ("membership_removed")
    assert f"member:{guest.id}" in removed.audience


# --- the owner reads along -----------------------------------------------------------------


def test_the_owner_of_an_agent_reads_along_and_does_nothing_else(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other-owner", role="admin")
    their_agent = flow.agent(make_client, other)
    admin = other_human(make_client, migrated, "bystander", role="admin")
    chat = create(owner, their_agent.id).json()
    assert chat["observers"] == [other.id]
    said = say(owner, chat["id"], "hello").json()
    view = other.get(f"{BASE}/{chat['id']}").json()
    assert view["access"] == "observer"
    assert [m["seq"] for m in read(other, chat["id"]).json()["items"]] == [said["seq"]]
    refused = say(other, chat["id"], "hi")
    assert (refused.status_code, reason(refused)) == (403, "observer")
    assert reason(other.patch(f"{BASE}/{chat['id']}", {"title": "x"})) == "observer"
    seen = other.get(f"/projects/maintainer/maity/events?after={said['seq'] - 1}").json()["items"]
    assert said["seq"] in [e["seq"] for e in seen]  # through GET /events too
    assert other.get(BASE).json()["items"] == [
        i for i in other.get(BASE).json()["items"] if i["id"] != chat["id"]
    ]
    [observed] = [
        i for i in other.get(f"{BASE}?observed=true").json()["items"] if i["id"] == chat["id"]
    ]
    assert (observed["access"], observed["unread"], observed["mentions_unread"]) == (
        "observer",
        None,
        None,
    )
    assert admin.get(f"{BASE}/{chat['id']}").status_code == 404  # an admin outside sees nothing
    outside = admin.get(f"/projects/maintainer/maity/events?after={said['seq'] - 1}").json()[
        "items"
    ]
    assert said["seq"] not in [e["seq"] for e in outside]


# --- redaction (§8.5) --------------------------------------------------------------------


def redact(who: Any, seq: int, **body: Any) -> Any:
    return who.post(
        f"/projects/maintainer/maity/events/{seq}/redact", {"reason": "a secret", **body}
    )


def test_any_human_in_the_room_redacts_nobody_else(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    other = other_human(make_client, migrated, "other-owner", role="admin")
    their_agent = flow.agent(make_client, other)
    guest = other_human(make_client, migrated, "guest")  # no events:admin
    chat = create(owner, agent.id, their_agent.id, guest.id).json()
    seq = say(agent, chat["id"], "the token is abc").json()["seq"]
    assert reason(redact(agent, seq)) == "humans_only"
    assert reason(redact(other, seq)) == "not_a_participant"  # reads through its agent
    done = redact(guest, seq)
    assert done.status_code == 200, done.text
    [message] = read(owner, chat["id"]).json()["items"]
    assert message["body"] is None and message["redaction"]["reason"] == "a secret"
    [as_agent] = read(agent, chat["id"]).json()["items"]
    assert as_agent["redaction"]["reason"] is None
    [as_observer] = read(other, chat["id"]).json()["items"]
    assert as_observer["redaction"]["reason"] is None


def test_a_closed_room_is_redacted_by_its_former_humans_or_blind_by_an_admin(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other-owner", role="admin")
    their_agent = flow.agent(make_client, other)
    mine = flow.agent(make_client, owner)
    chat = create(owner, their_agent.id, mine.id).json()
    first = say(their_agent, chat["id"], "secret one").json()["seq"]
    second = say(mine, chat["id"], "secret two").json()["seq"]
    plain = say(owner, chat["id"], "fine").json()["seq"]
    delete(owner, f"{BASE}/{chat['id']}/participants/{owner.id}")  # closes it
    assert redact(owner, first).status_code == 200  # a former human participant
    admin = other_human(make_client, migrated, "admin", role="admin")
    assert redact(admin, first, expect="unknown").json()["error"]["details"]["fields"] == {
        "expect": "unknown"
    }
    blind = redact(admin, second, expect="closed_chat_message")
    assert (blind.status_code, blind.json()) == (200, {"seq": second, "redacted": True})
    with migrated.connect() as conn:
        notice = conn.execute(
            select(t.event)
            .where(t.event.c.kind == "event_redacted")
            .order_by(t.event.c.seq.desc())
            .limit(1)
        ).one()
    assert f"member:{admin.id}" in notice.audience and f"member:{owner.id}" in notice.audience
    assert plain not in (first, second)
    not_closed = owner.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "x"},
    ).json()["seq"]
    mismatch = redact(owner, not_closed, expect="closed_chat_message")
    assert mismatch.json()["error"]["details"]["fields"] == {"expect": "mismatch"}


# --- review fixes: replay, history redaction, the lock -----------------------------------


def test_a_replayed_create_shows_nothing_the_caller_may_no_longer_read(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    guest = other_human(make_client, migrated, "guest", role="admin")
    other = other_human(make_client, migrated, "other")
    headers = {"X-CSRF-Token": owner.csrf, "Idempotency-Key": "create-replay-000001"}
    body = {"title": "first", "participants": [guest.id, other.id]}
    first = owner.client.post(f"/api/v1{BASE}", json=body, headers=headers)
    assert first.status_code == 201, first.text
    chat_id = first.json()["id"]
    delete(owner, f"{BASE}/{chat_id}/participants/{owner.id}")
    guest.patch(f"{BASE}/{chat_id}", {"title": "private now"})
    again = owner.client.post(f"/api/v1{BASE}", json=body, headers=headers)
    assert again.status_code == 404
    assert "private now" not in again.text


def test_someone_added_later_redacts_what_it_reads_in_the_history(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    late = other_human(make_client, migrated, "late")
    chat = create(owner, agent.id, other_human(make_client, migrated, "guest").id).json()
    secret = say(agent, chat["id"], "the token is abc").json()["seq"]
    owner.post(f"{BASE}/{chat['id']}/participants", {"member_id": late.id})
    assert [m["seq"] for m in read(late, chat["id"], f"?before={secret + 1}").json()["items"]] == [
        secret
    ]
    done = redact(late, secret)
    assert done.status_code == 200, done.text


def test_a_close_that_commits_first_is_never_overtaken(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer's stale-snapshot probe: the chat closes between the caller's first
    read and its lock; the add and the post see the close."""
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, agent.id, guest.id).json()
    real = events.lock_project

    def closed_meanwhile(conn: Any, project: str) -> Any:
        conn.execute(
            update(t.conversation)
            .where(t.conversation.c.id == chat["id"])
            .values(closed_at=t.conversation.c.created_at, closed_reason="no_human")
        )
        return real(conn, project)

    monkeypatch.setattr(events, "lock_project", closed_meanwhile)
    added = owner.post(f"{BASE}/{chat['id']}/participants", {"member_id": guest.id})
    assert added.json()["error"]["code"] == "conversation_closed"
    assert added.json()["error"]["details"] == {"closed_reason": "no_human"}
    posted = say(owner, chat["id"], "still here?")
    assert posted.json()["error"]["code"] == "conversation_closed"


def test_a_demotion_that_commits_first_ends_the_blind_redaction(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reviewer's probe: the admin is demoted right before the lock returns; the
    blind redaction of a closed chat it cannot read is then `not_found`."""
    other = other_human(make_client, migrated, "other-owner", role="admin")
    their_agent = flow.agent(make_client, other)
    chat = create(owner, their_agent.id).json()
    seq = say(their_agent, chat["id"], "secret").json()["seq"]
    delete(owner, f"{BASE}/{chat['id']}/participants/{owner.id}")  # closes it
    admin = other_human(make_client, migrated, "admin", role="admin")
    real = events.lock_project

    def demoted_meanwhile(conn: Any, project: str) -> Any:
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == admin.id).values(role="member")
        )
        return real(conn, project)

    monkeypatch.setattr(events, "lock_project", demoted_meanwhile)
    refused = redact(admin, seq, expect="closed_chat_message")
    assert refused.status_code == 404, refused.text
