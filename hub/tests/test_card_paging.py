"""docs/api.md §1.4, §6.4: the card list and its search page by cursor while the hub reads the
order's keys first and full rows only for the page, and searches a batch of cards at a time
(tsk-ybc2ma72dzvq, PR 2). Pages add up to the whole list in both orders, a search whose hits
lie far apart pages over its batches, cards added between pages neither repeat nor push out
the ones already there, a cursor holds only for what gave it, and a paged search keeps the
reader's hidden windows."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine

from maity_hub import card_search
from tests import flow
from tests.conftest import ClientFactory
from tests.statements import listening
from tests.test_isolation import isolate
from tests.test_reader_windows import _lift_flow
from tests.test_tasks import task

PROJECT = "/projects/maintainer/maity"


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _page(who: Any, params: dict[str, Any]) -> dict[str, Any]:
    got = who.get(f"{PROJECT}/tasks", params=params)
    assert got.status_code == 200, got.text
    body: dict[str, Any] = got.json()
    return body


def _walk(who: Any, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Every page of the list, following `next_cursor` to its end."""
    items: list[dict[str, Any]] = []
    cursor = None
    for _ in range(100):
        page = _page(who, {**params, **({"cursor": cursor} if cursor else {})})
        assert page["items"] or not items, "a cursor led to an empty page"
        items += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            return items
    raise AssertionError("the pages never ended")


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [item["id"] for item in items]


@pytest.mark.parametrize("order", ["board", "updated"])
def test_pages_add_up_to_the_whole_list(owner: flow.Human, order: str) -> None:
    for n in range(9):
        made = task(owner, title=f"Card {n}")
        if n % 3 == 1:
            owner.patch(f"{PROJECT}/tasks/{made['id']}", {"status": "proposed"})
        if n % 3 == 2:
            owner.patch(f"{PROJECT}/tasks/{made['id']}", {"status": "cancelled"})
    whole = _page(owner, {"order": order, "limit": 200})
    assert len(whole["items"]) == 9 and whole["next_cursor"] is None
    for limit in (1, 2, 3, 4, 8, 9):
        assert _ids(_walk(owner, {"order": order, "limit": limit})) == _ids(whole["items"]), limit


def test_the_last_page_ends_exactly_at_the_limit(owner: flow.Human) -> None:
    for _ in range(4):
        task(owner)
    first = _page(owner, {"status": "open", "limit": 2})
    second = _page(owner, {"status": "open", "limit": 2, "cursor": first["next_cursor"]})
    assert len(second["items"]) == 2 and second["next_cursor"] is None
    assert _page(owner, {"status": "open", "limit": 4})["next_cursor"] is None
    three = _page(owner, {"status": "open", "limit": 3})
    assert three["next_cursor"] is not None
    rest = _page(owner, {"status": "open", "limit": 3, "cursor": three["next_cursor"]})
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None


@pytest.mark.parametrize("order", ["board", "updated"])
def test_a_search_with_far_apart_hits_pages_over_its_batches(
    owner: flow.Human, order: str
) -> None:
    """With `limit=2` a batch reads 3, 6, 12 … cards: hits every seventh card, and one found
    only by a note, lie in different batches and on different pages."""
    hits = []
    for n in range(30):
        made = task(owner, title=f"Hit {n}" if n % 7 == 0 else f"Card {n}")
        if n % 7 == 0:
            hits.append(made["id"])
        if n == 10:
            assert owner.post(f"{PROJECT}/tasks/{made['id']}/notes", {"body": "a hit"}).status_code
            hits.append(made["id"])
        if n == 14:
            owner.post(f"{PROJECT}/tasks/{made['id']}/notes", {"body": "another hit"})
    whole = _page(owner, {"q": "hit", "order": order, "status": "all", "limit": 200})
    assert sorted(_ids(whole["items"])) == sorted(hits)
    walked = _walk(owner, {"q": "hit", "order": order, "status": "all", "limit": 2})
    assert walked == whole["items"]
    matched = {item["title"]: item["match"] for item in walked}
    assert matched["Card 10"] == ["note"]
    assert matched["Hit 14"] == ["title", "note"]
    assert matched["Hit 7"] == ["title"]


def test_a_search_keeps_its_place_when_its_hits_change_between_pages(owner: flow.Human) -> None:
    """The last card shown stops matching and a card after it that did not move begins to:
    the next page goes on after the last card shown, so that card is not skipped (§6.4)."""
    a, b, c, d, _ = (task(owner, title=t)["id"] for t in ("Hit a", "Hit b", "c", "Hit d", "e"))
    first = _page(owner, {"q": "hit", "status": "open", "limit": 2})
    assert _ids(first["items"]) == [a, b]
    owner.patch(f"{PROJECT}/tasks/{b}", {"title": "b"})
    owner.patch(f"{PROJECT}/tasks/{c}", {"title": "Hit c"})
    second = _page(
        owner, {"q": "hit", "status": "open", "limit": 2, "cursor": first["next_cursor"]}
    )
    assert (_ids(second["items"]), second["next_cursor"]) == ([c, d], None)


def test_cards_added_between_pages_keep_the_others_in_place(owner: flow.Human) -> None:
    before = [task(owner, title=f"Card {n}")["id"] for n in range(6)]
    first = _page(owner, {"status": "open", "limit": 2})
    added = [task(owner, title=f"Late {n}")["id"] for n in range(3)]
    rest = _walk(owner, {"status": "open", "limit": 2, "cursor": first["next_cursor"]})
    assert _ids(first["items"]) + _ids(rest) == before + added  # unranked: by creation


def test_changes_between_pages_of_updated_order_move_before_the_cursor(
    owner: flow.Human,
) -> None:
    """A card added or edited while a client pages by `updated_at` sorts before the cursor:
    every card that did not change shows once, in order, and no card twice (§6.4)."""
    before = [task(owner, title=f"Card {n}")["id"] for n in range(6)]
    first = _page(owner, {"order": "updated", "limit": 2})
    task(owner, title="Late")
    owner.patch(f"{PROJECT}/tasks/{before[0]}", {"title": "Card 0, edited"})
    rest = _walk(owner, {"order": "updated", "limit": 2, "cursor": first["next_cursor"]})
    seen = _ids(first["items"]) + _ids(rest)
    assert seen == list(reversed(before))[:-1]  # Card 0 changed after the first page
    assert len(set(seen)) == len(seen)


@pytest.mark.parametrize("order", ["board", "updated"])
@pytest.mark.parametrize("q", [None, "card"])
def test_a_cursor_round_trips_and_a_bad_one_is_invalid(
    owner: flow.Human, order: str, q: str | None
) -> None:
    for n in range(3):
        task(owner, title=f"Card {n}")
    params = {"order": order, "limit": 1, **({"q": q} if q else {})}
    first = _page(owner, params)
    again = _page(owner, {**params, "cursor": first["next_cursor"]})
    assert _ids(again["items"]) != _ids(first["items"])
    other = "updated" if order == "board" else "board"
    for bad in (
        "x",
        "%%%",
        "WyJrZXkiXQ",  # ["key"]
        _page(owner, {**params, "status": "open"})["next_cursor"],  # other filters
        _page(owner, {**params, "order": other})["next_cursor"],
    ):
        refused = owner.get(f"{PROJECT}/tasks", params={**params, "cursor": bad})
        assert refused.status_code == 400, bad
        assert refused.json()["error"]["code"] == "invalid", bad
        assert refused.json()["error"]["details"]["fields"] == {"cursor": "invalid"}, bad


@pytest.mark.parametrize("limit", ["0", "201", "-1", "x"])
def test_a_limit_out_of_bounds_is_invalid(owner: flow.Human, limit: str) -> None:
    task(owner)
    refused = owner.get(f"{PROJECT}/tasks?limit={limit}")
    assert refused.status_code == 400 and refused.headers["Maity-Error"] == "invalid"


def test_the_limit_bounds_themselves_hold(owner: flow.Human) -> None:
    for _ in range(3):
        task(owner)
    assert len(_page(owner, {"limit": 1})["items"]) == 1
    assert len(_page(owner, {"limit": 200})["items"]) == 3
    assert len(_page(owner, {})["items"]) == 3  # the default, 50


def test_a_paged_search_keeps_the_readers_windows(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    """A card found only by a note of the agent's window is on none of its pages, and a card
    found by its title names no `note` to it when only such a note matches (§6.2, §6.4)."""
    agent = flow.agent(make_client, owner, role="admin")
    cards = {name: task(owner, title=name)["id"] for name in ("Alpha", "Quokka beta", "Gamma")}
    isolate(owner, agent.id)
    for name, body in (("Alpha", "quokka remark"), ("Quokka beta", "quokka too")):
        assert owner.post(f"{PROJECT}/tasks/{cards[name]}/notes", {"body": body}).status_code == 201
    assert _lift_flow(owner, agent)
    note = owner.post(f"{PROJECT}/tasks/{cards['Gamma']}/notes", {"body": "later quokka"})
    assert note.status_code == 201
    for order in ("board", "updated"):
        params = {"q": "quokka", "order": order, "limit": 1}
        theirs = {i["title"]: i["match"] for i in _walk(agent, params)}
        assert theirs == {"Quokka beta": ["title"], "Gamma": ["note"]}, order
        mine = {i["title"]: i["match"] for i in _walk(owner, params)}
        assert mine == {"Alpha": ["note"], "Quokka beta": ["title", "note"], "Gamma": ["note"]}


def test_a_page_reads_full_rows_only_for_its_cards(owner: flow.Human, migrated: Engine) -> None:
    """Keys first: no statement of a page reads a card's body for every card of the project,
    only for the page's cards (by id)."""
    for n in range(12):
        task(owner, title=f"Card {n}", body="a body")
    sent: list[str] = []
    with listening(migrated, lambda *a: sent.append(a[2])):
        page = _page(owner, {"status": "open", "limit": 3})
    assert len(page["items"]) == 3
    reads_bodies = [s for s in sent if "card.body" in s and "FROM card" in s]
    assert reads_bodies
    for statement in reads_bodies:
        assert "card.id IN" in statement, statement


def test_a_search_reads_no_note_of_a_card_its_own_text_found(
    owner: flow.Human, migrated: Engine
) -> None:
    """Notes are read for the cards nothing else found, and for the shown ones to name their
    `match`: a card found by its title past the page has its notes read never."""
    for n in range(6):
        made = task(owner, title=f"Needle {n}")
        owner.post(f"{PROJECT}/tasks/{made['id']}/notes", {"body": "needle remark"})
    sent: list[tuple[str, Any]] = []
    with listening(migrated, lambda *a: sent.append((a[2], a[3]))):
        page = _page(owner, {"q": "needle", "status": "open", "limit": 2})
    assert [i["match"] for i in page["items"]] == [["title", "note"]] * 2
    note_reads = [p for s, p in sent if "FROM card_note" in s and "card_note.body" in s]
    asked = {v for p in note_reads for v in p if isinstance(v, str) and v.startswith("tsk-")}
    assert asked == {i["id"] for i in page["items"]}


def test_a_card_gone_since_its_key_matches_nothing(migrated: Engine) -> None:
    with migrated.connect() as conn:
        search = card_search.Search(conn, "anything")
        assert search.keep(["tsk-gone"]) == set()
        assert search.places([]) == {}
