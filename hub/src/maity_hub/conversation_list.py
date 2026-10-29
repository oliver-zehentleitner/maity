"""The entries of a conversation list (docs/api.md §9.3), built for all conversations at
once: a fixed number of statements however many chats the caller has, where one entry at
a time cost about ten each. The routes' single-chat views (`routes.conversations`) stay
the reference these must equal; `tests/test_conversation_list.py` compares them.

An entry carries `_activity` for the caller to sort and cut by, and drops it before it
answers.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from itertools import islice
from typing import Any

from sqlalchemy import Connection, String, and_, cast, func, or_, select

from maity_hub import group_chats
from maity_hub import tables as t
from maity_hub.views import principal_ids, ts

PREVIEW = 200  # code points (§9)
CHUNK = 100  # chats per statement that names each one's window


def short(person: dict[str, Any]) -> dict[str, Any]:
    """A participant as the list shows it; an agent with its global name (§6.3)."""
    return {k: person[k] for k in ("member_id", "kind", "handle", "name") if k in person}


def preview(row: Any, sender: str | None) -> dict[str, Any] | None:
    """A message as a list preview: text for the list, never mentions (§9.1)."""
    if row is None:
        return None
    body = None if row.redacted else (row.payload or {}).get("body")
    return {
        "seq": row.seq,
        "from": sender,
        "body": body[:PREVIEW] if isinstance(body, str) else None,
        "sent_at": ts(row.at),
        "redacted": bool(row.redacted),
    }


def _chunks(items: Sequence[Any]) -> Iterable[Sequence[Any]]:
    it = iter(items)
    while batch := tuple(islice(it, CHUNK)):
        yield batch


def _latest(conn: Connection, project_id: str, windows: dict[str, int]) -> dict[str, Any]:
    """Per chat the newest message after its window: the whole row."""
    found: dict[str, Any] = {}
    for batch in _chunks(list(windows)):
        newest = (
            select(t.event.c.conversation_id, func.max(t.event.c.seq).label("seq"))
            .where(
                t.event.c.project_id == project_id,
                t.event.c.kind == "message",
                or_(
                    *(
                        and_(t.event.c.conversation_id == chat, t.event.c.seq > windows[chat])
                        for chat in batch
                    )
                ),
            )
            .group_by(t.event.c.conversation_id)
            .subquery()
        )
        for row in conn.execute(select(t.event).join(newest, t.event.c.seq == newest.c.seq)):
            found[row.conversation_id] = row
    return found


# --- direct chats --------------------------------------------------------------------------


def direct_entries(
    conn: Connection, mine: Any, caller: Any, agent_ids: list[str]
) -> list[dict[str, Any]]:
    """The caller's direct conversations with `agent_ids`: each needs both parties active
    in the project (§9.1), so an agent whose owner is no member has none."""
    if not agent_ids:
        return []
    project_id = mine.project.id
    agents = {
        row.agent_id: row
        for row in conn.execute(
            select(t.membership).where(
                t.membership.c.project_id == project_id,
                t.membership.c.active.is_(True),
                t.membership.c.agent_id.in_(agent_ids),
            )
        )
    }
    owners = dict(
        conn.execute(
            select(t.agent_profile.c.id, t.agent_profile.c.owner_id).where(
                t.agent_profile.c.id.in_(agent_ids)
            )
        ).all()
    )
    humans = {
        row.human_id: row
        for row in conn.execute(
            select(t.membership).where(
                t.membership.c.project_id == project_id,
                t.membership.c.active.is_(True),
                t.membership.c.human_id.in_(set(owners.values())),
            )
        )
    }
    chats = [a for a in agent_ids if a in agents and owners.get(a) in humans]
    if not chats:
        return []
    people = group_chats.people(
        conn, {agents[a].id for a in chats} | {humans[owners[a]].id for a in chats}
    )
    lasts = _latest(conn, project_id, dict.fromkeys(chats, 0))
    senders = principal_ids(conn, (row.actor_membership for row in lasts.values()))
    unread = _direct_unread(conn, mine, caller, chats)
    entries = []
    for agent_id in chats:
        agent, human = agents[agent_id], humans[owners[agent_id]]
        last = lasts.get(agent_id)
        entries.append(
            {
                "id": agent_id,
                "kind": "direct",
                "agent_id": agent_id,
                "title": None,
                "participants": [short(people[human.id]), short(people[agent.id])],
                "access": "party",
                "closed_at": None,
                "last_message_at": ts(last.at) if last is not None else None,
                "unread": unread.get(agent_id, 0),
                "mentions_unread": 0,
                "last_message": preview(last, senders.get(last.actor_membership) if last else None),
                "_activity": last.at if last is not None else agent.joined_at,
            }
        )
    return entries


def _direct_unread(conn: Connection, mine: Any, caller: Any, chats: list[str]) -> dict[str, int]:
    """The other party's messages after what this reader has seen, per chat (§9.1): a
    human's chat mark, or the agent's event cursor."""
    count = (
        select(t.event.c.conversation_id, func.count())
        .select_from(t.event)
        .where(
            t.event.c.project_id == mine.project.id,
            t.event.c.kind == "message",
            t.event.c.conversation_id.in_(chats),
            t.event.c.actor_membership != mine.id,
        )
        .group_by(t.event.c.conversation_id)
    )
    if caller.kind == "human":
        count = count.outerjoin(
            t.conversation_read,
            and_(
                t.conversation_read.c.reader == mine.id,
                t.conversation_read.c.conversation_id == t.event.c.conversation_id,
            ),
        ).where(t.event.c.seq > func.coalesce(t.conversation_read.c.last_seq, 0))
    else:  # the agent's side is its event cursor
        seen = (
            conn.execute(
                select(t.agent_session.c.acknowledged_seq).where(
                    t.agent_session.c.id == caller.session_id
                )
            ).scalar()
            or 0
        )
        count = count.where(t.event.c.seq > seen)
    return {chat: int(n) for chat, n in conn.execute(count).all()}


# --- group chats ---------------------------------------------------------------------------


def group_entries(conn: Connection, mine: Any, observed: bool) -> list[dict[str, Any]]:
    """The group chats the caller takes part in, and with `observed` those it reads
    along in as an owner (§9.3)."""
    project_id = mine.project.id
    ids = set(
        conn.execute(
            select(t.conversation_participant.c.conversation_id).where(
                t.conversation_participant.c.membership_id == mine.id,
                t.conversation_participant.c.here.is_(True),
            )
        ).scalars()
    )
    if observed and mine.kind == "human":
        ids |= set(
            conn.execute(
                select(t.conversation_participant.c.conversation_id)
                .join(
                    t.membership,
                    t.membership.c.id == t.conversation_participant.c.membership_id,
                )
                .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
                .where(
                    t.conversation_participant.c.here.is_(True),
                    t.agent_profile.c.owner_id == mine.principal_id,
                    t.membership.c.project_id == project_id,
                )
            ).scalars()
        )
    if not ids:
        return []
    groups = {
        row.id: row
        for row in conn.execute(
            select(t.conversation).where(
                t.conversation.c.project_id == project_id, t.conversation.c.id.in_(ids)
            )
        )
    }
    stays: dict[str, list[Any]] = defaultdict(list)
    for row in conn.execute(
        select(t.conversation_participant, t.membership.c.agent_id, t.membership.c.human_id)
        .join(t.membership, t.membership.c.id == t.conversation_participant.c.membership_id)
        .where(
            t.conversation_participant.c.conversation_id.in_(list(groups)),
            t.conversation_participant.c.here.is_(True),
        )
        .order_by(t.conversation_participant.c.joined_at, t.conversation_participant.c.id)
    ):
        stays[row.conversation_id].append(row)
    agent_ids = {s.agent_id for rows in stays.values() for s in rows if s.agent_id}
    owners = (
        dict(
            conn.execute(
                select(t.agent_profile.c.id, t.agent_profile.c.owner_id).where(
                    t.agent_profile.c.id.in_(agent_ids)
                )
            ).all()
        )
        if agent_ids
        else {}
    )
    rounds: set[str] = set()
    if mine.kind == "human" and mine.role == "owner":
        rounds = set(
            conn.execute(
                select(t.jour_fixe_round.c.conversation_id).where(
                    t.jour_fixe_round.c.conversation_id.in_(list(groups))
                )
            ).scalars()
        )
    found = _access(mine, groups, stays, owners, rounds)
    if not found:
        return []
    people = group_chats.people(conn, {s.membership_id for chat in found for s in stays[chat]})
    windows = _windows(conn, mine, found, stays)
    lasts = _latest(conn, project_id, windows)
    senders = principal_ids(conn, (row.actor_membership for row in lasts.values()))
    unread, mentioned = _unread(
        conn, mine, {c: w for c, w in windows.items() if found[c] == "participant"}
    )
    entries = []
    for chat, access in found.items():
        group, last = groups[chat], lasts.get(chat)
        current = stays[chat]
        entries.append(
            {
                "id": chat,
                "kind": "group",
                "title": group.title,
                "participants": [short(people[s.membership_id]) for s in current],
                "observers": group_chats.observers_of(current, owners),
                "access": access,
                "closed_at": ts(group.closed_at),
                "last_message_at": ts(last.at) if last is not None else None,
                "unread": unread.get(chat, 0) if access == "participant" else None,
                "mentions_unread": mentioned.get(chat, 0) if access == "participant" else None,
                "last_message": preview(last, senders.get(last.actor_membership) if last else None),
                "_activity": last.at if last is not None else group.created_at,
            }
        )
    return entries


def _access(
    mine: Any,
    groups: dict[str, Any],
    stays: dict[str, list[Any]],
    owners: dict[str, str],
    rounds: set[str],
) -> dict[str, str]:
    """`group_chats.access` of each chat, from the rows already read: the chats that
    exist for the caller, with how it sees them."""
    found: dict[str, str] = {}
    for chat in sorted(groups):
        current = stays[chat]
        if any(s.membership_id == mine.id for s in current):
            found[chat] = "participant"
        elif mine.kind == "human" and mine.principal_id in group_chats.observers_of(
            current, owners
        ):
            found[chat] = "observer"
        elif mine.kind == "human" and mine.role == "owner" and chat in rounds:
            found[chat] = "observer"  # every project owner reads a round's thread along (§20.5)
    return found


def _windows(
    conn: Connection, mine: Any, found: dict[str, str], stays: dict[str, list[Any]]
) -> dict[str, int]:
    """The seq after which the caller's window starts in each chat (§9.2): its latest
    join, for an observer the earliest join of its agents in the chat."""
    owned: set[str] = set()
    if "observer" in found.values():
        owned = set(
            conn.execute(
                select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == mine.principal_id)
            ).scalars()
        )
    windows = {}
    for chat, access in found.items():
        if access == "participant":
            windows[chat] = int(
                next(s.window_after for s in stays[chat] if s.membership_id == mine.id)
            )
        else:
            windows[chat] = int(min(s.window_after for s in stays[chat] if s.agent_id in owned))
    return windows


def _unread(
    conn: Connection, mine: Any, windows: dict[str, int]
) -> tuple[dict[str, int], dict[str, int]]:
    """Per chat the caller takes part in: the other members' messages after its read mark
    and its window, and how many of them mention it."""
    if not windows:
        return {}, {}
    marks = dict(
        conn.execute(
            select(t.conversation_read.c.conversation_id, t.conversation_read.c.last_seq).where(
                t.conversation_read.c.reader == mine.id,
                t.conversation_read.c.conversation_id.in_(list(windows)),
            )
        ).all()
    )
    seen = {chat: max(window, int(marks.get(chat) or 0)) for chat, window in windows.items()}
    unread: dict[str, int] = {}
    mentioned: dict[str, int] = {}
    named = _may_name(mine.principal_id)
    for batch in _chunks(list(seen)):
        behind = or_(
            *(and_(t.event.c.conversation_id == chat, t.event.c.seq > seen[chat]) for chat in batch)
        )
        kept = and_(
            t.event.c.project_id == mine.project.id,
            t.event.c.kind == "message",
            t.event.c.actor_membership != mine.id,
            behind,
        )
        unread.update(
            {
                chat: int(n)
                for chat, n in conn.execute(
                    select(t.event.c.conversation_id, func.count())
                    .where(kept)
                    .group_by(t.event.c.conversation_id)
                ).all()
            }
        )
        for row in conn.execute(
            select(t.event.c.conversation_id, t.event.c.redacted, t.event.c.payload).where(
                kept, named
            )
        ):
            if not row.redacted and any(
                m.get("member_id") == mine.principal_id
                for m in (row.payload or {}).get("mentions") or []
            ):
                mentioned[row.conversation_id] = mentioned.get(row.conversation_id, 0) + 1
    return unread, mentioned


def _may_name(principal: str) -> Any:
    """A payload whose text has a `member_id` and the principal's id: a superset of the
    messages that mention it (the exact test is on the rows read). The id alone would not
    do, a chat message names its addressee in `to`."""
    text = cast(t.event.c.payload, String)
    return and_(
        text.contains("member_id", autoescape=True), text.contains(principal, autoescape=True)
    )


__all__ = ["direct_entries", "group_entries", "preview", "short"]
