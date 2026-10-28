"""A page of the notifications is cut from items derived only as far as the page reaches
(docs/api.md §18.2): it equals the page cut from every item of the 30 days, for every
filter, the cursor through items of one timestamp, and `after`."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import tables as t
from maity_hub.notifications import items
from tests import flow
from tests.conftest import ClientFactory
from tests.test_notifications import N, bell

PROJECTS = ("maity", "other")


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    for slug in PROJECTS:
        flow.project(human, slug)
    return human


def talk(make_client: ClientFactory, owner: flow.Human, migrated: Engine) -> None:
    """Chats from three agents in two projects, mentions, requests, some read, and
    groups of events that share one timestamp."""
    for slug in PROJECTS:
        agents = [flow.agent(make_client, owner, slug=slug) for _ in range(3)]
        base = f"/projects/maintainer/{slug}"
        for turn in range(7):
            for agent in agents:
                said = agent.post(
                    f"{base}/conversations/{agent.id}/messages", {"body": f"hi {turn}"}
                )
                assert said.status_code == 201, said.text
        agents[0].post(
            f"{base}/events",
            {"kind": "message", "type": "notice", "to": "all", "body": "@maintainer look"},
        )
        agents[1].post(
            f"{base}/requests", {"class": "decision", "title": f"Which {slug}?", "to": "owner"}
        )
        agents[2].post(f"{base}/conversations/{agents[2].id}/messages", {"body": "@maintainer hey"})
    some = [i["id"] for i in bell(owner, limit=50)["items"] if i["kind"] == "chat"][::4]
    assert owner.post(f"{N}/read", {"ids": some}).status_code == 200
    with migrated.begin() as conn:  # equal timestamps, in groups of four
        seqs = list(conn.execute(select(t.event.c.seq).order_by(t.event.c.seq)).scalars())
        for n, seq in enumerate(seqs):
            moment = conn.execute(
                select(t.event.c.at).where(t.event.c.seq == seqs[n - n % 4])
            ).scalar_one()
            conn.execute(update(t.event).where(t.event.c.seq == seq).values(at=moment))


def pages(owner: flow.Human, **query: Any) -> list[Any]:
    """Every page of a listing by `next_cursor`, whole but for the time of the answer."""
    seen: list[Any] = []
    cursor = None
    for _ in range(200):
        got = bell(owner, **query, **({"cursor": cursor} if cursor else {}))
        got.pop("server_time")
        got.pop("next_after")
        seen.append(got)
        cursor = got["next_cursor"]
        if cursor is None:
            return seen
    raise AssertionError("a listing that does not end")


def after_chain(owner: flow.Human, start: str, limit: int, **query: Any) -> list[Any]:
    seen: list[Any] = []
    position = start
    for _ in range(200):
        got = bell(owner, after=position, limit=limit, **query)
        got.pop("server_time")
        position, token = got["next_after"], got.pop("next_after")
        seen.append(got)
        if not got["items"]:
            return seen
    raise AssertionError(f"a chain that does not end at {token}")


def everything(owner: flow.Human) -> dict[str, Any]:
    found: dict[str, Any] = {}
    kinds = (None, "chat", "mention", "inbox", "chat,mention")
    for limit, kind, unread in itertools.product((1, 2, 3, 5, 50), kinds, (False, True)):
        query: dict[str, Any] = {"limit": limit, "unread": unread}
        if kind:
            query["kind"] = kind
        found[f"pages {query}"] = pages(owner, **query)
    found["project"] = pages(owner, limit=2, project="maintainer/other")
    found["limit 0"] = bell(owner, limit=0) | {"server_time": None, "next_after": None}
    return found


def test_a_page_equals_the_page_cut_from_every_item(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    start = bell(owner, limit=0)["next_after"]
    talk(make_client, owner, migrated)
    bounded = everything(owner)
    chains = {
        (limit, unread): after_chain(owner, start, limit, unread=unread)
        for limit in (1, 4, 50)
        for unread in (False, True)
    }

    def every(conn: Any, where: Any, **_: Any) -> Any:
        return items.derive(conn, where)

    monkeypatch.setattr(items, "derive_page", every)
    assert everything(owner) == bounded
    for (limit, unread), chain in chains.items():
        assert after_chain(owner, start, limit, unread=unread) == chain
    assert sum(len(p["items"]) for p in bounded["pages {'limit': 3, 'unread': False}"]) > 30


def test_a_page_derives_only_a_few_of_the_chats(
    make_client: ClientFactory, owner: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    talk(make_client, owner, migrated)
    classified: list[int] = []
    real: Callable[..., Any] = items._classify

    def counted(look: Any, where: Any, mine: Any, row: Any, hidden: Any) -> Any:
        classified.append(row.seq)
        return real(look, where, mine, row, hidden)

    monkeypatch.setattr(items, "_classify", counted)
    monkeypatch.setattr(items, "CHUNK", 3)
    bell(owner, limit=2)
    bounded = len(classified)
    classified.clear()
    monkeypatch.setattr(items, "derive_page", lambda conn, where, **_: items.derive(conn, where))
    bell(owner, limit=2)
    assert bounded < len(classified) / 2, (bounded, len(classified))
