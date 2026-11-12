"""Links to reset a forgotten password (docs/api.md §2.10): their single-use rows, and the
password generation every link carries.

The routes that send and use a link come in the next step of tsk-tadt2vw7589n; until then
nothing writes a `password_reset` row, and what voids them here finds none.
"""

from __future__ import annotations

from sqlalchemy import Connection, update

from maity_hub import clock
from maity_hub import tables as t


def password_changed(conn: Connection, human_id: str) -> None:
    """A new password, by `POST /auth/password` or a reset: the generation moves, so every
    link made under the old one dies with it, and the open ones are voided now too."""
    conn.execute(
        update(t.human)
        .where(t.human.c.id == human_id)
        .values(password_generation=t.human.c.password_generation + 1)
    )
    void_human(conn, human_id)


def void_human(conn: Connection, human_id: str) -> None:
    """Every open link of one human: a password change, the human's own switch turned off, a
    change or removal of the address, or five wrong codes in a day."""
    conn.execute(
        update(t.password_reset)
        .where(t.password_reset.c.human_id == human_id, t.password_reset.c.used_at.is_(None))
        .values(used_at=clock.now())
    )


def void_open(conn: Connection) -> None:
    """Every open link of the instance, when its switch turns the reset off."""
    conn.execute(
        update(t.password_reset)
        .where(t.password_reset.c.used_at.is_(None))
        .values(used_at=clock.now())
    )
