"""docs/api.md §18.2, tsk-a5pxwgkgr73e: a held bell long-poll whose stamp moved only by rows
that make no item of the human (agents writing to each other) keeps holding without deriving
its answer again (`listing.quietly_moved`); a row that may make an item (a chat with the
human, a mention of them, a request to them) still derives and answers at once among the
chatter, and so does an account record (a personal request, a security item). A personal
request from a project the human is no member of answers at once on its own, without chatter.
A row that changes a relation the derive reads (a cover, a role) makes the next move of a head
derive again, in its own project or, for a cover, with the chatter in another one.

Counting rule: a full derivation is one call of `listing.answer`'s page derive,
`items.derive_page`, counted by wrapping it; the look itself is one statement per pass."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, event, select, update

from maity_hub import clock, events
from maity_hub import tables as t
from maity_hub.notifications import items, listing, records
from tests import flow
from tests.conftest import ClientFactory
from tests.test_notifications import bell
from tests.test_personal_requests import _file, _outside_owner

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


def _between(agent: flow.Agent, other: flow.Agent, n: int, project: str = PROJECT) -> None:
    """`n` messages from one agent to another: no item of the human's."""
    for k in range(n):
        said = agent.post(
            f"{project}/events",
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


def _at_once(answers: list[Any], took: float, kind: str) -> None:
    assert answers and kind in [i["kind"] for i in answers[0]["items"]], answers
    assert took < 8, took


def test_a_request_to_the_human_among_agent_chatter_answers_at_once(
    make_client: ClientFactory, owner: flow.Human, derives: list[int]
) -> None:
    one, two = flow.agent(make_client, owner), flow.agent(make_client, owner)

    def chatter_with_request() -> None:
        _between(one, two, 2)
        asked = one.post(
            f"{PROJECT}/requests", {"class": "decision", "title": "Go?", "to": "owner"}
        )
        assert asked.status_code == 201, asked.text
        _between(one, two, 2)

    answers, _, took = _while_held(owner, derives, chatter_with_request)
    _at_once(answers, took, "inbox")


def test_a_personal_request_among_agent_chatter_answers_at_once(
    make_client: ClientFactory, owner: flow.Human, derives: list[int], migrated: Engine
) -> None:
    one, two = flow.agent(make_client, owner), flow.agent(make_client, owner)

    def chatter_with_personal() -> None:
        _between(one, two, 2)
        _file(migrated, one.id)
        _between(one, two, 2)

    answers, _, took = _while_held(owner, derives, chatter_with_personal)
    _at_once(answers, took, "inbox")


def test_a_personal_request_from_a_project_without_membership_answers_at_once(
    make_client: ClientFactory, owner: flow.Human, derives: list[int], migrated: Engine
) -> None:
    """The asker's owner is no member of the project: the request comes as their account record."""
    outside, agent_id = _outside_owner(make_client, migrated)
    seen = bell(outside, limit=0)["next_after"]
    begun = time.monotonic()
    waiter, answers = _held(outside, seen, 10)
    _file(migrated, agent_id)
    waiter.join(timeout=20)
    _at_once(answers, time.monotonic() - begun, "inbox")


def test_a_security_item_among_agent_chatter_answers_at_once(
    make_client: ClientFactory, owner: flow.Human, derives: list[int], migrated: Engine
) -> None:
    one, two = flow.agent(make_client, owner), flow.agent(make_client, owner)

    def chatter_with_security() -> None:
        _between(one, two, 2)
        with migrated.begin() as conn:
            records.write(conn, owner.id, "second_factor_changed", {"change": "enabled"})
        _between(one, two, 2)

    answers, _, took = _while_held(owner, derives, chatter_with_security)
    _at_once(answers, took, "security")


def test_a_cover_among_agent_chatter_makes_an_older_request_an_item_at_once(
    make_client: ClientFactory, owner: flow.Human, derives: list[int], migrated: Engine
) -> None:
    """A request from one agent to another, filed while the wait holds, is no item of the
    human's, and the pass after it leaves it below the seen head. It becomes the human's when the
    human starts to cover the addressee (`inbox.covers`), and the cover moves no head. The next
    move of a head, agents writing to each other, derives again and finds it (prju's probe,
    review of #1623)."""
    one, two = flow.agent(make_client, owner), flow.agent(make_client, owner)

    def cover_then_chatter() -> None:
        asked = one.post(f"{PROJECT}/requests", {"class": "decision", "title": "Go?", "to": two.id})
        assert asked.status_code == 201, asked.text
        time.sleep(1.2)  # a pass sees the request's head move and holds: it is not the human's
        _cover(migrated, asked.json()["id"], two.id, owner.id)
        time.sleep(0.6)
        _between(one, two, 3)

    answers, _, took = _while_held(owner, derives, cover_then_chatter)
    _at_once(answers, took, "inbox")


def _cover(migrated: Engine, request_id: str, member_id: str, by: str) -> None:
    """A cover of `member_id` by `by` that takes the request, written as cover.py writes it,
    its wakes included: it moves no head of an item kind."""
    with events.transaction(migrated) as conn:
        row = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
        cover = {"for": member_id, "by": by, "since": clock.now().isoformat()}
        conn.execute(update(t.request).where(t.request.c.id == request_id).values(cover=cover))
        events.emit(
            conn,
            row.project_id,
            "cover_started",
            [f"member:{member_id}"],
            {"member_id": member_id, "substitute_id": by, "tasks": [],
             "requests": [request_id], "left": []},  # fmt: skip
        )


def test_a_cover_in_one_project_and_chatter_in_another_answers_at_once(
    make_client: ClientFactory, owner: flow.Human, derives: list[int], migrated: Engine
) -> None:
    """The cover moves no head in its project, and only the other project's head moves after it:
    the look still reads the first project past its seen position (spq4, review of #1623)."""
    flow.project(owner, "other")
    other = "/projects/maintainer/other"
    one, two = flow.agent(make_client, owner), flow.agent(make_client, owner)
    three, four = flow.agent(make_client, owner, "other"), flow.agent(make_client, owner, "other")
    # A message in each project before the wait: its item head then stands past the agents'
    # joins. This head's look reads from the position of any kind and needs none of it; they
    # keep the test red for the right reason on a look from the item heads (a1f50690), where
    # B's joins would make it derive anyway.
    _between(one, two, 1)
    _between(three, four, 1, other)

    def cover_here_chatter_there() -> None:
        asked = one.post(f"{PROJECT}/requests", {"class": "decision", "title": "Go?", "to": two.id})
        assert asked.status_code == 201, asked.text
        time.sleep(1.2)  # a pass sees the request's head move and holds: it is not the human's
        _cover(migrated, asked.json()["id"], two.id, owner.id)
        time.sleep(0.6)
        _between(three, four, 3, other)

    answers, _, took = _while_held(owner, derives, cover_here_chatter_there)
    _at_once(answers, took, "inbox")


def test_a_role_change_among_agent_chatter_derives_again(
    make_client: ClientFactory, owner: flow.Human, derives: list[int]
) -> None:
    """A membership's role or trust is a relation the derive reads (a pool of admins): its row
    is not quiet, so the chatter after it derives again."""
    one, two = flow.agent(make_client, owner), flow.agent(make_client, owner)

    def role_then_chatter() -> None:
        changed = owner.patch(f"{PROJECT}/members/{two.id}", {"trust": "admin"})
        assert changed.status_code == 200, changed.text
        time.sleep(0.6)
        _between(one, two, 3)
        time.sleep(1.2)

    _, derived, _ = _while_held(owner, derives, role_then_chatter, wait=4)
    assert derived >= 2, derived  # a pass after the change, then the deadline


def _per_project_heads(statements: list[str]) -> list[str]:
    """The statements that read each project's highest `seq` (`listing.stamp`'s heads and
    `listing.held_stamp`'s positions), the grouped reads only a held call compares."""
    flat = [" ".join(s.lower().replace('"', "").split()) for s in statements]
    return [s for s in flat if "max(event.seq)" in s and "group by event.project_id" in s]


def test_a_call_that_cannot_hold_reads_no_stamp(
    owner: flow.Human, migrated: Engine, make_client: ClientFactory
) -> None:
    """The positions of any kind cost a grouped read per call: an answer without `wait` reads
    neither them nor the heads, a held one reads both (fmzu, review of #1623)."""
    one, two = flow.agent(make_client, owner), flow.agent(make_client, owner)
    _between(one, two, 2)
    start = bell(owner, limit=0)["next_after"]  # the key's first use is behind
    statements: list[str] = []

    def heard(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        statements.append(statement)

    event.listen(migrated, "before_cursor_execute", heard)
    try:
        bell(owner, limit=0)
        assert _per_project_heads(statements) == [], statements
        statements.clear()
        bell(owner, after=start, wait=1)
        heads = _per_project_heads(statements)
        assert any("event.kind in " in s for s in heads), heads  # the stamp's heads
        assert any("event.kind in " not in s for s in heads), heads  # the positions of any kind
    finally:
        event.remove(migrated, "before_cursor_execute", heard)


def test_the_quiet_kinds_make_no_item() -> None:
    """A kind the look passes over is none the derive reads."""
    assert not listing.QUIET_KINDS & set(items.EVENT_KINDS)
