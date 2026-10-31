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


def names_of(conn: Connection, project: Any) -> set[str]:
    """Every full name the project answers to: its slug and its aliases' slugs, under its
    owner's current handle and the handle aliases of an owner that is a human (§6.24, §6.25)."""
    slugs = {project.slug}
    slugs.update(
        conn.execute(
            select(t.project_alias.c.slug).where(t.project_alias.c.project_id == project.id)
        ).scalars()
    )
    owner = namespace.owner_of(conn, project)
    owners = {owner["handle"]}
    if project.owner_human_id is not None:
        owners.update(handles.aliases(conn, [project.owner_human_id])[project.owner_human_id])
    return {f"{o}/{s}" for o in owners for s in slugs}


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
