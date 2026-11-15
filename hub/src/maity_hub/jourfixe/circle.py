"""Who reads a round of an owner's series (docs/api.md §20.7, §20.3, §20.5, §20.9).

A round of a series with `circle: owner` is its `circle_owner`'s own: read by that human,
their agents in the project and the round's moderator; to every other member it does not
exist, the admin team's other humans included. Where a round of another series goes to
`all` or to `trust:owner`, a round of an owner's series goes to these readers, or to the
`circle_owner` alone.

The round's own `config` names the circle and its owner, so a round keeps its readers
after its series is deleted (§20.1: a running round runs to its end).

The round's stored moderator acts and reads as moderator only while it still holds the
series' moderator right (§20.2): ending the right takes effect for an open round too. A
round whose series was deleted keeps its moderator to its end, since the deletion took the
rights with it and the round still runs out (`holds_right`).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.jourfixe import series as series_mod


def owner_of(round_row: Any) -> str | None:
    """The `circle_owner` of the round's series, or None for any other circle."""
    config = round_row.config or {}
    if config.get("circle") != "owner":
        return None
    owner: str | None = config.get("circle_owner")
    return owner


def _moderator(round_row: Any) -> str | None:
    return (round_row.moderator or {}).get("member_id")


def holds_right(conn: Connection, round_row: Any, membership_id: int) -> bool:
    """Whether the membership still holds the moderator right of the round's series (§20.2).
    A round whose series was deleted has no rights left to check and runs to its end."""
    if round_row.series_id is None:
        return True
    return membership_id in series_mod.moderators(conn, round_row.series_id)


def moderates(conn: Connection, round_row: Any, mine: Any) -> bool:
    """Whether the caller is the round's moderator: its stored moderator, while it still holds
    the series' moderator right."""
    who = _moderator(round_row)
    return who is not None and mine.principal_id == who and holds_right(conn, round_row, mine.id)


def _moderator_now(conn: Connection, round_row: Any) -> str | None:
    """The round's stored moderator while it holds the right, else None."""
    who = _moderator(round_row)
    if who is None or round_row.series_id is None:
        return who
    held = any(
        r.state == "active" and r.active and who in (r.agent_id, r.human_id)
        for r in series_mod.grants(conn, round_row.series_id)
    )
    return who if held else None


def owner_agents(conn: Connection, project_id: str, human_id: str) -> list[str]:
    """The human's agents that are active members of the project."""
    m, a = t.membership.c, t.agent_profile.c
    return list(
        conn.execute(
            select(m.agent_id)
            .join(t.agent_profile, a.id == m.agent_id)
            .where(m.project_id == project_id, m.active.is_(True), a.owner_id == human_id)
            .order_by(m.id)
        ).scalars()
    )


def _owns(conn: Connection, human_id: str, agent_id: str) -> bool:
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar()
    return bool(owner == human_id)


def reads(conn: Connection, round_row: Any, mine: Any) -> bool:
    """Whether the member reads the round (§20.7)."""
    owner = owner_of(round_row)
    if owner is None:
        return True
    if mine.principal_id == owner or moderates(conn, round_row, mine):
        return True
    return mine.kind == "agent" and _owns(conn, owner, mine.principal_id)


def reads_member(conn: Connection, round_row: Any, member: Any) -> bool:
    """`reads` for a membership row rather than a caller."""
    who = member.agent_id or member.human_id
    owner = owner_of(round_row)
    if owner is None:
        return True
    if who == owner or (who == _moderator(round_row) and holds_right(conn, round_row, member.id)):
        return True
    return member.agent_id is not None and _owns(conn, owner, member.agent_id)


def audience(conn: Connection, round_row: Any, default: list[str]) -> list[str]:
    """The readers of the round as an audience: `default` for a round of another series."""
    owner = owner_of(round_row)
    if owner is None:
        return list(default)
    found = [
        owner,
        *owner_agents(conn, round_row.project_id, owner),
        _moderator_now(conn, round_row),
    ]
    return [f"member:{who}" for who in dict.fromkeys(found) if who]


def owners(round_row: Any) -> list[str]:
    """Who reads along as the round's owner (§20.5): `trust:owner`, or the `circle_owner`."""
    owner = owner_of(round_row)
    return [f"member:{owner}"] if owner else ["trust:owner"]
