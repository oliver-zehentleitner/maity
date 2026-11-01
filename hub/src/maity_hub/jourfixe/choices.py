"""A member's own choices in a series (docs/api.md §20.2): opting out, and the report list.

Every member may leave a series and come back; every member who reads the series' rounds
puts itself on the report list or takes itself off. A human owner does both for their own
agents. The keepers receive the report by default; a keeper who takes itself off is kept
as a row with `receives: false`. Nobody but the member and its owner sees that it opted
out, and only the keepers see the list.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, delete, insert, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.errors import ApiError, invalid
from maity_hub.jourfixe import series as series_mod
from maity_hub.jourfixe.circle import owner_agents
from maity_hub.scopes import has_scope


def _member_row(conn: Connection, project_id: str, member_id: str) -> Any:
    m = t.membership.c
    return conn.execute(
        select(t.membership).where(
            m.project_id == project_id,
            m.active.is_(True),
            (m.agent_id == member_id) | (m.human_id == member_id),
        )
    ).first()


def target(conn: Connection, mine: Membership, member_id: str | None) -> Any:
    """The membership a call acts for: the caller, or with `?member=` one of the calling
    human's own agents in the project (§20.2); anyone else is `forbidden`."""
    if member_id is None or member_id == mine.principal_id:
        return mine.row
    row = _member_row(conn, mine.project.id, member_id)
    if row is None:
        raise invalid({"member": "not_a_member"})
    if (
        mine.kind != "human"
        or row.agent_id is None
        or row.agent_id not in owner_agents(conn, mine.project.id, mine.principal_id)
    ):
        raise ApiError(
            403, "forbidden", "only the member, or its owner for an agent", {"reason": "not_own"}
        )
    return row


def _principal(row: Any) -> str:
    return str(row.agent_id or row.human_id)


# --- opting out -------------------------------------------------------------------------------


def opted_out(conn: Connection, series_id: str, membership_id: int) -> bool:
    c = t.jour_fixe_opt_out.c
    return (
        conn.execute(
            select(c.membership_id).where(
                c.series_id == series_id, c.membership_id == membership_id
            )
        ).first()
        is not None
    )


def set_opt_out(conn: Connection, series: Any, member: Any, out: bool) -> None:
    """Out of the series, or back in; either again is answered as it is."""
    c = t.jour_fixe_opt_out.c
    conn.execute(
        delete(t.jour_fixe_opt_out).where(c.series_id == series.id, c.membership_id == member.id)
    )
    if out:
        conn.execute(
            insert(t.jour_fixe_opt_out).values(
                series_id=series.id, membership_id=member.id, at=clock.now()
            )
        )


# --- the report list --------------------------------------------------------------------------


def reads_rounds(conn: Connection, series: Any, member: Any) -> bool:
    """Whether the member reads the series' rounds (§20.7): every member, or for an owner's
    series its `circle_owner`, that owner's agents and the members holding its moderator
    right."""
    if not member.active:
        return False
    if series.circle != "owner":
        return True
    who = _principal(member)
    if who == series.circle_owner or who in owner_agents(
        conn, series.project_id, series.circle_owner
    ):
        return True
    return member.id in series_mod.moderators(conn, series.id)


def _keepers(conn: Connection, series: Any) -> list[Any]:
    """The keepers' memberships (§20.1): an owner series' `circle_owner`, else the humans
    with `project:admin`."""
    m = t.membership.c
    rows = conn.execute(
        select(t.membership).where(
            m.project_id == series.project_id, m.active.is_(True), m.human_id.isnot(None)
        )
    ).all()
    if series.circle == "owner":
        return [r for r in rows if r.human_id == series.circle_owner]
    return [r for r in rows if has_scope(r.trust, r.role_base, "human", "project:admin")]


def recipients(conn: Connection, series: Any) -> list[Any]:
    """The memberships the series' report goes to: the keepers that did not take themselves
    off and the members on the list, each only while it reads the rounds (§20.2)."""
    c = t.jour_fixe_recipient.c
    choices = dict(
        conn.execute(select(c.membership_id, c.receives).where(c.series_id == series.id)).all()
    )
    keepers = [r for r in _keepers(conn, series) if choices.get(r.id) is not False]
    listed = [i for i, receives in choices.items() if receives]
    rows = conn.execute(select(t.membership).where(t.membership.c.id.in_(listed or [-1]))).all()
    found = {r.id: r for r in [*keepers, *sorted(rows, key=lambda r: r.id)]}
    return [r for r in found.values() if reads_rounds(conn, series, r)]


def receives(conn: Connection, series: Any, member: Any) -> bool:
    return any(r.id == member.id for r in recipients(conn, series))


def set_recipient(conn: Connection, series: Any, member: Any, on: bool) -> None:
    """On the list, or off it; a keeper off it is kept as `receives: false`, and either
    again is answered as it is. Only a member who reads the rounds asks (`not_found`
    otherwise, before this is reached)."""
    c = t.jour_fixe_recipient.c
    conn.execute(
        delete(t.jour_fixe_recipient).where(c.series_id == series.id, c.membership_id == member.id)
    )
    keeper = any(r.id == member.id for r in _keepers(conn, series))
    if on != keeper:  # the default needs no row
        conn.execute(
            insert(t.jour_fixe_recipient).values(
                series_id=series.id, membership_id=member.id, receives=on, at=clock.now()
            )
        )


def tokens(conn: Connection, series: Any, round_row: Any) -> list[str]:
    """The report's recipients as an audience (§20.9): `member:` of a human, the selected
    instance of an agent, so the report wakes each agent recipient once. In an owner's series
    the list may hold a moderator of the series who did not moderate this round: it reads
    only the rounds it moderated (§20.7), so this report does not go to it."""
    from maity_hub.jourfixe.circle import reads_member
    from maity_hub.jourfixe.rounds import wake_now

    found: list[str] = []
    for row in recipients(conn, series):
        if not reads_member(conn, round_row, row):
            continue
        if row.agent_id is None:
            found.append(f"member:{row.human_id}")
        else:
            found += wake_now(conn, series.project_id, row.agent_id)
    return found


# --- what the caller sees ---------------------------------------------------------------------


def shown(conn: Connection, series: Any, mine: Membership) -> dict[str, Any]:
    """The caller's own flags, its agents' under `own_agents` for a human with agents in the
    project, and for a keeper the list as `report_recipients` (§20.2)."""
    listed = recipients(conn, series)
    on = {r.id for r in listed}
    fields: dict[str, Any] = {
        "opted_out": opted_out(conn, series.id, mine.id),
        "report_recipient": mine.id in on,
    }
    if mine.kind == "human":
        agents = [
            _member_row(conn, series.project_id, a)
            for a in owner_agents(conn, series.project_id, mine.principal_id)
        ]
        fields["own_agents"] = [
            {
                "member_id": a.agent_id,
                "opted_out": opted_out(conn, series.id, a.id),
                "report_recipient": a.id in on,
            }
            for a in agents
            if a is not None
        ]
    if series_mod.is_keeper(series, mine):
        fields["report_recipients"] = [{"member_id": _principal(r)} for r in listed]
    return fields
