"""docs/api.md §9.6 "History": a human's own history of their allow and deny entries and of
their answers to the request to chat with their agents, `GET /me/chat-access/history`; its
causes, the snapshot before a write, the handles at the read, paging, the cap, the export and
the account's deletion."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, select, update

from maity_hub import account_deletion, chat_access, chat_access_history, chat_gate, clock, events
from maity_hub import tables as t
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory
from tests.test_chat_access import allow, deny, profile
from tests.test_chat_request import answer, create, other_human, requests, the_request

PATH = "/me/chat-access/history"


@pytest.fixture
def anna(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated, "anna")


@pytest.fixture
def ben(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated, "ben")


def history(who: Any, **query: Any) -> dict[str, Any]:
    got = who.get(PATH, params=query)
    assert got.status_code == 200, got.text
    assert got.headers["cache-control"] == "private, no-store"
    body: dict[str, Any] = got.json()
    return body


def items(who: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = history(who, limit=200)["items"]
    return found


def rows(engine: Engine, human_id: str | None = None) -> int:
    c = t.chat_access_history.c
    query = select(func.count()).select_from(t.chat_access_history)
    if human_id is not None:
        query = query.where(c.human_id == human_id)
    with engine.connect() as conn:
        return int(conn.execute(query).scalar_one())


def test_created_changed_deleted_by_the_owner(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    made = allow(anna, agents=[mine], owner_id=ben.id, duration="day").json()
    assert anna.patch(f"/me/chat-access/allow/{made['id']}", {}).status_code == 200  # no change
    patched = anna.patch(
        f"/me/chat-access/allow/{made['id']}", {"duration": "week", "allowed": "web"}
    ).json()
    assert anna.delete(f"/me/chat-access/allow/{made['id']}").status_code == 204
    assert anna.delete(f"/me/chat-access/allow/{made['id']}").status_code == 204  # not there
    gone, changed, created = items(anna)  # newest first
    assert created["kind"] == "entry" and created["change"] == "created"
    assert created["id"].startswith("chh-") and created["at"]
    assert created["list"] == "allow" and created["entry_id"] == made["id"]
    assert created["entry"] == made and created["before"] is None and created["fields"] == []
    assert (created["by"], created["cause"]) == (anna.id, "list")
    assert created["request_id"] is None and created["deny_id"] is None
    assert created["conversation"] is None
    assert created["names"] == {
        mine: {"handle": "anna-a", "deleted": False},
        ben.id: {"handle": "ben", "deleted": False},
    }
    assert created["seq"] < changed["seq"] < gone["seq"]
    assert changed["change"] == "changed" and changed["entry"] == patched
    assert changed["before"] == made
    assert changed["fields"] == ["allowed", "duration", "until"]
    assert gone["change"] == "deleted" and gone["entry"] == patched
    assert [i["entry_exists"] for i in (gone, changed, created)] == [False] * 3
    assert history(ben)["items"] == []  # only the owner reads it


def test_a_replay_writes_no_item(anna: flow.Human, ben: flow.Human, migrated: Engine) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    headers = {"X-CSRF-Token": anna.csrf, "Idempotency-Key": "history-replay-0001"}
    body = {"agents": [mine], "owner_id": ben.id}
    first = anna.client.post("/api/v1/me/chat-access/allow", json=body, headers=headers)
    again = anna.client.post("/api/v1/me/chat-access/allow", json=body, headers=headers)
    assert first.status_code == again.status_code == 201
    [only] = items(anna)
    assert only["entry_id"] == first.json()["id"] and only["entry_exists"] is True


def test_a_deny_shows_the_allow_it_removed_as_it_was_before(
    anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    """A1340 P2-2: the allow a deny narrows to no agent and then deletes keeps its agents."""
    mine = profile(migrated, anna.id, "anna-a")
    other = profile(migrated, anna.id, "anna-b")
    one = allow(anna, agents=[mine], owner_id=ben.id).json()
    two = allow(anna, agents=[mine, other], owner_id=ben.id).json()
    stop = deny(anna, agents=[mine], owner_id=ben.id).json()
    newest = items(anna)[:3]
    by_entry = {i["entry_id"]: i for i in newest}
    assert by_entry[stop["id"]]["change"] == "created"
    assert by_entry[stop["id"]]["list"] == "deny" and by_entry[stop["id"]]["deny_id"] is None
    removed = by_entry[one["id"]]
    assert removed["change"] == "deleted" and removed["entry"]["agents"] == [mine]
    assert (removed["cause"], removed["deny_id"]) == ("list", stop["id"])
    narrowed = by_entry[two["id"]]
    assert narrowed["change"] == "changed" and narrowed["fields"] == ["agents"]
    assert narrowed["before"]["agents"] == sorted([mine, other])
    assert narrowed["entry"]["agents"] == [other] and narrowed["deny_id"] == stop["id"]


def test_the_answers_and_the_entries_they_wrote(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    mine = flow.agent(make_client, owner)
    create(owner, theirs.id, mine.id)
    row = the_request(migrated, other.id)
    sent = {"their_human": True, "allowed": "web only"}
    assert answer(other, row.id, reply_id="allow_day", chat_access=sent).status_code == 200
    said, made = items(other)[:2]  # the answer is written after the entries it made
    [entry] = other.get("/me/chat-access").json()["allow"]
    assert said["kind"] == "answer" and said["by"] == other.id
    assert said["request_id"] == row.id and said["side"] == owner.id
    assert (said["reply_id"], said["withdrawn"]) == ("allow_day", False)
    assert said["agents"] == [theirs.id] and said["their_human"] is True
    assert said["their_agents"] is None and said["allowed"] == "web only"
    assert said["denied"] is None and said["entries"] == [entry["id"]]
    assert said["names"][owner.id] == {"handle": "maintainer", "deleted": False}
    assert said["names"][theirs.id]["deleted"] is False
    assert said["seq"] > made["seq"]
    assert "entry_exists" not in said
    assert made["change"] == "created" and made["entry"] == entry
    assert (made["cause"], made["request_id"], made["by"]) == ("request", row.id, other.id)


def test_no_block_and_the_owners_withdrawal(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    create(owner, theirs.id, title="One")
    row = the_request(migrated, other.id)
    assert answer(other, row.id, reply_id="no").status_code == 200
    [said] = items(other)
    assert (said["reply_id"], said["agents"], said["entries"]) == ("no", [theirs.id], [])
    assert said["their_human"] is False and said["withdrawn"] is False
    create(owner, theirs.id, title="Two")
    row = the_request(migrated, other.id)
    assert other.post(f"/requests/{row.id}/withdraw", {}).status_code == 200
    said = items(other)[0]
    assert (said["reply_id"], said["withdrawn"], said["request_id"]) == ("no", True, row.id)
    create(owner, theirs.id, title="Three")
    row = the_request(migrated, other.id)
    assert answer(other, row.id, reply_id="block").status_code == 200
    said, made = items(other)[:2]
    [stop] = other.get("/me/chat-access").json()["deny"]
    assert (said["reply_id"], said["agents"], said["entries"]) == (
        "block",
        [theirs.id],
        [stop["id"]],
    )
    assert (made["list"], made["cause"], made["request_id"]) == ("deny", "request", row.id)


def test_the_hubs_withdrawal_is_no_answer(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    other = other_human(make_client, migrated, "other")
    theirs = flow.agent(make_client, other)
    chat = create(owner, theirs.id)
    row = the_request(migrated, other.id)
    gone = owner.delete(
        f"/projects/maintainer/maity/conversations/{chat['id']}/participants/{theirs.id}"
    )
    assert gone.status_code == 200, gone.text
    assert [r.status for r in requests(migrated, other.id, status=None)] == ["withdrawn"]
    assert row.id and items(other) == []


def test_the_owners_add_and_the_end_of_until(make_client: ClientFactory, migrated: Engine) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    other = other_human(make_client, migrated, "other")
    mine = flow.agent(make_client, owner)
    chat = create(owner, mine.id, other.id)
    [added] = items(owner)
    assert (added["change"], added["cause"], added["by"]) == ("created", "chat_add", owner.id)
    assert added["conversation"] == {
        "id": chat["id"],
        "project": {"owner": "maintainer", "slug": "maity"},
    }
    patched = owner.patch(f"/me/chat-access/allow/{added['entry_id']}", {"duration": "hour"})
    assert patched.status_code == 200, patched.text
    with migrated.begin() as conn:
        conn.execute(update(t.chat_access).values(until=clock.now() - timedelta(minutes=1)))
    assert chat_gate.sweep(migrated) == 1
    ended = items(owner)[0]
    assert (ended["change"], ended["cause"], ended["by"]) == ("expired", "expiry", None)
    assert ended["entry_exists"] is True  # an expired entry stays in the lists


def test_a_deleted_agent_and_account_show_ids_with_no_handle(
    anna: flow.Human, ben: flow.Human, migrated: Engine, settings: Settings
) -> None:
    """A1340 P2-1, A1341 P2: a deleted account's and agent's handle is null, the ids stay."""
    mine = profile(migrated, anna.id, "anna-a")
    b1 = profile(migrated, ben.id, "ben-1")
    b2 = profile(migrated, ben.id, "ben-2")
    made = allow(anna, agents=[mine], owner_id=ben.id, their_agents=[b1, b2]).json()
    with migrated.begin() as conn:
        conn.execute(
            update(t.agent_profile).where(t.agent_profile.c.id == b1).values(deleted_at=clock.now())
        )
        chat_access.forget_agent(conn, b1)
    narrowed = items(anna)[0]
    assert (narrowed["change"], narrowed["cause"], narrowed["by"]) == ("changed", "gone", None)
    assert narrowed["before"]["their_agents"] == sorted([b1, b2])
    assert narrowed["entry"]["their_agents"] == [b2]
    assert narrowed["names"][b1] == {"handle": None, "deleted": True}
    assert narrowed["names"][b2] == {"handle": "ben-2", "deleted": False}
    with events.transaction(migrated) as conn:
        account_deletion.delete_account(conn, settings, ben.id)
    newest = items(anna)
    assert newest[0]["change"] == "deleted" and newest[0]["cause"] == "gone"
    for item in newest:
        assert item["names"][ben.id] == {"handle": None, "deleted": True}
        assert item["entry"]["owner_id"] == ben.id and item["entry"]["handle"] is None
    assert made["handle"] == "ben"
    assert rows(migrated, ben.id) == 0


def test_an_accounts_deletion_is_one_write(
    anna: flow.Human, ben: flow.Human, migrated: Engine, settings: Settings
) -> None:
    """163796: one item per entry, against the entry as it was before the deletion began,
    however many of the account's agents go; none for the account's own."""
    mine = profile(migrated, anna.id, "anna-a")
    agents = sorted(
        ben.post("/agents", {"handle": h, "display_name": h}).json()["id"] for h in ("b1", "b2")
    )
    side = allow(anna, agents=[mine], owner_id=ben.id, their_agents=agents).json()
    flow.project(anna)
    project = allow(anna, agents=[mine], project={"owner": "anna", "slug": "maity"}).json()
    allow(ben, agents=agents, owner_id=anna.id)
    count = rows(migrated, anna.id)
    with events.transaction(migrated) as conn:
        account_deletion.delete_account(conn, settings, ben.id)
    assert rows(migrated, anna.id) == count + 1  # the side's entry; the project's untouched
    [gone] = items(anna)[:1]
    assert (gone["change"], gone["cause"], gone["entry_id"]) == ("deleted", "gone", side["id"])
    assert gone["entry"]["their_agents"] == agents  # as before the deletion began
    assert all(gone["names"][a] == {"handle": None, "deleted": True} for a in agents)
    assert project["id"] in [e["id"] for e in anna.get("/me/chat-access").json()["allow"]]
    assert rows(migrated, ben.id) == 0


def test_paging_and_who_reads(
    make_client: ClientFactory, anna: flow.Human, ben: flow.Human, migrated: Engine
) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    made = [allow(anna, agents=[mine], owner_id=ben.id).json()["id"] for _ in range(3)]
    first = history(anna, limit=2)
    assert [i["entry_id"] for i in first["items"]] == [made[2], made[1]]
    rest = history(anna, limit=2, cursor=first["next_cursor"])
    assert [i["entry_id"] for i in rest["items"]] == [made[0]]
    assert rest["next_cursor"] is None
    refused = ben.get(PATH, params={"cursor": first["next_cursor"]})
    assert refused.status_code == 400  # a cursor is the reader's own
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner)
    refused = agent.get(PATH)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"]["reason"] == "humans_only"


def test_at_most_the_newest_items_are_kept(
    anna: flow.Human, ben: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chat_access_history, "KEPT", 3)
    mine = profile(migrated, anna.id, "anna-a")
    made = [allow(anna, agents=[mine], owner_id=ben.id).json()["id"] for _ in range(5)]
    assert [i["entry_id"] for i in items(anna)] == made[:1:-1]
    allow(ben, agents="all", owner_id=anna.id)
    assert rows(migrated, anna.id) == 3 and rows(migrated, ben.id) == 1  # per human


def test_the_export_carries_the_history_and_the_deletion_takes_it(
    anna: flow.Human, ben: flow.Human, migrated: Engine, settings: Settings
) -> None:
    mine = profile(migrated, anna.id, "anna-a")
    made = allow(anna, agents=[mine], owner_id=ben.id).json()
    deny(anna, agents=[mine], human_id=ben.id)
    exported = anna.get("/me/export").json()["chat_access_history"]
    assert exported == list(reversed(items(anna)))  # oldest first
    assert exported[0]["entry_id"] == made["id"]
    allow(ben, agents="all", owner_id=anna.id)
    with events.transaction(migrated) as conn:
        account_deletion.delete_account(conn, settings, anna.id)
    assert rows(migrated, anna.id) == 0
    assert rows(migrated, ben.id) >= 1  # ben's own history stays
