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
