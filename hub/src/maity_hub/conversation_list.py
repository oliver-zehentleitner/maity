"""The entries of a conversation list (docs/api.md §9.3), built for all conversations of
one or several projects at once: a fixed number of statements however many chats and
projects the caller has, where one entry at a time cost about ten each. The routes'
single-chat views (`routes.conversations`) stay the reference these must equal;
`tests/test_conversation_list.py` compares them.

An entry carries `_activity` and `_project` (the project's id) for the caller to sort, cut
and label by, and drops them before it answers. A direct conversation's id is its agent's,
so one agent in two projects has two chats of one id: every lookup here is keyed by
(project id, chat id).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from itertools import islice
from types import SimpleNamespace
from typing import Any

from sqlalchemy import Connection, String, and_, cast, func, or_, select

from maity_hub import chat_meat_proxy, events, group_chats
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.views import principal_ids, ts

PREVIEW = 200  # code points (§9)
CHUNK = 100  # chats per statement that names each one's window

Key = tuple[str, str]  # (project id, chat id)


# What a participant shows in a list: who it is, and for a human the meat-proxy fields (§9.3).
SHORT = (
    "member_id",
    "kind",
    "handle",
    "name",
    "meat_proxy",
    "meat_proxy_chat",
    "meat_proxy_note",
)


def short(person: dict[str, Any]) -> dict[str, Any]:
    """A participant as the list shows it; an agent with its global name (§6.3)."""
    return {k: person[k] for k in SHORT if k in person}


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


def _after(key: Key, seq: int, mines: dict[str, Any] | None = None) -> Any:
    """Messages of the chat `key` past `seq`, but those in the hidden isolation windows of the
    caller's membership in that project (§6.2), when `mines` names it."""
    clause = and_(
        t.event.c.project_id == key[0], t.event.c.conversation_id == key[1], t.event.c.seq > seq
    )
    visible = events.outside_windows(getattr(mines.get(key[0]), "row", None)) if mines else None
    return clause if visible is None else and_(clause, visible)


def _latest(
    conn: Connection, windows: dict[Key, int], mines: dict[str, Any] | None = None
) -> dict[Key, Any]:
    """Per chat the newest message after its window: the whole row."""
    found: dict[Key, Any] = {}
    for batch in _chunks(list(windows)):
        newest = (
            select(
                t.event.c.project_id,
                t.event.c.conversation_id,
                func.max(t.event.c.seq).label("seq"),
            )
            .where(t.event.c.kind == "message", or_(*(_after(k, windows[k], mines) for k in batch)))
            .group_by(t.event.c.project_id, t.event.c.conversation_id)
            .subquery()
        )
        for row in conn.execute(select(t.event).join(newest, t.event.c.seq == newest.c.seq)):
            found[row.project_id, row.conversation_id] = row
    return found


def _counts(conn: Connection, mines: dict[str, Any], seen: dict[Key, int]) -> dict[Key, int]:
    """Per chat the messages past `seen` that the caller did not write."""
    counted: dict[Key, int] = {}
    for batch in _chunks(list(seen)):
        for project_id, chat, n in conn.execute(
            select(t.event.c.project_id, t.event.c.conversation_id, func.count())
            .where(
                t.event.c.kind == "message",
                or_(
                    *(
                        and_(
                            _after(k, seen[k], mines), t.event.c.actor_membership != mines[k[0]].id
                        )
                        for k in batch
                    )
                ),
            )
            .group_by(t.event.c.project_id, t.event.c.conversation_id)
        ):
            counted[project_id, chat] = int(n)
    return counted


def _marks(conn: Connection, mines: dict[str, Any], chats: Iterable[Key]) -> dict[Key, int]:
    """The caller's read mark in each chat: the seq it has read up to."""
    wanted = list(chats)
    if not wanted:
        return {}
    reader = {m.id: p for p, m in mines.items()}
    found: dict[Key, int] = {}
    for reader_id, chat, last in conn.execute(
        select(
            t.conversation_read.c.reader,
            t.conversation_read.c.conversation_id,
            t.conversation_read.c.last_seq,
        ).where(
            t.conversation_read.c.reader.in_(list(reader)),
            t.conversation_read.c.conversation_id.in_({c for _, c in wanted}),
        )
    ):
        found[reader[reader_id], chat] = int(last or 0)
    return found


def memberships(conn: Connection, human_id: str) -> list[Membership]:
    """The human's active memberships, in every project, archived ones included (§9.3):
    two statements however many projects."""
    members = conn.execute(
        select(t.membership).where(
            t.membership.c.human_id == human_id, t.membership.c.active.is_(True)
        )
    ).all()
    projects = {
        row.id: row
        for row in conn.execute(
            select(t.project).where(t.project.c.id.in_({m.project_id for m in members}))
        )
    }
    return [Membership(projects[m.project_id], m, "human") for m in members]


# --- direct chats --------------------------------------------------------------------------


def owned_agents(conn: Connection, mines: Sequence[Any], caller: Any) -> dict[str, list[str]]:
    """Per project the agents whose direct chats the caller has: its own agents for a
    human, itself for an agent."""
    if caller.kind == "agent":
        return {m.project.id: [caller.agent_id] for m in mines if caller.agent_id}
    owned: dict[str, list[str]] = defaultdict(list)
    for project_id, agent_id in conn.execute(
        select(t.membership.c.project_id, t.membership.c.agent_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(
            t.membership.c.project_id.in_([m.project.id for m in mines]),
            t.membership.c.active.is_(True),
            t.agent_profile.c.owner_id == caller.human_id,
        )
        .order_by(t.agent_profile.c.handle)
    ):
        owned[project_id].append(agent_id)
    return owned


def _direct_chats(
    conn: Connection, by_project: dict[str, Any], owned: dict[str, list[str]]
) -> tuple[list[Key], dict[Key, Any], dict[Key, Any]]:
    """The direct chats of the agents `owned` per project: each needs both parties active
    in the project (§9.1). With them, per chat the agent's membership and its owner's."""
    pairs = [(p, a) for p, agents in owned.items() if p in by_project for a in agents]
    if not pairs:
        return [], {}, {}
    agent_ids = {a for _, a in pairs}
    agents = {
        (row.project_id, row.agent_id): row
        for row in conn.execute(
            select(t.membership).where(
                t.membership.c.project_id.in_(list(by_project)),
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
        (row.project_id, row.human_id): row
        for row in conn.execute(
            select(t.membership).where(
                t.membership.c.project_id.in_(list(by_project)),
                t.membership.c.active.is_(True),
                t.membership.c.human_id.in_(set(owners.values())),
            )
        )
    }
    chats = [(p, a) for p, a in pairs if (p, a) in agents and (p, owners.get(a)) in humans]
    return chats, {k: agents[k] for k in chats}, {k: humans[k[0], owners[k[1]]] for k in chats}


def direct_entries(
    conn: Connection, mines: Sequence[Any], caller: Any, owned: dict[str, list[str]]
) -> list[dict[str, Any]]:
    """The caller's direct conversations with the agents `owned` per project: each needs
    both parties active in the project (§9.1), so an agent whose owner is no member has
    none."""
    by_project = {m.project.id: m for m in mines}
    chats, agents, humans = _direct_chats(conn, by_project, owned)
    if not chats:
        return []
    people = group_chats.people(conn, {agents[k].id for k in chats} | {humans[k].id for k in chats})
    lasts = _latest(conn, dict.fromkeys(chats, 0), by_project)
    senders = principal_ids(conn, (row.actor_membership for row in lasts.values()))
    unread = _direct_unread(conn, by_project, caller, chats)
    entries = []
    for key in chats:
        project_id, agent_id = key
        agent, human = agents[key], humans[key]
        last = lasts.get(key)
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
                "unread": unread.get(key, 0),
                "mentions_unread": 0,
                "last_message": preview(last, senders.get(last.actor_membership) if last else None),
                "_activity": last.at if last is not None else agent.joined_at,
                "_project": project_id,
            }
        )
    chat_meat_proxy.shown(
        conn,
        [(e["_project"], e["id"], e["participants"]) for e in entries],
        caller.human_id if caller.kind == "human" else None,
    )
    return entries


def agent_cursor(conn: Connection, caller: Any, membership_id: int) -> int:
    """How far an agent has read its events: its session's cursor; through a bridge, whose
    session is the bridge's, the furthest of the served agent's own sessions, ended ones too,
    since a new session takes the cursor over (§2.3)."""
    a = t.agent_session.c
    if caller.bridge is None:
        found = conn.execute(select(a.acknowledged_seq).where(a.id == caller.session_id))
    else:
        found = conn.execute(
            select(func.max(a.acknowledged_seq)).where(a.membership_id == membership_id)
        )
    return int(found.scalar() or 0)


def _direct_unread(
    conn: Connection, mines: dict[str, Any], caller: Any, chats: list[Key]
) -> dict[Key, int]:
    """The other party's messages after what this reader has seen, per chat (§9.1): a
    human's chat mark, or the agent's event cursor."""
    if caller.kind == "human":
        marks = _marks(conn, mines, chats)
        seen = {k: marks.get(k, 0) for k in chats}
    else:  # the agent's side is its event cursor
        cursor = agent_cursor(conn, caller, next(iter(mines.values())).id) if mines else 0
        seen = dict.fromkeys(chats, cursor)
    return _counts(conn, mines, seen)


# --- group chats ---------------------------------------------------------------------------


def group_entries(conn: Connection, mines: Sequence[Any], observed: bool) -> list[dict[str, Any]]:
    """The group chats the caller takes part in, and with `observed` those it reads
    along in as an owner (§9.3)."""
    by_project = {m.project.id: m for m in mines}
    by_member = {m.id: m for m in mines}
    pairs: set[Key] = set()
    for member_id, chat in conn.execute(
        select(
            t.conversation_participant.c.membership_id,
            t.conversation_participant.c.conversation_id,
        ).where(
            t.conversation_participant.c.membership_id.in_(list(by_member)),
            t.conversation_participant.c.here.is_(True),
        )
    ):
        pairs.add((by_member[member_id].project.id, chat))
    humans = [m for m in mines if m.kind == "human"]
    if observed and humans:
        for project_id, owner_id, chat in conn.execute(
            select(
                t.membership.c.project_id,
                t.agent_profile.c.owner_id,
                t.conversation_participant.c.conversation_id,
            )
            .select_from(t.conversation_participant)
            .join(t.membership, t.membership.c.id == t.conversation_participant.c.membership_id)
            .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
            .where(
                t.conversation_participant.c.here.is_(True),
                t.agent_profile.c.owner_id.in_({m.principal_id for m in humans}),
                t.membership.c.project_id.in_([m.project.id for m in humans]),
            )
        ):
            if by_project[project_id].principal_id == owner_id:
                pairs.add((project_id, chat))
        # A round's thread is read along by every project owner, or for an owner's series
        # by its `circle_owner`, with or without an agent of theirs in it (§20.5).
        r = t.jour_fixe_round.c
        for project_id, chat, config in conn.execute(
            select(r.project_id, r.conversation_id, r.config).where(
                r.project_id.in_([m.project.id for m in humans]), r.conversation_id.isnot(None)
            )
        ):
            mine, keeper = by_project[project_id], group_chats.keeper_of(config)
            if keeper == mine.principal_id or (keeper is None and mine.trust == "owner"):
                pairs.add((project_id, chat))
    if not pairs:
        return []
    groups = {
        (row.project_id, row.id): row
        for row in conn.execute(
            select(t.conversation).where(
                t.conversation.c.project_id.in_(list(by_project)),
                t.conversation.c.id.in_({c for _, c in pairs}),
            )
        )
    }
    pairs &= groups.keys()
    if not pairs:
        return []
    stays: dict[str, list[Any]] = defaultdict(list)
    for row in conn.execute(
        select(t.conversation_participant, t.membership.c.agent_id, t.membership.c.human_id)
        .join(t.membership, t.membership.c.id == t.conversation_participant.c.membership_id)
        .where(
            t.conversation_participant.c.conversation_id.in_({c for _, c in pairs}),
            t.conversation_participant.c.here.is_(True),
        )
        .order_by(t.conversation_participant.c.joined_at, t.conversation_participant.c.id)
    ):
        stays[row.conversation_id].append(row)
    agent_ids = {s.agent_id for rows in stays.values() for s in rows if s.agent_id}
    owners_of = (
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
    if any(m.kind == "human" and m.trust == "owner" for m in mines):
        rounds = set(
            conn.execute(
                select(t.jour_fixe_round.c.conversation_id).where(
                    t.jour_fixe_round.c.conversation_id.in_({c for _, c in pairs})
                )
            ).scalars()
        )
    keepers = group_chats.round_keepers(conn, {c for _, c in pairs})
    found = _access(by_project, pairs, stays, owners_of, rounds, keepers)
    if not found:
        return []
    people = group_chats.people(conn, {s.membership_id for _, chat in found for s in stays[chat]})
    carried = group_chats.carriers(
        conn, {s.membership_id for _, chat in found for s in stays[chat]}
    )
    windows = _windows(conn, by_project, found, stays)
    lasts = _latest(conn, windows, by_project)
    senders = principal_ids(conn, (row.actor_membership for row in lasts.values()))
    unread, mentioned = _unread(
        conn, by_project, {k: w for k, w in windows.items() if found[k] == "participant"}
    )
    entries = []
    for key, access in found.items():
        project_id, chat = key
        group, last = groups[key], lasts.get(key)
        current = stays[chat]
        entries.append(
            {
                "id": chat,
                "kind": "group",
                "title": group.title,
                "participants": [short(people[s.membership_id]) for s in current],
                "observers": group_chats.shown_observers(
                    current,
                    group_chats.thread_observers(current, owners_of, keepers.get(chat)),
                    carried,
                ),
                "access": access,
                "closed_at": ts(group.closed_at),
                "last_message_at": ts(last.at) if last is not None else None,
                "unread": unread.get(key, 0) if access == "participant" else None,
                "mentions_unread": mentioned.get(key, 0) if access == "participant" else None,
                "last_message": preview(last, senders.get(last.actor_membership) if last else None),
                "_activity": last.at if last is not None else group.created_at,
                "_project": project_id,
            }
        )
    viewer = next((m.principal_id for m in mines if m.kind == "human"), None)
    chat_meat_proxy.shown(
        conn, [(e["_project"], e["id"], e["participants"]) for e in entries], viewer
    )
    return entries


def _access(
    mines: dict[str, Any],
    pairs: set[Key],
    stays: dict[str, list[Any]],
    owners: dict[str, str],
    rounds: set[str],
    keepers: dict[str, str],
) -> dict[Key, str]:
    """`group_chats.access` of each chat, from the rows already read: the chats that
    exist for the caller, with how it sees them."""
    found: dict[Key, str] = {}
    for key in sorted(pairs):
        mine, current = mines[key[0]], stays[key[1]]
        keeper = keepers.get(key[1])
        if any(s.membership_id == mine.id for s in current):
            found[key] = "participant"
        elif keeper is not None:  # an owner's round: only its `circle_owner` reads along
            if mine.kind == "human" and mine.principal_id == keeper:
                found[key] = "observer"
        elif mine.kind == "human" and mine.principal_id in group_chats.observers_of(
            current, owners
        ):
            found[key] = "observer"
        elif mine.kind == "human" and mine.trust == "owner" and key[1] in rounds:
            found[key] = "observer"  # every project owner reads a round's thread along (§20.5)
    return found


def _windows(
    conn: Connection, mines: dict[str, Any], found: dict[Key, str], stays: dict[str, list[Any]]
) -> dict[Key, int]:
    """The seq after which the caller's window starts in each chat (§9.2): its latest
    join, for an observer the earliest join of its agents in the chat."""
    owned: set[str] = set()
    if "observer" in found.values():
        owned = set(
            conn.execute(
                select(t.agent_profile.c.id).where(
                    t.agent_profile.c.owner_id.in_({m.principal_id for m in mines.values()})
                )
            ).scalars()
        )
    windows = {}
    for key, access in found.items():
        current = stays[key[1]]
        if access == "participant":
            mine = mines[key[0]]
            windows[key] = int(next(s.window_after for s in current if s.membership_id == mine.id))
        else:
            windows[key] = group_chats.observer_window(current, owned)
    return windows


def _seen(conn: Connection, mines: dict[str, Any], windows: dict[Key, int]) -> dict[Key, int]:
    """Per chat the seq the caller counts from: its read mark, or its window if later."""
    marks = _marks(conn, mines, windows)
    return {k: max(window, marks.get(k, 0)) for k, window in windows.items()}


def _unread(
    conn: Connection, mines: dict[str, Any], windows: dict[Key, int]
) -> tuple[dict[Key, int], dict[Key, int]]:
    """Per chat the caller takes part in: the other members' messages after its read mark
    and its window, and how many of them mention it."""
    if not windows:
        return {}, {}
    seen = _seen(conn, mines, windows)
    unread = _counts(conn, mines, seen)
    mentioned: dict[Key, int] = {}
    for batch in _chunks(list(seen)):
        for project_id, chat, redacted, payload in conn.execute(
            select(
                t.event.c.project_id,
                t.event.c.conversation_id,
                t.event.c.redacted,
                t.event.c.payload,
            ).where(
                t.event.c.kind == "message",
                or_(
                    *(
                        and_(
                            _after(k, seen[k], mines), t.event.c.actor_membership != mines[k[0]].id
                        )
                        for k in batch
                    )
                ),
                _may_name({mines[k[0]].principal_id for k in batch}),
            )
        ):
            principal = mines[project_id].principal_id
            if not redacted and any(
                m.get("member_id") == principal for m in (payload or {}).get("mentions") or []
            ):
                mentioned[project_id, chat] = mentioned.get((project_id, chat), 0) + 1
    return unread, mentioned


def unread_chats(conn: Connection, mines: Sequence[Any], human_id: str) -> dict[str, int]:
    """Per project id the unread messages of the human's chats: the direct chats with its
    agents and the group chats it takes part in, an observer's reading along counting
    nothing. The number §18.2 gives as `counts.chat` and §9.3 as `totals.unread`: the
    bell and the list both rest on it, and `tests/test_me_conversations.py` holds them
    equal."""
    by_project = {m.project.id: m for m in mines}
    if not by_project:
        return {}
    caller = SimpleNamespace(kind="human", human_id=human_id, agent_id=None, session_id=None)
    chats, _, _ = _direct_chats(conn, by_project, owned_agents(conn, mines, caller))
    unread = _direct_unread(conn, by_project, caller, chats) if chats else {}
    windows = _participations(conn, mines)
    if windows:
        unread |= _counts(conn, by_project, _seen(conn, by_project, windows))
    totals: dict[str, int] = dict.fromkeys(by_project, 0)
    for (project_id, _), n in unread.items():
        totals[project_id] += n
    return totals


def _participations(conn: Connection, mines: Sequence[Any]) -> dict[Key, int]:
    """The group chats the caller takes part in, with the seq its window starts after."""
    return {
        (row.project_id, row.conversation_id): int(row.window_after)
        for row in conn.execute(
            select(
                t.membership.c.project_id,
                t.conversation_participant.c.conversation_id,
                t.conversation_participant.c.window_after,
            )
            .select_from(t.conversation_participant)
            .join(t.membership, t.membership.c.id == t.conversation_participant.c.membership_id)
            .join(
                t.conversation,
                and_(
                    t.conversation.c.id == t.conversation_participant.c.conversation_id,
                    t.conversation.c.project_id == t.membership.c.project_id,
                ),
            )
            .where(
                t.conversation_participant.c.membership_id.in_([m.id for m in mines]),
                t.conversation_participant.c.here.is_(True),
            )
        )
    }


def _may_name(principals: set[str]) -> Any:
    """A payload whose text has a `member_id` and one of the principals' ids: a superset of
    the messages that mention one (the exact test is on the rows read). The id alone would
    not do, a chat message names its addressee in `to`."""
    text = cast(t.event.c.payload, String)
    return and_(
        text.contains("member_id", autoescape=True),
        or_(*(text.contains(p, autoescape=True) for p in sorted(principals))),
    )


__all__ = [
    "direct_entries",
    "group_entries",
    "memberships",
    "owned_agents",
    "preview",
    "short",
    "unread_chats",
]
