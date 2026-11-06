"""Instance administration (docs/api.md §16): the instance admin is a human account, and
for now the earliest one `maity-hub owner create` made. It opens no project, inbox or
chat; the admin endpoints answer metadata about accounts, never content."""

from __future__ import annotations

from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.errors import forbidden


def instance_admin_id(conn: Connection) -> str | None:
    """The earliest-created human, until the accounts design adds a flag (§16)."""
    found: str | None = conn.execute(
        select(t.human.c.id).order_by(t.human.c.created_at, t.human.c.id).limit(1)
    ).scalar()
    return found


def is_instance_admin(conn: Connection, human_id: str) -> bool:
    return instance_admin_id(conn) == human_id


def without_address(conn: Connection) -> bool:
    """Whether there is an instance admin and it has no verified address, which its password
    sign-in needs (§2.1): the start warns (`app.check_startup`)."""
    admin = instance_admin_id(conn)
    if admin is None:
        return False
    status = conn.execute(
        select(t.notification_settings.c.address_status).where(
            t.notification_settings.c.human_id == admin,
            t.notification_settings.c.address.is_not(None),
        )
    ).scalar()
    return status not in ("verified", "disabled")


def require_instance_admin(conn: Connection, human_id: str) -> None:
    """`forbidden` (`instance:admin`) for every caller but the instance admin (§16.1)."""
    if not is_instance_admin(conn, human_id):
        raise forbidden("instance:admin")
