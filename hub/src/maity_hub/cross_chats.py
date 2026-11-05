"""Cross-project group chats (docs/api.md §9.5).

A room one human holds for agent profiles they own, including agents that share no
project. It is not a project resource: its messages are rows of this module, and the
only project event a message writes is one `cross_chat_mention` per mentioned agent,
in one project, with no body. The owner creates the chat and manages it. An agent is
in it only because the owner added it, and is woken only by a mention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, insert, or_, select, update
from sqlalchemy.orm import aliased

from maity_hub import clock, mentions, namespace, paging
from maity_hub import tables as t
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError, invalid, not_found, rate_limited
from maity_hub.events import Actor, emit, on_rollback
from maity_hub.ids import new_id
from maity_hub.mentions import PING_WINDOW, PINGS_PER_WINDOW, global_name
from maity_hub.policy import CLOSED_STATES
from maity_hub.ratelimit import Limiter
from maity_hub.views import ts

PREFIX = "xch-"
MIN_AGENTS = 2  # besides the owner (§9.5)
MAX_PARTICIPANTS = 12  # the owner included (§1.7)
OPEN_PER_OWNER = 200
PREVIEW = 200  # code points (§9.1)
PACKET = 50  # cross_chats in the resume packet (§5.2)

# The owner's own mentions, apart from any membership's 30 (§9.5, §1.7).
OWNER_PINGS = Limiter(PINGS_PER_WINDOW, PING_WINDOW, name="cross_chats.OWNER_PINGS")


def _activity_of(row: Any) -> datetime:
    found: datetime = row.last_message_at or row.created_at
    return found


def lock_owner(conn: Any, owner_id: str) -> None:
    """One owner's creates and quota, serialised on the account row."""
    conn.execute(select(t.human.c.id).where(t.human.c.id == owner_id).with_for_update()).one()


def find(conn: Any, chat_id: str) -> Any:
    return conn.execute(select(t.cross_chat).where(t.cross_chat.c.id == chat_id)).first()


def lock_chat(conn: Any, chat_id: str) -> Any:
    return conn.execute(
        select(t.cross_chat).where(t.cross_chat.c.id == chat_id).with_for_update()
    ).first()


def stays(conn: Any, chat_id: str, *, current: bool = True) -> list[Any]:
    query = (
        select(t.cross_chat_participant)
        .where(t.cross_chat_participant.c.conversation_id == chat_id)
        .order_by(t.cross_chat_participant.c.joined_at, t.cross_chat_participant.c.id)
    )
    if current:
        query = query.where(t.cross_chat_participant.c.here.is_(True))
    return list(conn.execute(query).all())


def stay(conn: Any, chat_id: str, member_id: str) -> Any:
    return conn.execute(
        select(t.cross_chat_participant).where(
            t.cross_chat_participant.c.conversation_id == chat_id,
            t.cross_chat_participant.c.member_id == member_id,
            t.cross_chat_participant.c.here.is_(True),
        )
    ).first()


def last_stay(conn: Any, chat_id: str, member_id: str) -> Any:
    return conn.execute(
        select(t.cross_chat_participant)
        .where(
            t.cross_chat_participant.c.conversation_id == chat_id,
            t.cross_chat_participant.c.member_id == member_id,
        )
        .order_by(t.cross_chat_participant.c.id.desc())
        .limit(1)
    ).first()


def refuse_closed(chat: Any) -> None:
    if chat.closed_at is not None:
        raise ApiError(
            409,
            "conversation_closed",
            "the chat has closed; start a new one",
            {"closed_reason": chat.closed_reason},
        )


def _quota(conn: Any, owner_id: str) -> None:
    open_chats = conn.execute(
        select(func.count()).where(
            t.cross_chat.c.owner_id == owner_id, t.cross_chat.c.closed_at.is_(None)
        )
    ).scalar_one()
    if open_chats >= OPEN_PER_OWNER:
        raise ApiError(
            409,
            "conversation_quota",
            "the owner has as many open cross-project group chats as they may",
            {"max": OPEN_PER_OWNER, "scope": "owner"},
        )


def _no_membership(member_id: str) -> ApiError:
    return ApiError(
        400,
        "invalid",
        "the profile has no active membership",
        {"fields": {"participants": "no_membership"}, "member_id": member_id},
    )


def _checked_agents(
    conn: Any, owner_id: str, raw: list[str], *, minimum: bool, room: int
) -> list[str]:
    """The agent profiles a create or an add may name, in the contract's check order.

    `room` is how many participants the chat may still take, the owner already counted
    where they are in it. `minimum` is creation's two agents; an add has none.
    """
    ids = [i for i in dict.fromkeys(raw) if i != owner_id]
    if ids:
        humans = set(conn.execute(select(t.human.c.id).where(t.human.c.id.in_(ids))).scalars())
        if humans:
            raise invalid(
                {"participants": "agents_only"}, "a cross-project group chat holds agents"
            )
    profiles = (
        {
            r.id: r
            for r in conn.execute(
                select(t.agent_profile).where(t.agent_profile.c.id.in_(ids))
            ).all()
        }
        if ids
        else {}
    )
    # not_found for the whole list, then deleted: one earlier id must not hide a later
    # one the caller does not own (§9.5).
    for member_id in ids:
        row = profiles.get(member_id)
        if row is None or row.owner_id != owner_id:
            raise not_found()
    for member_id in ids:
        if profiles[member_id].deleted_at is not None:
            raise invalid({"participants": "deleted"}, "the profile was deleted")
    active = (
        set(
            conn.execute(
                select(t.membership.c.agent_id).where(
                    t.membership.c.agent_id.in_(ids), t.membership.c.active.is_(True)
                )
            ).scalars()
        )
        if ids
        else set()
    )
    for member_id in ids:
        if member_id not in active:
            raise _no_membership(member_id)
    if minimum and len(ids) < MIN_AGENTS:
        raise invalid({"participants": "too_few"}, "name at least two agents")
    if len(ids) > room:
        raise invalid({"participants": "too_many"}, "a cross-project group chat holds twelve")
    return ids


def _shares_project(conn: Any, owner_id: str, agent_ids: list[str]) -> bool:
    """Some project that is not archived holds every named agent, and the owner as a
    human member who is not a guest: there the owner can open the project group chat."""
    if not agent_ids:
        return False
    projects = conn.execute(
        select(t.membership.c.project_id)
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(
            t.membership.c.human_id == owner_id,
            t.membership.c.active.is_(True),
            t.membership.c.trust != "guest",
            t.project.c.state.notin_(CLOSED_STATES),
        )
    ).scalars()
    wanted = set(agent_ids)
    for project_id in projects:
        found = set(
            conn.execute(
                select(t.membership.c.agent_id).where(
                    t.membership.c.project_id == project_id,
                    t.membership.c.agent_id.in_(wanted),
                    t.membership.c.active.is_(True),
                )
            ).scalars()
        )
        if found == wanted:
            return True
    return False


def _join(conn: Any, chat_id: str, member_id: str, by: str | None, after: int) -> None:
    conn.execute(
        insert(t.cross_chat_participant).values(
            conversation_id=chat_id,
            member_id=member_id,
            joined_at=clock.now(),
            window_after=after,
            added_by=by,
            here=True,
        )
    )


def create(conn: Any, owner_id: str, title: str | None, participants: list[str]) -> str:
    """Create a chat the owner holds; returns its id. The owner is a participant whether
    or not `participants` names them."""
    lock_owner(conn, owner_id)
    agents = _checked_agents(conn, owner_id, participants, minimum=True, room=MAX_PARTICIPANTS - 1)
    if _shares_project(conn, owner_id, agents):
        raise invalid(
            {"participants": "use_group"},
            "these agents share a project where the owner can open a group chat",
        )
    _quota(conn, owner_id)
    chat_id = new_id("cross_chat")
    now = clock.now()
    conn.execute(
        insert(t.cross_chat).values(
            id=chat_id,
            owner_id=owner_id,
            title=title,
            created_by=owner_id,
            created_at=now,
            next_seq=1,
        )
    )
    _join(conn, chat_id, owner_id, owner_id, 0)
    for agent_id in agents:
        _join(conn, chat_id, agent_id, owner_id, 0)
    return chat_id


def add(conn: Any, chat: Any, member_id: str) -> bool:
    """Add one profile the owner names. False when it is in the chat already."""
    chat = lock_chat(conn, chat.id)
    refuse_closed(chat)
    if stay(conn, chat.id, member_id) is not None:
        return False
    current = len(stays(conn, chat.id))
    agents = _checked_agents(
        conn, chat.owner_id, [member_id], minimum=False, room=MAX_PARTICIPANTS - current
    )
    if not agents:
        return False  # the owner's own id, and they are in it from the start
    _join(conn, chat.id, agents[0], chat.owner_id, int(chat.next_seq) - 1)
    return True


def end_stay(conn: Any, chat: Any, member_id: str, by: str | None, reason: str) -> Any:
    """End the current stay. The owner's leaving closes the chat. Returns the ended row,
    or None when the member has no current stay."""
    chat = lock_chat(conn, chat.id)
    current = stay(conn, chat.id, member_id)
    if current is None:
        return None
    now = clock.now()
    conn.execute(
        update(t.cross_chat_participant)
        .where(t.cross_chat_participant.c.id == current.id)
        .values(left_at=now, removed_by=by, reason=reason, here=None)
    )
    if member_id == chat.owner_id and chat.closed_at is None:
        conn.execute(
            update(t.cross_chat)
            .where(t.cross_chat.c.id == chat.id)
            .values(closed_at=now, closed_reason="no_human")
        )
    return conn.execute(
        select(t.cross_chat_participant).where(t.cross_chat_participant.c.id == current.id)
    ).one()


def rename(conn: Any, chat: Any, title: str | None) -> None:
    chat = lock_chat(conn, chat.id)
    refuse_closed(chat)
    if title == chat.title:
        return
    conn.execute(update(t.cross_chat).where(t.cross_chat.c.id == chat.id).values(title=title))


def participation(row: Any) -> dict[str, Any]:
    return {
        "conversation_id": row.conversation_id,
        "member_id": row.member_id,
        "joined_at": ts(row.joined_at),
        "left_at": ts(row.left_at),
        "by": row.removed_by if row.left_at else row.added_by,
        "reason": row.reason,
    }


def _people(conn: Any, member_ids: list[str]) -> dict[str, dict[str, Any]]:
    """`{member_id, kind, handle, name?, owner_id}` of each id. A deleted human shows no
    handle (§2.9). An unknown id is left out."""
    if not member_ids:
        return {}
    humans = {
        r.id: r
        for r in conn.execute(
            select(t.human.c.id, t.human.c.handle, t.human.c.deleted_at).where(
                t.human.c.id.in_(member_ids)
            )
        ).all()
    }
    owner = t.human.alias("owner")
    agents = {
        r.id: r
        for r in conn.execute(
            select(
                t.agent_profile.c.id,
                t.agent_profile.c.handle,
                t.agent_profile.c.owner_id,
                owner.c.handle.label("owner_handle"),
            )
            .join(owner, owner.c.id == t.agent_profile.c.owner_id)
            .where(t.agent_profile.c.id.in_(member_ids))
        ).all()
    }
    found: dict[str, dict[str, Any]] = {}
    for member_id in member_ids:
        human = humans.get(member_id)
        if human is not None:
            person: dict[str, Any] = {
                "member_id": member_id,
                "kind": "human",
                "handle": None if human.deleted_at is not None else human.handle,
                "owner_id": None,
            }
            found[member_id] = person
            continue
        agent = agents.get(member_id)
        if agent is None:
            continue
        found[member_id] = {
            "member_id": member_id,
            "kind": "agent",
            "handle": agent.handle,
            "name": global_name(agent.owner_handle, agent.handle),
            "owner_id": agent.owner_id,
        }
    return found


def _projects(conn: Any, agent_ids: list[str]) -> dict[str, list[str]]:
    """Each agent's active memberships, full names ascending."""
    if not agent_ids:
        return {}
    rows = conn.execute(
        select(t.membership.c.agent_id, t.membership.c.project_id).where(
            t.membership.c.agent_id.in_(agent_ids), t.membership.c.active.is_(True)
        )
    ).all()
    names = namespace.full_names(conn, [r.project_id for r in rows])
    found: dict[str, list[str]] = {agent_id: [] for agent_id in agent_ids}
    for row in rows:
        found[row.agent_id].append(names[row.project_id])
    for agent_id in found:
        found[agent_id] = sorted(set(found[agent_id]))
    return found


def _shown_projects(
    projects: dict[str, list[str]], reader_id: str, *, owner_reads: bool
) -> dict[str, list[str]]:
    """The owner sees every active membership. An agent sees the projects it shares
    with that participant, and its own. A project the reader is not in is left out."""
    if owner_reads:
        return projects
    mine = set(projects.get(reader_id, []))
    return {
        agent_id: (names if agent_id == reader_id else sorted(mine & set(names)))
        for agent_id, names in projects.items()
    }


def _ordered(current: list[Any], owner_id: str) -> list[Any]:
    """The owner first, then the order they joined."""
    return sorted(current, key=lambda s: (s.member_id != owner_id, s.joined_at, s.id))


def _participant(
    person: dict[str, Any], stay_row: Any, projects: list[str] | None, *, detail: bool
) -> dict[str, Any]:
    if detail:
        shown = {
            "member_id": person["member_id"],
            "kind": person["kind"],
            "handle": person["handle"],
            "owner_id": person["owner_id"],
            "joined_at": ts(stay_row.joined_at),
        }
        if person["kind"] == "agent":
            shown["name"] = person["name"]
            shown["projects"] = projects or []
        return shown
    shown = {"member_id": person["member_id"], "kind": person["kind"], "handle": person["handle"]}
    if person["kind"] == "agent":
        shown["name"] = person["name"]
    return shown


def _access(chat: Any, reader_id: str, current: list[Any]) -> str | None:
    if any(s.member_id == reader_id for s in current):
        return "participant"
    if reader_id == chat.owner_id and chat.closed_at is not None:
        return "owner"
    return None


def view(conn: Any, chat: Any, reader_id: str) -> dict[str, Any] | None:
    """The conversation view, or None when this reader may not see the chat."""
    current = stays(conn, chat.id)
    access = _access(chat, reader_id, current)
    if access is None:
        return None
    people = _people(conn, [s.member_id for s in current])
    agents = [s.member_id for s in current if people.get(s.member_id, {}).get("kind") == "agent"]
    projects = _shown_projects(
        _projects(conn, agents), reader_id, owner_reads=reader_id == chat.owner_id
    )
    return {
        "id": chat.id,
        "kind": "cross",
        "title": chat.title,
        "created_by": chat.created_by,
        "created_at": ts(chat.created_at),
        "participants": [
            _participant(people[s.member_id], s, projects.get(s.member_id), detail=True)
            for s in _ordered(current, chat.owner_id)
            if s.member_id in people
        ],
        "observers": [],
        "closed_at": ts(chat.closed_at),
        "closed_reason": chat.closed_reason,
        "access": access,
    }


def _window_of(conn: Any, chat: Any, reader_id: str) -> int | None:
    """The seq the reader's default window starts after, or None when they may not read."""
    current = stay(conn, chat.id, reader_id)
    if current is not None:
        return int(current.window_after)
    if reader_id == chat.owner_id and chat.closed_at is not None:
        last = last_stay(conn, chat.id, reader_id)
        return int(last.window_after) if last is not None else 0
    return None


def _reads(conn: Any, reader_id: str, chat_ids: list[str]) -> dict[str, int]:
    if not chat_ids:
        return {}
    rows = conn.execute(
        select(t.cross_chat_read.c.conversation_id, t.cross_chat_read.c.last_seq).where(
            t.cross_chat_read.c.member_id == reader_id,
            t.cross_chat_read.c.conversation_id.in_(chat_ids),
        )
    ).all()
    return {r.conversation_id: int(r.last_seq) for r in rows}


def remember(conn: Any, reader_id: str, chat_id: str, seq: int) -> None:
    """Move the participant's read mark up to `seq`, never down."""
    updated = conn.execute(
        update(t.cross_chat_read)
        .where(
            t.cross_chat_read.c.member_id == reader_id,
            t.cross_chat_read.c.conversation_id == chat_id,
            t.cross_chat_read.c.last_seq < seq,
        )
        .values(last_seq=seq)
    ).rowcount
    if updated:
        return
    exists = conn.execute(
        select(t.cross_chat_read.c.last_seq).where(
            t.cross_chat_read.c.member_id == reader_id,
            t.cross_chat_read.c.conversation_id == chat_id,
        )
    ).first()
    if exists is None:
        conn.execute(
            insert(t.cross_chat_read).values(
                member_id=reader_id, conversation_id=chat_id, last_seq=seq
            )
        )


def _preview(row: Any) -> dict[str, Any]:
    body = None if row.redacted else row.body
    return {
        "seq": int(row.seq),
        "from": row.author_id,
        "body": body[:PREVIEW] if isinstance(body, str) else None,
        "sent_at": ts(row.sent_at),
        "redacted": bool(row.redacted),
    }


def _latest(conn: Any, windows: dict[str, int]) -> dict[str, Any]:
    """Per chat the newest message after the reader's window."""
    clauses = [
        and_(t.cross_chat_message.c.conversation_id == cid, t.cross_chat_message.c.seq > after)
        for cid, after in windows.items()
    ]
    if not clauses:
        return {}
    sub = (
        select(
            t.cross_chat_message.c.conversation_id,
            func.max(t.cross_chat_message.c.seq).label("seq"),
        )
        .where(or_(*clauses))
        .group_by(t.cross_chat_message.c.conversation_id)
        .subquery()
    )
    rows = conn.execute(
        select(t.cross_chat_message).join(
            sub,
            and_(
                t.cross_chat_message.c.conversation_id == sub.c.conversation_id,
                t.cross_chat_message.c.seq == sub.c.seq,
            ),
        )
    ).all()
    return {r.conversation_id: r for r in rows}


def _unreads(
    conn: Any, reader_id: str, seen: dict[str, int]
) -> tuple[dict[str, int], dict[str, int]]:
    """Per chat, the others' messages after the read mark, and how many mention the reader."""
    clauses = [
        and_(
            t.cross_chat_message.c.conversation_id == cid,
            t.cross_chat_message.c.seq > seq,
            t.cross_chat_message.c.author_id != reader_id,
        )
        for cid, seq in seen.items()
    ]
    if not clauses:
        return {}, {}
    unread = {
        cid: int(n)
        for cid, n in conn.execute(
            select(t.cross_chat_message.c.conversation_id, func.count())
            .where(or_(*clauses))
            .group_by(t.cross_chat_message.c.conversation_id)
        ).all()
    }
    # Mentions of this reader live in their own rows, so the count does not read the
    # chat's other messages.
    hits = [
        and_(
            t.cross_chat_mention_for.c.conversation_id == cid,
            t.cross_chat_mention_for.c.member_id == reader_id,
            t.cross_chat_mention_for.c.seq > seq,
        )
        for cid, seq in seen.items()
    ]
    mentioned = {
        cid: int(n)
        for cid, n in conn.execute(
            select(t.cross_chat_mention_for.c.conversation_id, func.count())
            .where(or_(*hits))
            .group_by(t.cross_chat_mention_for.c.conversation_id)
        ).all()
    }
    return unread, mentioned


def _windows_for(conn: Any, chats: list[Any], reader_id: str, *, as_owner: bool) -> dict[str, int]:
    if not chats:
        return {}
    ids = [c.id for c in chats]
    rows = conn.execute(
        select(
            t.cross_chat_participant.c.conversation_id,
            t.cross_chat_participant.c.window_after,
            t.cross_chat_participant.c.here,
            t.cross_chat_participant.c.id,
        )
        .where(
            t.cross_chat_participant.c.conversation_id.in_(ids),
            t.cross_chat_participant.c.member_id == reader_id,
        )
        .order_by(t.cross_chat_participant.c.id)
    ).all()
    current = {r.conversation_id: int(r.window_after) for r in rows if r.here}
    if not as_owner:
        return current
    # The owner who has left a closed chat keeps the window of their latest stay.
    latest: dict[str, int] = {}
    for row in rows:
        latest[row.conversation_id] = int(row.window_after)
    return {c.id: current.get(c.id, latest.get(c.id, 0)) for c in chats}


def _list_item(
    conn: Any,
    chat: Any,
    reader_id: str,
    people: dict[str, dict[str, Any]],
    preview: Any,
    unread: int,
    mentions_unread: int,
) -> dict[str, Any]:
    current = stays(conn, chat.id)
    access = _access(chat, reader_id, current)
    return {
        "id": chat.id,
        "kind": "cross",
        "title": chat.title,
        "created_at": ts(chat.created_at),
        "participants": [
            _participant(people[s.member_id], s, None, detail=False)
            for s in _ordered(current, chat.owner_id)
            if s.member_id in people
        ],
        "observers": [],
        "access": access,
        "closed_at": ts(chat.closed_at),
        "last_message_at": ts(chat.last_message_at),
        "unread": unread,
        "mentions_unread": mentions_unread,
        "last_message": _preview(preview) if preview is not None else None,
    }


def listing(
    conn: Any, reader_id: str, *, as_owner: bool, limit: int, cursor: str | None, bound: str
) -> dict[str, Any]:
    """The caller's chats, newest activity first."""
    activity = func.coalesce(t.cross_chat.c.last_message_at, t.cross_chat.c.created_at)
    if as_owner:
        query = select(t.cross_chat).where(t.cross_chat.c.owner_id == reader_id)
    else:
        query = (
            select(t.cross_chat)
            .join(
                t.cross_chat_participant,
                t.cross_chat_participant.c.conversation_id == t.cross_chat.c.id,
            )
            .where(
                t.cross_chat_participant.c.member_id == reader_id,
                t.cross_chat_participant.c.here.is_(True),
            )
        )
    if cursor is not None:
        at, row_id = paging.uncursor(cursor, bound)
        query = query.where(or_(activity < at, and_(activity == at, t.cross_chat.c.id < row_id)))
    rows = list(
        conn.execute(
            query.order_by(activity.desc(), t.cross_chat.c.id.desc()).limit(limit + 1)
        ).all()
    )
    page, extra = rows[:limit], rows[limit:]
    windows = _windows_for(conn, page, reader_id, as_owner=as_owner)
    reads = _reads(conn, reader_id, [c.id for c in page])
    seen = {cid: max(reads.get(cid, 0), after) for cid, after in windows.items()}
    unread, mentioned = _unreads(conn, reader_id, seen)
    previews = _latest(conn, windows)
    member_ids = [s.member_id for chat in page for s in stays(conn, chat.id)]
    people = _people(conn, member_ids)
    items = [
        _list_item(
            conn,
            chat,
            reader_id,
            people,
            previews.get(chat.id),
            unread.get(chat.id, 0),
            mentioned.get(chat.id, 0),
        )
        for chat in page
    ]
    next_cursor = (
        paging.cursor(_activity_of(page[-1]), page[-1].id, bound) if extra and page else None
    )
    return {"items": items, "next_cursor": next_cursor}


def resume_packet(conn: Any, agent_id: str) -> list[dict[str, Any]]:
    """`cross_chats` of the resume packet: the chats the agent is in now, at most 50."""
    found = listing(conn, agent_id, as_owner=False, limit=PACKET, cursor=None, bound="packet")
    return [
        {
            "id": item["id"],
            "kind": "cross",
            "title": item["title"],
            "unread": item["unread"],
            "mentions_unread": item["mentions_unread"],
        }
        for item in found["items"]
    ]


def _message(row: Any, *, show_reason: bool) -> dict[str, Any]:
    mark = row.redaction if row.redacted else None
    if isinstance(mark, dict) and not show_reason:
        mark = {**mark, "reason": None}
    return {
        "id": row.id,
        "seq": int(row.seq),
        "conversation_id": row.conversation_id,
        "from": row.author_id,
        "to": row.conversation_id,
        "body": None if row.redacted else row.body,
        "sent_at": ts(row.sent_at),
        "mentions": [] if row.redacted else list(row.mentions or []),
        "from_instance": row.from_instance,
        "to_instance": None,
        "redacted": bool(row.redacted),
        "redaction": mark,
    }


def message_view(row: Any, *, show_reason: bool) -> dict[str, Any]:
    return _message(row, show_reason=show_reason)


def messages(
    conn: Any,
    chat: Any,
    reader_id: str,
    *,
    after: int | None,
    before: int | None,
    limit: int,
) -> dict[str, Any]:
    """One page. Without `before`, the reader's window, and the page moves the read mark."""
    window = _window_of(conn, chat, reader_id)
    if window is None:
        raise not_found()
    query = select(t.cross_chat_message).where(t.cross_chat_message.c.conversation_id == chat.id)
    if before is not None:
        rows = list(
            reversed(
                conn.execute(
                    query.where(t.cross_chat_message.c.seq < before)
                    .order_by(t.cross_chat_message.c.seq.desc())
                    .limit(limit)
                ).all()
            )
        )
        cursor = 0
    else:
        start = max(after or 0, window)
        rows = list(
            conn.execute(
                query.where(t.cross_chat_message.c.seq > start)
                .order_by(t.cross_chat_message.c.seq)
                .limit(limit)
            ).all()
        )
        cursor = int(rows[-1].seq) if rows else start
        if rows:
            remember(conn, reader_id, chat.id, int(rows[-1].seq))
    earlier = None
    if rows:
        older = conn.execute(
            query.with_only_columns(t.cross_chat_message.c.seq)
            .where(t.cross_chat_message.c.seq < rows[0].seq)
            .limit(1)
        ).first()
        earlier = int(rows[0].seq) if older is not None else None
    show = reader_id == chat.owner_id
    return {
        "items": [_message(row, show_reason=show) for row in rows],
        "cursor": cursor,
        "earlier": earlier,
    }


def _charge(conn: Any, caller: Caller, count: int) -> None:
    """One ping per mentioned participant other than the writer (§8.6, §9.5)."""
    if count <= 0:
        return
    if caller.kind == "human":
        key = caller.principal_id
        wait, mark = OWNER_PINGS.place(key, count)
        if wait:
            raise rate_limited(wait)
        on_rollback(conn, lambda: OWNER_PINGS.release(key, mark, count))
        return
    assert caller.membership_id is not None
    mentions.charge(conn, caller.membership_id, count)


def _resolve(conn: Any, chat_id: str, text: str) -> list[dict[str, Any]]:
    """Mentions of current participants only (§8.6, §9.5). Anyone else stays text."""
    found = mentions.candidates(text)
    if not found:
        return []
    from maity_hub import handles

    current = stays(conn, chat_id)
    people = _people(conn, [s.member_id for s in current])
    aliased = handles.aliases(
        conn, [*people, *(p["owner_id"] for p in people.values() if p.get("owner_id"))]
    )
    humans = {p["handle"]: p["member_id"] for p in people.values() if p["kind"] == "human"}
    members = []
    for person in people.values():
        names = {person["handle"], *aliased.get(person["member_id"], [])}
        names.discard(None)
        if person["kind"] == "agent":
            owners = {person["name"].split("/", 1)[0], *aliased.get(person["owner_id"], [])}
            members.append((person, names, owners))
        else:
            members.append((person, names, set()))

    def matches(candidate: Any) -> list[dict[str, Any]]:
        hit = []
        for person, names, owners in members:
            if candidate.handle not in names:
                continue
            if candidate.owner is not None and (
                person["kind"] != "agent" or candidate.owner not in owners
            ):
                continue
            hit.append(person)
        return hit

    resolved: dict[tuple[str | None, str], dict[str, Any] | None] = {}
    shared: dict[str, list[str]] = {}
    for candidate in sorted(found, key=lambda c: c.handle):
        hit = matches(candidate)
        first = [
            p
            for p in hit
            if p["kind"] == "human" and humans.get(candidate.handle) == p["member_id"]
        ]
        pick: list[dict[str, Any]] | None
        pick = hit if len(hit) <= 1 else (first if len(first) == 1 else None)
        if pick is None:
            key = (
                candidate.handle
                if candidate.owner is None
                else f"{candidate.owner}/{candidate.handle}"
            )
            shared[key] = sorted(p["name"] if p["kind"] == "agent" else p["handle"] for p in hit)
            continue
        resolved[(candidate.owner, candidate.handle)] = pick[0] if pick else None
    if shared:
        raise ApiError(
            400,
            "invalid",
            "a short handle names more than one member: use the global name",
            {"fields": {"body": "ambiguous_mention"}, "mentions": shared},
        )
    agents = {p["member_id"] for p in people.values() if p["kind"] == "agent"}
    known = _known_instances(conn, agents, {c.instance for c in found if c.instance})
    stored = []
    for candidate in found:
        named = resolved.get((candidate.owner, candidate.handle))
        if named is None:
            continue
        if candidate.instance is not None and (named["member_id"], candidate.instance) not in known:
            continue
        stored.append(
            {
                "member_id": named["member_id"],
                "handle": named["handle"],
                "name": named.get("name"),
                "instance": candidate.instance,
                "field": "body",
                "offset": candidate.offset,
                "length": candidate.length,
            }
        )
    if (
        len({m["member_id"] for m in stored}) > mentions.MAX_MEMBERS
        or len(stored) > mentions.MAX_OCCURRENCES
    ):
        raise invalid({"body": "too_many_mentions"}, "too many mentions in one text")
    return stored


def _known_instances(conn: Any, agent_ids: set[str], wanted: set[str]) -> set[tuple[str, str]]:
    if not agent_ids or not wanted:
        return set()
    successor = aliased(t.credential)
    replaced = (
        select(successor.c.id)
        .where(
            successor.c.membership_id == t.credential.c.membership_id,
            successor.c.replaces == t.credential.c.instance,
        )
        .exists()
    )
    rows = conn.execute(
        select(t.membership.c.agent_id, t.credential.c.instance)
        .join(t.credential, t.credential.c.membership_id == t.membership.c.id)
        .where(
            t.membership.c.agent_id.in_(agent_ids),
            t.membership.c.active.is_(True),
            t.credential.c.instance.in_(wanted),
            or_(t.credential.c.revoked_at.is_(None), replaced),
        )
    )
    return {(r.agent_id, r.instance) for r in rows}


def _author_actor(conn: Any, caller: Caller, project_id: str) -> Actor:
    """The member actor when the author is a member of the project the event is written
    in, the human actor when the owner is not a member there, and `kind: agent` when the
    author is an agent profile that is not a member there (§9.5)."""
    if caller.kind == "human":
        membership_id = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.project_id == project_id,
                t.membership.c.human_id == caller.human_id,
                t.membership.c.active.is_(True),
            )
        ).scalar()
        if membership_id is not None:
            return Actor(
                membership_id=int(membership_id),
                via=caller.via,
                credential_id=caller.credential_id,
                session_id=caller.session_id,
            )
        return Actor(None, via=caller.via, human_id=caller.human_id)
    membership_id = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == project_id,
            t.membership.c.agent_id == caller.agent_id,
            t.membership.c.active.is_(True),
        )
    ).scalar()
    if membership_id is not None:
        if caller.membership_id == membership_id:
            return caller.actor(int(membership_id))
        return Actor(
            membership_id=int(membership_id),
            session_id=caller.session_id,
            credential_id=caller.credential_id,
            via=caller.via,
            harness=caller.harness,
            model=caller.model,
        )
    return Actor(None, via=caller.via, agent_id=caller.agent_id, agent_instance=caller.instance)


def _mention_home(conn: Any, agent_id: str) -> Any:
    """The one non-isolated membership that resumed most recently, or None."""
    rows = conn.execute(
        select(
            t.membership.c.id,
            t.membership.c.project_id,
            func.max(t.credential.c.resumed_at).label("resumed"),
        )
        .select_from(
            t.membership.outerjoin(t.credential, t.credential.c.membership_id == t.membership.c.id)
        )
        .where(
            t.membership.c.agent_id == agent_id,
            t.membership.c.active.is_(True),
            t.membership.c.isolated_since.is_(None),
        )
        .group_by(t.membership.c.id, t.membership.c.project_id)
    ).all()
    if not rows:
        return None

    def _key(row: Any) -> tuple[bool, float, int]:
        resumed = row.resumed
        return (resumed is None, -(resumed.timestamp() if resumed else 0), int(row.id))

    return min(rows, key=_key)


def _instance_home(conn: Any, agent_id: str, instance: str) -> Any:
    """The active membership whose instance id is the one the mention wrote."""
    rows = conn.execute(
        select(t.membership.c.id, t.membership.c.project_id, t.credential.c.revoked_at)
        .join(t.credential, t.credential.c.membership_id == t.membership.c.id)
        .where(
            t.membership.c.agent_id == agent_id,
            t.membership.c.active.is_(True),
            t.membership.c.isolated_since.is_(None),
            t.credential.c.instance == instance,
        )
    ).all()
    if not rows:
        return None
    live = [r for r in rows if r.revoked_at is None]
    return (live or rows)[0]


def _mention_events(
    conn: Any, caller: Caller, chat: Any, message_id: str, seq: int, stored: list[dict[str, Any]]
) -> None:
    """One `cross_chat_mention` per mentioned agent, in one project, with no body."""
    by_agent: dict[str, dict[str, Any]] = {}
    for mention in stored:
        if not str(mention["member_id"]).startswith("agt-"):
            continue
        current = by_agent.get(mention["member_id"])
        if current is None or (current.get("instance") is None and mention.get("instance")):
            by_agent[mention["member_id"]] = mention
    payload_of = {
        "conversation": {"id": chat.id, "kind": "cross", "title": chat.title},
        "message_id": message_id,
        "seq": seq,
    }
    for agent_id, mention in by_agent.items():
        instance = mention.get("instance")
        home = _instance_home(conn, agent_id, instance) if instance else None
        if instance and home is None:
            home = _mention_home(conn, agent_id)
            instance = None
        if home is None and instance is None:
            home = _mention_home(conn, agent_id)
        if home is None:
            continue
        if instance:
            audience = [mentions.instance_token(conn, home.project_id, agent_id, instance)]
        else:
            audience = [f"member:{agent_id}"]
        emit(
            conn,
            home.project_id,
            "cross_chat_mention",
            audience,
            payload_of,
            actor=_author_actor(conn, caller, home.project_id),
        )


def post(conn: Any, caller: Caller, chat: Any, body: str) -> dict[str, Any]:
    chat = lock_chat(conn, chat.id)
    reader = caller.principal_id
    if _window_of(conn, chat, reader) is None:
        raise not_found()
    refuse_closed(chat)
    stored = _resolve(conn, chat.id, body)
    others = {m["member_id"] for m in stored if m["member_id"] != reader}
    _charge(conn, caller, len(others))
    seq = int(chat.next_seq)
    message_id = new_id("cross_message")
    now = clock.now()
    conn.execute(
        insert(t.cross_chat_message).values(
            id=message_id,
            conversation_id=chat.id,
            seq=seq,
            author_id=reader,
            from_instance=caller.instance if caller.kind == "agent" else None,
            body=body,
            sent_at=now,
            mentions=stored,
            redacted=False,
        )
    )
    conn.execute(
        update(t.cross_chat)
        .where(t.cross_chat.c.id == chat.id)
        .values(next_seq=seq + 1, last_message_at=now)
    )
    if others:
        conn.execute(
            insert(t.cross_chat_mention_for),
            [
                {"conversation_id": chat.id, "member_id": member_id, "seq": seq}
                for member_id in others
            ],
        )
    remember(conn, reader, chat.id, seq)
    _mention_events(conn, caller, chat, message_id, seq, stored)
    row = conn.execute(
        select(t.cross_chat_message).where(t.cross_chat_message.c.id == message_id)
    ).one()
    return _message(row, show_reason=reader == chat.owner_id)


def message_row(conn: Any, chat_id: str, message_id: str) -> Any:
    return conn.execute(
        select(t.cross_chat_message).where(
            t.cross_chat_message.c.id == message_id,
            t.cross_chat_message.c.conversation_id == chat_id,
        )
    ).first()


def redact(conn: Any, chat: Any, row: Any, reason: str, by: str) -> dict[str, Any]:
    """The owner redacts any message, in an open chat and after it has closed."""
    if row.redacted:
        raise ApiError(
            400, "invalid", "the message is already redacted", {"reason": "already_redacted"}
        )
    mark = {"at": ts(clock.now()), "by": by, "reason": reason}
    conn.execute(
        update(t.cross_chat_message)
        .where(t.cross_chat_message.c.id == row.id)
        .values(body=None, mentions=[], redacted=True, redaction=mark)
    )
    conn.execute(
        t.cross_chat_mention_for.delete().where(
            t.cross_chat_mention_for.c.conversation_id == chat.id,
            t.cross_chat_mention_for.c.seq == row.seq,
        )
    )
    updated = conn.execute(
        select(t.cross_chat_message).where(t.cross_chat_message.c.id == row.id)
    ).one()
    return _message(updated, show_reason=True)


def _current_chats(conn: Any, member_id: str, *, owner_id: str | None = None) -> list[Any]:
    query = (
        select(t.cross_chat)
        .join(
            t.cross_chat_participant,
            t.cross_chat_participant.c.conversation_id == t.cross_chat.c.id,
        )
        .where(
            t.cross_chat_participant.c.member_id == member_id,
            t.cross_chat_participant.c.here.is_(True),
        )
        .order_by(t.cross_chat.c.id)
    )
    if owner_id is not None:
        query = query.where(t.cross_chat.c.owner_id == owner_id)
    return list(conn.execute(query).all())


def profile_left(
    conn: Any, agent_id: str, by: str | None, reason: str, *, owner_id: str | None = None
) -> None:
    """End the profile's current stays. `owner_id` limits it to one owner's chats."""
    for chat in _current_chats(conn, agent_id, owner_id=owner_id):
        end_stay(conn, chat, agent_id, by, reason)


def membership_ended(conn: Any, agent_id: str, by: str | None) -> None:
    """The profile's last active membership ended: it leaves every such chat. One
    membership ending while another remains does not, unless every one that remains
    is isolated: that is every active membership isolated, and the profile leaves
    (§9.5). Lifting the isolation does not put it back."""
    remaining = conn.execute(
        select(t.membership.c.isolated_since).where(
            t.membership.c.agent_id == agent_id, t.membership.c.active.is_(True)
        )
    ).all()
    if not remaining:
        profile_left(conn, agent_id, by, "membership_removed")
        return
    if all(row.isolated_since is not None for row in remaining):
        profile_left(conn, agent_id, by, "membership_isolated")


def isolation_settled(conn: Any, agent_id: str, by: str | None) -> None:
    """When every active membership is isolated, the profile leaves. One that is not
    keeps it in the chat. Lifting an isolation does not put it back."""
    rows = conn.execute(
        select(t.membership.c.isolated_since).where(
            t.membership.c.agent_id == agent_id, t.membership.c.active.is_(True)
        )
    ).all()
    if not rows or any(r.isolated_since is None for r in rows):
        return
    profile_left(conn, agent_id, by, "membership_isolated")


def owner_changed(conn: Any, agent_id: str, old_owner_id: str) -> None:
    """The profile leaves every cross-project group chat of its old owner. It is not
    added to a chat of the new owner. No route changes an owner yet: the change that
    does calls this, as it moves the not-listening digest (§5.3, §9.5)."""
    profile_left(conn, agent_id, None, "owner_changed", owner_id=old_owner_id)


def remove_owned(conn: Any, human_id: str) -> None:
    """The owner's account is gone: the chats go with it (§2.9, §9.5)."""
    ids = list(
        conn.execute(select(t.cross_chat.c.id).where(t.cross_chat.c.owner_id == human_id)).scalars()
    )
    if not ids:
        return
    for table in (
        t.cross_chat_mention_for,
        t.cross_chat_message,
        t.cross_chat_read,
        t.cross_chat_participant,
    ):
        conn.execute(table.delete().where(table.c.conversation_id.in_(ids)))
    conn.execute(t.cross_chat.delete().where(t.cross_chat.c.id.in_(ids)))


def export_of(conn: Any, human_id: str) -> list[dict[str, Any]]:
    """The owner's chats, whole, their messages and their agents' messages (§2.9)."""
    chats = conn.execute(
        select(t.cross_chat)
        .where(t.cross_chat.c.owner_id == human_id)
        .order_by(t.cross_chat.c.created_at, t.cross_chat.c.id)
    ).all()
    found = []
    for chat in chats:
        rows = conn.execute(
            select(t.cross_chat_message)
            .where(t.cross_chat_message.c.conversation_id == chat.id)
            .order_by(t.cross_chat_message.c.seq)
        ).all()
        found.append(
            {
                "id": chat.id,
                "title": chat.title,
                "created_at": ts(chat.created_at),
                "closed_at": ts(chat.closed_at),
                "closed_reason": chat.closed_reason,
                "messages": [_message(row, show_reason=True) for row in rows],
            }
        )
    return found
