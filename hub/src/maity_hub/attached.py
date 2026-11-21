"""An agent instance's projects on a route outside any project (docs/api.md §6.17, "One
instance in several projects": "Project-less routes name their project where it matters").

Such a call resolves no membership (`auth.caller.settle_project_less`): there is no implicit
current project, not even for an instance with a single attachment, and never "the oldest
attachment". A route about one project takes it from its body (`named`, `one`), or applies to
every live attachment that is not isolated (`every`); a route about the profile reads no
membership at all. Each lookup reads the attachments again in the route's transaction, and a
lookup that finds nothing refuses: `invalid` for a project the instance is not attached to,
`isolated` for an isolated one, `unauthenticated` for an instance attached nowhere any more.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, Select, select

from maity_hub import namespace
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import Caller, attachment_in, attachments
from maity_hub.errors import ApiError, invalid, unauthenticated

PROJECT_MAX = 300  # an `<owner>/<slug>`; anything longer names no project


def project_named(conn: Connection, text: str) -> Any | None:
    """The project `text` names: its full name `<owner>/<slug>` (§5.3, "Per project"),
    current or an alias; None for anything else, a project id included, which `project`
    does not take. The whole text must be the name: `FULL_NAME` ends in `$`, which also
    passes a trailing newline under `match`."""
    if namespace.FULL_NAME.fullmatch(text) is None:
        return None
    return namespace.resolve(conn, text)


def _live(conn: Connection, caller: Caller) -> list[Any]:
    found = attachments(conn, caller.credential_id or "")
    if not found:  # detached from everything since the call was authenticated
        raise unauthenticated()
    return found


def _refuse_isolated(attachment: Any) -> Any:
    if attachment.isolated_since is not None:
        from maity_hub import isolation

        raise isolation.refusal(attachment)
    return attachment


def named(conn: Connection, caller: Caller, project: str) -> Any:
    """The live attachment in the project `project` names: one the instance is not attached
    to, or none at all (a project id or any other form than `<owner>/<slug>` names none), is
    `invalid` (`project: not_a_member`), which tells the caller nothing it does not know; an
    isolated one `403 isolated` (§6.2)."""
    found = project_named(conn, project)
    attachment = attachment_in(conn, caller, found.id) if found is not None else None
    if attachment is None:
        raise invalid({"project": "not_a_member"})
    return _refuse_isolated(attachment)


def every(conn: Connection, caller: Caller, project: str | None) -> list[Any]:
    """The attachments a write without a project applies to: the one `project` names, else
    every live attachment that is not isolated; `isolated` when every one is."""
    if project is not None:
        return [named(conn, caller, project)]
    live = _live(conn, caller)
    free = [a for a in live if a.isolated_since is None]
    if not free:
        _refuse_isolated(live[0])
    return free


def one(conn: Connection, caller: Caller, project: str | None) -> Any:
    """The one attachment a call is about: the one `project` names, else the instance's only
    live attachment; with more than one, `project` is `required` (no implicit choice)."""
    if project is not None:
        return named(conn, caller, project)
    live = _live(conn, caller)
    if len(live) > 1:
        raise invalid({"project": "required"}, "name the project: the instance is in several")
    return _refuse_isolated(live[0])


def single(conn: Connection, caller: Caller, project: str | None) -> bool:
    """Whether a write answers one member view: `project` named, or one live attachment."""
    return project is not None or len(_live(conn, caller)) == 1


def membership_of(conn: Connection, caller: Caller, attachment: Any) -> Membership:
    """The caller's `Membership` in an attachment's project, as a project route has it."""
    row = conn.execute(select(t.membership).where(t.membership.c.id == attachment.membership_id))
    member = row.one()
    project = conn.execute(select(t.project).where(t.project.c.id == member.project_id)).one()
    return Membership(project, member, "agent", caller.instance)


def in_project(error: ApiError, conn: Connection, project_id: str) -> ApiError:
    """`error`, refused for one of several attachments, naming that project in
    `details.project` (§5.3, "Per project": all or nothing)."""
    return ApiError(
        error.status,
        error.code,
        error.message,
        {**error.details, "project": namespace.name_of(conn, project_id)},
        error.headers,
    )


def free_memberships(caller: Caller) -> Select[Any]:
    """The memberships of the caller's live attachments that are active and not isolated: the
    projects a call outside any project reads in, as a subquery (§6.2: an isolated membership
    reads nothing of its project)."""
    a, m = t.instance_attachment, t.membership
    return (
        select(a.c.membership_id)
        .join(m, m.c.id == a.c.membership_id)
        .where(
            a.c.credential_id == (caller.credential_id or ""),
            a.c.detached_at.is_(None),
            m.c.active.is_(True),
            m.c.isolated_since.is_(None),
        )
    )
