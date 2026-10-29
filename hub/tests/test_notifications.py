"""Notifications for humans: the bell, positions, read marks and watches (docs/api.md
§18.1–§18.3, §6.4)."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
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
        "/projects/maintainer/maity/requests",
        {"class": "decision", "title": "Which?", "to": "owner"},
    )
    assert asked.status_code == 201, asked.text
    got = bell(owner)
    assert got["counts"]["inbox"] == 1 and got["counts"]["total"] == 1
    assert got["by_project"]["maintainer/maity"]["inbox"] == 1
    item = next(i for i in got["items"] if i["kind"] == "inbox")
    assert item["title"].endswith("asks: Which?")
    assert item["target"] == {"type": "request", "id": asked.json()["id"]}
    assert item["url"] == "https://hub.example/maintainer/maity/inbox"
    assert item["actor"]["member_id"] == agent.id


def test_a_chat_message_counts_and_reads_through_the_chat(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    sent = agent.post(
        f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "done"}
    )
    assert sent.status_code in (200, 201), sent.text
    got = bell(owner)
    assert got["counts"]["chat"] == 1 and got["counts"]["total"] == 1
    item = next(i for i in got["items"] if i["kind"] == "chat")
    assert item["target"] == {"type": "conversation", "id": agent.id}
    marked = owner.post(f"{N}/read", {"ids": [item["id"]]})
    assert marked.status_code == 200 and marked.json()["counts"]["chat"] == 0
    chats = owner.get(f"/projects/maintainer/maity/conversations/{agent.id}/messages").json()
    assert chats["items"][-1]["seq"] == item["seq"]


def test_cards_and_watches_notify_nobody(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """§18.1 (2026-10-26): a card's changes, and a watch on it, show on the board, not
    as notifications; only four kinds remain, and items carry no `reason`."""
    agent = flow.agent(make_client, owner)
    mine = owner.post("/projects/maintainer/maity/tasks", {"title": "Mine"}).json()
    theirs = agent.post("/projects/maintainer/maity/tasks", {"title": "Theirs"}).json()
    watched = owner.client.put(
        f"/api/v1/projects/maintainer/maity/tasks/{theirs['id']}/watch",
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert watched.status_code == 200
    assert agent.post(f"/projects/maintainer/maity/tasks/{mine['id']}/claim", {}).status_code == 200
    agent.patch(f"/projects/maintainer/maity/tasks/{theirs['id']}", {"title": "Theirs, renamed"})
    got = bell(owner)
    assert got["items"] == [
        i for i in got["items"] if i["kind"] in ("inbox", "chat", "mention", "security")
    ]
    assert not [i for i in got["items"] if i["kind"] != "security"]
    assert set(got["counts"]) == {"inbox", "chat", "mention", "security", "total"}
    assert all("reason" not in i for i in got["items"])


def test_an_unknown_kind_is_invalid(owner: flow.Human) -> None:
    for asked, reason in (
        ("card", "unknown"),
        ("agent,chat", "unknown"),
        ("bogus", "unknown"),
    ):
        refused = owner.get(N, params={"kind": asked})
        assert refused.status_code == 400, asked
        assert refused.json()["error"]["details"]["fields"] == {"kind": reason}
    head = bell(owner, limit=0)["next_after"]
    marked = owner.post(f"{N}/read", {"up_to": head, "kind": "ticker"})
    assert marked.json()["error"]["details"]["fields"] == {"kind": "unknown"}


def test_a_request_opened_to_the_admins_reaches_an_admin(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    """§18.1: `request_forwarded` that opens the request to `trust:admin` is an `inbox`
    item for a human holding `admin`, though the request was not addressed to them."""
    agent = flow.agent(make_client, owner)
    admin = flow.human(make_client, migrated, "an-admin")
    with migrated.connect() as conn:
        project_id = str(conn.execute(select(t.project.c.id)).scalar_one())
    factory.membership(migrated, project_id, "admin", human_id=admin.id)
    asked = agent.post(
        "/projects/maintainer/maity/requests",
        {"class": "decision", "title": "Which?", "to": "owner"},
    ).json()
    assert not [i for i in bell(admin)["items"] if i["kind"] == "inbox"]
    opened = owner.post(
        f"/projects/maintainer/maity/requests/{asked['id']}/forward",
        {"to": "trust:admin", "reason": "yours"},
    )
    assert opened.status_code == 200, opened.text
    [found] = [i for i in bell(admin)["items"] if i["kind"] == "inbox"]  # one per request
    assert found["target"] == {"type": "request", "id": asked["id"]}
    events = admin.get("/projects/maintainer/maity/events").json()["items"]
    forwarded = max(e["seq"] for e in events if e["kind"] == "request_forwarded")
    assert found["seq"] == forwarded  # the forward itself is the item
    assert found["title"].endswith("asks: Which?")
    assert not [i for i in bell(owner)["items"] if i["kind"] == "inbox"]  # no longer holds it
    with migrated.begin() as conn:  # the admin loses the role: the item goes with it
        conn.execute(
            update(t.membership).where(t.membership.c.human_id == admin.id).values(trust="member")
        )
    assert not [i for i in bell(admin)["items"] if i["kind"] == "inbox"]


def test_a_claim_leaves_the_item_with_the_claiming_admin_only(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    agent = flow.agent(make_client, owner)
    admins = [flow.human(make_client, migrated, h) for h in ("admin-one", "admin-two")]
    with migrated.connect() as conn:
        project_id = str(conn.execute(select(t.project.c.id)).scalar_one())
    for admin in admins:
        factory.membership(migrated, project_id, "admin", human_id=admin.id)
    asked = agent.post(
        "/projects/maintainer/maity/requests",
        {"class": "decision", "title": "Which?", "to": "owner"},
    ).json()
    owner.post(
        f"/projects/maintainer/maity/requests/{asked['id']}/forward",
        {"to": "trust:admin", "reason": "yours"},
    )
    claimed = admins[0].post(f"/projects/maintainer/maity/requests/{asked['id']}/claim", {})
    assert claimed.status_code == 200, claimed.text
    holding, other = ([i for i in bell(a)["items"] if i["kind"] == "inbox"] for a in admins)
    assert len(holding) == 1 and other == []


def test_own_actions_never_notify(owner: flow.Human) -> None:
    card = owner.post("/projects/maintainer/maity/tasks", {"title": "Mine"}).json()
    owner.patch(f"/projects/maintainer/maity/tasks/{card['id']}", {"title": "Renamed"})
    assert [i["kind"] for i in bell(owner)["items"]] == ["security"]


def test_positions_follow_new_items_and_never_skip(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    start = bell(owner, limit=0)
    assert start["items"] == []
    for n in range(3):
        agent.post(
            f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": f"m{n}"}
        )
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
    said = agent.post(
        "/projects/maintainer/maity/events",
        {"kind": "message", "type": "notice", "to": "all", "body": "@maintainer look"},
    )
    assert said.status_code in (200, 201), said.text
    got = bell(owner)
    assert got["counts"]["mention"] == 1 and got["counts"]["security"] >= 1
    after = owner.post(f"{N}/read", {"up_to": got["next_after"]}).json()
    assert after["counts"]["mention"] == 0
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
    assert inbox[0]["url"] == f"https://hub.example/requests/{request_id}"
    assert got["counts"]["inbox"] == 1


def test_the_long_poll_returns_on_a_new_item(make_client: ClientFactory, owner: flow.Human) -> None:
    agent = flow.agent(make_client, owner)
    start = bell(owner, limit=0)["next_after"]
    answers: list[dict[str, Any]] = []
    waiter = threading.Thread(target=lambda: answers.append(bell(owner, after=start, wait=10)))
    begun = time.monotonic()
    waiter.start()
    time.sleep(0.6)
    agent.post(f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "now"})
    waiter.join(timeout=15)
    assert answers and [i["kind"] for i in answers[0]["items"]] == ["chat"]
    assert time.monotonic() - begun < 8


def test_the_long_poll_answers_when_the_hub_stops(owner: flow.Human) -> None:
    from maity_hub import longpoll

    start = bell(owner, limit=0)["next_after"]
    answers: list[dict[str, Any]] = []
    waiter = threading.Thread(target=lambda: answers.append(bell(owner, after=start, wait=30)))
    begun = time.monotonic()
    waiter.start()
    time.sleep(0.6)
    longpoll.begin_shutdown()
    waiter.join(timeout=10)
    assert answers and answers[0]["items"] == []
    assert time.monotonic() - begun < 5  # not the 30 seconds it asked for


def test_the_cursor_keeps_items_that_share_a_timestamp(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    frozen = clock.now().replace(microsecond=123456)
    clock.set_source(lambda: frozen)
    for n in range(3):
        agent.post(
            f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": f"m{n}"}
        )
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
    agent.post(f"/projects/maintainer/maity/conversations/{agent.id}/messages", {"body": "private"})
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
    card = agent.post("/projects/maintainer/maity/tasks", {"title": "Watched"}).json()
    owner.client.put(
        f"/api/v1/projects/maintainer/maity/tasks/{card['id']}/watch",
        headers={"X-CSRF-Token": owner.csrf},
    )
    assert owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["watching"] is True
    listed = owner.get("/projects/maintainer/maity/tasks").json()["items"]
    assert next(c for c in listed if c["id"] == card["id"])["watching"] is True
    assert agent.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()["watching"] is False
    assert "watchers" not in owner.get(f"/projects/maintainer/maity/tasks/{card['id']}").json()


def test_a_malformed_cursor_is_invalid(owner: flow.Human) -> None:
    import base64
    import json

    raw = json.dumps(["2026-10-23T10:00:00+00:00", "x", 1]).encode()
    cursor = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    response = owner.get(N, params={"cursor": cursor})
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == {"cursor": "invalid"}


def test_a_replayed_card_write_carries_watching(
    make_client: ClientFactory, owner: flow.Human
) -> None:
    agent = flow.agent(make_client, owner)
    key = {"Idempotency-Key": "replay-key-0000000001"}
    body = {"title": "Once"}
    first = agent.client.post(
        "/api/v1/projects/maintainer/maity/tasks", json=body, headers=agent.auth | key
    )
    again = agent.client.post(
        "/api/v1/projects/maintainer/maity/tasks", json=body, headers=agent.auth | key
    )
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert first.json()["watching"] is False and again.json()["watching"] is False


# --- group chats (§9.2) ----------------------------------------------------------------


def group_member(make_client: ClientFactory, engine: Engine, handle: str) -> flow.Human:
    from tests.test_group_chats import other_human

    return other_human(make_client, engine, handle)


def test_a_group_chat_notifies_its_participants(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from tests.test_group_chats import create, say

    someone = group_member(make_client, migrated, "someone")
    chat = create(owner, someone.id, title="Release go/no-go").json()
    assert say(someone, chat["id"], "ship it?").status_code in (200, 201)
    got = bell(owner)
    assert got["counts"]["chat"] == 1 and got["by_project"]["maintainer/maity"]["chat"] == 1
    item = next(i for i in got["items"] if i["kind"] == "chat")
    assert item["title"] == "Human someone in Release go/no-go"
    assert item["target"] == {"type": "conversation", "id": chat["id"]}
    assert item["url"] == f"https://hub.example/maintainer/maity/chat/{chat['id']}"
    marked = owner.post(f"{N}/read", {"ids": [item["id"]]}).json()
    assert marked["counts"]["chat"] == 0
    say(owner, chat["id"], "yes")  # the writer's own message notifies nobody but the others
    assert bell(owner)["counts"]["chat"] == 0
    assert bell(someone)["counts"]["chat"] == 1


def test_an_observer_reads_along_without_notifications(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from tests.test_group_chats import create, say

    agent = flow.agent(make_client, owner)  # the owner owns it
    someone = group_member(make_client, migrated, "someone")
    chat = create(someone, agent.id, title="Agents only").json()
    assert chat.get("id"), chat
    say(agent, chat["id"], "working on it")
    got = bell(owner)
    assert got["counts"]["chat"] == 0
    assert not any(i["target"] == {"type": "conversation", "id": chat["id"]} for i in got["items"])


def test_a_mention_in_a_group_chat_is_a_mention(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from tests.test_group_chats import create, say

    someone = group_member(make_client, migrated, "someone")
    chat = create(owner, someone.id, title="Room").json()
    say(someone, chat["id"], "@maintainer please look")
    item = next(i for i in bell(owner)["items"] if i["kind"] in ("chat", "mention"))
    assert item["kind"] == "mention"
    assert item["title"] == "Human someone mentioned you in Room"


def test_after_leaving_a_group_chat_nothing_more(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from sqlalchemy import update

    from maity_hub import tables as t
    from tests.test_group_chats import create, membership_row, say

    someone = group_member(make_client, migrated, "someone")
    third = group_member(make_client, migrated, "third")
    chat = create(someone, owner.id, third.id, title="Room").json()
    say(someone, chat["id"], "before you left")
    assert bell(owner)["counts"]["chat"] == 1
    mine = membership_row(migrated, owner.id).id
    with migrated.begin() as conn:  # the owner left the chat
        conn.execute(
            update(t.conversation_participant)
            .where(
                t.conversation_participant.c.conversation_id == chat["id"],
                t.conversation_participant.c.membership_id == mine,
            )
            .values(here=None, left_at=clock.now(), reason="left")
        )
    say(someone, chat["id"], "after you left")
    got = bell(owner)
    # A chat the human left drops out, what came before included (§18.1).
    assert got["counts"]["chat"] == 0
    assert not any(i["kind"] == "chat" for i in got["items"])


def test_a_group_message_redacted_before_it_is_read_counts_as_the_chat_counts_it(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine
) -> None:
    from tests.test_group_chats import create, redact, say

    someone = group_member(make_client, migrated, "someone")
    chat = create(owner, someone.id, title="Room").json()
    seq = say(someone, chat["id"], "a secret").json()["seq"]
    assert redact(someone, seq).status_code == 200
    listed = owner.get("/projects/maintainer/maity/conversations").json()["items"]
    unread = next(c["unread"] for c in listed if c["id"] == chat["id"])
    got = bell(owner)
    assert got["counts"]["chat"] == unread == 1
    assert got["by_project"]["maintainer/maity"]["chat"] == 1
    item = next(i for i in got["items"] if i["kind"] == "chat")
    assert (item["redacted"], item["title"]) == (True, None)
