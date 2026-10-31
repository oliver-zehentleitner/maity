"""Group chats (docs/api.md §9.2): rooms of members, created by a human.

A group chat's messages are `message` events of type `chat` whose `conversation_id` is
the chat's `cnv-…` id, addressed to its participants at write time. Its own rows hold
the title, who is in it and since when: each stay of a member is a row, and the
member's window, what it reads by default, starts after `window_after`, the project's
highest event seq when it joined. The chat closes for good when its last human leaves,
so that no channel among agents of different owners exists without a human in it.

The hub's own thread for a jour fixe round (§20.5, `hub_thread`) has no creator and is
exempt from the participant cap, `use_direct` and the quota; its round bounds it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import Connection, func, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid
from maity_hub.events import Actor, emit, lock_project
from maity_hub.ids import new_id
from maity_hub.mentions import global_name
from maity_hub.policy import CLOSED_STATES
from maity_hub.views import ts

PREFIX = "cnv-"
MIN_PARTICIPANTS, MAX_PARTICIPANTS = 2, 12  # the creator included (§1.7)
OPEN_PER_PROJECT = 200  # open group chats per project (§1.7)


def is_group(conversation_id: str | None) -> bool:
    """The hub tells the kinds apart by the id; a client reads `kind` (§9)."""
    return conversation_id is not None and conversation_id.startswith(PREFIX)


def find(conn: Connection, project_id: str, conversation_id: str) -> Any:
    """The chat row in this project, or None."""
    return conn.execute(
        select(t.conversation).where(
            t.conversation.c.id == conversation_id, t.conversation.c.project_id == project_id
        )
    ).first()


def stays(conn: Connection, conversation_id: str, *, current: bool = True) -> list[Any]:
    """The chat's stays, oldest join first: the current ones, or every one."""
    query = (
        select(
            t.conversation_participant,
            t.membership.c.agent_id,
            t.membership.c.human_id,
        )
        .join(t.membership, t.membership.c.id == t.conversation_participant.c.membership_id)
        .where(t.conversation_participant.c.conversation_id == conversation_id)
        .order_by(t.conversation_participant.c.joined_at, t.conversation_participant.c.id)
    )
    if current:
        query = query.where(t.conversation_participant.c.here.is_(True))
    return list(conn.execute(query).all())


def stay(conn: Connection, conversation_id: str, membership_id: int) -> Any:
    """The member's current stay in the chat, or None."""
    return conn.execute(
        select(t.conversation_participant).where(
            t.conversation_participant.c.conversation_id == conversation_id,
            t.conversation_participant.c.membership_id == membership_id,
            t.conversation_participant.c.here.is_(True),
        )
    ).first()


def windows(conn: Connection, membership_id: int) -> dict[str, int]:
    """Each group chat the member is in now, and the seq its current stay's window
    starts after (§9.2)."""
    rows = conn.execute(
        select(
            t.conversation_participant.c.conversation_id,
            t.conversation_participant.c.window_after,
        ).where(
            t.conversation_participant.c.membership_id == membership_id,
            t.conversation_participant.c.here.is_(True),
        )
    ).all()
    return {r.conversation_id: int(r.window_after) for r in rows}


def last_stay(conn: Connection, conversation_id: str, membership_id: int) -> Any:
    """The member's latest stay, current or not, or None."""
    return conn.execute(
        select(t.conversation_participant)
        .where(
            t.conversation_participant.c.conversation_id == conversation_id,
            t.conversation_participant.c.membership_id == membership_id,
        )
        .order_by(t.conversation_participant.c.id.desc())
        .limit(1)
    ).first()


def principal(row: Any) -> str:
    found: str = row.agent_id or row.human_id
    return found


def people(conn: Connection, membership_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
    """`{member_id, kind, handle, owner_id}` of each membership, and an agent's global
    `name` (§6.3)."""
    wanted = set(membership_ids)
    if not wanted:
        return {}
    owner = t.human.alias("owner")
    rows = conn.execute(
        select(
            t.membership.c.id,
            t.membership.c.agent_id,
            t.membership.c.human_id,
            t.agent_profile.c.handle.label("agent_handle"),
            t.agent_profile.c.owner_id,
            t.human.c.handle.label("human_handle"),
            t.human.c.deleted_at.label("human_deleted_at"),
            owner.c.handle.label("owner_handle"),
        )
        .select_from(t.membership)
        .outerjoin(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .outerjoin(owner, owner.c.id == t.agent_profile.c.owner_id)
        .outerjoin(t.human, t.human.c.id == t.membership.c.human_id)
        .where(t.membership.c.id.in_(wanted))
    ).all()
    return {
        r.id: {
            "member_id": r.agent_id or r.human_id,
            "kind": "agent" if r.agent_id else "human",
            "handle": r.agent_handle or r.human_handle,
            **({"name": global_name(r.owner_handle, r.agent_handle)} if r.agent_id else {}),
            "owner_id": r.owner_id if r.agent_id else None,
            # A deleted account shows no handle (§2.9).
            **({"handle": None, "deleted": True} if r.human_deleted_at is not None else {}),
        }
        for r in rows
    }


def observers(conn: Connection, current: list[Any]) -> list[str]:
    """The owners of agent participants who are not participants themselves, member of
    the project or not (§9.2), in the order their first agent joined."""
    agents = [s.agent_id for s in current if s.agent_id]
    if not agents:
        return []
    owners = dict(
        conn.execute(
            select(t.agent_profile.c.id, t.agent_profile.c.owner_id).where(
                t.agent_profile.c.id.in_(agents)
            )
        ).all()
    )
    return observers_of(current, owners)


def observers_of(current: list[Any], owners: dict[str, str]) -> list[str]:
    """`observers` from the owners of the agents already read (agent id → owner id)."""
    agents = [s.agent_id for s in current if s.agent_id]
    inside = {s.human_id for s in current if s.human_id}
    return list(dict.fromkeys(owners[a] for a in agents if owners[a] not in inside))


def access(conn: Connection, conversation_id: str, mine: Any) -> str | None:
    """`participant`, `observer` (a human owning an agent participant), or None: then
    the chat does not exist for the caller (§9.2)."""
    current = stays(conn, conversation_id)
    if any(s.membership_id == mine.id for s in current):
        return "participant"
    if mine.kind == "human" and mine.principal_id in observers(conn, current):
        return "observer"
    if mine.kind == "human" and mine.trust == "owner" and _round_of(conn, conversation_id):
        return "observer"  # every project owner reads a round's thread along (§20.5)
    return None


def _round_of(conn: Connection, conversation_id: str) -> str | None:
    """The jour fixe round whose thread this is, or None."""
    found: str | None = conn.execute(
        select(t.jour_fixe_round.c.id).where(t.jour_fixe_round.c.conversation_id == conversation_id)
    ).scalar()
    return found


def view(conn: Connection, conversation: Any, access_of: str | None = None) -> dict[str, Any]:
    """The conversation view (§9.2); `access` only when it is a caller's answer."""
    current = stays(conn, conversation.id)
    found = people(conn, [s.membership_id for s in current])
    creator = people(conn, [conversation.created_by]) if conversation.created_by else {}
    result: dict[str, Any] = {
        "id": conversation.id,
        "kind": "group",
        "title": conversation.title,
        "created_by": creator[conversation.created_by]["member_id"] if creator else None,
        "created_at": ts(conversation.created_at),
        "participants": [{**found[s.membership_id], "joined_at": ts(s.joined_at)} for s in current],
        "observers": observers(conn, current),
        "closed_at": ts(conversation.closed_at),
        "closed_reason": conversation.closed_reason,
    }
    if conversation.hub_thread:
        result["jour_fixe"] = {"round_id": _round_of(conn, conversation.id)}
    if access_of is not None:
        result["access"] = access_of
    return result


def participation(conn: Connection, stay_row: Any) -> dict[str, Any]:
    """One stay as `DELETE …/participants/{id}` answers it."""
    who = people(conn, [stay_row.membership_id])[stay_row.membership_id]
    return {
        "conversation_id": stay_row.conversation_id,
        "member_id": who["member_id"],
        "joined_at": ts(stay_row.joined_at),
        "left_at": ts(stay_row.left_at),
        "by": stay_row.removed_by if stay_row.left_at else stay_row.added_by,
        "reason": stay_row.reason,
    }


def reason_readers(conn: Connection, conversation_ids: Iterable[str]) -> dict[str, set[str]]:
    """Who reads a redaction's reason in each group chat (§8.5): its current human
    participants while it is open, every former one once it has closed. The redactor
    reads its own in any case; agents and observers never do."""
    wanted = {c for c in conversation_ids if is_group(c)}
    if not wanted:
        return {}
    closed = set(
        conn.execute(
            select(t.conversation.c.id).where(
                t.conversation.c.id.in_(wanted), t.conversation.c.closed_at.is_not(None)
            )
        ).scalars()
    )
    rows = conn.execute(
        select(
            t.conversation_participant.c.conversation_id,
            t.conversation_participant.c.here,
            t.membership.c.human_id,
        )
        .join(t.membership, t.membership.c.id == t.conversation_participant.c.membership_id)
        .where(
            t.conversation_participant.c.conversation_id.in_(wanted),
            t.membership.c.human_id.is_not(None),
        )
    ).all()
    found: dict[str, set[str]] = {c: set() for c in wanted}
    for row in rows:
        if row.conversation_id in closed or row.here:
            found[row.conversation_id].add(row.human_id)
    return found


def audience(current: list[Any]) -> list[str]:
    return [f"member:{principal(s)}" for s in current]


def _highest_seq(conn: Connection, project_id: str) -> int:
    found = conn.execute(
        select(func.max(t.event.c.seq)).where(t.event.c.project_id == project_id)
    ).scalar()
    return int(found or 0)


def _members(conn: Connection, project_id: str, member_ids: Iterable[str]) -> dict[str, Any]:
    """Active memberships by member id; `invalid` (`not_a_member`) for any other id."""
    wanted = list(dict.fromkeys(member_ids))
    rows = (
        conn.execute(
            select(t.membership).where(
                t.membership.c.project_id == project_id,
                t.membership.c.active.is_(True),
                t.membership.c.agent_id.in_(wanted) | t.membership.c.human_id.in_(wanted),
            )
        ).all()
        if wanted
        else []
    )
    found = {principal(r): r for r in rows}
    if any(m not in found for m in wanted):
        raise invalid({"participants": "not_a_member"}, "participants are active members")
    return {m: found[m] for m in wanted}


def refuse_closed_project(project: Any) -> None:
    """A closed project refuses what adds to a room (§9.2)."""
    if project.state in CLOSED_STATES:
        raise ApiError(409, "project_closed", f"the project is {project.state}")


def round_thread() -> ApiError:
    """A round's thread takes messages and members only through the round (§20.5)."""
    return ApiError(
        403,
        "forbidden",
        "a jour fixe round's thread is written through the round",
        {"reason": "round_thread"},
    )


def close_thread(conn: Connection, conversation: Any) -> None:
    """Close a round's thread for good when its exchange closes (§20.5)."""
    lock_project(conn, conversation.project_id)
    conversation = find(conn, conversation.project_id, conversation.id)  # as of the lock
    if conversation.closed_at is not None:
        return
    conn.execute(
        update(t.conversation)
        .where(t.conversation.c.id == conversation.id)
        .values(closed_at=clock.now(), closed_reason="round_closed")
    )
    _announce(
        conn,
        find(conn, conversation.project_id, conversation.id),
        "conversation_updated",
        {"closed": {"closed_reason": "round_closed"}},
        [],
        None,
    )


def refuse_closed(conversation: Any) -> None:
    if conversation.closed_at is not None:
        raise ApiError(
            409,
            "conversation_closed",
            "the chat has closed; start a new one",
            {"closed_reason": conversation.closed_reason},
        )


def _join(
    conn: Connection, conversation_id: str, membership_id: int, by: str | None, after: int
) -> None:
    conn.execute(
        insert(t.conversation_participant).values(
            conversation_id=conversation_id,
            membership_id=membership_id,
            joined_at=clock.now(),
            window_after=after,
            added_by=by,
            here=True,
        )
    )


def _owner_of(conn: Connection, agent_id: str) -> str:
    owner: str = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar_one()
    return owner


def create(
    conn: Connection,
    project: Any,
    creator: Any,
    title: str | None,
    member_ids: list[str],
    actor: Actor | None,
    *,
    hub_thread: bool = False,
) -> str:
    """Create a group chat; returns its id. `creator` is the creating human's membership
    row (a participant whether or not `member_ids` names it), None for the hub's thread
    (§20.5), which skips the cap, `use_direct` and the quota."""
    project = lock_project(conn, project.id)  # its state as of the lock, not the read before
    refuse_closed_project(project)
    names = list(member_ids)
    if creator is not None and principal(creator) not in names:
        names.insert(0, principal(creator))
    members = _members(conn, project.id, names)
    if not hub_thread:
        if len(members) < MIN_PARTICIPANTS:
            raise invalid({"participants": "too_few"}, "a group chat has at least two members")
        if len(members) > MAX_PARTICIPANTS:
            raise invalid({"participants": "too_many"}, "a group chat has at most twelve")
        others = [r for r in members.values() if r.id != creator.id]
        if (
            len(others) == 1
            and others[0].agent_id is not None
            and _owner_of(conn, others[0].agent_id) == creator.human_id
        ):
            raise invalid(
                {"participants": "use_direct"}, "the creator and its own agent: the direct chat"
            )
        open_chats = conn.execute(
            select(func.count()).where(
                t.conversation.c.project_id == project.id,
                t.conversation.c.closed_at.is_(None),
                t.conversation.c.hub_thread.is_(False),
            )
        ).scalar_one()
        if open_chats >= OPEN_PER_PROJECT:
            raise ApiError(
                409,
                "conversation_quota",
                "the project has as many open group chats as it may",
                {"max": OPEN_PER_PROJECT},
            )
    conversation_id = new_id("conversation")
    conn.execute(
        insert(t.conversation).values(
            id=conversation_id,
            project_id=project.id,
            title=title,
            created_by=creator.id if creator is not None else None,
            created_at=clock.now(),
            hub_thread=hub_thread,
        )
    )
    after = _highest_seq(conn, project.id)
    by = principal(creator) if creator is not None else None
    for row in members.values():
        _join(conn, conversation_id, row.id, by, after)
    conversation = find(conn, project.id, conversation_id)
    _announce(conn, conversation, "conversation_created", {}, [], actor)
    return conversation_id


def add(conn: Connection, conversation: Any, member_id: str, by: str, actor: Actor | None) -> bool:
    """Add an active member; False when it is in the chat already (answered as it is)."""
    project = lock_project(conn, conversation.project_id)
    conversation = find(conn, conversation.project_id, conversation.id)  # as of the lock
    refuse_closed(conversation)
    refuse_closed_project(project)
    if conversation.hub_thread:
        raise round_thread()
    row = _members(conn, conversation.project_id, [member_id])[member_id]
    if stay(conn, conversation.id, row.id) is not None:
        return False
    if not conversation.hub_thread and len(stays(conn, conversation.id)) >= MAX_PARTICIPANTS:
        raise invalid({"participants": "too_many"}, "a group chat has at most twelve")
    _join(conn, conversation.id, row.id, by, _highest_seq(conn, conversation.project_id))
    _announce(
        conn,
        conversation,
        "conversation_updated",
        {"participants_added": [{"member_id": member_id, "by": by}]},
        [],
        actor,
    )
    return True


def remove(
    conn: Connection,
    conversation: Any,
    membership_id: int,
    by: str | None,
    reason: str,
    actor: Actor | None,
) -> Any:
    """End the member's stay (`removed`, `left` or `membership_removed`) and close the
    chat when no human is left in it; returns the ended stay. Allowed in a closed
    project, as everything that removes is (§9.2)."""
    lock_project(conn, conversation.project_id)
    conversation = find(conn, conversation.project_id, conversation.id)  # as of the lock
    current = stay(conn, conversation.id, membership_id)
    if current is None:
        return None
    now = clock.now()
    conn.execute(
        update(t.conversation_participant)
        .where(t.conversation_participant.c.id == current.id)
        .values(left_at=now, removed_by=by, reason=reason, here=None)
    )
    left = people(conn, [membership_id])[membership_id]["member_id"]
    changed: dict[str, Any] = {
        "participants_removed": [{"member_id": left, "by": by, "reason": reason}]
    }
    remaining = stays(conn, conversation.id)
    if (
        conversation.closed_at is None
        and not conversation.hub_thread  # a round's thread needs no human (§20.5)
        and not any(s.human_id for s in remaining)
    ):
        conn.execute(
            update(t.conversation)
            .where(t.conversation.c.id == conversation.id)
            .values(closed_at=now, closed_reason="no_human")
        )
        changed["closed"] = {"closed_reason": "no_human"}
    from maity_hub import pins  # pins reads chats through this module

    pins.prune(conn, conversation.project_id)  # who no longer reads it keeps no pin (§9.3)
    _announce(
        conn,
        find(conn, conversation.project_id, conversation.id),
        "conversation_updated",
        changed,
        [f"member:{left}"],
        actor,
    )
    return conn.execute(
        select(t.conversation_participant).where(t.conversation_participant.c.id == current.id)
    ).one()


def rename(conn: Connection, conversation: Any, title: str | None, actor: Actor | None) -> None:
    lock_project(conn, conversation.project_id)
    conversation = find(conn, conversation.project_id, conversation.id)  # as of the lock
    refuse_closed(conversation)
    if title == conversation.title:
        return
    conn.execute(
        update(t.conversation).where(t.conversation.c.id == conversation.id).values(title=title)
    )
    _announce(
        conn,
        find(conn, conversation.project_id, conversation.id),
        "conversation_updated",
        {"title": title},
        [],
        actor,
    )


def membership_removed(
    conn: Connection,
    target: Any,
    actor: Actor | None,
    by: str,
    reason: str = "membership_removed",
) -> None:
    """A member removed from the project leaves every chat (§6.2); an isolated agent too,
    with `reason: membership_isolated`."""
    chats = conn.execute(
        select(t.conversation)
        .join(
            t.conversation_participant,
            t.conversation_participant.c.conversation_id == t.conversation.c.id,
        )
        .where(
            t.conversation_participant.c.membership_id == target.id,
            t.conversation_participant.c.here.is_(True),
        )
        .order_by(t.conversation.c.id)
    ).all()
    for chat in chats:
        remove(conn, chat, target.id, by, reason, actor)


def _announce(
    conn: Connection,
    conversation: Any,
    kind: str,
    changed: dict[str, Any],
    also: list[str],
    actor: Actor | None,
) -> None:
    """`conversation_created`/`_updated` to the participants after the change and whoever
    it removed (§8.2); a conversation's event, so no see-all reaches it."""
    current = stays(conn, conversation.id)
    readers = ["trust:owner"] if conversation.hub_thread else []  # they read along (§20.5)
    emit(
        conn,
        conversation.project_id,
        kind,
        list(dict.fromkeys([*audience(current), *also, *readers])),
        {**view(conn, conversation), "changed": changed},
        actor=actor,
        subject=("conversation", conversation.id),
        conversation_id=conversation.id,
    )
