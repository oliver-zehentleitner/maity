"""docs/api.md §6.4: card order within a status column, and `move`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock, ranks
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import task


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def column(who: Any, status: str = "open") -> list[str]:
    return [c["id"] for c in who.get(f"/projects/maity/tasks?status={status}").json()["items"]]


def move(who: Any, card_id: str, **body: Any) -> Any:
    return who.post(f"/projects/maity/tasks/{card_id}/move", body)


def rank_events(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        rows = conn.execute(
            select(t.event).where(t.event.c.kind == "task_updated").order_by(t.event.c.seq)
        ).all()
    return [r for r in rows if r.payload.get("fields") == ["rank"]]


def test_a_move_places_the_card_and_ranks_only_what_it_must(
    owner: flow.Human, migrated: Engine
) -> None:
    a, b, c, d = (task(owner, title=x)["id"] for x in "abcd")
    assert column(owner) == [a, b, c, d]  # unranked: by creation
    moved = move(owner, c, before=b)
    assert moved.status_code == 200, moved.text
    assert column(owner) == [a, c, b, d]
    ranked = {e.payload["id"]: e.payload["rank"] for e in rank_events(migrated)}
    assert set(ranked) == {a, c}  # a needs a rank to stay first; b and d do not
    assert moved.json()["rank"] == ranked[c]
    assert all(e.audience and e.payload["project_state"] == "build" for e in rank_events(migrated))
    move(owner, d, to="top")
    assert column(owner) == [d, a, c, b]
    move(owner, a, to="bottom")
    assert column(owner) == [d, c, b, a]
    move(owner, d, after=b)
    assert column(owner) == [c, b, d, a]


def test_the_order_lasts_through_a_status_change(owner: flow.Human) -> None:
    a, b, c = (task(owner, title=x)["id"] for x in "abc")
    move(owner, c, to="top")
    assert column(owner) == [c, a, b]
    owner.patch(f"/projects/maity/tasks/{c}", {"status": "proposed"})
    owner.patch(f"/projects/maity/tasks/{c}", {"status": "open"})
    assert column(owner) == [c, a, b]  # the rank stays


@pytest.mark.parametrize(
    "body", [{}, {"to": "top", "before": "tsk-x"}, {"to": "middle"}, {"before": "x", "after": "y"}]
)
def test_one_place_exactly(owner: flow.Human, body: dict[str, Any]) -> None:
    card = task(owner)["id"]
    assert move(owner, card, **body).status_code == 400


def test_a_neighbour_must_exist_and_share_the_column(owner: flow.Human) -> None:
    a, b = task(owner)["id"], task(owner)["id"]
    proposed = task(owner, status="proposed")["id"]
    assert move(owner, a, before="tsk-nonexistent").status_code == 404
    other = move(owner, a, after=proposed)
    assert other.json()["error"]["details"]["fields"] == {"after": "not_in_this_column"}
    itself = move(owner, a, before=a)
    assert itself.json()["error"]["details"]["fields"] == {"before": "not_in_this_column"}
    assert move(owner, b, before=a).status_code == 200


def test_who_may_move(owner: flow.Human, make_client: ClientFactory) -> None:
    card = task(owner)["id"]
    task(owner)
    member = flow.agent(make_client, owner)
    refused = member.post(f"/projects/maity/tasks/{card}/move", {"to": "bottom"})
    assert refused.status_code == 403
    admin = flow.agent(make_client, owner, role="admin")
    assert admin.post(f"/projects/maity/tasks/{card}/move", {"to": "bottom"}).status_code == 200


def test_a_closed_project_refuses_and_a_freeze_does_not(owner: flow.Human) -> None:
    a, b = task(owner)["id"], task(owner)["id"]
    owner.patch("/projects/maity", {"state": "freeze", "reason": "release"})
    assert move(owner, b, to="top").status_code == 200  # no reason needed: no status changes
    owner.patch("/projects/maity", {"state": "accepted", "reason": "done"})
    answer = move(owner, a, to="top")
    assert (answer.status_code, answer.headers["Maity-Error"]) == (409, "project_closed")


def test_the_resume_packet_lists_assigned_cards_in_order(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    first, second = (task(owner, assigned_to=agent.id)["id"] for _ in range(2))
    move(owner, second, to="top")
    assigned = [c["id"] for c in agent.resume().json()["assigned"]]
    assert assigned == [second, first]


def test_many_moves_keep_the_order(owner: flow.Human) -> None:
    cards = [task(owner, title=str(i))["id"] for i in range(6)]
    expected = list(cards)
    for step in range(40):
        card = expected[-1]
        move(owner, card, after=expected[0])
        expected.remove(card)
        expected.insert(1, card)
        assert column(owner) == expected, step


def card(card_id: str, rank: str | None, n: int) -> SimpleNamespace:
    created = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=n)
    return SimpleNamespace(id=card_id, rank=rank, created_at=created)


def test_keys_that_grow_too_long_spread_the_column_out() -> None:
    column_ = [card(f"c{i}", None, i) for i in range(6)]
    longest, spreads = 0, 0
    for _ in range(150):  # always between the same two: past ~116 a key passes 24
        column_.sort(key=ranks.column_key)
        last = column_[-1]
        changed = ranks.place(column_, last.id, 1)
        for c in column_:
            c.rank = changed.get(c.id, c.rank)
        longest = max([longest, *(len(k) for k in changed.values())])
        spreads += len(changed) == len(column_)
        order = [c.id for c in sorted(column_, key=ranks.column_key)]
        assert order[1] == last.id
    assert longest <= ranks.LONGEST
    assert spreads >= 1  # the keys did grow that far: the spread is what kept them short


def test_equal_ranks_are_spread_out_rather_than_refused() -> None:
    a, b, x = card("a", "i", 0), card("b", "i", 1), card("x", None, 2)
    changed = ranks.place([a, b, x], "x", 1)
    assert set(changed) == {"a", "b", "x"}
    assert changed["a"] < changed["x"] < changed["b"]


def test_a_move_between_equal_ranks(owner: flow.Human) -> None:
    a = task(owner)["id"]
    b = task(owner, status="proposed")["id"]
    x = task(owner)["id"]
    move(owner, a, to="top")
    move(owner, b, to="top")  # the first key of an empty column: the same as a's
    owner.patch(f"/projects/maity/tasks/{b}", {"status": "open"})  # the rank goes along
    assert column(owner) == [a, b, x]  # equal ranks: by creation
    moved = move(owner, x, after=a)
    assert moved.status_code == 200, moved.text
    assert column(owner) == [a, x, b]
    listed = owner.get("/projects/maity/tasks?status=open").json()["items"]
    assert len({c["rank"] for c in listed}) == 3


def pages(who: Any, query: str, cursor: str | None = None) -> tuple[list[str], str | None]:
    url = f"/projects/maity/tasks?{query}" + (f"&cursor={cursor}" if cursor else "")
    body = who.get(url).json()
    return [c["id"] for c in body["items"]], body["next_cursor"]


def test_paging_goes_on_after_the_last_card_shown(owner: flow.Human) -> None:
    c = [task(owner, title=str(i))["id"] for i in range(6)]
    first, cursor = pages(owner, "status=open&limit=3")
    assert first == c[:3]
    move(owner, c[0], to="bottom")  # ranks every card: the keys change, not the order
    second, cursor = pages(owner, "status=open&limit=3", cursor)
    assert second == c[3:6]
    third, cursor = pages(owner, "status=open&limit=3", cursor)
    assert (third, cursor) == ([c[0]], None)  # the moved card shows again, nothing is lost


def test_paging_after_a_move_ranks_the_last_card_shown(owner: flow.Human) -> None:
    c = [task(owner, title=str(i))["id"] for i in range(6)]
    first, cursor = pages(owner, "status=open&limit=3")
    move(owner, c[5], before=c[3])  # c0–c2 take ranks on the way
    second, _ = pages(owner, "status=open&limit=3", cursor)
    assert second == [c[5], c[3], c[4]]


def test_paging_after_the_last_card_shown_left(owner: flow.Human) -> None:
    c = [task(owner, title=str(i))["id"] for i in range(6)]
    _, cursor = pages(owner, "status=open&limit=3")
    owner.patch(f"/projects/maity/tasks/{c[2]}", {"status": "proposed"})
    second, _ = pages(owner, "status=open&limit=3", cursor)
    assert second == c[3:6]


@pytest.mark.parametrize("order", ["board", "updated"])
def test_a_cursor_holds_for_its_filters_only(owner: flow.Human, order: str) -> None:
    for _ in range(3):
        task(owner)
    _, cursor = pages(owner, f"order={order}&limit=1")
    assert cursor is not None
    assert (
        owner.get(f"/projects/maity/tasks?order={order}&limit=1&cursor={cursor}").status_code == 200
    )
    for other in (f"order={order}&limit=1&label=fix", f"order={order}&status=open&limit=1"):
        refused = owner.get(f"/projects/maity/tasks?{other}&cursor={cursor}")
        assert refused.json()["error"]["details"]["fields"] == {"cursor": "invalid"}, other
    swapped = "updated" if order == "board" else "board"
    assert owner.get(f"/projects/maity/tasks?order={swapped}&cursor={cursor}").status_code == 400


def test_closed_cards_list_newest_first(owner: flow.Human) -> None:
    start = datetime(2026, 5, 1, tzinfo=UTC)
    a, b, c = (task(owner)["id"] for _ in range(3))
    for n, card_id in enumerate((a, b, c)):

        def now(at: datetime = start + timedelta(minutes=n)) -> datetime:
            return at

        clock.set_source(now)
        owner.patch(f"/projects/maity/tasks/{card_id}", {"status": "cancelled"})
    assert column(owner, "cancelled") == [c, b, a]


def test_a_neighbour_from_another_project_is_not_found(owner: flow.Human) -> None:
    a = task(owner)["id"]
    flow.project(owner, "other")
    other = owner.post("/projects/other/tasks", {"title": "elsewhere"}).json()["id"]
    refused = move(owner, a, before=other)
    assert (refused.status_code, refused.headers["Maity-Error"]) == (404, "not_found")
