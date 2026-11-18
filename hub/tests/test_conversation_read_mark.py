"""One way to move a conversation's read mark (`conversation_list.move_read_mark`): reading
the chat and marking its bell item read both move it up, never back."""

from __future__ import annotations

from sqlalchemy import Engine, select

from maity_hub import conversation_list
from maity_hub import tables as t
from tests import factory

CHAT = "conv_read_mark_test"


def _mark(engine: Engine, reader: int) -> int | None:
    with engine.connect() as conn:
        found = conn.execute(
            select(t.conversation_read.c.last_seq).where(
                t.conversation_read.c.reader == reader,
                t.conversation_read.c.conversation_id == CHAT,
            )
        ).scalar()
    return None if found is None else int(found)


def _move(engine: Engine, reader: int, seq: int) -> None:
    with engine.begin() as conn:
        conversation_list.move_read_mark(conn, reader, CHAT, seq)


def test_the_mark_is_made_then_only_moves_forward(migrated: Engine) -> None:
    reader = factory.membership(
        migrated, factory.project(migrated), "member", human_id=factory.human(migrated)
    )
    assert _mark(migrated, reader) is None
    _move(migrated, reader, 5)
    assert _mark(migrated, reader) == 5
    _move(migrated, reader, 3)
    assert _mark(migrated, reader) == 5
    _move(migrated, reader, 5)
    assert _mark(migrated, reader) == 5
    _move(migrated, reader, 9)
    assert _mark(migrated, reader) == 9


def test_each_reader_has_a_mark_of_their_own(migrated: Engine) -> None:
    project_id = factory.project(migrated)
    one = factory.membership(migrated, project_id, "member", human_id=factory.human(migrated))
    other = factory.membership(migrated, project_id, "member", human_id=factory.human(migrated))
    _move(migrated, one, 7)
    _move(migrated, other, 4)
    assert (_mark(migrated, one), _mark(migrated, other)) == (7, 4)
