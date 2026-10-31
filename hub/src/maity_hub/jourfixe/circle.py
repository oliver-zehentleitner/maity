"""Who reads a round of an owner's series (docs/api.md §20.7, §20.3, §20.5, §20.9).

A round of a series with `circle: owner` is its `circle_owner`'s own: read by that human,
their agents in the project and the round's moderator; to every other member it does not
exist, the admin team's other humans included. Where a round of another series goes to
`all` or to `trust:owner`, a round of an owner's series goes to these readers, or to the
`circle_owner` alone.

The round's own `config` names the circle and its owner, so a round keeps its readers
after its series is deleted (§20.1: a running round runs to its end).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t


def owner_of(round_row: Any) -> str | None:
    """The `circle_owner` of the round's series, or None for any other circle."""
    config = round_row.config or {}
    if config.get("circle") != "owner":
        return None
    owner: str | None = config.get("circle_owner")
    return owner


def _moderator(round_row: Any) -> str | None:
    return (round_row.moderator or {}).get("member_id")


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
    if mine.principal_id in (owner, _moderator(round_row)):
        return True
    return mine.kind == "agent" and _owns(conn, owner, mine.principal_id)


def audience(conn: Connection, round_row: Any, default: list[str]) -> list[str]:
    """The readers of the round as an audience: `default` for a round of another series."""
    owner = owner_of(round_row)
    if owner is None:
        return list(default)
    found = [owner, *owner_agents(conn, round_row.project_id, owner), _moderator(round_row)]
    return [f"member:{who}" for who in dict.fromkeys(found) if who]


def owners(round_row: Any) -> list[str]:
    """Who reads along as the round's owner (§20.5): `trust:owner`, or the `circle_owner`."""
    owner = owner_of(round_row)
    return [f"member:{owner}"] if owner else ["trust:owner"]
