"""`GET /me/notifications` and `POST /me/notifications/read` (docs/api.md §18.2, §18.3):
the counts, the items, positions and read marks, all from one snapshot."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Connection, func, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import sessions
from maity_hub.notifications.items import Item, Scope
from maity_hub.notifications.positions import Position
from maity_hub.routes.me import open_requests

COUNTED = ("inbox", "chat", "mention", "card", "agent", "ticker", "jour_fixe")


# --- counts --------------------------------------------------------------------------


def counts(conn: Connection, where: Scope, found: list[Item]) -> dict[str, Any]:
    """§18.2: `inbox` from open requests, `chat` from the chats' own unread, the rest
    from unread items; `total` is what asks for the human."""
    by_project: dict[str, dict[str, Any]] = {}
    for mine in where.memberships:
        entry = dict.fromkeys(COUNTED, 0)
        entry["inbox"] = open_requests(conn, mine.id, mine.row.role)
        entry["chat"] = _unread_chats(conn, mine)
        by_project[mine.project.id] = {"member": True, **entry}
    for request in _open_personal(conn, where.human_id):
        entry = by_project.setdefault(
            request.project_id, {"member": False, **dict.fromkeys(COUNTED, 0)}
        )
        entry["inbox"] += 1
    for item in found:
        if item.read or item.kind in ("inbox", "chat") or item.project_id is None:
            continue
        if item.project_id in by_project:
            by_project[item.project_id][item.kind] += 1
    total = dict.fromkeys((*COUNTED, "security", "system"), 0)
    shown: dict[str, Any] = {}
    slugs = _slugs(conn, by_project)
    for project_id, entry in by_project.items():
        for kind in COUNTED:
            total[kind] += entry[kind]
        entry["total"] = entry["inbox"] + entry["chat"] + entry["mention"]
        if not entry["member"]:
            entry = {"member": False, "inbox": entry["inbox"], "total": entry["inbox"]}
        if any(entry.get(kind) for kind in COUNTED):
            shown[slugs[project_id]] = entry
    for item in found:
        if not item.read and item.kind in ("security", "system"):
            total[item.kind] += 1
    total["total"] = total["inbox"] + total["chat"] + total["mention"]
    return {"counts": total, "by_project": shown}


def _unread_chats(conn: Connection, mine: Any) -> int:
    """The other party's messages after the human's chat mark, over the human's direct
    chats in this project: the number the chat list shows (§9)."""
    agents = conn.execute(
        select(t.membership.c.agent_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(
            t.membership.c.project_id == mine.project.id,
            t.agent_profile.c.owner_id == mine.row.human_id,
        )
    ).scalars()
    unread = 0
    for agent_id in agents:
        seen = (
            conn.execute(
                select(t.conversation_read.c.last_seq).where(
                    t.conversation_read.c.reader == mine.id,
                    t.conversation_read.c.conversation_id == agent_id,
                )
            ).scalar()
            or 0
        )
        unread += int(
            conn.execute(
                select(func.count()).where(
                    t.event.c.project_id == mine.project.id,
                    t.event.c.kind == "message",
                    t.event.c.conversation_id == agent_id,
                    t.event.c.seq > seen,
                    t.event.c.actor_membership != mine.id,
                )
            ).scalar_one()
        )
    return unread


def _open_personal(conn: Connection, human_id: str) -> list[Any]:
    return list(
        conn.execute(
            select(t.request).where(
                t.request.c.personal.is_(True),
                t.request.c.to_human == human_id,
                t.request.c.status == "open",
            )
        ).all()
    )


def _slugs(conn: Connection, by_project: dict[str, Any]) -> dict[str, str]:
    if not by_project:
        return {}
    rows = conn.execute(
        select(t.project.c.id, t.project.c.slug).where(t.project.c.id.in_(list(by_project)))
    ).all()
    return {row.id: row.slug for row in rows}


# --- positions -----------------------------------------------------------------------


def head(conn: Connection, where: Scope) -> Position:
    """Per project its highest visible `seq`, for the account its highest record."""
    projects = {}
    for mine in where.memberships:
        projects[mine.project.id] = int(
            conn.execute(
                select(func.coalesce(func.max(t.event.c.seq), 0)).where(
                    t.event.c.project_id == mine.project.id
                )
            ).scalar_one()
        )
    account = int(
        conn.execute(
            select(func.coalesce(func.max(t.account_record.c.n), 0)).where(
                t.account_record.c.human_id == where.human_id
            )
        ).scalar_one()
    )
    return Position(projects, account)


def behind(item: Item, position: Position, where: Scope) -> bool:
    if item.seq is not None and item.project_id is not None:
        return position.covers_event(item.project_id, item.seq, where.joined_seq[item.project_id])
    return position.covers_record(item.record or 0)


def advanced(position: Position, listed: list[Item], where: Scope) -> Position:
    """`next_after` of a cut list: per component the highest number listed, or the
    component of `after` (raised to where the membership began); left projects drop."""
    projects = {
        mine.project.id: max(
            position.projects.get(mine.project.id, 0), where.joined_seq[mine.project.id]
        )
        for mine in where.memberships
    }
    account = position.account
    for item in listed:
        if item.seq is not None and item.project_id in projects:
            projects[item.project_id] = max(projects[item.project_id], item.seq)
        elif item.record is not None:
            account = max(account, item.record)
    return Position(projects, account)


def at_least(position: Position, floor: Position | None) -> Position:
    """No component is ever lower than in `after`."""
    if floor is None:
        return position
    return Position(
        {p: max(seq, floor.projects.get(p, 0)) for p, seq in position.projects.items()},
        max(position.account, floor.account),
    )


# --- the listing ---------------------------------------------------------------------


def cursor_of(item: Item) -> str:
    """The exact place of the last listed item: its `at` to the microsecond and the tie
    keys, so items that share a timestamp are neither skipped nor repeated."""
    raw = json.dumps([item.at.astimezone(UTC).isoformat(), item.order[1], item.order[2]])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def older_than(cursor: str) -> tuple[datetime, int, int] | None:
    try:
        at, side, number = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        moment = datetime.fromisoformat(str(at))
    except (binascii.Error, ValueError, TypeError):
        return None
    if moment.utcoffset() != timedelta(0):
        return None  # a cursor this hub made is UTC
    return (moment, int(side), int(number))


def select_items(
    found: list[Item], *, kinds: set[str] | None, projects: set[str] | None, unread: bool
) -> list[Item]:
    return [
        item
        for item in found
        if (kinds is None or item.kind in kinds)
        and (projects is None or item.project_id in projects)
        and not (unread and item.read)
    ]


# --- reading -------------------------------------------------------------------------


def mark(
    conn: Connection,
    where: Scope,
    found: list[Item],
    chosen: Iterable[Item],
    session: Any,
) -> None:
    """Mark `chosen` read as this session may (§18.3): a chat item moves the chat's own
    mark, never backwards; a security item only from a session allowed to."""
    now = clock.now()
    confirmed = sessions.confirmed_sessions(conn, where.human_id)
    for item in chosen:
        if item.read:
            continue
        if item.kind == "security" and not _may_mark(conn, item, session, confirmed):
            continue
        if item.record is not None:
            conn.execute(
                update(t.account_record)
                .where(t.account_record.c.n == item.record, t.account_record.c.read_at.is_(None))
                .values(read_at=now, read_by=session.public_id)
            )
        elif item.target and item.target["type"] == "conversation":
            _move_chat_mark(conn, where, item)
        else:
            exists = conn.execute(
                select(t.notification_read.c.seq).where(
                    t.notification_read.c.human_id == where.human_id,
                    t.notification_read.c.seq == item.seq,
                )
            ).first()
            if exists is None:
                conn.execute(
                    insert(t.notification_read).values(
                        human_id=where.human_id, seq=item.seq, at=now
                    )
                )


def _may_mark(conn: Connection, item: Item, session: Any, confirmed: frozenset[str]) -> bool:
    """A sign-in alert is confirmed only from a session in good standing that existed
    before the sign-in, never from the session it reports on (§2.6.5); an address change
    likewise from a session older than the change."""
    if not sessions.good_standing(session, confirmed):
        return False
    if item.record_type == "session_created":
        if item.session_id == session.public_id:
            return False
        reported = conn.execute(
            select(t.human_session.c.created_at).where(
                t.human_session.c.public_id == item.session_id
            )
        ).scalar()
        return reported is not None and session.created_at < reported
    return bool(session.created_at < item.at)


def _move_chat_mark(conn: Connection, where: Scope, item: Item) -> None:
    mine = where.membership(item.project_id or "")
    if mine is None or item.seq is None or item.target is None:
        return
    conversation = item.target["id"]
    current = conn.execute(
        select(t.conversation_read.c.last_seq).where(
            t.conversation_read.c.reader == mine.id,
            t.conversation_read.c.conversation_id == conversation,
        )
    ).scalar()
    if current is None:
        conn.execute(
            insert(t.conversation_read).values(
                reader=mine.id, conversation_id=conversation, last_seq=item.seq
            )
        )
    elif current < item.seq:
        conn.execute(
            update(t.conversation_read)
            .where(
                t.conversation_read.c.reader == mine.id,
                t.conversation_read.c.conversation_id == conversation,
            )
            .values(last_seq=item.seq)
        )
