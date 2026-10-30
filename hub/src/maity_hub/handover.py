"""What a replaced instance left undone (docs/api.md §5.2 `handover`, §6.17).

An instance that `replaces` another gets, in its resume packets, the events addressed to the
chain it took over: from the cursor the newest instance of the chain with a session had
acknowledged, up to where its own first packet starts. It is delivered at least once, as
`events` are: until the instance has acknowledged a position at or above the cursor of its
first packet. It moves no cursor and wakes nothing.

Three numbers on the credential make this independent of when the packet is asked for:
`exchange_seq` (the project's newest event when the exchange created the instance), and
`first_after` and `first_cursor` (`events.after` and `events.cursor` of its first packet).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, func, select, update

from maity_hub import events
from maity_hub import tables as t

ITEMS_MAX = 50
# The events looked through for one packet, in pages: a chain that left a very long stretch
# unread is cut there, `truncated` says so and `GET …/events?after=` pages on.
PAGE = 200
PAGES_MAX = 25


def chain(conn: Connection, credential: Any) -> list[Any]:
    """The instances `credential` took over, newest first: the replaced one and, while that
    one never had a session, the one it replaced in turn, and so on. Their credential rows."""
    found: list[Any] = []
    seen = {credential.instance}
    wanted = credential.replaces
    while wanted is not None and wanted not in seen:
        row = conn.execute(
            select(t.credential).where(
                t.credential.c.membership_id == credential.membership_id,
                t.credential.c.instance == wanted,
            )
        ).first()
        if row is None:
            break
        seen.add(wanted)
        found.append(row)
        if _acknowledged(conn, row.id) is not None:
            break
        wanted = row.replaces
    return found


def _acknowledged(conn: Connection, credential_id: str) -> int | None:
    """The highest position a credential's sessions acknowledged, None without a session."""
    value = conn.execute(
        select(func.max(t.agent_session.c.acknowledged_seq)).where(
            t.agent_session.c.credential_id == credential_id
        )
    ).scalar()
    return None if value is None else int(value)


def newest_seq(conn: Connection, project_id: str) -> int:
    """The project's newest event, `0` for none: what an exchange records."""
    found = conn.execute(
        select(func.max(t.event.c.seq)).where(t.event.c.project_id == project_id)
    ).scalar()
    return int(found or 0)


def block(
    conn: Connection,
    mine: Any,
    principal: str,
    credential_id: str,
    after: int,
    cursor: int,
    chat_windows: dict[str, int],
) -> dict[str, Any] | None:
    """The packet's `handover` for the instance behind `credential_id`, or None: it replaces
    nothing, or it has acknowledged its first packet's cursor. `after` and `cursor` are
    `events.after` and `events.cursor` of the packet being built; the first packet's are
    stored with it. The caller has stored the session of this packet already."""
    credential = conn.execute(select(t.credential).where(t.credential.c.id == credential_id)).one()
    if credential.replaces is None:
        return None
    if credential.first_cursor is None:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == credential_id)
            .values(first_after=after, first_cursor=cursor)
        )
        first_after, first_cursor = after, cursor
    else:
        first_after, first_cursor = credential.first_after, credential.first_cursor
    own = _acknowledged(conn, credential_id)
    if own is not None and own >= first_cursor:
        return None
    left = chain(conn, credential)
    if not left:
        return None
    since = _since(conn, left)
    named = [f"instance:{principal}#{row.instance}" for row in left]
    named.append(f"instance:{principal}#{credential.instance}")
    team = f"member:{principal}"
    by_instance: list[Any] = []
    by_team: list[Any] = []
    position, cut = since, False
    for _ in range(PAGES_MAX):
        rows, _examined, more = events.read(
            conn, mine.project.id, mine.row, principal, position, PAGE, chat_windows=chat_windows
        )
        past = False
        for row in rows:
            if row.seq > first_after:
                past = True
                break
            audience = row.audience or []
            if any(token in audience for token in named):
                by_instance.append(row)
            elif team in audience:
                by_team.append(row)
        if past or not more:
            break
        position = rows[-1].seq
    else:
        cut = True  # PAGES_MAX pages and still before the first packet: page on by hand
    found = by_instance + by_team
    return {
        "from": [row.instance for row in left],
        "after": since,
        "items": found[:ITEMS_MAX],
        "truncated": cut or len(found) > ITEMS_MAX,
    }


def _since(conn: Connection, left: list[Any]) -> int:
    """`after` of the handover: the position the newest instance of the chain that had a
    session acknowledged, else the event of the exchange that created the oldest one."""
    for row in left:
        acknowledged = _acknowledged(conn, row.id)
        if acknowledged is not None:
            return acknowledged
    return int(left[-1].exchange_seq or 0)
