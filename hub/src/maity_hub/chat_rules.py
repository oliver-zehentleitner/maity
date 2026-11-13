"""The rules per side an owner sets on an allow entry, delivered to the agent (docs/api.md §9.6,
"Rules per side").

An allow entry carries two texts, `allowed` and `denied`. The agent receives them whenever it is
in a chat across that side's boundary: in the resume packet (`packet`) and in the chat's view
it reads (`for_chat`), one item per entry that admits it to a chat it is in. An entry
**admits** an agent to a chat when the agent takes part admitted there (`waiting_for == []`),
the entry names it, and it covers a participant on another side; a `project` entry covers
everyone of the chat's project. An entry with neither text sets no rule and gives no item.

Every write of an owner's entries runs inside `announcing`: what each entry reaches is taken
before and after, and `chat_rules_changed` goes to `member:<agent>` in each project where an
entry's texts or its reach changed for that agent. Its payload is `{entry_id}`, never the
texts; only the agent it names reads it (`events.readable`).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import chat_access, chat_gate, clock
from maity_hub import tables as t

KIND = "chat_rules_changed"
# How long before its `until` an entry not yet lapsed is judged, so that it still covers
# (`_allows` compares `until <= now`).
LAPSING = timedelta(microseconds=1)

Texts = tuple[str | None, str | None]


@dataclass
class _Reach:
    """One allow entry as read (`row`), its texts, and the chats it admits each agent to, as
    `(agent, project, conversation)`."""

    row: Any
    texts: Texts
    chats: set[tuple[str, str, str]] = field(default_factory=set)


def _reach(conn: Connection, owner: str, agent: str | None = None) -> dict[str, _Reach]:
    """Every allow entry of `owner` with a text, and what it admits the owner's agents to in
    their open group chats; with `agent`, only that agent's chats.

    An entry whose `until` passed counts as it was until the worker lapses it (`lapsed_at`,
    `chat_gate.lapse`): until then the stays it admitted still hold the admission, and a write
    of the owner's entries in between must see what the entry admitted before it, or the change
    it makes is announced by neither the write nor the lapse (9s6p on #1733)."""
    entries = _entries(conn, owner)
    found = {
        e.id: _Reach(e, (e.allowed, e.denied))
        for e in entries.rows
        if e.allowed is not None or e.denied is not None
    }
    if not found:
        return found
    from maity_hub import group_chats  # group_chats calls chat_gate, which this module calls

    now = clock.now()
    rows = [e for e in entries.rows if e.id in found]
    for chat in chat_gate.chats_of_owner(conn, owner):
        current = group_chats.stays(conn, chat.id)
        met = chat_gate.parties(conn, current)
        sides = {p.member_id: p.side for p in met}
        others = [p for p in met if p.side != owner]
        for s in current:
            if not s.agent_id or sides.get(s.agent_id) != owner or s.waiting_for != []:
                continue  # not the owner's agent, waiting, or with no other side in the chat
            if agent is not None and s.agent_id != agent:
                continue
            for e in rows:
                if not chat_gate._names_agent(e, entries, s.agent_id):
                    continue
                at = now
                if e.until is not None and e.lapsed_at is None:
                    at = min(now, e.until - LAPSING)
                if any(chat_gate._allows(e, entries, p, chat.project_id, at) for p in others):
                    found[e.id].chats.add((s.agent_id, chat.project_id, chat.id))
    return found


def _entries(conn: Connection, owner: str) -> chat_gate._Entries:
    """The owner's allow entries with the agents each names on each side, read in one statement:
    on PostgreSQL every statement of a read sees what was committed when it began, so a second
    statement could pair an entry's texts with the agents of a write committed in between, and
    an agent read the rules written for another (v5vp's hint on #1733). The texts the items carry
    are these rows' (`_items`), never read again."""
    c, g = t.chat_access.c, t.chat_access_agent.c
    found = chat_gate._Entries()
    seen: set[str] = set()
    for r in conn.execute(
        select(t.chat_access, g.side.label("named_side"), g.agent_id.label("named_agent"))
        .outerjoin(t.chat_access_agent, g.entry_id == c.id)
        .where(c.human_id == owner, c.kind == chat_access.ALLOW)
        .order_by(c.id)
    ):
        if r.id not in seen:
            seen.add(r.id)
            found.rows.append(r)
        if r.named_agent is not None:
            side = found.own if r.named_side == chat_access.OWN else found.theirs
            side[r.id].add(r.named_agent)
    return found


def _items(conn: Connection, reach: dict[str, _Reach], keep: Any) -> list[dict[str, Any]]:
    """The items of the entries whose chats `keep` lets through, oldest entry first, with the
    texts as `_entries` read them."""
    chosen = {
        entry_id: sorted({c for _, _, c in filter(keep, r.chats)}) for entry_id, r in reach.items()
    }
    chosen = {k: v for k, v in chosen.items() if v}
    if not chosen:
        return []
    rows = sorted((reach[k].row for k in chosen), key=lambda r: (r.since, r.id))
    return [
        {
            "entry_id": view["id"],
            "owner_id": view["owner_id"],
            "handle": view["handle"],
            "project": view["project"],
            "allowed": view["allowed"],
            "denied": view["denied"],
            "conversations": chosen[view["id"]],
        }
        for view in chat_access.render(conn, rows)
    ]


def _owner(conn: Connection, agent_id: str) -> str | None:
    return chat_gate.owners_of(conn, [agent_id]).get(agent_id)


def packet(conn: Connection, agent_id: str | None, project_id: str) -> list[dict[str, Any]]:
    """`chat_rules` of the resume packet (§5.2): the items for the agent's chats in this
    project."""
    owner = _owner(conn, agent_id) if agent_id else None
    if owner is None or agent_id is None:
        return []
    reach = _reach(conn, owner, agent_id)
    return _items(conn, reach, lambda c: c[0] == agent_id and c[1] == project_id)


def for_chat(conn: Connection, agent_id: str, conversation_id: str) -> list[dict[str, Any]]:
    """`chat_rules` of a chat's view as the agent reads it: the items for that chat."""
    owner = _owner(conn, agent_id)
    if owner is None:
        return []
    reach = _reach(conn, owner, agent_id)
    return _items(conn, reach, lambda c: c[0] == agent_id and c[2] == conversation_id)


@contextmanager
def announcing(conn: Connection, owner: str) -> Iterator[None]:
    """Around a write of `owner`'s entries and the `recheck` after it: `chat_rules_changed` to
    each agent, in each project, where an entry's texts changed while it admits or admitted the
    agent there, or where an entry with a text came to admit the agent or stopped admitting it
    (removed, narrowed, or its `until` passed), each judged per chat: an entry that comes to
    admit the agent to a second chat in a project, or stops admitting it to one of two, is a
    change in that project (9s6p on #1733).

    Only the owner's human row is taken first (`chat_access._lock`), as every write of the
    entries takes it first: the projects come later, in `recheck`, after the other human's
    `account_lock` a write may share (`chat_access._human`), and taking them here would turn
    that order round. So a chat write may come between the reading before and the write; what
    it changes then shows as a difference too, and the agent gets an event that is still true
    (its entry came to admit it or stopped), never one less for the entry's own change."""
    chat_access._lock(conn, owner)
    before = _reach(conn, owner)
    yield
    after = _reach(conn, owner)
    from maity_hub import events

    sent: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry_id in sorted(before.keys() | after.keys()):
        old, new = before.get(entry_id), after.get(entry_id)
        old_chats = old.chats if old else set()
        new_chats = new.chats if new else set()
        if (old.texts if old else None) != (new.texts if new else None):
            changed = old_chats | new_chats
        else:
            changed = old_chats ^ new_chats
        for pair in sorted({(agent, project) for agent, project, _ in changed}):
            sent[pair].append(entry_id)
    for (agent, project_id), entry_ids in sorted(sent.items(), key=lambda x: (x[0][1], x[0][0])):
        for entry_id in entry_ids:
            events.emit(
                conn,
                project_id,
                KIND,
                [f"member:{agent}"],
                {"entry_id": entry_id},
                subject=("member", agent),
            )
