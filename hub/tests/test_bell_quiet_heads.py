"""docs/api.md §18.2, tsk-a5pxwgkgr73e: a held bell long-poll whose stamp moved only by rows
that make no item of the human (agents writing to each other) keeps holding without deriving
its answer again (`listing.quietly_moved`); a row that may make an item (a chat with the
human, a mention of them, a request of theirs) still derives and answers at once.

Counting rule: a full derivation is one call of `listing.answer`'s page derive,
`items.derive_page`, counted by wrapping it; the look itself is one statement per pass."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub.notifications import items
from tests import flow
from tests.conftest import ClientFactory
from tests.test_notifications import bell

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human, "maity")
    return human


@pytest.fixture
def derives(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """One entry per derivation of a page (`items.derive_page`), the full read a held pass
    makes when its stamp moved."""
    calls: list[int] = []
    real = items.derive_page

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(items, "derive_page", counted)
    return calls


def _between(agent: flow.Agent, other: flow.Agent, n: int) -> None:
    """`n` messages from one agent to another: no item of the human's."""
    for k in range(n):
        said = agent.post(
            f"{PROJECT}/events",
            {"kind": "message", "type": "notice", "to": other.id, "body": f"between us {k}"},
        )
        assert said.status_code in (200, 201), said.text


def _held(owner: flow.Human, after: str, wait: int) -> tuple[threading.Thread, list[Any]]:
    answers: list[Any] = []
    waiter = threading.Thread(target=lambda: answers.append(bell(owner, after=after, wait=wait)))
    waiter.start()
    time.sleep(0.6)  # the first pass is done and the wait holds
    return waiter, answers


def _while_held(
    owner: flow.Human, derives: list[int], during: Callable[[], None], wait: int = 10
) -> tuple[list[Any], int, float]:
    start = bell(owner, limit=0)["next_after"]
    begun = time.monotonic()
    waiter, answers = _held(owner, start, wait)
    before = len(derives)
    during()
    waiter.join(timeout=wait + 10)
    return answers, len(derives) - before, time.monotonic() - begun


def test_agents_writing_to_each_other_derive_nothing_while_held(
    make_client: ClientFactory, owner: flow.Human, derives: list[int]
) -> None:
    one, two = flow.agent(make_client, owner), flow.agent(make_client, owner)

    def chatter() -> None:
        for _ in range(4):
            _between(one, two, 3)
            time.sleep(0.6)  # past the pass's poll, so every burst is looked at

    answers, derived, took = _while_held(owner, derives, chatter, wait=4)
    assert answers and answers[0]["items"] == []
    # The deadline's last answer derives once; no pass in between did.
    assert derived == 1, derived
    assert took >= 3.5  # it held to the deadline


def test_a_chat_with_the_human_after_agent_chatter_answers_at_once(
    make_client: ClientFactory, owner: flow.Human, derives: list[int]
) -> None:
    one, two = flow.agent(make_client, owner), flow.agent(make_client, owner)

    def chatter_then_chat() -> None:
        _between(one, two, 3)
        time.sleep(0.6)
        one.post(f"{PROJECT}/conversations/{one.id}/messages", {"body": "to you"})

    answers, derived, took = _while_held(owner, derives, chatter_then_chat)
    assert answers and [i["kind"] for i in answers[0]["items"]] == ["chat"]
    assert took < 8 and derived == 1, (took, derived)


def test_a_mention_among_agent_chatter_answers_at_once(
    make_client: ClientFactory, owner: flow.Human, derives: list[int]
) -> None:
    one, two = flow.agent(make_client, owner), flow.agent(make_client, owner)

    def chatter_with_mention() -> None:
        _between(one, two, 2)
        said = one.post(
            f"{PROJECT}/events",
            {"kind": "message", "type": "notice", "to": "all", "body": "@maintainer look"},
        )
        assert said.status_code in (200, 201), said.text
        _between(one, two, 2)

    answers, _, took = _while_held(owner, derives, chatter_with_mention)
    assert answers and "mention" in [i["kind"] for i in answers[0]["items"]]
    assert took < 8


def test_a_read_mark_moving_still_derives(
    make_client: ClientFactory, owner: flow.Human, derives: list[int]
) -> None:
    """Only a move of the heads alone is looked at: a read mark (here the human reading a chat)
    is a stamp part the look leaves to the full derivation."""
    one = flow.agent(make_client, owner)
    one.post(f"{PROJECT}/conversations/{one.id}/messages", {"body": "older"})
    seen = bell(owner, limit=0)["next_after"]

    def read() -> None:
        assert owner.post("/me/notifications/read", {"up_to": seen}).status_code == 200
        time.sleep(1.2)

    _, derived, _ = _while_held(owner, derives, read, wait=3)
    assert derived >= 2, derived  # the pass after the mark, then the deadline
