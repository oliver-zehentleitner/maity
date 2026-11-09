"""Counting the statements a call sends to the database, for the tests that say a cost does
not grow with the data (the chat lists, a human's sign-in)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, event


def count_statements(engine: Engine, call: Any) -> int:
    seen = [0]

    def counted(*_: Any) -> None:
        seen[0] += 1

    event.listen(engine, "before_cursor_execute", counted)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", counted)
    return seen[0]


def count_executions(engine: Engine, call: Any) -> int:
    """Like `count_statements`, but a list of parameters (`executemany`) counts once per row,
    as sqlite3 and psycopg run it: one INSERT with many VALUES rows counts once. A driver that
    folds an INSERT's parameter list into one statement (PyMySQL) runs fewer than this counts;
    the rule is the conservative one, so a regression to a parameter list fails the test."""
    seen = [0]

    def counted(
        conn: Any, cursor: Any, statement: Any, parameters: Any, context: Any, many: bool
    ) -> None:
        seen[0] += len(parameters) if many else 1

    event.listen(engine, "before_cursor_execute", counted)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", counted)
    return seen[0]
