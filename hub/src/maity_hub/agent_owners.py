"""An agent whose owner is no member (docs/api.md §6.1 `agent_owners`, `outside_roles`; §6.2).

In a project that reads `members`, an agent leaves with its owner: the hub isolates every
agent whose owner holds no active membership, when the membership ends and when the setting
comes to read `members`. Under `anyone` an owner from outside may keep an agent working, within
`outside_roles`: trust `member` or `guest` and a role that does the work, so the project's own
members check what outsiders deliver; one beyond those limits when its owner leaves is isolated.
`reconcile` is the one pass for all of it. It only isolates, never lifts, and an isolation
already in place stays as it is. A security team stays among the project's own owners: an
outsider's agent that holds `blue-team` falls back to `coder` where
the list allows it, and is isolated otherwise; `settle` does that for one member, and a resume
calls it too, so a membership from before the rule settles without a migration.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select, update

from maity_hub import clock, isolation, policy, project_roles, public_projects
from maity_hub import tables as t
from maity_hub.errors import invalid
from maity_hub.events import Actor

OWNER_LEFT = "The agent's owner is no longer a member of this project."
HUB = Actor(None)  # the events name no actor: the hub's own change
OUTSIDE_TRUST = ("member", "guest")
# The role base an outsider's agent may no longer hold, and the role it falls back to (§6.2).
FALLS_BACK = "blue-team"
FALLBACK_ROLE = "coder"
FELL_BACK = (
    "The agent's owner is no member of this project, and a security team stays among the "
    "project's own owners."
)


def effective(conn: Connection, project: Any) -> str:
    """`members` or `anyone`: what a human set, else `anyone` while the project has a public
    page and `members` otherwise (§6.1)."""
    if project.agent_owners is not None:
        return str(project.agent_owners)
    return "anyone" if public_projects.served(conn, project) else "members"


def owner_of(conn: Connection, row: Any) -> str:
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == row.agent_id)
    ).scalar_one()
    return str(owner)


def owner_is_member(conn: Connection, project_id: str, owner_id: str) -> bool:
    """Whether the human holds an active membership in the project, an organisation's
    `org_owner` seat the hub keeps for them included (§6.26)."""
    return (
        conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.project_id == project_id,
                t.membership.c.human_id == owner_id,
                t.membership.c.active.is_(True),
            )
        ).first()
        is not None
    )


def is_outside(conn: Connection, project: Any, row: Any) -> bool:
    """An active agent member whose profile's owner is no member of the project."""
    return (
        row.agent_id is not None
        and row.active is not None
        and not owner_is_member(conn, project.id, owner_of(conn, row))
    )


def within_limits(project: Any, trust: str, role: str, role_base: str | None) -> bool:
    """What `outside_roles` lets an outsider's agent hold: trust `member` or `guest`, a role on
    the list, and one built on a base that works (never one that reviews, tests, manages,
    deploys or relays decisions, whatever the list says)."""
    return (
        trust in OUTSIDE_TRUST
        and role in policy.outside_roles(project)
        and (role_base or project_roles.base_of(project, role)) in policy.OUTSIDE_BASES
    )


def role_errors(project: Any, roles: list[str]) -> str | None:
    """`unknown` or `role_not_allowed` for the first role of a list that cannot be one (§6.1)."""
    for role in roles:
        base = project_roles.base_of(project, role)
        if base is None:
            return "unknown"
        if base not in policy.OUTSIDE_BASES:
            return "role_not_allowed"
    return None


def isolate_by_hub(conn: Connection, project: Any, row: Any, actor: Actor) -> None:
    """Isolate the agent as the hub, with the owner's notice, and withdraw the open requests
    to its owner about it (`owner_not_member`). An isolation in place is never overwritten."""
    from maity_hub import cross_owner, foreign_agent

    if isolation.is_isolated(row):
        return
    isolation.isolate(conn, project, row, OWNER_LEFT, isolation.BY_HUB, actor)
    foreign_agent.withdraw_open(conn, row.id, actor, "owner_not_member")
    cross_owner.withdraw_for_member(conn, row.id, actor, "owner_not_member")


def falls_back(project: Any, row: Any) -> bool:
    """Whether an outsider's agent beyond the limits only by a `blue-team` role is brought
    within them as a `coder` (§6.2): its trust is one an outsider may hold and the project's
    `outside_roles` lists `coder`."""
    return (
        row.role_base == FALLS_BACK
        and row.trust in OUTSIDE_TRUST
        and within_limits(project, row.trust, FALLBACK_ROLE, FALLBACK_ROLE)
    )


def fall_back(conn: Connection, project: Any, row: Any, actor: Actor) -> None:
    """The role `coder` for an outsider's agent that holds `blue-team` (§6.2): the member
    change as a `PATCH` writes it (`member_updated`, `changed` naming the role, a rules bump),
    with no actor, and a notice to the agent's owner."""
    from maity_hub import namespace
    from maity_hub.routes import members
    from maity_hub.routes.requests import file_hub_notice

    change = members.Change(project, actor, isolation.BY_HUB, isolation.BY_HUB, None, None)
    members.apply_patch(
        conn,
        change,
        row,
        {"role": FALLBACK_ROLE, "role_base": FALLBACK_ROLE},
        (False, None),
    )
    handle = conn.execute(
        select(t.agent_profile.c.handle).where(t.agent_profile.c.id == row.agent_id)
    ).scalar_one()
    summary = "\n".join(
        [
            f"Project: `{namespace.full_name(conn, project)}`.",
            f"Role: `{row.role}` is now `{FALLBACK_ROLE}`.",
            f"Reason: {FELL_BACK}",
            "By: `the hub`.",
        ]
    )
    file_hub_notice(
        conn, project.id, row.id, row.agent_id, f"{handle} is now a {FALLBACK_ROLE}", summary
    )


def settle(conn: Connection, project: Any, row: Any, actor: Actor, mode: str | None = None) -> None:
    """One active agent member against the project's setting (§6.2): nothing while its owner
    is a member or it stays within the limits, `coder` for a `blue-team` that may fall back,
    else the hub's isolation. An isolated member stays as it is."""
    if isolation.is_isolated(row) or not is_outside(conn, project, row):
        return
    mode = mode or effective(conn, project)
    if mode == "anyone":
        if within_limits(project, row.trust, row.role, row.role_base):
            return
        if falls_back(project, row):
            fall_back(conn, project, row, actor)
            return
    isolate_by_hub(conn, project, row, actor)


def reconcile(conn: Connection, project_id: str, actor: Actor | None = None) -> None:
    """Isolate what the project's setting does not let stay: under `members` every agent whose
    owner is no member, under `anyone` those of an outside owner beyond `outside_roles`, where
    one beyond them only by `blue-team` falls back to `coder` instead (`settle`)."""
    found = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
    mode = effective(conn, found)
    rows = conn.execute(
        select(t.membership)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.agent_id.is_not(None),
            t.membership.c.active.is_(True),
            t.membership.c.isolated_since.is_(None),
        )
        .order_by(t.membership.c.id)
    ).all()
    for row in rows:
        settle(conn, found, row, actor or HUB, mode)


def human_left(conn: Connection, project: Any, human_id: str, actor: Actor, by: str) -> None:
    """A human's membership ended (§6.2): the joins they created and nobody used are revoked,
    the placements they proposed that made no membership yet are closed, and what the
    project's setting does not let stay without its owner is isolated. Under both settings."""
    from maity_hub import bridges, placements

    j = t.join_link.c
    conn.execute(
        update(t.join_link)
        .where(
            j.project_id == project.id,
            j.created_by == human_id,
            j.used_at.is_(None),
            j.burned_at.is_(None),
            j.revoked_at.is_(None),
        )
        .values(revoked_at=clock.now())
    )
    placements.creator_left(conn, project.id, human_id, actor, by)
    bridges.owner_left(conn, project.id, human_id, actor)  # §2.3, "Ending on its own"
    reconcile(conn, project.id, actor)


def refuse_lift(conn: Connection, project: Any, row: Any) -> None:
    """No lift while the owner is no member and the agent may not stay (§6.2): `owner_not_member`
    under `members`, `outside_owner` under `anyone` while it is beyond the limits."""
    if not is_outside(conn, project, row):
        return
    mode = effective(conn, project)
    if mode == "members":
        raise invalid({"member": "owner_not_member"}, "the agent's owner is no member")
    if not within_limits(project, row.trust, row.role, row.role_base):
        raise invalid(
            {"member": "outside_owner"},
            "the agent is beyond what an outside owner's agent may hold",
        )


def check_assignment(conn: Connection, project: Any, row: Any, values: dict[str, Any]) -> None:
    """A trust or role an outsider's agent is set to must be one it may hold: `invalid` with
    `trust` / `role: outside_owner` otherwise (§6.2). Each field is judged by its own new value,
    so an isolated agent is brought within the limits one field after the other, and no PATCH,
    isolated or not, gives it trust `admin` or a role that reviews. A project that reads
    `members` holds no limits."""
    if row.agent_id is None or not ({"trust", "role"} & values.keys()):
        return
    if effective(conn, project) != "anyone" or not is_outside(conn, project, row):
        return
    errors: dict[str, str] = {}
    if "trust" in values and values["trust"] not in OUTSIDE_TRUST:
        errors["trust"] = "outside_owner"
    if "role" in values:
        base = values.get("role_base") or project_roles.base_of(project, values["role"])
        if values["role"] not in policy.outside_roles(project) or base not in policy.OUTSIDE_BASES:
            errors["role"] = "outside_owner"
    if errors:
        raise invalid(errors, "an agent of an owner from outside stays within outside_roles")


def check_policy(conn: Connection, project: Any, roles: list[str]) -> str | None:
    """`outside_owner` when a new `outside_roles` would leave an outsider's agent that is at
    work with a role not on it. One on `blue-team` is no list's to keep: the pass after the
    change settles it (`settle`)."""
    for row in conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project.id,
            t.membership.c.agent_id.is_not(None),
            t.membership.c.active.is_(True),
            t.membership.c.isolated_since.is_(None),
        )
    ):
        if row.role_base == FALLS_BACK:
            continue
        if is_outside(conn, project, row) and row.role not in roles:
            return "outside_owner"
    return None
