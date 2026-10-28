"""Memory endpoints: the soul, team and community memory (docs/api.md §19).

The domain — views, writes, caps, events, the resume block — is `maity_hub.memory`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, StringConstraints
from sqlalchemy import Connection, and_, or_, select

from maity_hub import idempotency, memory, namespace, paging
from maity_hub import tables as t
from maity_hub.access import Membership, member_row_or_removed, membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AgentCaller, AnyCaller, HumanCaller, engine_of
from maity_hub.errors import forbidden, humans_only, invalid, not_found
from maity_hub.models import Strict, markdown
from maity_hub.namespace import ProjectRoute
from maity_hub.routes.agents import owned
from maity_hub.routes.requests import file_consent, file_personal, request_view

router = APIRouter(route_class=ProjectRoute)

PAGE_DEFAULT, PAGE_MAX = 50, 200

Tag = Annotated[str, StringConstraints(pattern=r"^[a-z0-9-]{1,32}$")]


class SoulIn(Strict):
    markdown: str = Field(max_length=memory.SOUL_MAX)


class SoulProposalIn(SoulIn):
    reason: str = markdown(min_length=1)


class EntryIn(Strict):
    store: Literal["team", "community"]
    text: str = Field(min_length=1, max_length=memory.ENTRY_MAX)
    tags: list[Tag] = Field(default_factory=list, max_length=5)


class DeleteIn(Strict):
    reason: str | None = markdown(default=None)


# --- the soul (§19.1) ---------------------------------------------------------------------------


@router.get("/agents/{agent_id}/soul")
def get_soul(agent_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        owned(conn, agent_id, caller.principal_id)
        return JSONResponse(memory.soul_view(conn, agent_id))


@router.put("/agents/{agent_id}/soul")
def put_soul(agent_id: str, body: SoulIn, request: Request, caller: HumanCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        agent = owned(conn, agent_id, caller.principal_id)
        view = memory.write_soul(
            conn, agent, body.markdown, ("human", caller.principal_id), None, caller
        )
        return idempotency.Outcome(200, "soul", f"{agent_id}@{view['version']}", view)

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/agents/{agent_id}/soul/versions")
def soul_versions(agent_id: str, request: Request, caller: HumanCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        owned(conn, agent_id, caller.principal_id)
        return JSONResponse({"items": memory.soul_versions(conn, agent_id)})


@router.get("/me/soul")
def my_soul(request: Request, caller: AgentCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        return JSONResponse(memory.soul_view(conn, str(caller.agent_id)))


@router.post("/me/soul/proposals")
def propose_soul(body: SoulProposalIn, request: Request, caller: AgentCaller) -> JSONResponse:
    if memory.size(body.markdown) > memory.SOUL_MAX:
        raise invalid({"markdown": "too_long"}, "a soul is at most 8 KiB")

    def action(conn: Connection) -> idempotency.Outcome:
        project = conn.execute(select(t.project).where(t.project.c.id == caller.project_id)).one()
        mine = membership(conn, caller, namespace.full_name(conn, project))
        agent_id = str(caller.agent_id)
        request_id = file_personal(
            conn,
            mine,
            caller,
            agent_id,
            "consent",
            "May my soul read like this?",
            body.reason,
            proposal=memory.propose_soul(conn, agent_id, body.markdown),
        )
        return idempotency.Outcome(
            202, "proposal_request", request_id, _load_proposal(conn, request_id)
        )

    return idempotency.run(engine_of(request), request, caller, action)


# --- team and community memory (§19.2) -----------------------------------------------------------


def _team(conn: Connection, mine: Membership, member_id: str) -> Any:
    team = member_row_or_removed(conn, mine.project.id, member_id)
    if team.agent_id is None:
        raise invalid({"member_id": "not_an_agent"}, "team memory belongs to an agent's membership")
    if not memory.reads_team(conn, mine, team):  # a team the caller cannot read: none (§1.3)
        raise not_found()
    return team


def _matches(row: Any, q: str) -> bool:
    needle = q.casefold()
    return needle in (row.text or "").casefold() or any(needle in tag for tag in row.tags or [])


@router.get("/projects/{owner}/{slug}/memory")
def list_memory(
    slug: str,
    request: Request,
    caller: AnyCaller,
    store: Literal["team", "community"] | None = None,
    member_id: str | None = None,
    q: str | None = Query(default=None, min_length=1, max_length=200),
    deleted: bool = False,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        c = t.memory_entry.c
        query = select(t.memory_entry).where(c.project_id == mine.project.id)
        if member_id is not None:
            if store == "community":
                raise invalid({"member_id": "team_only"}, "member_id names a team")
            query = query.where(c.team_membership == _team(conn, mine, member_id).id)
        elif store == "team":
            query = query.where(memory.readable_teams(mine))
        elif store == "community":
            query = query.where(c.store == "community")
        else:
            query = query.where(or_(c.store == "community", memory.readable_teams(mine)))
        if not deleted:
            query = query.where(c.deleted_at.is_(None))
        if cursor is not None:
            after_at, after_id = paging.uncursor(cursor)
            query = query.where(
                or_(c.created_at < after_at, and_(c.created_at == after_at, c.id < after_id))
            )
        query = query.order_by(c.created_at.desc(), c.id.desc())
        if q is None:
            rows = conn.execute(query.limit(limit + 1)).all()
        else:
            # A substring of the text or a tag, matched here (context/memory.md): the live
            # text is capped at 64 KiB a store; with `deleted=true` the tombstones add rows.
            rows = [r for r in conn.execute(query).all() if _matches(r, q)][: limit + 1]
        page = rows[:limit]
        next_cursor = paging.cursor(page[-1].created_at, page[-1].id) if len(rows) > limit else None
        items = [memory.entry_view(conn, r) for r in page]
        return JSONResponse({"items": items, "next_cursor": next_cursor})


@router.post("/projects/{owner}/{slug}/memory")
def post_memory(slug: str, body: EntryIn, request: Request, caller: AnyCaller) -> JSONResponse:
    if not body.text.strip():
        raise invalid({"text": "blank"}, "an entry needs text")

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        if body.store == "team":
            if mine.kind != "agent":
                raise forbidden(message="team memory is written by the team's agents")
        elif mine.kind == "agent":
            return _propose_community(conn, mine, caller, body)
        else:
            mine.require("project:admin")
        entry_id = memory.add_entry(
            conn,
            mine.project.id,
            memory.Writer.of(mine, caller),
            caller.actor(mine.id),
            body.store,
            body.text,
            body.tags,
        )
        return idempotency.Outcome(201, "memory", entry_id, memory.load_entry(conn, entry_id))

    return idempotency.run(engine_of(request), request, caller, action)


def _load_proposal(conn: Connection, request_id: str) -> dict[str, Any]:
    """A replayed proposal answers as the first time: the request with its proposal."""
    row = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
    return request_view(conn, row, with_proposal=True)


idempotency.LOADERS["proposal_request"] = idempotency.plain(_load_proposal)


def _propose_community(
    conn: Connection, mine: Membership, caller: Caller, body: EntryIn
) -> idempotency.Outcome:
    """An agent's community entry is a `consent` request to `owner` carrying the entry
    (§19.2); a human with `project:admin` confirms it and the go stores it."""
    if memory.size(body.text) > memory.ENTRY_MAX:  # refused now, not at the go
        raise invalid({"text": "too_long"}, "an entry is at most 2 KiB")
    request_id = file_consent(
        conn,
        mine,
        caller,
        "Add an entry to the community memory",
        "An agent proposes the entry in `memory_proposal` for the community memory. "
        "A project admin's go stores it with the agent as its author.",
        proposal=memory.proposal(body.text, body.tags),
    )
    # The asker's own answer, as its `GET …/requests/{id}` shows the request (§19.2).
    view = _load_proposal(conn, request_id)
    return idempotency.Outcome(202, "proposal_request", request_id, view)


@router.delete("/projects/{owner}/{slug}/memory/{entry_id}")
def delete_memory(
    slug: str,
    entry_id: str,
    request: Request,
    caller: AnyCaller,
    body: Annotated[DeleteIn | None, Body()] = None,
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        row = conn.execute(
            select(t.memory_entry).where(
                t.memory_entry.c.id == entry_id, t.memory_entry.c.project_id == mine.project.id
            )
        ).first()
        if row is None:
            raise not_found()
        if row.store == "team":
            # Readable first: refusing another team's agent with `humans_only` would tell
            # it that the entry exists (§1.3). An agent reads its own team only, so this
            # is also what keeps an admin agent from deleting another team's memory.
            if not memory.reads_team(conn, mine, memory.member(conn, row.team_membership)):
                raise not_found()
        elif mine.kind == "agent":
            raise humans_only("agents never delete community memory; propose a replacement")
        else:
            mine.require("project:admin")
        row = memory.delete_entry(conn, row, mine, caller, body.reason if body else None)
        return idempotency.Outcome(200, "memory", entry_id, memory.entry_view(conn, row))

    return idempotency.run(engine_of(request), request, caller, action)
