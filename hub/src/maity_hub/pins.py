"""A human's pinned conversations (docs/api.md §9.3 "Pinned").

A pin is the human's own: a row (human, project, chat id) that nobody else reads and no event
announces. At most 20 per human across its projects, counted under the human's row lock so
two pins in two projects cannot both be the 21st. A pin lives only while its holder can read
the chat: every change that ends a stay in a group chat or a membership calls `prune` for the
project, so a chat left and joined again comes back unpinned; `pin` prunes the holder's own
pins before it counts, which also catches an access lost another way.
"""

from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any

from sqlalchemy import Connection, delete, func, insert, select

from maity_hub import clock, group_chats
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.notifications.records import lock_human

LIMIT = 20

Key = tuple[str, str]  # (project id, chat id)


def pinned(conn: Connection, human_id: str) -> set[Key]:
    """The chats the human has pinned, in every project."""
    return {
        (row.project_id, row.conversation_id)
        for row in conn.execute(
            select(t.conversation_pin.c.project_id, t.conversation_pin.c.conversation_id).where(
                t.conversation_pin.c.human_id == human_id
            )
        )
    }


def pin(conn: Connection, human_id: str, project_id: str, conversation_id: str) -> None:
    """Pin a chat the caller reads; a second pin of it changes nothing."""
    lock_human(conn, human_id)
    _prune_holder(conn, human_id)
    held = pinned(conn, human_id)
    if (project_id, conversation_id) in held:
        return
    if len(held) >= LIMIT:
        raise invalid({"pin": "too_many"})
    conn.execute(
        insert(t.conversation_pin).values(
            human_id=human_id,
            project_id=project_id,
            conversation_id=conversation_id,
            pinned_at=clock.now(),
        )
    )


def unpin(conn: Connection, human_id: str, project_id: str, conversation_id: str) -> None:
    conn.execute(
        delete(t.conversation_pin).where(
            t.conversation_pin.c.human_id == human_id,
            t.conversation_pin.c.project_id == project_id,
            t.conversation_pin.c.conversation_id == conversation_id,
        )
    )


def prune(conn: Connection, project_id: str) -> None:
    """Drop the project's pins whose holder can no longer read the chat."""
    rows = conn.execute(
        select(t.conversation_pin).where(t.conversation_pin.c.project_id == project_id)
    ).all()
    _drop_unreadable(conn, rows)


def _prune_holder(conn: Connection, human_id: str) -> None:
    rows = conn.execute(
        select(t.conversation_pin).where(t.conversation_pin.c.human_id == human_id)
    ).all()
    _drop_unreadable(conn, rows)


def _drop_unreadable(conn: Connection, rows: Sequence[Any]) -> None:
    for row in rows:
        if not readable(conn, row.human_id, row.project_id, row.conversation_id):
            unpin(conn, row.human_id, row.project_id, row.conversation_id)


def readable(conn: Connection, human_id: str, project_id: str, conversation_id: str) -> bool:
    """Whether the human reads the chat: a participant or an observer of a group chat
    (§9.2), a party of a direct one (§9.1)."""
    member = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id == human_id,
            t.membership.c.active.is_(True),
        )
    ).first()
    if group_chats.is_group(conversation_id):
        if group_chats.find(conn, project_id, conversation_id) is None:
            return False
        # Shaped as `group_chats.access` reads a caller; an owner outside the project
        # holds no membership and no trust, and reads along only.
        mine = SimpleNamespace(
            id=member.id if member is not None else -1,
            kind="human",
            principal_id=human_id,
            trust=member.trust if member is not None else None,
        )
        return group_chats.access(conn, conversation_id, mine) is not None
    if member is None:
        return False
    return bool(
        conn.execute(
            select(func.count())
            .select_from(t.membership)
            .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
            .where(
                t.membership.c.project_id == project_id,
                t.membership.c.agent_id == conversation_id,
                t.membership.c.active.is_(True),
                t.agent_profile.c.owner_id == human_id,
            )
        ).scalar_one()
    )
