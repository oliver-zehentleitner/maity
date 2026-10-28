"""The conversation list is built for all chats at once (docs/api.md §9.3) and equals the
list built one chat at a time, whose single-chat views stay in `routes.conversations`."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Connection, Engine, event, select

from maity_hub import conversation_list, group_chats
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError
from maity_hub.routes import conversations as routes
from maity_hub.views import ts
from tests import flow
from tests.conftest import ClientFactory
from tests.test_group_chats import BASE, create, other_human, read, say


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


# The list as it was built before: one chat at a time.


def reference_direct(conn: Connection, mine: Membership, caller: Caller) -> list[dict[str, Any]]:
    items = []
    for agent_id in routes._owned_agents(conn, mine, caller):
        try:
            items.append(routes._direct_item(conn, mine, caller, agent_id))
        except ApiError as gone:
            if gone.status != 404:
                raise
    return items


def reference_groups(conn: Connection, mine: Any, observed: bool) -> list[dict[str, Any]]:
    ids = set(
        conn.execute(
            select(t.conversation_participant.c.conversation_id).where(
                t.conversation_participant.c.membership_id == mine.id,
                t.conversation_participant.c.here.is_(True),
            )
        ).scalars()
    )
    if observed and mine.kind == "human":
        ids |= set(
            conn.execute(
                select(t.conversation_participant.c.conversation_id)
                .join(t.membership, t.membership.c.id == t.conversation_participant.c.membership_id)
                .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
                .where(
                    t.conversation_participant.c.here.is_(True),
                    t.agent_profile.c.owner_id == mine.principal_id,
                    t.membership.c.project_id == mine.project.id,
                )
            ).scalars()
        )
    items = []
    for conversation_id in sorted(ids):
        group = group_chats.find(conn, mine.project.id, conversation_id)
        found = group_chats.access(conn, conversation_id, mine) if group is not None else None
        if found is None:
            continue
        view = group_chats.view(conn, group, found)
        window = routes._window(conn, group, mine, found)
        in_window = routes._messages(mine.project.id, group.id).where(t.event.c.seq > window)
        last = conn.execute(in_window.order_by(t.event.c.seq.desc()).limit(1)).first()
        unread: int | None = None
        mentioned: int | None = None
        if found == "participant":
            seen = max(window, routes._read_mark(conn, mine.id, group.id))
            rows = conn.execute(
                in_window.where(t.event.c.seq > seen, t.event.c.actor_membership != mine.id)
            ).all()
            unread = len(rows)
            mentioned = sum(
                1
                for r in rows
                if not r.redacted
                and any(
                    m.get("member_id") == mine.principal_id
                    for m in (r.payload or {}).get("mentions") or []
                )
            )
        items.append(
            {
                "id": group.id,
                "kind": "group",
                "title": group.title,
                "participants": [routes._short(p) for p in view["participants"]],
                "observers": view["observers"],
                "access": found,
                "closed_at": view["closed_at"],
                "last_message_at": ts(last.at) if last is not None else None,
                "unread": unread,
                "mentions_unread": mentioned,
                "last_message": routes._preview(conn, last),
                "_activity": last.at if last is not None else group.created_at,
            }
        )
    return items


def talk(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> dict[str, Any]:
    """Direct chats read and unread, rooms of every shape: with mentions and redactions,
    one an owner reads along in, one closed, one a member left and came back to."""
    guest = other_human(make_client, migrated, "guest")
    other = other_human(make_client, migrated, "other-owner", role="admin")
    theirs = flow.agent(make_client, other)
    mine = [flow.agent(make_client, owner) for _ in range(3)]
    for n, agent in enumerate(mine):  # the third has said nothing
        for turn in range(n * 2):
            agent.post(f"{BASE}/{agent.id}/messages", {"body": f"hello {turn} " * 30})
    owner.post(f"{BASE}/{mine[0].id}/messages", {"body": "answer"})
    read(owner, mine[1].id)  # a chat mark
    mine[1].post(f"{BASE}/{mine[1].id}/messages", {"body": "after the mark"})
    plain = create(owner, guest.id, title="plain").json()
    say(guest, plain["id"], "one")
    say(guest, plain["id"], "@maintainer two")
    say(guest, plain["id"], "@maintainer and again")
    redacted = say(guest, plain["id"], "@maintainer three").json()
    owner.post(
        f"/projects/maintainer/maity/events/{redacted['seq']}/redact", {"reason": "a secret"}
    )
    mixed = create(owner, mine[0].id, guest.id, title=None).json()
    say(mine[0], mixed["id"], "from the agent")
    say(owner, mixed["id"], "from the owner")
    say(guest, mixed["id"], "@maintainer late")
    watched = create(owner, theirs.id, title="watched").json()
    say(owner, watched["id"], "for the agent")
    left = create(owner, guest.id, mine[2].id, title="left").json()
    say(owner, left["id"], "before")
    assert guest.delete(f"{BASE}/{left['id']}/participants/{guest.id}").status_code == 200
    say(owner, left["id"], "while away")
    assert owner.post(f"{BASE}/{left['id']}/participants", {"member_id": guest.id}).status_code in (
        200,
        201,
    )
    say(owner, left["id"], "@guest welcome back")
    empty = create(owner, guest.id, title="empty").json()
    closed = create(owner, guest.id, title="closed").json()
    say(guest, closed["id"], "bye")
    for who in (guest, owner):
        who.delete(f"{BASE}/{closed['id']}/participants/{who.id}")
    return {"guest": guest, "other": other, "mine": mine, "theirs": theirs, "empty": empty}


def lists(who: Any, **query: Any) -> list[Any]:
    """Every page of a list by `next_cursor`."""
    pages = []
    cursor = None
    for _ in range(40):
        params = {**query, **({"cursor": cursor} if cursor else {})}
        got = who.get(BASE, params=params)
        assert got.status_code == 200, got.text
        pages.append(got.json())
        cursor = pages[-1]["next_cursor"]
        if cursor is None:
            return pages
    raise AssertionError("a list that does not end")


def test_the_list_equals_the_list_built_one_chat_at_a_time(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    people = talk(owner, make_client, migrated)
    callers = {
        "owner": owner,
        "guest": people["guest"],
        "observer": people["other"],
        "agent": people["mine"][0],
        "agent without owner in the room": people["mine"][2],
    }
    queries: list[dict[str, Any]] = [
        {"limit": 1},
        {"limit": 2},
        {"limit": 50},
        {"limit": 2, "observed": True},
        {"observed": True},
    ]
    new = {(who, str(q)): lists(caller, **q) for who, caller in callers.items() for q in queries}
    assert sum(len(p["items"]) for p in new[("owner", str({"limit": 50}))]) >= 8
    with monkeypatch.context() as patched:
        patched.setattr(
            conversation_list,
            "direct_entries",
            lambda conn, mine, caller, agent_ids: reference_direct(conn, mine, caller),
        )
        patched.setattr(conversation_list, "group_entries", reference_groups)
        old = {
            (who, str(q)): lists(caller, **q) for who, caller in callers.items() for q in queries
        }
    assert new == old


def count_statements(engine: Engine, call: Any) -> int:
    seen = [0]

    def counted(*_: Any) -> None:
        seen[0] += 1

    event.listen(engine, "before_cursor_execute", counted)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", counted)
    return seen[0]


def test_the_list_costs_the_same_statements_for_more_chats(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    guest = other_human(make_client, migrated, "guest")

    def list_it() -> None:
        assert owner.get(BASE).status_code == 200

    def add(n: int) -> None:
        for _ in range(n):
            agent = flow.agent(make_client, owner)
            agent.post(f"{BASE}/{agent.id}/messages", {"body": "hi"})
            room = create(owner, guest.id, agent.id, title="room").json()
            say(guest, room["id"], "@maintainer hello")

    add(2)
    few = count_statements(migrated, list_it)
    add(6)
    many = count_statements(migrated, list_it)
    assert many == few, (few, many)
