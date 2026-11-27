"""docs/api.md §16.9: the rule of which cards a public page may show, `public_cards.shown`, and
its SQL twin `shown_clause`, which the Board's columns read (`public_project_views.board_rows`).

The twins are held to the same answer on every status and label the matrix names, on the
engine the suite runs on, and the Board is held to the answer of its own inline rule before it
took `shown_clause` (main at 1cebbeff): the same cards, in the same order, under the same holds,
closed-cutoff and column limit (hub/context/public-pages.md)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, func, not_, or_, select

from maity_hub import cards, clock, moderation, public_project_views
from maity_hub import tables as t
from maity_hub.public_cards import shown, shown_clause
from tests import factory
from tests.test_outside_reads import _hold_on

# None and the empty label are no label; `security` in any case is the one the rule reads; the
# rest only look like it. All ASCII without blanks, as the hub writes labels: past that the
# engines' `lower` and comparison may differ from Python's (see `shown_clause`).
LABELS = (
    None,
    "",
    "security",
    "Security",
    "SECURITY",
    "sEcUrItY",
    "fix",
    "feature",
    "chore",
    "secure",
    "insecurity",
    "security-review",
)


def _board_rows_before(
    conn: Connection, project_id: str, limit: int
) -> list[tuple[str, list[str]]]:
    """`board_rows` as of main 1cebbeff, with its inline `security` rule, as ids per column."""
    c = t.card.c
    cutoff = clock.now() - timedelta(days=public_project_views.CLOSED_DAYS)
    held = set(
        moderation.holds_of(
            conn,
            "card",
            list(conn.execute(select(c.id).where(c.project_id == project_id)).scalars()),
        )
    )
    columns = []
    for status in cards.STATUSES:
        query = select(c.id).where(c.project_id == project_id, c.status == status)
        if status in cards.CLOSED:
            query = query.where(c.closed_at >= cutoff)
        if status != "done":
            query = query.where(or_(c.label.is_(None), func.lower(c.label) != "security"))
        if held:
            query = query.where(c.id.notin_(held))
        ids = conn.execute(query.order_by(c.created_at.desc(), c.id.desc()).limit(limit))
        columns.append((status, list(ids.scalars())))
    return columns


class Matrix:
    """Every status × every label of `LABELS`, plus closed cards past the cutoff, cards under a
    hold and two cards made at the same instant, in one project."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.project_id = factory.project(engine)
        member = factory.membership(
            engine, self.project_id, "owner", human_id=factory.human(engine)
        )
        start = clock.now() - timedelta(days=2)
        n = 0

        def card(**values: Any) -> str:
            nonlocal n
            n += 1
            values.setdefault("created_at", start + timedelta(seconds=n))
            return factory.card(engine, self.project_id, member, title=f"card {n}", **values)

        recent = clock.now() - timedelta(hours=1)
        old = clock.now() - timedelta(days=public_project_views.CLOSED_DAYS + 1)
        for status in cards.STATUSES:
            for label in LABELS:
                closed = {"closed_at": recent} if status in cards.CLOSED else {}
                card(status=status, label=label, **closed)
        for status in cards.CLOSED:  # past the cutoff: on no board, whatever the label
            for label in (None, "fix", "security", "Security"):
                card(status=status, label=label, closed_at=old)
        same = start + timedelta(hours=1)  # a tie on created_at: the id decides, descending
        card(status="open", label="fix", created_at=same)
        card(status="open", label=None, created_at=same)
        reporter = factory.human(engine)
        self.held = [
            card(status="open", label="fix"),
            card(status="open", label="Security"),
            card(status="done", label="security", closed_at=recent),
            card(status="review", label=None),
        ]
        with engine.begin() as conn:
            for card_id in self.held:
                _hold_on(conn, reporter, card_id)

    def rows(self) -> list[Any]:
        with self.engine.connect() as conn:
            return list(conn.execute(select(t.card).where(t.card.c.project_id == self.project_id)))


@pytest.fixture
def matrix(migrated: Engine) -> Matrix:
    return Matrix(migrated)


def test_the_matrix_covers_both_answers_of_every_status(matrix: Matrix) -> None:
    rows = matrix.rows()
    for status in cards.STATUSES:
        answers = {shown(r) for r in rows if r.status == status}
        assert answers == ({True} if status == "done" else {True, False}), status


@pytest.mark.parametrize("aliased", [False, True])
def test_shown_clause_answers_as_shown_on_every_status_and_label(
    matrix: Matrix, aliased: bool
) -> None:
    card = t.card.alias("other") if aliased else t.card
    mine = card.c.project_id == matrix.project_id
    rows = matrix.rows()
    with matrix.engine.connect() as conn:
        selected = set(conn.execute(select(card.c.id).where(mine, shown_clause(card))).scalars())
        # never NULL: its negation is exactly the rest, so no row falls between the two
        left_out = set(
            conn.execute(select(card.c.id).where(mine, not_(shown_clause(card)))).scalars()
        )
    assert selected == {r.id for r in rows if shown(r)}
    assert left_out == {r.id for r in rows if not shown(r)}
    assert len(selected) + len(left_out) == len(rows)


@pytest.mark.parametrize("limit", [200, 5, 1])
def test_the_board_shows_what_its_inline_rule_showed(
    matrix: Matrix, monkeypatch: pytest.MonkeyPatch, limit: int
) -> None:
    monkeypatch.setattr(public_project_views, "BOARD_LIMIT", limit)
    with matrix.engine.connect() as conn:
        columns, gone = public_project_views.board_rows(conn, matrix.project_id, {})
        before = _board_rows_before(conn, matrix.project_id, limit)
    now = [(status, [r.id for r in rows]) for status, rows in columns]
    assert now == before and gone == set()

    # and both are the rule spelled out in Python: shown, unheld, inside the closed window,
    # newest first with the id breaking a tie, at most `limit` per column
    cutoff = clock.now() - timedelta(days=public_project_views.CLOSED_DAYS)
    rows = matrix.rows()
    expected = []
    for status in cards.STATUSES:
        kept = [
            r
            for r in rows
            if r.status == status
            and shown(r)
            and r.id not in matrix.held
            and (status not in cards.CLOSED or r.closed_at >= cutoff)
        ]
        kept.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        expected.append((status, [r.id for r in kept[:limit]]))
    assert now == expected
    assert any(ids for _, ids in now)
