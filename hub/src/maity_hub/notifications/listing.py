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
from sqlalchemy.dialects import postgresql, sqlite

from maity_hub import clock, conversation_list, namespace
from maity_hub import tables as t
from maity_hub.auth import sessions
from maity_hub.notifications import records
from maity_hub.notifications.items import EVENT_KINDS, Item, Scope
from maity_hub.notifications.positions import Position
from maity_hub.routes.me import open_requests

COUNTED = ("inbox", "chat", "mention")


# --- counts --------------------------------------------------------------------------


def counts(conn: Connection, where: Scope, found: list[Item]) -> dict[str, Any]:
    """§18.2: `inbox` from open requests and the open inbox records, `chat` from the
    chats' own unread (`conversation_list.unread_chats`, the number of the chat list),
    `mention` and `security` from unread items; `total` is what asks for the human. The
    keys are exactly these five."""
    by_project: dict[str, dict[str, Any]] = {}
    chats = conversation_list.unread_chats(conn, where.memberships, where.human_id)
    for mine in where.memberships:
        entry = dict.fromkeys(COUNTED, 0)
        entry["inbox"] = open_requests(conn, mine.id)
        entry["chat"] = chats[mine.project.id]
        by_project[mine.project.id] = {"member": True, **entry}
    loose = 0
    for project_id, open_count in _open_personal(conn, where.human_id):
        if project_id is None:  # an organisation's invitation: no project's count
            loose += open_count
            continue
        entry = by_project.setdefault(project_id, {"member": False, **dict.fromkeys(COUNTED, 0)})
        entry["inbox"] += open_count
    for item in found:
        if item.read or item.kind != "mention" or item.project_id is None:
            continue
        if item.project_id in by_project:
            by_project[item.project_id][item.kind] += 1
    total = dict.fromkeys((*COUNTED, "security"), 0)
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
        if not item.read and item.kind == "security":
            total["security"] += 1
        # A pending registration or a disabled address: belongs to no project, counts
        # until its matter is closed, not until it is read (§18.1).
        if item.kind == "inbox" and item.open:
            total["inbox"] += 1
    total["inbox"] += loose
    total["total"] = total["inbox"] + total["chat"] + total["mention"]
    return {"counts": total, "by_project": shown}


def _open_personal(conn: Connection, human_id: str) -> list[Any]:
    """`(project_id, count)` of the human's open personal requests, counted in SQL."""
    c = t.request.c
    return list(
        conn.execute(
            select(c.project_id, func.count())
            .where(c.personal.is_(True), c.to_human == human_id, c.status == "open")
            .group_by(c.project_id)
        ).all()
    )


def _slugs(conn: Connection, by_project: dict[str, Any]) -> dict[str, str]:
    """project id → full name: `by_project` is keyed on full names (§6.25, §18)."""
    return namespace.full_names(conn, by_project)


# --- positions -----------------------------------------------------------------------


def stamp(conn: Connection, human_id: str) -> tuple[Any, ...]:
    """A few aggregate reads that change whenever a notifications answer could: the
    human's memberships, each project's highest `seq` among the kinds that make items,
    the account records and their read marks, the event items' read marks and the
    chats' marks. A held long-poll compares it before it derives everything again
    (§18.2). A pending registration's
    decision moves no record and no event, and is not a new item: the counts take it at
    the next answer."""
    members = sorted(
        conn.execute(
            select(t.membership.c.id, t.membership.c.project_id).where(
                t.membership.c.human_id == human_id, t.membership.c.active.is_(True)
            )
        ).all()
    )
    project_ids = [project_id for _, project_id in members]
    heads = (
        sorted(
            conn.execute(
                select(t.event.c.project_id, func.max(t.event.c.seq))
                # Only the kinds that can make an item (§18.1): a card's or a placement's
                # churn moves no notification, so it wakes no held long-poll either.
                .where(
                    t.event.c.project_id.in_(project_ids), t.event.c.kind.in_(EVENT_KINDS)
                ).group_by(t.event.c.project_id)
            ).all()
        )
        if project_ids
        else []
    )
    records = conn.execute(
        select(func.max(t.account_record.c.n), func.count(t.account_record.c.read_at)).where(
            t.account_record.c.human_id == human_id
        )
    ).one()
    reads = conn.execute(
        select(func.count(), func.max(t.notification_read.c.seq)).where(
            t.notification_read.c.human_id == human_id
        )
    ).one()
    chats = (
        conn.execute(
            select(func.count(), func.sum(t.conversation_read.c.last_seq)).where(
                t.conversation_read.c.reader.in_([member_id for member_id, _ in members])
            )
        ).one()
        if members
        else (0, None)
    )
    return (
        tuple(members),
        tuple(heads),
        tuple(records),
        tuple(reads),
        tuple(chats),
    )


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
        place = (moment, int(side), int(number))
    except (binascii.Error, ValueError, TypeError):
        return None
    if moment.utcoffset() != timedelta(0):
        return None  # a cursor this hub made is UTC
    return place


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
    seqs: list[int] = []
    for item in chosen:
        if item.read or item.record_type in records.INBOX:
            continue  # an open matter reads as read only once it is closed (§18.3)
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
        elif item.seq is not None:
            seqs.append(item.seq)
    if seqs:  # one statement; a mark that another wrote meanwhile is skipped, not an error
        conn.execute(
            ignoring_duplicates(conn, t.notification_read),
            [{"human_id": where.human_id, "seq": seq, "at": now} for seq in seqs],
        )


def ignoring_duplicates(conn: Connection, table: Any) -> Any:
    """`INSERT` that skips a row whose key exists, waiting for a concurrent writer of it
    first, on every database the hub runs on."""
    if conn.dialect.name == "postgresql":
        return postgresql.insert(table).on_conflict_do_nothing()
    if conn.dialect.name == "sqlite":
        return sqlite.insert(table).on_conflict_do_nothing()
    return insert(table).prefix_with("IGNORE")  # MariaDB / MySQL


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
    # Made if absent, then only ever moved forward: two marks at once never collide on
    # the key and never move it back.
    conn.execute(
        ignoring_duplicates(conn, t.conversation_read).values(
            reader=mine.id, conversation_id=conversation, last_seq=item.seq
        )
    )
    conn.execute(
        update(t.conversation_read)
        .where(
            t.conversation_read.c.reader == mine.id,
            t.conversation_read.c.conversation_id == conversation,
            t.conversation_read.c.last_seq < item.seq,
        )
        .values(last_seq=item.seq)
    )
