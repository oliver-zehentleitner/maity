"""The request to chat with an owner's agents (docs/api.md §9.6, "The request").

For each owner and each side the owner's agents wait for (`chat_gate.settle`) or are held for
(a free work message, `chat_gate.hold`), the hub keeps one personal `consent` request to the
owner open, `filed_by: hub`, with no project. Its proposal names the side and the messages held
since the owner's last answer for that side; who waits is read from the chats when it is needed,
so the request never holds a stale list of chats.

`sync` is the one place that files, updates and withdraws it. Every path that changes who waits
ends in it: `chat_gate.settle` for the owners of the agents that waited or wait, `group_chats`
for a waiting agent that leaves or a chat that closes, the answer below, and the worker's minute
pass (`sweep`) for anything that ends a chat or a project without passing those. A batch of
changes of one owner (`deferred`) syncs once at its end, so a request is not filed and then
withdrawn again within one transaction.

The owner's human row is locked before the owner's requests are read (`chat_access._lock`), so
two transactions do not file two requests for one pair. A chat change holds its project's lock
before it, an entry change the human's row before its projects': the two orders can meet, and
the database then rolls one back as a transient deadlock, which is run again (`db.TRANSIENT`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import chat_access, clock, namespace, proposals
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.ids import new_id
from maity_hub.notifications import records

KIND = "chat_access"
DECLINED = "declined"
DURATION = {"allow_hour": "hour", "allow_day": "day", "allow_week": "week", "allow_always": None}
OPTIONS = [
    {"id": "allow_hour", "label": "Allow for an hour", "detail": None},
    {"id": "allow_day", "label": "Allow for a day", "detail": None},
    {"id": "allow_week", "label": "Allow for a week", "detail": None},
    {"id": "allow_always", "label": "Always allow", "detail": None},
    {"id": "no", "label": "No", "detail": "the waiting agents leave those chats"},
    {"id": "block", "label": "Block", "detail": "a deny entry for that side"},
]
_DEFERRED = "chat_request.deferred"


# Who waits ------------------------------------------------------------------------------------


def _waiting(conn: Connection, owner: str) -> dict[str, dict[str, list[Any]]]:
    """Per side, per agent of `owner`, the agent's open chats where it waits for that side."""
    p, m, a, c = (
        t.conversation_participant.c,
        t.membership.c,
        t.agent_profile.c,
        t.conversation.c,
    )
    rows = conn.execute(
        select(
            p.conversation_id,
            p.waiting_for,
            p.added_by,
            m.agent_id,
            c.project_id,
            c.title,
        )
        .select_from(
            t.conversation_participant.join(t.membership, m.id == p.membership_id)
            .join(t.agent_profile, a.id == m.agent_id)
            .join(t.conversation, c.id == p.conversation_id)
        )
        .where(
            p.here.is_(True),
            p.waiting.is_(True),
            a.owner_id == owner,
            c.closed_at.is_(None),
        )
        .order_by(m.agent_id, c.project_id, c.id)
    ).all()
    found: dict[str, dict[str, list[Any]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        for side in row.waiting_for or []:
            found[side][row.agent_id].append(row)
    return found


def _open(conn: Connection, owner: str) -> dict[str, Any]:
    """The owner's open requests of this kind, by side."""
    r = t.request.c
    rows = conn.execute(
        select(t.request).where(
            r.to_human == owner,
            r.personal.is_(True),
            r.status == "open",
            r.filed_by == "hub",
            r.proposal.is_not(None),
        )
    ).all()
    return {
        (row.proposal or {})["side"]: row
        for row in rows
        if (row.proposal or {}).get("kind") == KIND
    }


def _held_agents(proposal: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(a for h in proposal.get("held", []) for a in h["agents"]))


def agents_of(conn: Connection, request: Any) -> list[str]:
    """The request's agents now: those waiting for its side, then those held for it."""
    side = request.proposal["side"]
    waiting = list(_waiting(conn, request.to_human).get(side, {}))
    return list(dict.fromkeys([*waiting, *_held_agents(request.proposal)]))


# Filing, updating, withdrawing ------------------------------------------------------------------


def _handles(conn: Connection, ids: set[str]) -> dict[str, str]:
    wanted = sorted(i for i in ids if i)
    if not wanted:
        return {}
    a, h = t.agent_profile.c, t.human.c
    found: dict[str, str] = dict(conn.execute(select(a.id, a.handle).where(a.id.in_(wanted))).all())
    rest = [i for i in wanted if i not in found]
    if rest:
        found.update(conn.execute(select(h.id, h.handle).where(h.id.in_(rest))).all())
    return {i: str(found.get(i) or i) for i in wanted}


def _title(conn: Connection, side: str) -> str:
    handle = _handles(conn, {side})[side]
    return f"{handle} and their agents want to chat with your agents"[: t.TITLE]


def _people_in(conn: Connection, conversation_id: str, side: str) -> tuple[list[str], bool]:
    """The side's agents in the chat now, and whether its human is."""
    from maity_hub import chat_gate, group_chats

    current = group_chats.stays(conn, conversation_id)
    sides = chat_gate.owners_of(conn, [s.agent_id for s in current if s.agent_id])
    agents = [s.agent_id for s in current if s.agent_id and sides.get(s.agent_id) == side]
    return agents, any(s.human_id == side for s in current if not s.agent_id)


def _summary(conn: Connection, owner: str, side: str, proposal: dict[str, Any]) -> str:
    """What the owner decides on: per agent its chats and their projects, who added it, who of
    the side is there, and the free work messages held for it, never their text."""
    waiting = _waiting(conn, owner).get(side, {})
    held = proposal.get("held", [])
    agents = list(dict.fromkeys([*waiting, *_held_agents(proposal)]))
    named: set[str] = {side, *agents}
    rooms: dict[str, tuple[list[str], bool]] = {}
    for stays in waiting.values():
        for s in stays:
            rooms[s.conversation_id] = _people_in(conn, s.conversation_id, side)
            named.update(rooms[s.conversation_id][0])
            named.add(s.added_by or "")
    for h in held:
        named.add(h["author"])
    names = _handles(conn, named)
    projects: dict[str, str] = {}
    lines = [f"**{names[side]}** and their agents want to chat with your agents.", ""]
    for agent in agents:
        lines.append(f"- **{names[agent]}**")
        for s in waiting.get(agent, []):
            if s.project_id not in projects:
                row = conn.execute(select(t.project).where(t.project.c.id == s.project_id)).one()
                projects[s.project_id] = namespace.full_name(conn, row)
            theirs, human = rooms[s.conversation_id]
            there = [names[a] for a in theirs] + ([names[side]] if human else [])
            added = names.get(s.added_by or "", "the hub") if s.added_by else "the hub"
            title = f'"{s.title}"' if s.title else "a chat"
            line = f"  - waits in {title} ({s.conversation_id}) in {projects[s.project_id]},"
            line += f" added by {added}; there: {', '.join(there) or 'nobody'}"
            if human:
                line += f" (admitted only when {names[side]} is ticked too)"
            lines.append(line)
        for h in held:
            if agent in h["agents"]:
                lines.append(
                    f"  - held for it: message {h['seq']} ({h['type']}) from {names[h['author']]}"
                )
    return "\n".join(lines)


def _file(conn: Connection, owner: str, side: str, held: list[dict[str, Any]]) -> Any:
    proposal = {"kind": KIND, "side": side, "held": held}
    request_id = new_id("request")
    conn.execute(
        insert(t.request).values(
            {
                "id": request_id,
                "project_id": None,
                "org_id": None,
                "class": "consent",
                "title": _title(conn, side),
                "summary": _summary(conn, owner, side, proposal),
                "options": OPTIONS,
                "priority": "normal",
                "to_kind": "human",
                "to_human": owner,
                "personal": True,
                "filed_by": "hub",
                "asked_by": None,
                "asked_by_human": None,
                "asked_session_id": None,
                "while_open": "wait",
                "status": "open",
                "humans_only": True,
                "proposal": proposal,
                "created_at": clock.now(),
            }
        )
    )
    row = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
    records.personal_request(conn, row)
    return row


def _refresh(conn: Connection, row: Any, proposal: dict[str, Any]) -> None:
    summary = _summary(conn, row.to_human, proposal["side"], proposal)
    if summary == row.summary and proposal == row.proposal:
        return
    conn.execute(
        update(t.request)
        .where(t.request.c.id == row.id)
        .values(summary=summary, proposal=proposal, title=_title(conn, proposal["side"]))
    )


def _withdraw(conn: Connection, row: Any) -> None:
    """The hub's withdrawal (reason `withdrawn`): nothing waits for the side any more and no
    message is held for it. Its settlement applies nothing (`settle`): nothing is left to."""
    from maity_hub.routes.requests import close_request

    close_request(conn, row.id, "withdrawn", None, reason="withdrawn")


@contextmanager
def deferred(conn: Connection) -> Iterator[None]:
    """Sync each owner the changes inside touch once, at the end (the outermost one)."""
    outer = _DEFERRED not in conn.info
    if outer:
        conn.info[_DEFERRED] = set()
    try:
        yield
    except BaseException:
        if outer:
            conn.info.pop(_DEFERRED, None)
        raise
    if outer:
        owners: set[str] = conn.info.pop(_DEFERRED)
        for owner in sorted(owners):
            sync(conn, owner)


def sync(conn: Connection, owner: str) -> None:
    """File, update or withdraw the owner's requests so that each side the owner's agents wait
    for or are held for has one open request, and no other is open."""
    pending: set[str] | None = conn.info.get(_DEFERRED)
    if pending is not None:
        pending.add(owner)
        return
    chat_access._lock(conn, owner)
    waiting = _waiting(conn, owner)
    open_ = _open(conn, owner)
    for side in sorted(set(waiting) | set(open_)):
        row = open_.get(side)
        held = (row.proposal or {}).get("held", []) if row is not None else []
        if not waiting.get(side) and not held:
            if row is not None:
                _withdraw(conn, row)
            continue
        if row is None:
            _file(conn, owner, side, [])
        else:
            _refresh(conn, row, {**row.proposal, "held": held})


def sync_agents(conn: Connection, agent_ids: list[str]) -> None:
    """`sync` for the owner of each agent."""
    from maity_hub import chat_gate

    for owner in sorted(set(chat_gate.owners_of(conn, agent_ids).values())):
        sync(conn, owner)


def note_held(
    conn: Connection,
    project_id: str,
    seq: int,
    kind: str,
    author: tuple[str, str],
    side: str,
    agents: list[str],
) -> None:
    """A free work message from `side` held for `agents` (§9.6): it joins the open request of
    each agent's owner for that side, or a new one. A message an owner's deny entry stops is
    not asked about: the owner said no already. `author` is `(id, "agent" | "human")`."""
    from maity_hub import chat_gate

    owners = chat_gate.owners_of(conn, agents)
    by_owner: dict[str, list[str]] = defaultdict(list)
    for agent in agents:
        by_owner[owners[agent]].append(agent)
    for owner, theirs in sorted(by_owner.items()):
        entries = chat_gate._entries(conn, [owner])[owner]
        party = chat_gate.Party(author[0], author[1], side)
        asked = [
            a for a in theirs if not chat_gate.judge(a, owner, [party], entries, project_id).denied
        ]
        if not asked:
            continue
        chat_access._lock(conn, owner)
        held = {
            "seq": seq,
            "project_id": project_id,
            "type": kind,
            "author": author[0],
            "author_kind": author[1],
            "agents": asked,
        }
        row = _open(conn, owner).get(side)
        if row is None:
            _file(conn, owner, side, [held])
        else:
            _refresh(conn, row, {**row.proposal, "held": [*row.proposal.get("held", []), held]})


def sweep_owners(conn: Connection) -> None:
    """The worker's pass: sync the owner of every open request of this kind, for what ended a
    chat or a project without passing a sync (a project deleted, a round's thread closed)."""
    r = t.request.c
    owners = conn.execute(
        select(r.to_human, r.proposal).where(
            r.personal.is_(True),
            r.status == "open",
            r.filed_by == "hub",
            r.proposal.is_not(None),
            r.to_human.is_not(None),
        )
    ).all()
    for owner in sorted({o for o, p in owners if (p or {}).get("kind") == KIND}):
        sync(conn, owner)


# The answer -------------------------------------------------------------------------------------


def check_answer(row: Any, reply_id: str | None, body: dict[str, Any] | None) -> None:
    """`chat_access` beside an answer: on this kind's request only, with an allow reply."""
    if body is None:
        return
    if (row.proposal or {}).get("kind") != KIND:
        raise invalid({"chat_access": "not_a_chat_request"})
    if reply_id not in DURATION:
        raise invalid({"chat_access": "allow_only"}, "chat_access goes with an allow reply")


def _their_agents(conn: Connection, request: Any, agent: str) -> list[str]:
    """The side's agents in the chats where `agent` waits for it, and the side's agents whose
    messages are held for it."""
    side = request.proposal["side"]
    found: list[str] = []
    for s in _waiting(conn, request.to_human).get(side, {}).get(agent, []):
        found.extend(_people_in(conn, s.conversation_id, side)[0])
    for h in request.proposal.get("held", []):
        if agent in h["agents"] and h["author_kind"] == "agent":
            found.append(h["author"])
    return list(dict.fromkeys(found))


def _allow(conn: Connection, request: Any, reply_id: str, body: dict[str, Any]) -> None:
    owner, side = request.to_human, request.proposal["side"]
    mine = agents_of(conn, request)
    ticked = body.get("agents", mine)
    stray = [a for a in ticked if a not in mine]
    if stray:
        raise invalid(
            {"chat_access.agents": "not_on_this_request"},
            "chat_access.agents names only the request's waiting and held agents",
        )
    human = body.get("their_human", False)
    for agent in dict.fromkeys(ticked):
        reach = body.get("their_agents")
        if reach is None:
            listed = _their_agents(conn, request, agent)
            if not listed and not human:
                continue  # nothing of that side to admit it for: it goes on waiting
            reach = listed or chat_access.NONE
        entry = {
            "agents": [agent],
            "owner_id": side,
            "their_agents": reach,
            "their_human": human,
            "duration": DURATION[reply_id],
        }
        for field in ("allowed", "denied"):
            if field in body:
                entry[field] = body[field]
        chat_access.create_allow(conn, owner, entry)


def _decline(conn: Connection, request: Any, reason: str) -> None:
    """The waiting agents leave every chat in which they wait for the request's side."""
    from maity_hub import group_chats

    side = request.proposal["side"]
    for stays in _waiting(conn, request.to_human).get(side, {}).values():
        for s in stays:
            chat = group_chats.find(conn, s.project_id, s.conversation_id)
            membership = conn.execute(
                select(t.membership.c.id).where(
                    t.membership.c.project_id == s.project_id,
                    t.membership.c.agent_id == s.agent_id,
                    t.membership.c.active.is_(True),
                )
            ).scalar()
            if chat is not None and membership is not None:
                group_chats.remove(conn, chat, membership, request.to_human, reason, None)


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """The owner's answer (§9.6): an allow reply writes one entry per ticked agent, `no` lets
    the waiting agents leave, `block` writes a deny entry. Then each chat of the owner's agents
    is settled again, and a side still waited for gets a new request at once. The hub's own
    withdrawal applies nothing; the owner's counts as `no`."""
    from maity_hub import chat_gate

    request = conn.execute(select(t.request).where(t.request.c.id == s.request.id)).one()
    owner, side = request.to_human, request.proposal["side"]
    if s.outcome == "withdrawn" and s.answerer is None:
        return
    reply = "no" if s.outcome == "withdrawn" else s.reply_id
    body: dict[str, Any] = s.chat_access or {}
    with deferred(conn):
        chat_access._lock(conn, owner)
        if reply in DURATION:
            _allow(conn, request, str(reply), body)
        elif reply == "block":
            agents = agents_of(conn, request)
            if agents:
                chat_access.create_deny(conn, owner, {"agents": agents, "owner_id": side})
        else:
            _decline(conn, request, DECLINED)
        chat_gate.recheck(conn, owner)
        sync(conn, owner)


def _view(conn: Connection, request: Any, proposal: dict[str, Any]) -> dict[str, Any]:
    """What the inbox draws its checkboxes from: the side, and the agents waiting or held for
    it now (each ticked by default), with whether the side's human is in one of their chats."""
    side = proposal["side"]
    open_ = request.status == "open"
    agents = agents_of(conn, request) if open_ else []
    waiting = _waiting(conn, request.to_human).get(side, {}) if open_ else {}
    human_in = any(
        _people_in(conn, s.conversation_id, side)[1] for stays in waiting.values() for s in stays
    )
    held = set(_held_agents(proposal)) if open_ else set()
    names = _handles(conn, {side, *agents})
    return {
        "chat_access_request": {
            "side": {"id": side, "handle": names[side]},
            "agents": [
                {"id": a, "handle": names[a], "waiting": a in waiting, "held": a in held}
                for a in agents
            ],
            "their_human_in_chat": human_in,
        }
    }


def _owner_only(conn: Connection, request: Any, mine: Any) -> str | None:
    return None


proposals.register(
    KIND,
    settle,
    proposals.Answerer(
        refusal="only the owner of the waiting agents answers this",
        predicate=_owner_only,
        reply_required=True,
    ),
    view=_view,
)
