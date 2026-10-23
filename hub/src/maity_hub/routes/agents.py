"""Agent profiles: a human's agents, across projects (docs/api.md §6.3)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, insert, select, update

from maity_hub import avatars, clock, idempotency
from maity_hub import tables as t
from maity_hub.deps import HumanCaller, engine_of
from maity_hub.errors import invalid, not_found
from maity_hub.ids import new_id
from maity_hub.models import HANDLE_PATTERN, GitIdentity, Strict, title
from maity_hub.views import agent_view

router = APIRouter()


class AgentCreate(Strict):
    handle: str = title(pattern=HANDLE_PATTERN)
    display_name: str = title()
    git_identity: GitIdentity | None = None


class AgentPatch(Strict):
    display_name: str | None = title(default=None)
    git_identity: GitIdentity | None = None


def load_agent(conn: Connection, agent_id: str) -> dict[str, Any]:
    return agent_view(conn, _row(conn, agent_id))


idempotency.LOADERS["agent"] = idempotency.plain(load_agent)


def _row(conn: Connection, agent_id: str) -> Any:
    return conn.execute(select(t.agent_profile).where(t.agent_profile.c.id == agent_id)).one()


def _owned(conn: Connection, agent_id: str, owner_id: str) -> Any:
    row = conn.execute(
        select(t.agent_profile).where(
            t.agent_profile.c.id == agent_id, t.agent_profile.c.owner_id == owner_id
        )
    ).first()
    if row is None:
        raise not_found()
    return row


def create_profile(
    conn: Connection, owner_id: str, handle: str, display_name: str, git: GitIdentity | None
) -> str:
    """A new profile of `owner_id`; `invalid` when the handle is taken (unique per owner)."""
    taken = conn.execute(
        select(t.agent_profile.c.id).where(
            t.agent_profile.c.owner_id == owner_id, t.agent_profile.c.handle == handle
        )
    ).first()
    if taken:
        raise invalid({"handle": "taken"}, "you already have an agent with this handle")
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
            .where(t.agent_profile.c.owner_id == caller.human_id)
            .order_by(t.agent_profile.c.handle)
        ).all()
        pictures = avatars.states(conn, [r.id for r in rows])  # one query for the list
        items = [agent_view(conn, r, pictures[r.id]) for r in rows]
        return JSONResponse({"items": items, "next_cursor": None})


@router.post("/agents")
def create_agent(body: AgentCreate, request: Request, caller: HumanCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        agent_id = create_profile(
            conn, caller.principal_id, body.handle, body.display_name, body.git_identity
        )
        return idempotency.Outcome(201, "agent", agent_id, load_agent(conn, agent_id))

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/agents/{agent_id}")
def get_agent(agent_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        return JSONResponse(agent_view(conn, _owned(conn, agent_id, caller.principal_id)))


@router.patch("/agents/{agent_id}")
def patch_agent(
    agent_id: str, body: AgentPatch, request: Request, caller: HumanCaller
) -> JSONResponse:
    given = body.model_fields_set

    def action(conn: Connection) -> idempotency.Outcome:
        _owned(conn, agent_id, caller.principal_id)
        values: dict[str, Any] = {}
        if "display_name" in given and body.display_name is not None:
            values["display_name"] = body.display_name
        if "git_identity" in given:
            git = body.git_identity
            values.update(git_name=git.name if git else None, git_email=git.email if git else None)
        if values:
            conn.execute(
                update(t.agent_profile).where(t.agent_profile.c.id == agent_id).values(**values)
            )
        return idempotency.Outcome(200, "agent", agent_id, load_agent(conn, agent_id))

    return idempotency.run(engine_of(request), request, caller, action)
