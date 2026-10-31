"""docs/api.md §9.3 "Pinned": a human pins the chats it reads, its own and across projects at
most 20; both lists come in four bands, a pin never hiding a new message."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import Engine, func, select

from maity_hub import paging
from maity_hub import tables as t
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_group_chats import BASE, create, delete, other_human, read, say

ME = "/me/conversations"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def put(who: Any, chat_id: str) -> Any:
    path = f"/api/v1{BASE}/{chat_id}/pin"
    if isinstance(who, flow.Human):
        return who.client.put(path, headers={"X-CSRF-Token": who.csrf})
    return who.client.put(path, headers=who.auth | who.key())


def unpin(who: Any, chat_id: str) -> Any:
    return delete(who, f"{BASE}/{chat_id}/pin")


def listed(who: Any, path: str = BASE, **params: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = None
    for _ in range(100):
        got = who.get(path, params={**params, **({"cursor": cursor} if cursor else {})})
        assert got.status_code == 200, got.text
        items += got.json()["items"]
        cursor = got.json()["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("a list that does not end")


def band(item: dict[str, Any]) -> int:
    if item["unread"]:
        return 0 if item["pinned"] else 1
    return 2 if item["pinned"] else 3


def pin_rows(engine: Engine) -> int:
    with engine.connect() as conn:
        return int(conn.execute(select(func.count()).select_from(t.conversation_pin)).scalar_one())


def test_a_human_pins_and_unpins_idempotently_and_only_it_sees_the_pin(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, guest.id, agent.id).json()
    for _ in range(2):
        assert put(owner, chat["id"]).status_code == 204
    assert put(owner, agent.id).status_code == 204  # the direct conversation too
    mine = {i["id"]: i["pinned"] for i in listed(owner)}
    assert mine == {chat["id"]: True, agent.id: True}
    assert [i["pinned"] for i in listed(guest)] == [False]  # a pin is its holder's own
    assert {i["pinned"] for i in listed(agent)} == {False}  # an agent never has one
    # a chat's own view says it too, a direct one's being its list item (§9.1)
    assert owner.get(f"{BASE}/{chat['id']}").json()["pinned"] is True
    assert owner.get(f"{BASE}/{agent.id}").json()["pinned"] is True
    assert guest.get(f"{BASE}/{chat['id']}").json()["pinned"] is False
    assert agent.get(f"{BASE}/{chat['id']}").json()["pinned"] is False
    assert [i["pinned"] for i in listed(owner, ME)] == [True, True]
    for _ in range(2):
        assert unpin(owner, chat["id"]).status_code == 204
    assert {i["id"]: i["pinned"] for i in listed(owner)}[chat["id"]] is False
    with migrated.connect() as conn:  # no event announces a pin
        kinds = set(conn.execute(select(t.event.c.kind)).scalars())
    assert not {k for k in kinds if "pin" in k}


def test_an_agent_pins_nothing_and_an_unreadable_chat_is_not_found(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    third = other_human(make_client, migrated, "third")
    theirs = create(owner, third.id).json()  # the guest is not in it
    refused = put(agent, theirs["id"])
    assert (refused.status_code, refused.json()["error"]["details"]["reason"]) == (
        403,
        "humans_only",
    )
    assert unpin(agent, theirs["id"]).status_code == 403
    for chat_id in (theirs["id"], agent.id, "cnv-nothere", "agt-nothere"):
        assert put(guest, chat_id).status_code == 404, chat_id
        assert unpin(guest, chat_id).status_code == 404, chat_id
    assert pin_rows(migrated) == 0


def test_an_owner_reading_along_pins_and_a_closed_room_stays_pinnable(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = other_human(make_client, migrated, "other-owner", role="admin")
    their_agent = flow.agent(make_client, other)
    chat = create(owner, their_agent.id).json()
    assert put(other, chat["id"]).status_code == 204  # an observer reads it
    [seen] = [i for i in listed(other, observed=True) if i["id"] == chat["id"]]
    assert seen["pinned"] is True
    guest = other_human(make_client, migrated, "guest")
    room = create(owner, guest.id).json()
    assert delete(owner, f"{BASE}/{room['id']}/participants/{owner.id}").status_code == 200
    assert delete(guest, f"{BASE}/{room['id']}/participants/{guest.id}").status_code == 200
    with_agent = create(owner, their_agent.id, title="closes").json()
    assert delete(owner, f"{BASE}/{with_agent['id']}/participants/{owner.id}").status_code == 200
    # closed (no human left), the agent is still in it, so its owner still reads along
    assert put(other, with_agent["id"]).status_code == 204


def test_the_lists_come_in_four_bands_and_page_across_them(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    guest = other_human(make_client, migrated, "guest")
    chats = {}
    for name in ("pinned new", "new", "pinned quiet", "quiet", "pinned new 2", "quiet 2"):
        chats[name] = create(owner, guest.id, title=name).json()["id"]
    for name in ("pinned new", "new", "pinned new 2"):
        assert say(guest, chats[name], f"in {name}").status_code == 201
    for name in ("pinned new", "pinned quiet", "pinned new 2"):
        assert put(owner, chats[name]).status_code == 204
    say(owner, chats["quiet"], "the newest activity, but nothing new for me")
    for path in (BASE, ME):
        whole = owner.get(path, params={"limit": 200}).json()["items"]
        assert [band(i) for i in whole] == sorted(band(i) for i in whole)
        assert [i["title"] for i in whole][:3] == ["pinned new 2", "pinned new", "new"]
        assert {i["title"] for i in whole if band(i) == 2} == {"pinned quiet"}
        for limit in (1, 2, 4):
            assert listed(owner, path, limit=limit) == whole
    # reading a pinned chat moves it below the chats with something new
    read(owner, chats["pinned new"])
    titles = [i["title"] for i in owner.get(BASE).json()["items"]]
    assert titles.index("pinned new") > titles.index("new")
    assert titles.index("pinned new") < titles.index("quiet")


def test_an_old_cursor_from_before_the_bands_is_refused(owner: flow.Human) -> None:
    old = paging.cursor(datetime(2026, 10, 31), "cnv-x", paging.scope(observed=False))
    assert owner.get(BASE, params={"cursor": old}).status_code == 400


def test_at_most_twenty_pins_across_projects(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    guest = other_human(make_client, migrated, "guest")
    made = [create(owner, guest.id, title=f"room {n}") for n in range(20)]
    assert {m.status_code for m in made} == {201}, made[-1].text
    ids = [m.json()["id"] for m in made]
    for chat_id in ids:
        assert put(owner, chat_id).status_code == 204
    assert put(owner, ids[0]).status_code == 204  # pinned already: no 21st
    one_more = create(owner, guest.id, title="one more").json()["id"]
    refused = put(owner, one_more)
    assert refused.status_code == 400
    assert refused.json()["error"]["details"]["fields"] == {"pin": "too_many"}
    flow.project(owner, "second")  # the limit is across projects
    with migrated.connect() as conn:
        second_id = conn.execute(
            select(t.project.c.id).where(t.project.c.slug == "second")
        ).scalar_one()
    factory.membership(migrated, second_id, "member", human_id=guest.id)
    elsewhere = owner.post(
        "/projects/maintainer/second/conversations", {"participants": [guest.id]}
    )
    assert elsewhere.status_code == 201, elsewhere.text
    path = f"/api/v1/projects/maintainer/second/conversations/{elsewhere.json()['id']}/pin"
    across = owner.client.put(path, headers={"X-CSRF-Token": owner.csrf})
    assert across.json()["error"]["details"]["fields"] == {"pin": "too_many"}
    assert unpin(owner, ids[0]).status_code == 204
    assert owner.client.put(path, headers={"X-CSRF-Token": owner.csrf}).status_code == 204


def test_who_leaves_or_loses_access_keeps_no_pin(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    guest = other_human(make_client, migrated, "guest")
    chat = create(owner, guest.id, agent.id).json()
    assert put(guest, chat["id"]).status_code == 204
    assert delete(guest, f"{BASE}/{chat['id']}/participants/{guest.id}").status_code == 200
    added = owner.post(f"{BASE}/{chat['id']}/participants", {"member_id": guest.id})
    assert added.status_code in (200, 201), added.text
    [again] = [i for i in listed(guest) if i["id"] == chat["id"]]
    assert again["pinned"] is False  # joined again: a fresh start, no old pin
    assert put(guest, chat["id"]).status_code == 204
    assert put(owner, agent.id).status_code == 204
    assert pin_rows(migrated) == 2
    assert owner.delete(f"/projects/maintainer/maity/members/{guest.id}").status_code == 200
    assert owner.delete(f"/projects/maintainer/maity/members/{agent.id}").status_code == 200
    assert pin_rows(migrated) == 0  # the guest's room and the owner's direct chat
