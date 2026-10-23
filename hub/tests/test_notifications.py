"""Notifications for humans: the bell, positions, read marks and watches (docs/api.md
§18.1–§18.3, §6.4)."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import clock
from maity_hub.notifications import positions
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.test_personal_requests import _file

N = "/me/notifications"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity")
    return human


def bell(who: flow.Human, **query: Any) -> dict[str, Any]:
    response = who.get(N, params=query)
    assert response.status_code == 200, response.text
    return dict(response.json())


def second_session(make_client: ClientFactory, owner: flow.Human) -> flow.Human:
    client = make_client(peer="198.51.100.30")
    client.post("/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD})
    return flow.Human(client, client.get("/api/v1/auth/session").json()["csrf_token"], owner.id)


def test_only_a_humans_session_reads_it(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = flow.agent(make_client, owner)
    refused = agent.get(N)
    assert refused.json()["error"]["details"] == {"reason": "humans_only"}
    assert agent.post(f"{N}/read", {"ids": ["ntf-1"]}).status_code == 403


def test_an_empty_bell(owner: flow.Human) -> None:
    got = bell(owner)
    assert got["counts"]["total"] == 0 and got["by_project"] == {}
    # The owner's own sign-in is an account record of its own session: no alert to
    # confirm from elsewhere, but it is listed.
    assert [i["kind"] for i in got["items"]] == ["security"]
    assert isinstance(got["next_after"], str) and "." not in got["next_after"][:3]
    assert got["next_cursor"] is None


def test_a_request_to_the_human_is_an_inbox_item(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    asked = agent.post(
        "/projects/maity/requests", {"class": "decision", "title": "Which?", "to": "owner"}
    )
    assert asked.status_code == 201, asked.text
    got = bell(owner)
    assert got["counts"]["inbox"] == 1 and got["counts"]["total"] == 1
    assert got["by_project"]["maity"]["inbox"] == 1
    item = next(i for i in got["items"] if i["kind"] == "inbox")
    assert item["title"].endswith("asks: Which?")
    assert item["target"] == {"type": "request", "id": asked.json()["id"]}
    assert item["url"] == "https://hub.example/#/p/maity/inbox"
    assert item["actor"]["member_id"] == agent.id


def test_a_chat_message_counts_and_reads_through_the_chat(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    sent = agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "done"})
    assert sent.status_code in (200, 201), sent.text
    got = bell(owner)
    assert got["counts"]["chat"] == 1 and got["counts"]["total"] == 1
    item = next(i for i in got["items"] if i["kind"] == "chat")
    assert item["target"] == {"type": "conversation", "id": agent.id}
    marked = owner.post(f"{N}/read", {"ids": [item["id"]]})
    assert marked.status_code == 200 and marked.json()["counts"]["chat"] == 0
    chats = owner.get(f"/projects/maity/conversations/{agent.id}/messages").json()
    assert chats["items"][-1]["seq"] == item["seq"]


def test_card_changes_reach_the_cards_creator_and_its_watcher(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    mine = owner.post("/projects/maity/tasks", {"title": "Mine"}).json()
    theirs = agent.post("/projects/maity/tasks", {"title": "Theirs"}).json()
    watched = owner.client.put(
        f"/api/v1/projects/maity/tasks/{theirs['id']}/watch",
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert watched.status_code == 200 and watched.json()["watching"] is True
    claimed = agent.post(f"/projects/maity/tasks/{mine["id"]}/claim", {})
    assert claimed.status_code == 200, claimed.text
    agent.patch(f"/projects/maity/tasks/{theirs['id']}", {"title": "Theirs, renamed"})
    cards = [i for i in bell(owner)["items"] if i["kind"] == "card"]
    reasons = {i["target"]["id"]: i["reason"] for i in cards}
    assert reasons == {mine["id"]: "creator", theirs["id"]: "watcher"}
    # The watch is in nobody's event audience.
    events = owner.get("/projects/maity/events").json()["items"]
    assert all(
        f"member:{owner.id}" not in (e.get("audience") or [])
        for e in events
        if e.get("subject", {}).get("id") == theirs["id"] and e["kind"] == "task_updated"
    )
    unwatched = owner.delete(f"/projects/maity/tasks/{theirs['id']}/watch")
    assert unwatched.json()["watching"] is False
    agent.patch(f"/projects/maity/tasks/{theirs['id']}", {"title": "Again"})
    # Derived when read: without the watch, the card is not the human's any more.
    later = [i for i in bell(owner)["items"] if i["kind"] == "card"]
    assert all(i["target"]["id"] == mine["id"] for i in later)
    assert agent.client.put(
        f"/api/v1/projects/maity/tasks/{theirs['id']}/watch", headers=agent.auth | agent.key()
    ).json()["error"]["details"] == {"reason": "humans_only"}


def test_own_actions_never_notify(owner: flow.Human) -> None:
    card = owner.post("/projects/maity/tasks", {"title": "Mine"}).json()
    owner.patch(f"/projects/maity/tasks/{card['id']}", {"title": "Renamed"})
    assert [i["kind"] for i in bell(owner)["items"]] == ["security"]


def test_positions_follow_new_items_and_never_skip(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    start = bell(owner, limit=0)
    assert start["items"] == []
    for n in range(3):
        agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": f"m{n}"})
    first = bell(owner, after=start["next_after"], limit=2)
    assert [i["kind"] for i in first["items"]] == ["chat", "chat"]
    assert first["items"][0]["seq"] < first["items"][1]["seq"]
    rest = bell(owner, after=first["next_after"], limit=2)
    assert len(rest["items"]) == 1 and rest["items"][0]["seq"] > first["items"][1]["seq"]
    assert bell(owner, after=rest["next_after"])["items"] == []


def test_a_position_that_does_not_open_is_invalid(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    other = flow.human(make_client, migrated, "someone")
    theirs = bell(other, limit=0)["next_after"]
    mine = bell(owner, limit=0)["next_after"]
    tampered = mine[:-2] + ("AA" if mine[-2:] != "AA" else "BB")
    for bad in (theirs, tampered, "4237.118", "x"):
        response = owner.get(N, params={"after": bad})
        assert response.json()["error"]["details"]["fields"] == {"after": "position"}, bad
        marked = owner.post(f"{N}/read", {"up_to": bad})
        assert marked.json()["error"]["details"]["fields"] == {"up_to": "position"}


def test_a_changed_instance_key_invalidates_positions(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    old = bell(owner, limit=0)["next_after"]
    keyed = make_client(secret_key=b"k" * 32)
    keyed.post("/api/v1/auth/login", json={"handle": "maintainer", "password": factory.PASSWORD})
    csrf = keyed.get("/api/v1/auth/session").json()["csrf_token"]
    response = keyed.get(f"/api/v1{N}", params={"after": old}, headers={"X-CSRF-Token": csrf})
    assert response.json()["error"]["details"]["fields"] == {"after": "position"}


def test_a_big_vector_becomes_a_handle(
    make_client: ClientFactory, owner: flow.Human, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(positions, "MAX_LENGTH", 40)
    handle = bell(owner, limit=0)["next_after"]
    monkeypatch.setattr(positions, "MAX_LENGTH", 4096)
    assert bell(owner, after=handle)["items"] == []


def test_mark_all_read_skips_security_items(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = flow.agent(make_client, owner)
    second_session(make_client, owner)
    card = owner.post("/projects/maity/tasks", {"title": "Mine"}).json()
    agent.post(f"/projects/maity/tasks/{card["id"]}/claim", {})
    got = bell(owner)
    assert got["counts"]["card"] == 1 and got["counts"]["security"] >= 1
    after = owner.post(f"{N}/read", {"up_to": got["next_after"]}).json()
    assert after["counts"]["card"] == 0
    assert after["counts"]["security"] == got["counts"]["security"]


def test_who_may_confirm_a_sign_in(make_client: ClientFactory, owner: flow.Human) -> None:
    newer = second_session(make_client, owner)
    newer_id = newer.get("/auth/session").json()["session_id"]
    alert = next(
        i for i in bell(owner)["items"] if i["target"] == {"type": "session", "id": newer_id}
    )
    # The session it reports on cannot confirm itself.
    newer.post(f"{N}/read", {"ids": [alert["id"]]})
    assert next(i for i in bell(owner)["items"] if i["id"] == alert["id"])["read"] is False
    # An older session in good standing can; that confirms the newer one's standing.
    owner.post(f"{N}/read", {"ids": [alert["id"]]})
    assert next(i for i in bell(owner)["items"] if i["id"] == alert["id"])["read"] is True
    listed = {s["id"]: s for s in owner.get("/auth/sessions").json()["items"]}
    assert listed[newer_id]["created"]["record"] == alert["record"]


def test_a_personal_request_is_one_inbox_item_from_its_record(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    request_id = _file(migrated, agent.id)
    got = bell(owner)
    inbox = [i for i in got["items"] if i["kind"] == "inbox"]
    assert len(inbox) == 1 and inbox[0]["record"].startswith("acr-")
    assert inbox[0]["url"] == f"https://hub.example/#/requests/{request_id}"
    assert got["counts"]["inbox"] == 1


def test_the_long_poll_returns_on_a_new_item(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = flow.agent(make_client, owner)
    start = bell(owner, limit=0)["next_after"]
    answers: list[dict[str, Any]] = []
    waiter = threading.Thread(target=lambda: answers.append(bell(owner, after=start, wait=10)))
    begun = time.monotonic()
    waiter.start()
    time.sleep(0.6)
    agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "now"})
    waiter.join(timeout=15)
    assert answers and [i["kind"] for i in answers[0]["items"]] == ["chat"]
    assert time.monotonic() - begun < 8


def test_the_cursor_keeps_items_that_share_a_timestamp(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    frozen = clock.now().replace(microsecond=123456)
    clock.set_source(lambda: frozen)
    for n in range(3):
        agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": f"m{n}"})
    seen: list[int] = []
    page = bell(owner, kind="chat", limit=1)
    seen += [i["seq"] for i in page["items"]]
    while page["next_cursor"]:
        page = bell(owner, kind="chat", limit=1, cursor=page["next_cursor"])
        seen += [i["seq"] for i in page["items"]]
    assert len(seen) == 3 and len(set(seen)) == 3


def test_a_session_ended_during_a_wait_gets_nothing(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    other = second_session(make_client, owner)
    mine = owner.get("/auth/session").json()["session_id"]
    start = bell(owner, limit=0)["next_after"]
    answers: list[Any] = []
    waiter = threading.Thread(
        target=lambda: answers.append(owner.get(N, params={"after": start, "wait": 10}))
    )
    waiter.start()
    time.sleep(0.6)
    # Another password session ends the waiting one.
    assert other.delete(f"/auth/sessions/{mine}").json()["ended_by"] == "revoked"
    agent.post(f"/projects/maity/conversations/{agent.id}/messages", {"body": "private"})
    waiter.join(timeout=15)
    assert answers and answers[0].status_code == 401
    assert "private" not in answers[0].text


def test_two_first_uses_agree_on_one_position_key(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def first_use() -> None:
        try:
            barrier.wait()
            positions.prepare(migrated, None)
        except BaseException as error:  # noqa: BLE001  reported below
            errors.append(error)

    threads = [threading.Thread(target=first_use) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    issued = bell(owner, limit=0)["next_after"]
    assert bell(owner, after=issued)["items"] == []


def test_a_card_view_shows_only_the_readers_own_watch(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    card = agent.post("/projects/maity/tasks", {"title": "Watched"}).json()
    owner.client.put(
        f"/api/v1/projects/maity/tasks/{card['id']}/watch", headers={"X-CSRF-Token": owner.csrf}
    )
    assert owner.get(f"/projects/maity/tasks/{card['id']}").json()["watching"] is True
    listed = owner.get("/projects/maity/tasks").json()["items"]
    assert next(c for c in listed if c["id"] == card["id"])["watching"] is True
    assert agent.get(f"/projects/maity/tasks/{card['id']}").json()["watching"] is False
    assert "watchers" not in owner.get(f"/projects/maity/tasks/{card['id']}").json()
