"""Who of a group chat's agents is admitted and who waits (docs/api.md §9.6, "Waiting").

A human and the agents that human owns are one side. An agent is admitted to a chat when, for
every participant on another side, its owner's allow entries cover the pair and no deny entry of
its owner names that participant, the participant's side or the chat's project. A bridge that
serves a participant across owners (§2.3) counts as a participant on its owner's side.

An agent that is not admitted waits: its stay holds the human of each side it waits for
(`waiting_for`), it is in no audience of the chat's events (`waiting:<id>` instead of
`member:<id>`, which its owner reads along by), reads and posts nothing and is woken by nothing.
An agent a deny entry stops leaves the chat with `reason: "denied_participant"`.

`settle` is the one place that writes the state: every change of who is in a chat, and every
change of an owner's entries, ends in it. The request to the owner (§9.6, "The request") is a
later part of the same card.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Connection, func, insert, select, update

from maity_hub import chat_access, clock
from maity_hub import tables as t
from maity_hub.errors import ApiError
from maity_hub.ids import new_id

DENIED = "denied_participant"


@dataclass(frozen=True)
class Party:
    """Someone a chat's agent meets: a participant, or a bridge serving one across owners."""

    member_id: str
    kind: str  # human, agent
    side: str  # the human, or the agent's owner


@dataclass
class _Entries:
    """One owner's entries, with the agents each names on each side."""

    rows: list[Any] = field(default_factory=list)
    own: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    theirs: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))


@dataclass(frozen=True)
class Verdict:
    """`waiting_for` as stored (None: the agent's side is the only one), and whether a deny
    entry stops the agent."""

    waiting_for: list[str] | None
    denied: bool


def owners_of(conn: Connection, agent_ids: Iterable[str]) -> dict[str, str]:
    wanted = {a for a in agent_ids if a}
    if not wanted:
        return {}
    return dict(
        conn.execute(
            select(t.agent_profile.c.id, t.agent_profile.c.owner_id).where(
                t.agent_profile.c.id.in_(wanted)
            )
        ).all()
    )


def parties(conn: Connection, current: list[Any]) -> list[Party]:
    """The chat's participants and the bridges serving them across owners, each once."""
    from maity_hub import group_chats  # group_chats calls this module

    carried = group_chats.carriers(conn, [s.membership_id for s in current])
    bridges = [b for s in current for b in carried.get(s.membership_id, [])]
    owners = owners_of(conn, [*(s.agent_id for s in current), *bridges])
    found: dict[str, Party] = {}
    for s in current:
        if s.agent_id:
            found[s.agent_id] = Party(s.agent_id, "agent", owners[s.agent_id])
        else:
            found[s.human_id] = Party(s.human_id, "human", s.human_id)
    for bridge in bridges:
        found.setdefault(bridge, Party(bridge, "agent", owners[bridge]))
    return list(found.values())


def _entries(conn: Connection, owners: Iterable[str]) -> dict[str, _Entries]:
    wanted = set(owners)
    found: dict[str, _Entries] = defaultdict(_Entries)
    if not wanted:
        return found
    c, g = t.chat_access.c, t.chat_access_agent.c
    rows = conn.execute(select(t.chat_access).where(c.human_id.in_(wanted))).all()
    by_id = {r.id: r.human_id for r in rows}
    for r in rows:
        found[r.human_id].rows.append(r)
    if by_id:
        for entry_id, side, agent_id in conn.execute(
            select(g.entry_id, g.side, g.agent_id).where(g.entry_id.in_(list(by_id)))
        ):
            entries = found[by_id[entry_id]]
            (entries.own if side == chat_access.OWN else entries.theirs)[entry_id].add(agent_id)
    return found


def _names_agent(entry: Any, entries: _Entries, agent_id: str) -> bool:
    return bool(entry.agents_all) or agent_id in entries.own[entry.id]


def _allows(entry: Any, entries: _Entries, party: Party, project_id: str, now: Any) -> bool:
    if entry.kind != chat_access.ALLOW:
        return False
    if entry.until is not None and entry.until <= now:
        return False  # an allow entry whose `until` has passed covers nothing
    if entry.project_id is not None:
        return bool(entry.project_id == project_id)
    if entry.owner_id != party.side:
        return False
    if party.kind == "human":
        return bool(entry.their_human)
    if entry.their_agents == chat_access.ALL:
        return True
    return entry.their_agents == chat_access.LIST and party.member_id in entries.theirs[entry.id]


def _denies(entry: Any, party: Party, project_id: str) -> bool:
    if entry.kind != chat_access.DENY:
        return False
    return bool(
        entry.owner_id == party.side
        or (entry.subject_human_id is not None and entry.subject_human_id == party.member_id)
        or (entry.subject_agent_id is not None and entry.subject_agent_id == party.member_id)
        or entry.project_id == project_id
    )


def judge(
    agent_id: str,
    owner: str,
    met: list[Party],
    entries: _Entries,
    project_id: str,
) -> Verdict:
    """The verdict on one agent of `owner` meeting `met` in a chat of `project_id`."""
    others = [p for p in met if p.side != owner]
    if not others:
        return Verdict(None, False)
    now = clock.now()
    mine = [e for e in entries.rows if _names_agent(e, entries, agent_id)]
    waiting: list[str] = []
    for party in others:
        if any(_denies(e, party, project_id) for e in mine):
            return Verdict(None, True)
        if not any(_allows(e, entries, party, project_id, now) for e in mine):
            waiting.append(party.side)
    return Verdict(sorted(set(waiting)), False)


def verdicts(conn: Connection, conversation: Any, current: list[Any]) -> dict[int, Verdict]:
    """The verdict on each agent participant of the chat, by membership id."""
    met = parties(conn, current)
    owners = {p.member_id: p.side for p in met if p.kind == "agent"}
    agents = [s for s in current if s.agent_id]
    entries = _entries(conn, {owners[s.agent_id] for s in agents})
    project_id = conversation.project_id
    return {
        s.membership_id: judge(
            s.agent_id, owners[s.agent_id], met, entries[owners[s.agent_id]], project_id
        )
        for s in agents
    }


def refuse_denied(conn: Connection, conversation: Any, current: list[Any], agent_id: str) -> None:
    """`forbidden` (`chat_denied`) when a deny entry of the agent's owner names someone in the
    chat or its project: the caller learns that the owner said no, not to whom (§9.6)."""
    met = parties(conn, current)
    owner = owners_of(conn, [agent_id])[agent_id]
    if judge(agent_id, owner, met, _entries(conn, [owner])[owner], conversation.project_id).denied:
        raise ApiError(
            403,
            "forbidden",
            "the agent's owner does not let it chat with someone here",
            {"reason": "chat_denied"},
        )


def owner_yes(conn: Connection, conversation: Any, current: list[Any], agent_id: str) -> None:
    """The owner's add is the yes (§9.6): an allow entry for the agent and each other side in
    the chat now, `their_agents` that side's agents in it and `their_human` whether its human
    is, with no `duration`."""
    met = parties(conn, current)
    owner = owners_of(conn, [agent_id])[agent_id]
    sides: dict[str, tuple[list[str], bool]] = {}
    for party in met:
        if party.side == owner:
            continue
        agents, human = sides.get(party.side, ([], False))
        if party.kind == "agent":
            agents = [*agents, party.member_id]
        else:
            human = True
        sides[party.side] = (agents, human)
    now = clock.now()
    for side, (agents, human) in sorted(sides.items()):
        chat_access._room(conn, owner)
        entry_id = new_id("chat_access")
        conn.execute(
            insert(t.chat_access).values(
                id=entry_id,
                human_id=owner,
                kind=chat_access.ALLOW,
                agents_all=False,
                owner_id=side,
                their_agents=chat_access.LIST if agents else chat_access.NONE,
                their_human=human,
                by=owner,
                since=now,
            )
        )
        chat_access._write_agents(conn, entry_id, [agent_id], agents)


def _highest_seq(conn: Connection, project_id: str) -> int:
    found = conn.execute(
        select(func.max(t.event.c.seq)).where(t.event.c.project_id == project_id)
    ).scalar()
    return int(found or 0)


def settle(
    conn: Connection,
    conversation: Any,
    by: str | None,
    *,
    fresh: Iterable[int] = (),
) -> tuple[list[dict[str, Any]], list[int]]:
    """Write who of the chat's agents waits, under the project lock the caller holds: the
    `participants_changed` items of the stays whose `waiting_for` changed (not of the `fresh`
    ones, which the change that brought them in names), and the membership ids a deny entry
    stops, which the caller removes. An agent admitted now reads from here on: its window
    starts at the admission (§9.6)."""
    from maity_hub import group_chats

    current = group_chats.stays(conn, conversation.id)
    if conversation.closed_at is not None:
        return [], []
    judged = verdicts(conn, conversation, current)
    changed: list[dict[str, Any]] = []
    denied: list[int] = []
    fresh = set(fresh)
    top: int | None = None
    for s in current:
        verdict = judged.get(s.membership_id)
        if verdict is None:
            continue
        if verdict.denied:
            denied.append(s.membership_id)
            continue
        wanted = verdict.waiting_for
        if wanted == s.waiting_for:
            continue
        values: dict[str, Any] = {"waiting_for": wanted, "waiting": bool(wanted)}
        if s.waiting and not wanted:
            top = _highest_seq(conn, conversation.project_id) if top is None else top
            values["window_after"] = top
        conn.execute(
            update(t.conversation_participant)
            .where(t.conversation_participant.c.id == s.id)
            .values(values)
        )
        if s.membership_id not in fresh and (s.waiting_for is not None or wanted):
            changed.append({"member_id": s.agent_id, "by": by, "waiting_for": wanted})
    return changed, denied


def waiting(conn: Connection, conversation_id: str, membership_id: int) -> bool:
    """Whether the member takes part in the chat as waiting now."""
    found = conn.execute(
        select(t.conversation_participant.c.waiting).where(
            t.conversation_participant.c.conversation_id == conversation_id,
            t.conversation_participant.c.membership_id == membership_id,
            t.conversation_participant.c.here.is_(True),
        )
    ).scalar()
    return bool(found)


def refuse_waiting() -> ApiError:
    return ApiError(
        403,
        "forbidden",
        "the agent waits for its owner's yes before it takes part in this chat",
        {"reason": "waiting"},
    )


def chats_of_owner(conn: Connection, owner: str) -> list[Any]:
    """The open group chats any agent of `owner` is in, by project and id: the chats a change
    of the owner's entries may admit an agent to or let it wait in."""
    p, m, a, c = (
        t.conversation_participant.c,
        t.membership.c,
        t.agent_profile.c,
        t.conversation.c,
    )
    return list(
        conn.execute(
            select(t.conversation)
            .where(
                c.closed_at.is_(None),
                c.id.in_(
                    select(p.conversation_id)
                    .join(t.membership, m.id == p.membership_id)
                    .join(t.agent_profile, a.id == m.agent_id)
                    .where(p.here.is_(True), a.owner_id == owner)
                ),
            )
            .order_by(c.project_id, c.id)
        ).all()
    )


def served(conn: Connection, membership_id: int) -> None:
    """After a connection across owners that serves this member starts or ends (§2.3): the
    bridge counts on its owner's side in the member's open chats, so settle them again."""
    from maity_hub import group_chats

    p, c = t.conversation_participant.c, t.conversation.c
    chats = conn.execute(
        select(t.conversation)
        .join(t.conversation_participant, p.conversation_id == c.id)
        .where(p.membership_id == membership_id, p.here.is_(True), c.closed_at.is_(None))
        .order_by(c.id)
    ).all()
    for chat in chats:
        group_chats.resettle(conn, chat, None)


def recheck(conn: Connection, owner: str) -> None:
    """After a change of the owner's entries (§9.6): settle each open chat of the owner's
    agents and announce what changed; an agent a new deny entry stops leaves."""
    from maity_hub import group_chats

    for chat in chats_of_owner(conn, owner):
        group_chats.resettle(conn, chat, owner)


def lapse(conn: Connection) -> int:
    """The worker's pass: the allow entries whose `until` passed since the last pass let the
    agents they admitted wait again in each open chat that needs them. Returns how many."""
    c = t.chat_access.c
    now = clock.now()
    rows = conn.execute(
        select(c.id, c.human_id).where(
            c.kind == chat_access.ALLOW, c.lapsed_at.is_(None), c.until.is_not(None), c.until <= now
        )
    ).all()
    if not rows:
        return 0
    conn.execute(update(t.chat_access).where(c.id.in_([r.id for r in rows])).values(lapsed_at=now))
    from maity_hub import group_chats

    for owner in sorted({r.human_id for r in rows}):
        for chat in chats_of_owner(conn, owner):
            group_chats.resettle(conn, chat, None)
    return len(rows)


def sweep(engine: Any) -> int:
    """`lapse` in a transaction of its own, for the worker's minute pass."""
    from maity_hub import events

    with events.transaction(engine) as conn:
        return lapse(conn)


def sides_of(conn: Connection, current: list[Any]) -> list[str]:
    """The sides of a chat now: the human of each, in the order first met."""
    return list(dict.fromkeys(p.side for p in parties(conn, current)))


def boundary(conn: Connection, project_id: str, author: str, body: str, sides: list[str]) -> None:
    """Where a chat text may come to cross the owner boundary (§9.6): every path that stores a
    `chat` message calls this after validating it and before storing it, whatever the sides
    at that moment. The check of such texts for dangerous content is to sit here (a later
    card); today nothing is checked and every message passes."""
    del conn, project_id, author, body, sides
