"""docs/api.md §6.4: card order within a status column, and `move`."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

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


def test_many_moves_keep_the_order_and_short_ranks(owner: flow.Human) -> None:
    cards = [task(owner, title=str(i))["id"] for i in range(6)]
    expected = list(cards)
    for step in range(40):  # always between the same two: the keys grow until spread out
        card = expected[-1]
        move(owner, card, after=expected[0])
        expected.remove(card)
        expected.insert(1, card)
        assert column(owner) == expected, step
    ranks = [c["rank"] for c in owner.get("/projects/maity/tasks?status=open").json()["items"]]
    assert all(r is None or len(r) <= 25 for r in ranks)
