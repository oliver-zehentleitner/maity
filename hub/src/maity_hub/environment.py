"""Shared environments: two members whose open sessions declare the same home or
workspace (docs/api.md §5.2, §5.3).

The ids are declared by the client, never verified, and only compared here: they never
appear in a view, an event or the log. Who shares with whom is computed from the live
sessions whenever it is asked; `environment_overlap` only remembers what was announced,
so `shared_environment_detected` goes out once when an overlap starts and again when its
level rises from `home` to `workspace`. An overlap ends after ten minutes in which the
two no longer share an id; a resume that replaces a session with the same ids, or comes
back within those ten minutes, continues it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import Connection, and_, insert, or_, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.scopes import has_scope

ID = re.compile(r"^[hw]-[0-9a-f]{12}$")  # anchored: pydantic searches, it does not match
LEVELS = ("home", "workspace")  # weakest first
QUIET = timedelta(minutes=10)


def _declared(conn: Connection, project_id: str) -> dict[int, tuple[set[str], set[str]]]:
    """The homes and workspaces each member's live sessions declare."""
    rows = conn.execute(
        select(
            t.agent_session.c.membership_id,
            t.agent_session.c.env_home,
            t.agent_session.c.env_workspace,
        )
        .select_from(t.agent_session)
        .join(t.membership, t.membership.c.id == t.agent_session.c.membership_id)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.active.is_(True),
            t.agent_session.c.live.is_(True),
            or_(
                t.agent_session.c.env_home.isnot(None),
                t.agent_session.c.env_workspace.isnot(None),
            ),
        )
    ).all()
    declared: dict[int, tuple[set[str], set[str]]] = {}
    for row in rows:
        homes, workspaces = declared.setdefault(row.membership_id, (set(), set()))
        if row.env_home:
            homes.add(row.env_home)
        if row.env_workspace:
            workspaces.add(row.env_workspace)
    return declared


def shared(conn: Connection, project_id: str) -> dict[int, dict[int, str]]:
    """For every member that shares an environment: its peers and the stronger level."""
    declared = _declared(conn, project_id)
    found: dict[int, dict[int, str]] = {}
    members = sorted(declared)
    for i, a in enumerate(members):
        for b in members[i + 1 :]:
            if declared[a][1] & declared[b][1]:
                level = "workspace"
            elif declared[a][0] & declared[b][0]:
                level = "home"
            else:
                continue
            found.setdefault(a, {})[b] = level
            found.setdefault(b, {})[a] = level
    return found


def views(
    conn: Connection, project_id: str, membership_ids: Iterable[int]
) -> dict[int, list[dict[str, str]]]:
    """`shared_environment` of each member (§5.3), peers in member id order."""
    from maity_hub.views import principal_ids

    wanted = set(membership_ids)
    pairs = {m: peers for m, peers in shared(conn, project_id).items() if m in wanted}
    ids = principal_ids(conn, {p for peers in pairs.values() for p in peers})
    return {
        m: sorted(
            ({"member_id": ids[p], "level": level} for p, level in peers.items()),
            key=lambda v: v["member_id"],
        )
        for m, peers in pairs.items()
    }


def refresh(conn: Connection, project_id: str, membership_id: int) -> None:
    """Bring the overlaps of one member up to date after its sessions changed: a
    resume, a revocation, a removal. Announces what started or rose. Under the project
    lock, so two members' changes cannot both read the pair before either writes it."""
    from maity_hub.events import lock_project

    lock_project(conn, project_id)
    now = clock.now()
    current = shared(conn, project_id).get(membership_id, {})
    known = {
        (row.member_a, row.member_b): row
        for row in conn.execute(
            select(t.environment_overlap).where(
                or_(
                    t.environment_overlap.c.member_a == membership_id,
                    t.environment_overlap.c.member_b == membership_id,
                )
            )
        )
    }
    for peer, level in current.items():
        pair = (min(membership_id, peer), max(membership_id, peer))
        key = and_(
            t.environment_overlap.c.member_a == pair[0],
            t.environment_overlap.c.member_b == pair[1],
        )
        row = known.get(pair)
        continues = row is not None and (row.quiet_since is None or now - row.quiet_since <= QUIET)
        if row is not None and continues:
            rises = LEVELS.index(level) > LEVELS.index(row.announced)
            conn.execute(
                update(t.environment_overlap)
                .where(key)
                .values(
                    level=level,
                    quiet_since=None,
                    announced=level if rises else row.announced,
                )
            )
            if rises:
                _announce(conn, project_id, pair, level)
            continue
        values = {"level": level, "announced": level, "started_at": now, "quiet_since": None}
        if row is None:
            conn.execute(
                insert(t.environment_overlap).values(
                    member_a=pair[0], member_b=pair[1], project_id=project_id, **values
                )
            )
        else:  # an earlier overlap that ended: this is a new one
            conn.execute(update(t.environment_overlap).where(key).values(**values))
        _announce(conn, project_id, pair, level)
    for pair, row in known.items():
        peer = pair[1] if pair[0] == membership_id else pair[0]
        if peer not in current and row.quiet_since is None:
            conn.execute(
                update(t.environment_overlap)
                .where(
                    t.environment_overlap.c.member_a == pair[0],
                    t.environment_overlap.c.member_b == pair[1],
                )
                .values(quiet_since=now)
            )


def _announce(conn: Connection, project_id: str, pair: tuple[int, int], level: str) -> None:
    """`shared_environment_detected` to the members' owners and the human admins (§8.2).
    Names humans only, so it wakes no agent; `events.readable_by` keeps it from every
    agent, admins included."""
    from maity_hub.events import emit
    from maity_hub.views import principal_ids

    ids = principal_ids(conn, pair)
    members = conn.execute(select(t.membership).where(t.membership.c.id.in_(pair))).all()
    agent_ids = [m.agent_id for m in members if m.agent_id is not None]
    owners = set(
        conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id.in_(agent_ids))
        ).scalars()
        if agent_ids
        else ()
    )
    owners |= {m.human_id for m in members if m.human_id is not None}
    admins = (
        row.human_id
        for row in conn.execute(
            select(t.membership.c.human_id, t.membership.c.trust, t.membership.c.role).where(
                t.membership.c.project_id == project_id,
                t.membership.c.active.is_(True),
                t.membership.c.human_id.isnot(None),
            )
        )
        if has_scope(row.trust, row.role, "human", "members:admin")
    )
    audience = [f"member:{h}" for h in sorted(owners | set(admins))]
    emit(
        conn,
        project_id,
        "shared_environment_detected",
        audience,
        {"member_ids": [ids[pair[0]], ids[pair[1]]], "level": level},
    )
