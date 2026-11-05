"""`cards.open_claims` (docs/api.md §6.5): the one condition every claim reader uses. A closed
card keeps its holder's columns as a record, so a reader that forgot the status test counted
`done` and `cancelled` cards as held; #1304 and #1305 each found that bug on their own."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import ColumnElement, Engine, select, update

from maity_hub import cards
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_tasks import task

BASE = "/projects/maintainer/maity"
SRC = Path(__file__).resolve().parents[1] / "src" / "maity_hub"


class Held:
    def __init__(self, agent: flow.Agent, membership_id: int, engine: Engine) -> None:
        self.agent, self.membership_id, self.engine = agent, membership_id, engine

    def found(self, where: ColumnElement[bool]) -> set[str]:
        with self.engine.connect() as conn:
            return set(conn.execute(select(t.card.c.id).where(where)).scalars())


@pytest.fixture
def held(make_client: ClientFactory, migrated: Engine) -> tuple[Held, dict[str, str]]:
    """An agent instance holding three cards, two of them then closed as the hub closes a
    card: the status moves, the holder's columns stay."""
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    agent = flow.agent(make_client, owner, role="member")
    assert agent.resume().status_code == 200
    ids = {}
    for name in ("open", "done", "cancelled"):
        card = task(owner)
        claimed = agent.post(f"{BASE}/tasks/{card['id']}/claim", {})
        assert claimed.status_code == 200, claimed.text
        ids[name] = str(card["id"])
    with migrated.begin() as conn:
        for status in ("done", "cancelled"):
            conn.execute(update(t.card).where(t.card.c.id == ids[status]).values(status=status))
        membership_id = conn.execute(
            select(t.membership.c.id).where(t.membership.c.agent_id == agent.id)
        ).scalar_one()
        kept = conn.execute(
            select(t.card.c.claim_holder).where(t.card.c.id.in_([ids["done"], ids["cancelled"]]))
        ).scalars()
        assert set(kept) == {membership_id}  # the record the bug read as a claim
    return Held(agent, membership_id, migrated), ids


def test_a_closed_card_is_no_open_claim_in_any_form(held: tuple[Held, dict[str, str]]) -> None:
    h, ids = held
    mine = {ids["open"]}
    assert h.found(cards.open_claims(h.membership_id)) == mine
    assert h.found(cards.open_claims([h.membership_id])) == mine
    assert h.found(cards.open_claims(t.membership.c.id)) <= mine  # compared, not filtered
    assert h.found(cards.open_claims(None)) == mine
    assert h.found(cards.open_claims(h.membership_id, instance=h.agent.instance)) == mine
    assert h.found(cards.open_claims(h.membership_id, instance=cards.SOME_INSTANCE)) == mine
    assert h.found(cards.open_claims(h.membership_id, status="in_progress")) == mine
    assert h.found(cards.open_claims(h.membership_id, status=("blocked", "review"))) == set()
    assert h.found(cards.open_claims(h.membership_id, instance=None)) == set()  # a bridge's
    assert h.found(cards.open_claims(h.membership_id, instance="zzzz")) == set()  # a sibling's


def test_a_status_filter_cannot_bring_a_closed_card_back(
    held: tuple[Held, dict[str, str]],
) -> None:
    h, _ = held
    assert h.found(cards.open_claims(h.membership_id, status="done")) == set()
    assert h.found(cards.open_claims(h.membership_id, status=cards.CLOSED)) == set()


def test_the_closed_statuses_are_written_down_once() -> None:
    """No module keeps its own copy of the closed statuses; the migrations, which never import
    the application, are the exception."""
    copy = re.compile(r"""["']done["'],\s*["']cancelled["']""")
    found = [
        f"{path.relative_to(SRC)}:{number}"
        for path in sorted(SRC.rglob("*.py"))
        if "migrations" not in path.parts
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if copy.search(line)
    ]
    assert found == ["cards.py:27", "cards.py:30"]  # STATUSES and CLOSED
