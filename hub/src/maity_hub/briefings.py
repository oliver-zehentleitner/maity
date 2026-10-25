"""A briefing's versions (docs/api.md §6.2).

An agent membership's briefing starts at version 1 with the join and goes up by one on
every change; each version is kept with who wrote it and when. The text is the
member's own and its admins' to read, and its versions its owner's and its admins':
an event only ever says that it changed and its new version.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import tables as t
from maity_hub.views import ts


def record(
    conn: Connection, membership_id: int, text: str | None, by: str | None, at: datetime
) -> int:
    """Write a new version of the membership's briefing; returns its number. The version
    is read with a lock on the membership row: a plain read sees the transaction's
    snapshot under MariaDB's repeatable read, so two admins editing one member at once
    would both write the same number."""
    current: int = conn.execute(
        select(t.membership.c.briefing_version)
        .where(t.membership.c.id == membership_id)
        .with_for_update()
    ).scalar_one()
    version = current + 1
    conn.execute(
        update(t.membership)
        .where(t.membership.c.id == membership_id)
        .values(briefing=text, briefing_version=version, briefing_by=by, briefing_updated_at=at)
    )
    conn.execute(
        insert(t.member_briefing).values(
            membership_id=membership_id, version=version, text=text, by=by, at=at
        )
    )
    return version


def writers(conn: Connection, ids: set[str]) -> dict[str, dict[str, Any]]:
    """`{kind, id, handle}` for each writer id (a human or an agent profile)."""
    humans = {i for i in ids if i.startswith("hum-")}
    agents = ids - humans
    found: dict[str, dict[str, Any]] = {}
    for table, kind, wanted in ((t.human, "human", humans), (t.agent_profile, "agent", agents)):
        if wanted:
            for row in conn.execute(
                select(table.c.id, table.c.handle).where(table.c.id.in_(wanted))
            ):
                found[row.id] = {"kind": kind, "id": row.id, "handle": row.handle}
    return found


def fields(row: Any, writers_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What comes with the briefing in a member view (§6.2)."""
    return {
        "briefing_by": writers_by_id.get(row.briefing_by) if row.briefing_by else None,
        "briefing_version": row.briefing_version,
        "briefing_updated_at": ts(row.briefing_updated_at),
    }


def history(conn: Connection, membership_id: int) -> list[dict[str, Any]]:
    """Every version, newest first."""
    rows = conn.execute(
        select(t.member_briefing)
        .where(t.member_briefing.c.membership_id == membership_id)
        .order_by(t.member_briefing.c.version.desc())
    ).all()
    by = writers(conn, {r.by for r in rows if r.by})
    return [
        {
            "version": r.version,
            "text": r.text,
            "by": by.get(r.by) if r.by else None,
            "at": ts(r.at),
        }
        for r in rows
    ]
