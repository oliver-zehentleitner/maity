"""Where an agent profile may go (docs/api.md §6.3 "Allowed projects").

`agent_profile.allowed_projects` is null (any project) or a list of at most 200 project full
names as the owner wrote them, so a profile may be allowed into a project before it exists.
While it is a list, the agent gets no membership and no instance in a project not on it: the
joins, the placements, a pickup and the exchange of a join already handed out all ask `admits`.
A project is matched by its current full name or any alias, the owner part through the owner's
handle aliases too, so neither a project's nor its owner's rename drops it. The list never ends
a membership: an agent already in a project that the list no longer names keeps it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from maity_hub import handles, namespace
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid

MAX_NAMES = 200


def parse(raw: Any) -> list[str] | None:
    """The list as it is stored, or `invalid` (`details.fields.allowed_projects`): at most 200
    names, each `<owner>/<slug>` in the syntax of §6.25, none twice."""
    if raw is None:
        return None
    if not isinstance(raw, list) or any(not isinstance(n, str) for n in raw):
        raise invalid({"allowed_projects": "format"}, "allowed_projects is null or a list of names")
    if len(raw) > MAX_NAMES:
        raise invalid({"allowed_projects": "too_many"}, "at most 200 projects")
    if any(namespace.FULL_NAME.match(name) is None for name in raw):
        raise invalid({"allowed_projects": "format"}, "a name is <owner>/<slug>")
    if len(set(raw)) != len(raw):
        raise invalid({"allowed_projects": "duplicate"}, "a name twice")
    return list(raw)


def _handles_of(conn: Connection, human_id: str | None, org_id: str | None) -> set[str]:
    """The handles a namespace owner answers to: a human's or an organisation's current one
    and their aliases (§6.24)."""
    owner_id = human_id if human_id is not None else org_id
    assert owner_id is not None
    table, key = (t.human, t.human.c.id) if human_id is not None else (t.org, t.org.c.id)
    found = set(handles.aliases(conn, [owner_id])[owner_id])
    current = conn.execute(select(table.c.handle).where(key == owner_id)).scalar()
    if current is not None:
        found.add(str(current))
    return found


def names_of(conn: Connection, project: Any) -> set[str]:
    """Every full name the project answers to: its own slug under its owner's handles, and
    each earlier name under the owner it had then, a transfer included (§6.24, §6.25)."""
    found = {
        f"{h}/{project.slug}"
        for h in _handles_of(conn, project.owner_human_id, project.owner_org_id)
    }
    aliases = conn.execute(
        select(
            t.project_alias.c.slug, t.project_alias.c.owner_human_id, t.project_alias.c.owner_org_id
        ).where(t.project_alias.c.project_id == project.id)
    ).all()
    for alias in aliases:
        for handle in _handles_of(conn, alias.owner_human_id, alias.owner_org_id):
            found.add(f"{handle}/{alias.slug}")
    return found


def admits(conn: Connection, allowed: list[str] | None, project: Any) -> bool:
    """Whether a profile with this list may be in the project."""
    if allowed is None:
        return True
    return bool(set(allowed) & names_of(conn, project)) if allowed else False


def admits_name(conn: Connection, allowed: list[str] | None, full_name: str) -> bool:
    """`admits` for a name the caller asks about, a project that may not exist yet: by its
    names when it does, else by the name as written (`GET /agents?allowed_in=`)."""
    if allowed is None:
        return True
    project = namespace.resolve(conn, full_name)
    return admits(conn, allowed, project) if project is not None else full_name in allowed


def of_profile(conn: Connection, agent_id: str | None) -> list[str] | None:
    """The list of a profile, null for none and for an id that names no profile (a join or a
    placement that still has to create one)."""
    if agent_id is None:
        return None
    found = conn.execute(
        select(t.agent_profile.c.allowed_projects).where(t.agent_profile.c.id == agent_id)
    ).first()
    if found is None or found.allowed_projects is None:
        return None
    return [str(n) for n in found.allowed_projects]


def admits_membership(conn: Connection, membership_id: int | None, project: Any) -> bool:
    """`admits` for the agent of a membership: a placement runs a member (§15.6, §15.9);
    one that still has to create its profile has no list."""
    if membership_id is None:
        return True
    agent = conn.execute(
        select(t.membership.c.agent_id).where(t.membership.c.id == membership_id)
    ).scalar()
    return admits(conn, of_profile(conn, agent), project)


def refuse(conn: Connection, agent_id: str | None, project: Any) -> None:
    """`403 forbidden`, `details.reason: project_not_allowed`, for a join or a placement the
    profile's list does not admit (§6.3)."""
    if not admits(conn, of_profile(conn, agent_id), project):
        raise not_allowed()


def not_allowed() -> ApiError:
    return ApiError(
        403,
        "forbidden",
        "the agent's owner has not allowed this project",
        {"reason": "project_not_allowed"},
    )
