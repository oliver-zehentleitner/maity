"""Runners as their owners, the projects and the runners themselves see them
(docs/api.md §15.2–15.4, §15.8).

A runner is a caller of its own, owned by a human; its presence is computed
like a member's (§5.3) from its last call and its open long-poll, never
stored. Attaching a runner to a project is a row of its own and the only way
a runner comes to read anything of the project. The routes are in
`routes/runners.py` (humans) and `routes/runner.py` (the runner).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, insert, select, update

from maity_hub import clock, events, listening
from maity_hub import tables as t
from maity_hub.events import Actor
from maity_hub.ids import new_id
from maity_hub.scopes import has_scope
from maity_hub.views import AWAY, ONLINE, ts


def listening_key(runner_id: str) -> str:
    """The runner's long-poll registers under this key (§15.8)."""
    return f"runner:{runner_id}"


def audience(runner_id: str) -> str:
    """The audience token that names one runner (§15.10)."""
    return f"runner:{runner_id}"


def attached_project_ids(conn: Connection, runner_id: str) -> list[str]:
    return list(
        conn.execute(
            select(t.runner_attachment.c.project_id)
            .where(
                t.runner_attachment.c.runner_id == runner_id,
                t.runner_attachment.c.active.is_(True),
            )
            .order_by(t.runner_attachment.c.project_id)
        ).scalars()
    )


def event_project_ids(conn: Connection, runner_id: str) -> list[str]:
    """Where the runner's stream looks: every project it was ever attached to. An event
    names the runner only while it concerns it, so a detached project still delivers
    what was addressed to the runner then, `runner_detached` included."""
    return list(
        conn.execute(
            select(t.runner_attachment.c.project_id)
            .where(t.runner_attachment.c.runner_id == runner_id)
            .distinct()
            .order_by(t.runner_attachment.c.project_id)
        ).scalars()
    )


def human_actor(conn: Connection, project_id: str, human_id: str | None) -> Actor | None:
    """The human as an event's actor in one project, when they are a member there."""
    if human_id is None:
        return None
    membership_id = _membership_id(conn, project_id, human_id)
    return None if membership_id is None else Actor(membership_id=membership_id, via="cookie")


def _membership_id(conn: Connection, project_id: str, human_id: str) -> int | None:
    found: int | None = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id == human_id,
            t.membership.c.active.is_(True),
        )
    ).scalar()
    return found


def administers(conn: Connection, project_id: str, human_id: str) -> bool:
    """`members:admin` in the project, read now (an enrollment's `attach` is checked twice)."""
    role = conn.execute(
        select(t.membership.c.role).where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id == human_id,
            t.membership.c.active.is_(True),
        )
    ).scalar()
    return role is not None and has_scope(role, "human", "members:admin")


def presence(row: Any, is_listening: bool) -> str:
    if is_listening:
        return "online"
    if row.last_seen_at is None:
        return "offline"
    age = clock.now() - row.last_seen_at
    if age <= ONLINE:
        return "online"
    if age <= AWAY:
        return "away"
    return "offline"


def latest_credential(conn: Connection, runner_id: str) -> Any:
    return conn.execute(
        select(t.runner_credential)
        .where(t.runner_credential.c.runner_id == runner_id)
        .order_by(t.runner_credential.c.created_at.desc(), t.runner_credential.c.id.desc())
        .limit(1)
    ).first()


def live_credential_id(conn: Connection, runner_id: str) -> str | None:
    found: str | None = conn.execute(
        select(t.runner_credential.c.id).where(
            t.runner_credential.c.runner_id == runner_id,
            t.runner_credential.c.live.is_(True),
        )
    ).scalar()
    return found


def _project_slugs(conn: Connection, runner_id: str, viewer_id: str | None) -> list[str]:
    """The runner's projects; for a human only those they are a member of (§15.3)."""
    query = (
        select(t.project.c.slug)
        .join(t.runner_attachment, t.runner_attachment.c.project_id == t.project.c.id)
        .where(
            t.runner_attachment.c.runner_id == runner_id,
            t.runner_attachment.c.active.is_(True),
        )
        .order_by(t.project.c.slug)
    )
    if viewer_id is not None:
        query = query.join(
            t.membership,
            (t.membership.c.project_id == t.project.c.id)
            & (t.membership.c.human_id == viewer_id)
            & t.membership.c.active.is_(True),
        )
    return list(conn.execute(query).scalars())


def runner_view(
    conn: Connection, row: Any, viewer_id: str | None, *, capabilities: bool = True
) -> dict[str, Any]:
    """`viewer_id` is the viewing human, or None for the runner itself."""
    credential = latest_credential(conn, row.id)
    if credential is None:
        state = "none"
    elif credential.revoked_at is None:
        state = "active"
    else:
        state = "revoked"
    is_listening = listening.is_listening(listening_key(row.id))
    view: dict[str, Any] = {
        "id": row.id,
        "name": row.name,
        "owner_id": row.owner_id,
        "presence": presence(row, is_listening),
        "listening": is_listening,
        "last_seen_at": ts(row.last_seen_at),
        "credential_state": state,
        "version": row.version,
        "capabilities": row.capabilities,
        "projects": _project_slugs(conn, row.id, viewer_id),
        "created_at": ts(row.created_at),
        "updated_at": ts(row.updated_at),
        "removed_at": ts(row.removed_at),
    }
    if not capabilities:
        del view["capabilities"]
    if viewer_id == row.owner_id:  # the record, never the value; the owner's only
        view["credential"] = (
            None
            if credential is None
            else {
                "id": credential.id,
                "created_at": ts(credential.created_at),
                "last_used_at": ts(credential.last_used_at),
                "revoked_at": ts(credential.revoked_at),
                "revoked_reason": credential.revoked_reason,
            }
        )
    return view


def load_runner(conn: Connection, runner_id: str, viewer_id: str | None) -> dict[str, Any]:
    row = conn.execute(select(t.runner).where(t.runner.c.id == runner_id)).one()
    return runner_view(conn, row, viewer_id)


def visible_to(conn: Connection, runner: Any, human_id: str) -> bool:
    """The owner, or `members:admin` in a project the runner is attached to (§15.3)."""
    if runner.owner_id == human_id:
        return True
    return any(
        administers(conn, project_id, human_id)
        for project_id in attached_project_ids(conn, runner.id)
    )


def enrollment_view(conn: Connection, row: Any) -> dict[str, Any]:
    """Nothing that opens it: no URL, no token, no code (§15.2)."""
    slugs = dict(
        conn.execute(
            select(t.project.c.id, t.project.c.slug).where(t.project.c.id.in_(row.attach))
        ).all()
        if row.attach
        else []
    )
    return {
        "id": row.id,
        "runner_id": row.runner_id,
        "name": row.name,
        "attach": [slugs[p] for p in row.attach if p in slugs],
        "created_at": ts(row.created_at),
        "expires_at": ts(row.expires_at),
        "used_at": ts(row.used_at),
        "burned": row.burned_at is not None,
        "revoked_at": ts(row.revoked_at),
    }


# --- attachments (§15.4) -------------------------------------------------------------------


def attachment_view(
    conn: Connection, row: Any, viewer_id: str | None, *, capabilities: bool = True
) -> dict[str, Any]:
    runner = conn.execute(select(t.runner).where(t.runner.c.id == row.runner_id)).one()
    slug = conn.execute(select(t.project.c.slug).where(t.project.c.id == row.project_id)).scalar()
    return {
        "id": row.id,
        "runner": runner_view(conn, runner, viewer_id, capabilities=capabilities),
        "project": slug,
        "attached_by": row.attached_by,
        "attached_at": ts(row.attached_at),
        "detached_at": ts(row.detached_at),
        # Placements come with §15.5.
        "active_placements": 0,
    }


def active_attachment(conn: Connection, project_id: str, runner_id: str) -> Any:
    return conn.execute(
        select(t.runner_attachment).where(
            t.runner_attachment.c.project_id == project_id,
            t.runner_attachment.c.runner_id == runner_id,
            t.runner_attachment.c.active.is_(True),
        )
    ).first()


def attach(conn: Connection, project_id: str, runner_id: str, by: str) -> tuple[Any, bool]:
    """Attach under the project lock: (the active attachment, whether it is new)."""
    events.lock_project(conn, project_id)
    existing = active_attachment(conn, project_id, runner_id)
    if existing is not None:
        return existing, False
    attachment_id = new_id("runner_attachment")
    conn.execute(
        insert(t.runner_attachment).values(
            id=attachment_id,
            project_id=project_id,
            runner_id=runner_id,
            attached_by=by,
            attached_at=clock.now(),
            active=True,
        )
    )
    _announce(conn, project_id, runner_id, attachment_id, "runner_attached", by)
    row = conn.execute(
        select(t.runner_attachment).where(t.runner_attachment.c.id == attachment_id)
    ).one()
    return row, True


def detach(conn: Connection, project_id: str, runner_id: str, by: str) -> Any:
    """Detach under the project lock; returns the closed attachment, or None if there
    was no active one."""
    events.lock_project(conn, project_id)
    existing = active_attachment(conn, project_id, runner_id)
    if existing is None:
        return None
    conn.execute(
        update(t.runner_attachment)
        .where(t.runner_attachment.c.id == existing.id)
        .values(detached_at=clock.now(), detached_by=by, active=None)
    )
    _announce(conn, project_id, runner_id, existing.id, "runner_detached", by)
    return conn.execute(
        select(t.runner_attachment).where(t.runner_attachment.c.id == existing.id)
    ).one()


def _announce(
    conn: Connection, project_id: str, runner_id: str, attachment_id: str, kind: str, by: str
) -> None:
    slug = conn.execute(select(t.project.c.slug).where(t.project.c.id == project_id)).scalar()
    events.emit(
        conn,
        project_id,
        kind,
        [audience(runner_id), "role:owner"],
        {"runner_id": runner_id, "attachment_id": attachment_id, "project": slug},
        actor=human_actor(conn, project_id, by),
        subject=("runner", runner_id),
    )
