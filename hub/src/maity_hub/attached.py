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

from collections.abc import Callable, Iterable
from typing import Any

from sqlalchemy import Connection, Select, select

from maity_hub import events, namespace
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import (
    Caller,
    attachment_in,
    attachments,
    in_attachment,
    refuse_if_isolated,
)
from maity_hub.errors import ApiError, invalid, unauthenticated

PROJECT_MAX = 300  # an `<owner>/<slug>`; anything longer names no project


def _live(conn: Connection, caller: Caller) -> list[Any]:
    found = attachments(conn, caller.credential_id or "")
    if not found:  # detached from everything since the call was authenticated
        raise unauthenticated()
    return found


def named(conn: Connection, caller: Caller, project: str) -> Any:
    """The live attachment in the project `project` names: one the instance is not attached
    to, or none at all (a project id or any other form than `<owner>/<slug>` names none), is
    `invalid` (`project: not_a_member`), which tells the caller nothing it does not know; an
    isolated one `403 isolated` (§6.2). The project is its full name, current or an alias
    (§5.3, "Per project"), the whole text (`namespace.resolve`)."""
    found = namespace.resolve(conn, project)
    attachment = attachment_in(conn, caller, found.id) if found is not None else None
    if attachment is None:
        raise invalid({"project": "not_a_member"})
    return refuse_if_isolated(attachment)


def every(conn: Connection, caller: Caller, project: str | None) -> tuple[list[Any], bool]:
    """The attachments a write without a project applies to: the one `project` names, else
    every live attachment that is not isolated; `isolated` when every one is, `unauthenticated`
    when there is none or the credential was revoked since the call was authenticated. Beside
    them, from the same read, whether the write answers one member view: `project` named, or
    one live attachment (an isolated one counts)."""
    if project is not None:
        return [named(conn, caller, project)], True
    credential_id = caller.credential_id or ""
    still_live(conn, credential_id)
    live = attachments(conn, credential_id)
    return _free(live), len(live) == 1


def per_attachment(
    conn: Connection,
    caller: Caller,
    project: str | None,
    change: Callable[[Caller, Any], int],
) -> tuple[list[int], bool]:
    """An agent's own write outside a project (§5.3, "Per project"): `change(here, attachment)`
    in the project named, or in every attachment that is not isolated (`every`), all or
    nothing: a refusal in one changes nothing anywhere and, when the write is not single, names
    its project in `details.project` (`in_project`). `here` is the caller in that attachment;
    `change` answers the membership id it wrote. Returns those ids and whether the write is
    single, for the route's `members_outcome`."""
    targets, single = every(conn, caller, project)
    # Every project up front, in id order, as a revocation takes them (§6.17): the loop below
    # goes by attach order, and a lock inside it would invert that order.
    events.lock_projects(conn, (a.project_id for a in targets))
    # Read again under those locks: an isolation or a detach in between is not written past.
    targets = recheck(conn, caller, targets, project)
    ids: list[int] = []
    for attachment in targets:
        try:
            ids.append(change(in_attachment(caller, attachment), attachment))
        except ApiError as error:
            if single:
                raise
            raise in_project(error, conn, attachment.project_id) from None
    return ids, single


def still_live(conn: Connection, credential_id: str) -> None:
    """Refuse `unauthenticated` when the credential was revoked since the call was
    authenticated. A revocation keeps the attachment rows, so a read of them alone would not
    see it: `recheck` asks this before a write, and a replay before it loads anything, so the
    replay refuses as the request it stands for would (§1.5)."""
    revoked = conn.execute(
        select(t.credential.c.revoked_at).where(t.credential.c.id == credential_id)
    ).scalar_one_or_none()
    if revoked is not None:
        raise unauthenticated()


def _free(live: list[Any]) -> list[Any]:
    """The attachments of `live` that are not isolated: `unauthenticated` when there is none
    at all, `isolated` when every one is. A replay refuses through it as its request would
    (`free_held`, §1.5), never answering an empty list."""
    if not live:  # detached from everything since the call was authenticated
        raise unauthenticated()
    found = [a for a in live if a.isolated_since is None]
    if not found:
        refuse_if_isolated(live[0])
    return found


def held(conn: Connection, credential_id: str, project_ids: Iterable[str]) -> None:
    """For a replay (§1.5): lock `project_ids` in the order of their ids, then ask whether
    the credential is live. A revocation locks the projects it writes in the same way before
    it writes the credential row (`auth.revocation.revoke`), and the replay holds them to its
    commit: one that committed before the lock is seen by `still_live`, one that had not yet
    waits until the answer is out, as it waits for the request's own write (`recheck`). Only
    project locks, never the credential row, so the two never wait on each other in a cycle."""
    events.lock_projects(conn, project_ids)
    still_live(conn, credential_id)


def free_held(conn: Connection, credential_id: str) -> list[Any]:
    """`free` for the replay of a write in every project, under `held`: the projects of the
    credential's live attachments are locked first, and only attachments in those projects
    are answered, as `recheck` keeps to `targets`, since one attached after the first read
    is in a project not locked."""
    locked = {a.project_id for a in attachments(conn, credential_id)}
    held(conn, credential_id, locked)
    # read again under the locks: an isolation or a detach that committed before them shows
    return _free([a for a in attachments(conn, credential_id) if a.project_id in locked])


def recheck(conn: Connection, caller: Caller, targets: list[Any], project: str | None) -> list[Any]:
    """`targets` read again once their projects are locked, before any write: an isolation, a
    detach or a revocation takes the same project lock, so one that landed between `every`
    and the lock is seen here. With `project` the one target refuses as `named` would have;
    without it a target that is no longer live and free is left out, and when none is left
    the call refuses as `every` does. Never a target outside `targets`: those are the projects
    locked."""
    credential_id = caller.credential_id or ""
    still_live(conn, credential_id)
    fresh = {a.membership_id: a for a in attachments(conn, credential_id)}
    if project is not None:
        target = fresh.get(targets[0].membership_id)
        if target is None:
            raise invalid({"project": "not_a_member"})
        return [refuse_if_isolated(target)]
    return _free([fresh[a.membership_id] for a in targets if a.membership_id in fresh])


def one(conn: Connection, caller: Caller, project: str | None) -> Any:
    """The one attachment a call is about: the one `project` names, else the instance's only
    live attachment; with more than one, `project` is `required` (no implicit choice)."""
    if project is not None:
        return named(conn, caller, project)
    live = _live(conn, caller)
    if len(live) > 1:
        raise invalid({"project": "required"}, "name the project: the instance is in several")
    return refuse_if_isolated(live[0])


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
