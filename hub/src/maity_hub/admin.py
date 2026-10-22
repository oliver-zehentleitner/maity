"""Instance administration (docs/api.md §16): the instance admin is a human account, and
for now the earliest one `maity-hub owner create` made. It opens no project, inbox or
chat; the admin endpoints answer metadata about accounts, never content."""

from __future__ import annotations

from sqlalchemy import Connection, select

from maity_hub import tables as t


def instance_admin_id(conn: Connection) -> str | None:
    """The earliest-created human, until the accounts design adds a flag (§16)."""
    found: str | None = conn.execute(
        select(t.human.c.id).order_by(t.human.c.created_at, t.human.c.id).limit(1)
    ).scalar()
    return found


def is_instance_admin(conn: Connection, human_id: str) -> bool:
    return instance_admin_id(conn) == human_id
