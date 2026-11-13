"""A human's 1:1 message and an agent's `maity wait` (tsk-3zm149w7bxg6): a direct conversation
with the agent's owner ends the wait without a mention (docs/api.md §9.1, §8.2); a two-party
group chat with a human of another side wakes the agent only by a mention (§9.2)."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine

from tests import flow
from tests.conftest import ClientFactory
from tests.test_chat_access import allow
from tests.test_group_chats import create, handle, other_human, owner  # noqa: F401

EVENTS = "/projects/maintainer/maity/events"
CHATS = "/projects/maintainer/maity/conversations"


def _waited(agent: flow.Agent, send: Callable[[], Any], wait: int) -> tuple[list[str], float]:
    """The bodies of the messages a long-poll the agent opened before `send` returns, and
    how long it held."""
    cursor = agent.get(f"{EVENTS}?after=latest").json()["cursor"]
    with ThreadPoolExecutor(max_workers=1) as pool:
        start = time.monotonic()
        waiting = pool.submit(agent.get, f"{EVENTS}?after={cursor}&wait={wait}")
        time.sleep(0.5)  # the poll is open before the message is written
        sent = send()
        assert sent.status_code == 201, sent.text
        body = waiting.result(timeout=wait + 10).json()
    bodies = [e["payload"].get("body") for e in body["items"] if e["kind"] == "message"]
    return bodies, time.monotonic() - start


@pytest.mark.parametrize("route", ["conversation", "events"])
def test_the_owners_direct_message_ends_the_wait_without_a_mention(
    owner: flow.Human, make_client: ClientFactory, route: str  # noqa: F811
) -> None:
    agent = flow.agent(make_client, owner)

    def send() -> Any:
        if route == "conversation":
            return owner.post(f"{CHATS}/{agent.id}/messages", {"body": "are you there?"})
        return owner.post(
            EVENTS,
            {
                "kind": "message",
                "type": "chat",
                "body": "are you there?",
                "conversation_id": agent.id,
            },
        )

    bodies, held = _waited(agent, send, wait=20)
    assert bodies == ["are you there?"]
    assert held < 8  # woken by the message, not by the timeout


def test_a_two_party_group_chat_with_another_human_wakes_only_by_a_mention(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine  # noqa: F811
) -> None:
    # A human the agent reports to but who is not its owner has no direct conversation with
    # it (§9.1): their 1:1 is a group chat of the two (§9.2), the owner having said yes (§9.6).
    agent = flow.agent(make_client, owner)
    boss = other_human(make_client, migrated, "boss")
    entry = allow(owner, agents=[agent.id], owner_id=boss.id, their_human=True)
    assert entry.status_code == 201, entry.text
    chat = create(boss, agent.id, title=None)
    assert chat.status_code == 201, chat.text
    chat_id = chat.json()["id"]
    assert [p["member_id"] for p in chat.json()["participants"]] == [boss.id, agent.id]

    plain, held = _waited(
        agent, lambda: boss.post(f"{CHATS}/{chat_id}/messages", {"body": "are you there?"}), wait=2
    )
    assert plain == [] and held >= 1.5  # not woken: no mention (§9.2)

    mention = f"@{handle(migrated, agent.id)} are you there?"
    pinged, held = _waited(
        agent, lambda: boss.post(f"{CHATS}/{chat_id}/messages", {"body": mention}), wait=20
    )
    assert pinged == [mention] and held < 8
