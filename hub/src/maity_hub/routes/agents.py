"""Agent profiles: a human's agents, across projects (docs/api.md §6.3)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, func, insert, select, update

from maity_hub import (
    avatars,
    clock,
    events,
    handles,
    idempotency,
    limits,
    moderation,
    namespace,
    public_projects,
)
from maity_hub import tables as t
from maity_hub.deps import HumanCaller, engine_of, settings_of
from maity_hub.errors import ApiError, invalid, not_found
from maity_hub.events import Actor
from maity_hub.ids import new_id
from maity_hub.models import HANDLE_PATTERN, GitIdentity, Strict, title
from maity_hub.views import agent_view

router = APIRouter()


class AgentCreate(Strict):
    handle: str = title(pattern=HANDLE_PATTERN)
    display_name: str = title()
    git_identity: GitIdentity | None = None


class AgentPatch(Strict):
    handle: str | None = None  # checked by handles.rename: format, taken, aliases (§6.24)
    display_name: str | None = title(default=None)
    git_identity: GitIdentity | None = None


def load_agent(conn: Connection, agent_id: str) -> dict[str, Any]:
    return agent_view(conn, _row(conn, agent_id))


idempotency.LOADERS["agent"] = idempotency.plain(load_agent)


def _row(conn: Connection, agent_id: str) -> Any:
    return conn.execute(select(t.agent_profile).where(t.agent_profile.c.id == agent_id)).one()


def owned(
    conn: Connection, agent_id: str, owner_id: str, *, deleted: bool = False, lock: bool = False
) -> Any:
    """The caller's own profile; a deleted one only where `deleted` says so (§6.3)."""
    query = select(t.agent_profile).where(
        t.agent_profile.c.id == agent_id, t.agent_profile.c.owner_id == owner_id
    )
    row = conn.execute(query.with_for_update() if lock else query).first()
    if row is None or (row.deleted_at is not None and not deleted):
        raise not_found()
    return row


def create_profile(
    conn: Connection,
    owner_id: str,
    handle: str,
    display_name: str,
    git: GitIdentity | None,
    limit: int | None = None,
    *,
    placement: bool = False,
) -> str:
    """A new profile of `owner_id`; `agent_limit` at `limit` profiles that are not deleted
    (§16.5, None for no limit). The owner's row is locked for the count, so two creations
    at `limit − 1` give one profile and one `agent_limit`, whichever endpoint they came by.
    `invalid` when the handle is the handle or an alias of another of their profiles (a
    deleted profile's are free, §6.3), or an active placement will create one with it
    (§6.24) unless `placement`: this is that placement's pickup."""
    if limit is not None:
        conn.execute(select(t.human.c.id).where(t.human.c.id == owner_id).with_for_update())
        count = int(
            conn.execute(
                select(func.count())
                .select_from(t.agent_profile)
                .where(
                    t.agent_profile.c.owner_id == owner_id,
                    t.agent_profile.c.deleted_at.is_(None),
                )
            ).scalar_one()
        )
        if count >= limit:
            raise limits.agent_limit(limit, count)
    handles.ensure_free(conn, owner_id, handle, exclude="placement" if placement else None)
    agent_id = new_id("agent")
    conn.execute(
        insert(t.agent_profile).values(
            id=agent_id,
            owner_id=owner_id,
            handle=handle,
            display_name=display_name,
            git_name=git.name if git else None,
            git_email=git.email if git else None,
            created_at=clock.now(),
        )
    )
    return agent_id


@router.get("/agents")
def list_agents(request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        rows = conn.execute(
            select(t.agent_profile)
            .where(
                t.agent_profile.c.owner_id == caller.human_id,
                t.agent_profile.c.deleted_at.is_(None),
            )
            .order_by(t.agent_profile.c.handle)
        ).all()
        pictures = avatars.states(conn, [r.id for r in rows])  # one query for the list
        items = [agent_view(conn, r, pictures[r.id]) for r in rows]
        return JSONResponse({"items": items, "next_cursor": None})


@router.post("/agents")
def create_agent(body: AgentCreate, request: Request, caller: HumanCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        limit = limits.of(conn, settings_of(request), "max_agents_per_human")
        agent_id = create_profile(
            conn, caller.principal_id, body.handle, body.display_name, body.git_identity, limit
        )
        return idempotency.Outcome(201, "agent", agent_id, load_agent(conn, agent_id))

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        return JSONResponse(
            agent_view(conn, owned(conn, agent_id, caller.principal_id, deleted=True))
        )


@router.patch("/agents/{agent_id}")
def patch_agent(
    agent_id: str, body: AgentPatch, request: Request, caller: HumanCaller
) -> JSONResponse:
    given = body.model_fields_set

    def action(conn: Connection) -> idempotency.Outcome:
        owned(conn, agent_id, caller.principal_id)
        if "handle" in given:
            if body.handle is None:  # as in `PATCH /me`: null renames nothing
                raise invalid({"handle": "required"})
            done = handles.rename(conn, agent_id, caller.principal_id, body.handle)
            if done is not None:
                handles.announce(conn, caller, agent_id, caller.principal_id, *done)
        values: dict[str, Any] = {}
        if "display_name" in given and body.display_name is not None:
            # A name moderation reset stays so while its hold stands (§16.8).
            moderation.refuse_held(conn, "profile", agent_id, "remove")
            values["display_name"] = body.display_name
        if "git_identity" in given:
            git = body.git_identity
            values.update(git_name=git.name if git else None, git_email=git.email if git else None)
        if values:
            conn.execute(
                update(t.agent_profile).where(t.agent_profile.c.id == agent_id).values(**values)
            )
        if "display_name" in values:  # a text shown on public pages is replaced at once (§16.9)
            public_projects.touch_of_agent(conn, agent_id)
        return idempotency.Outcome(200, "agent", agent_id, load_agent(conn, agent_id))

    return idempotency.run(engine_of(request), request, caller, action)


class ProfileInUse(ApiError):
    def __init__(self, memberships: list[dict[str, Any]], placements: list[str]) -> None:
        super().__init__(
            409,
            "profile_in_use",
            "the profile is a member or runs; delete it with cascade=true",
            {"memberships": memberships, "placements": placements},
        )


def _in_use(conn: Connection, agent_id: str) -> tuple[list[Any], list[str]]:
    """The profile's active memberships and the active placements that run them."""
    members = conn.execute(
        namespace.join_owner(
            select(
                t.membership, t.project.c.slug, namespace.owner_handle().label("owner_handle")
            ).join(t.project, t.project.c.id == t.membership.c.project_id)
        )
        .where(t.membership.c.agent_id == agent_id, t.membership.c.active.is_(True))
        .order_by(t.project.c.slug)
    ).all()
    running = (
        conn.execute(
            select(t.placement.c.id)
            .where(
                t.placement.c.membership_id.in_([m.id for m in members]),
                t.placement.c.active.is_(True),
            )
            .order_by(t.placement.c.id)
        )
        .scalars()
        .all()
        if members
        else []
    )
    return list(members), list(running)


def _owner_actor(conn: Connection, caller: Any, project_id: str) -> Actor:
    """The deleting owner as an event's actor (§6.3): their membership in that project,
    or the human without one."""
    own = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id == caller.human_id,
            t.membership.c.active.is_(True),
        )
    ).scalar()
    if own is not None:
        member: Actor = caller.actor(own)
        return member
    return Actor(None, credential_id=caller.credential_id, via=caller.via, human_id=caller.human_id)


@router.delete("/agents/{agent_id}")
def delete_agent(
    agent_id: str, request: Request, caller: HumanCaller, cascade: bool = False
) -> JSONResponse:
    """Delete a profile its owner no longer wants (§6.3): live joins revoked first, the
    profile's memberships removed only with `cascade`, a tombstone kept."""

    def action(conn: Connection) -> idempotency.Outcome:
        row = owned(conn, agent_id, caller.principal_id, deleted=True, lock=True)
        if row.deleted_at is not None:  # a second DELETE answers as it is
            return idempotency.Outcome(200, "agent", agent_id, load_agent(conn, agent_id))
        members, running = _in_use(conn, agent_id)
        if members and not cascade:
            raise ProfileInUse(
                [
                    {
                        "project": f"{m.owner_handle}/{m.slug}",
                        "member_id": agent_id,
                        "trust": m.trust,
                        "role": m.role,
                    }
                    for m in members
                ],
                running,
            )
        delete_profile(
            conn,
            agent_id,
            actor_in=lambda project_id: _owner_actor(conn, caller, project_id),
            by=caller.principal_id,
            credential_id=caller.credential_id,
            via=caller.via,
        )
        handles.retire(conn, agent_id)  # its aliases leave the owner's scope with its handle
        return idempotency.Outcome(200, "agent", agent_id, load_agent(conn, agent_id))

    return idempotency.run(engine_of(request), request, caller, action)


def delete_profile(
    conn: Connection,
    agent_id: str,
    *,
    actor_in: Callable[[str], Actor],
    by: str,
    credential_id: str | None,
    via: str | None,
) -> None:
    """Delete a profile as §6.3 does with `cascade`: live joins revoked first, every
    active membership removed (`apply_remove`), the avatar dropped, a tombstone kept.
    `actor_in(project_id)` is the event actor in each project, `by` the human on whose
    authority it happens. The caller has locked the profile row and checked the owner;
    shared by `DELETE /agents/{id}` and the deletion of the owner's account (§2.9)."""
    from maity_hub.routes.members import Change, apply_remove

    now = clock.now()
    members, _ = _in_use(conn, agent_id)
    # No membership is ever created for a deleted profile: its joins go first.
    conn.execute(
        update(t.join_link)
        .where(
            t.join_link.c.agent_id == agent_id,
            t.join_link.c.used_at.is_(None),
            t.join_link.c.burned_at.is_(None),
            t.join_link.c.revoked_at.is_(None),
            t.join_link.c.expires_at > now,
        )
        .values(revoked_at=now)
    )
    for member in members:
        events.lock_project(conn, member.project_id)
        project = conn.execute(select(t.project).where(t.project.c.id == member.project_id)).one()
        change = Change(project, actor_in(project.id), by, by, credential_id, via)
        target = conn.execute(select(t.membership).where(t.membership.c.id == member.id)).one()
        apply_remove(conn, change, target)
    avatars.remove_upload(conn, agent_id)  # the generated one applies (§6.10)
    conn.execute(
        update(t.agent_profile)
        .where(t.agent_profile.c.id == agent_id)
        .values(deleted_at=now, live=None)
    )
