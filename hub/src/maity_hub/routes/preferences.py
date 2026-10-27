"""A human's preferences (docs/api.md §19.4): the human's own endpoints, the agents'
read, and the proposals of an admin agent or the human's proxy."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, select

from maity_hub import clock, events, idempotency, namespace, preferences
from maity_hub import tables as t
from maity_hub.access import member_row, membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, invalid, not_found, rate_limited
from maity_hub.models import Strict
from maity_hub.models import markdown as text_field
from maity_hub.namespace import ProjectRoute
from maity_hub.routes.requests import file_to_human, load_request

router = APIRouter(route_class=ProjectRoute)

PAGE_DEFAULT, PAGE_MAX = 50, 200


class PreferencesIn(Strict):
    markdown: str = Field(max_length=16384)
    base_version: int | None = Field(default=None, ge=0)


class IncludeIn(Strict):
    include: bool


class ProposalIn(Strict):
    markdown: str = Field(max_length=16384)
    base_version: int = Field(ge=0)
    reason: str = text_field(min_length=1)


def _human(caller: Any) -> str:
    if caller.kind != "human":
        raise ApiError(403, "forbidden", "a human's own preferences", {"reason": "humans_only"})
    human_id: str = caller.human_id
    return human_id


def _mine(conn: Connection, human_id: str) -> dict[str, Any]:
    shown = preferences.view(conn, human_id)
    rows = conn.execute(
        select(t.project.c.slug, t.membership.c.preferences_include)
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(t.membership.c.human_id == human_id, t.membership.c.active.is_(True))
        .order_by(t.project.c.slug)
    ).all()
    return {**shown, "projects": [{"slug": r.slug, "include": r.preferences_include} for r in rows]}


def load_preferences(conn: Connection, human_id: str) -> dict[str, Any]:
    return _mine(conn, human_id)


idempotency.LOADERS["preferences"] = idempotency.plain(load_preferences)


@router.get("/me/preferences")
def get_mine(request: Request, caller: AnyCaller) -> JSONResponse:
    human_id = _human(caller)
    with engine_of(request).begin() as conn:
        return JSONResponse(_mine(conn, human_id))


@router.put("/me/preferences")
def put_mine(body: PreferencesIn, request: Request, caller: AnyCaller) -> JSONResponse:
    human_id = _human(caller)

    def action(conn: Connection) -> idempotency.Outcome:
        preferences.write(
            conn,
            human_id,
            body.markdown,
            by=("human", human_id),
            proposed_by=None,
            confirmed_by=None,
            base_version=body.base_version,
            actor_of=caller.actor,
        )
        return idempotency.Outcome(200, "preferences", human_id, _mine(conn, human_id))

    return idempotency.run(engine_of(request), request, caller, action)


@router.get("/me/preferences/versions")
def get_versions(
    request: Request,
    caller: AnyCaller,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    human_id = _human(caller)
    if cursor is not None and not cursor.isdigit():
        raise invalid({"cursor": "invalid"})
    with engine_of(request).begin() as conn:
        before = int(cursor) if cursor is not None else None
        return JSONResponse(preferences.versions(conn, human_id, before, limit))


@router.put("/me/preferences/projects/{owner}/{slug}")
def put_include(slug: str, body: IncludeIn, request: Request, caller: AnyCaller) -> JSONResponse:
    human_id = _human(caller)

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        preferences.switch(conn, mine.row, body.include, caller.actor(mine.id))
        return idempotency.Outcome(200, "preferences", human_id, _mine(conn, human_id))

    return idempotency.run(engine_of(request), request, caller, action)


def _the_human(conn: Connection, project_id: str, member_id: str) -> Any:
    """The human member `member_id` of the project; an agent's or a non-member's id is
    `not_found`, as for every reader who may not see it."""
    if not member_id.startswith("hum-"):
        raise not_found()
    try:
        return member_row(conn, project_id, member_id)
    except ApiError:
        raise not_found() from None


@router.get("/projects/{owner}/{slug}/members/{member_id}/preferences")
def get_theirs(slug: str, member_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    """The human itself, an agent member while the project reads the text, or the agent
    given its owner's text, the owner a member here or not; `not_found` for anyone else
    and for any id that is not a human's (§19.4)."""
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        if not member_id.startswith("hum-"):
            raise not_found()
        if not preferences.readable(conn, mine.row, mine.project, member_id):
            raise not_found()
        return JSONResponse(preferences.view(conn, member_id))


@router.post("/projects/{owner}/{slug}/members/{member_id}/preferences/proposals")
def propose(
    slug: str, member_id: str, body: ProposalIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    if preferences.size(body.markdown) > preferences.MAX_BYTES:
        raise invalid({"markdown": "too_long"}, "preferences are at most 8 KiB")

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        human = _the_human(conn, mine.project.id, member_id)
        if human.active is not True:
            raise not_found()
        if not preferences.may_propose(conn, mine, member_id):
            raise ApiError(
                403,
                "forbidden",
                "an admin agent or the human's proxy proposes preferences",
                {"reason": "may_not_propose"},
            )
        # Under the project lock: two proposals at once cannot both pass the caps.
        events.lock_project(conn, mine.project.id)
        recent = preferences.recent_proposals(conn, mine.id, member_id)
        if len(recent) >= preferences.PROPOSALS_PER_DAY:
            oldest = min(r.created_at for r in recent)
            wait = int((oldest + preferences.PROPOSAL_WINDOW - clock.now()).total_seconds())
            raise rate_limited(max(wait, 1))
        from maity_hub.routes.requests import close_request

        for older in preferences.open_proposals(conn, mine.id, member_id):
            # One open proposal per membership and human, however old the open one is.
            close_request(conn, older.id, "withdrawn", caller.actor(mine.id), reason="superseded")
        handle = conn.execute(
            select(t.human.c.handle).where(t.human.c.id == member_id)
        ).scalar_one()
        request_id = file_to_human(
            conn,
            mine,
            caller,
            member_id,
            f"Preferences for {handle}",
            body.reason,
            {
                "kind": preferences.KIND,
                "human_id": member_id,
                "markdown": body.markdown,
                "base_version": body.base_version,
                "reason": body.reason,
                "proposed_by": {
                    "kind": "agent",
                    "member_id": mine.principal_id,
                    "instance": mine.instance,
                    "handle": conn.execute(
                        select(t.agent_profile.c.handle).where(
                            t.agent_profile.c.id == mine.principal_id
                        )
                    ).scalar_one(),
                    "project": namespace.full_name(conn, mine.project),
                },
            },
        )
        return idempotency.Outcome(202, "request", request_id, load_request(conn, request_id))

    return idempotency.run(engine_of(request), request, caller, action)
