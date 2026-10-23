"""The jour fixe's endpoints (docs/api.md §20.9), part 1: the overview, the moderator
order, the rounds, the manual start, and the answers."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, and_, or_, select

from maity_hub import clock, events, idempotency, paging, policy, rules
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found, rate_limited
from maity_hub.jourfixe import answers, rounds, schedule, views
from maity_hub.models import Strict
from maity_hub.models import markdown as text_field

router = APIRouter()

PAGE_DEFAULT, PAGE_MAX = 50, 200


class StartIn(Strict):
    reason: str = text_field(min_length=1)


class ModeratorsIn(Strict):
    order: list[str] | None = Field(max_length=50)
    reason: str = text_field(min_length=1)


class AnswerIn(Strict):
    went_well: str | None = Field(default=None, max_length=answers.TEXT_MAX)
    went_badly: str | None = Field(default=None, max_length=answers.TEXT_MAX)
    would_help: str | None = Field(default=None, max_length=answers.TEXT_MAX)
    anonymous: bool = False


def _active(conn: Connection, project_id: str) -> set[str]:
    rows = conn.execute(
        select(t.membership.c.agent_id, t.membership.c.human_id).where(
            t.membership.c.project_id == project_id, t.membership.c.active.is_(True)
        )
    ).all()
    return {r.agent_id or r.human_id for r in rows}


def _round(conn: Connection, project_id: str, round_id: str) -> Any:
    row = conn.execute(
        select(t.jour_fixe_round).where(
            t.jour_fixe_round.c.id == round_id, t.jour_fixe_round.c.project_id == project_id
        )
    ).first()
    if row is None:
        raise not_found()
    return row


def round_view(conn: Connection, round_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.jour_fixe_round).where(t.jour_fixe_round.c.id == round_id)).one()
    slug = conn.execute(
        select(t.project.c.slug).where(t.project.c.id == row.project_id)
    ).scalar_one()
    return views.full(row, slug, _active(conn, row.project_id))


def answer_view(conn: Connection, answer_id: str) -> dict[str, Any]:
    """A named answer's replay: what its first call answered (an anonymous one has none)."""
    row = conn.execute(select(t.jour_fixe_answer).where(t.jour_fixe_answer.c.id == answer_id)).one()
    return {"round_id": row.round_id, "anonymous": False, "id": row.id}


def moderators_view(conn: Connection, project_id: str) -> dict[str, Any]:
    project = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
    return {"order": project.jour_fixe_moderators, "moderators": _resolved(conn, project)}


idempotency.LOADERS["jour_fixe_round"] = idempotency.plain(round_view)
idempotency.LOADERS["jour_fixe_answer"] = idempotency.plain(answer_view)
idempotency.LOADERS["jour_fixe_moderators"] = idempotency.plain(moderators_view)


def _resolved(conn: Connection, project: Any) -> list[str]:
    return [m.agent_id for m in rounds.moderator_order(conn, project)]


# --- the overview and the moderator order ----------------------------------------------------


@router.get("/projects/{slug}/jour-fixe")
def overview(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        project = mine.project
        slot = None
        if project.jour_fixe and project.jour_fixe.get("enabled"):
            slot = schedule.next_slot(project.jour_fixe, clock.now(), rounds.anchor_date(project))
        running = rounds.current(conn, project.id)
        last = conn.execute(
            select(t.jour_fixe_round)
            .where(
                t.jour_fixe_round.c.project_id == project.id,
                t.jour_fixe_round.c.status == "reported",
            )
            .order_by(t.jour_fixe_round.c.scheduled_for.desc())
        ).first()
        active = _active(conn, project.id)
        return JSONResponse(
            {
                "policy": project.jour_fixe,
                "moderators": _resolved(conn, project),
                "next_at": clock.rfc3339(slot) if slot is not None else None,
                "current_round": views.full(running, slug, active) if running else None,
                "last_round": views.full(last, slug, active) if last else None,
            }
        )


@router.put("/projects/{slug}/jour-fixe/moderators")
def put_moderators(
    slug: str, body: ModeratorsIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    """The one policy field an agent writes: the admin agents order themselves (§20.2)."""

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        if not (mine.may("project:admin") or (mine.kind == "agent" and mine.role == "admin")):
            raise forbidden("project:admin", "a human with project:admin or an admin agent")
        project = events.lock_project(conn, mine.project.id)
        order = body.order
        if order is not None and not rounds.admin_agents_only(conn, project.id, order):
            raise invalid({"order": "not_admin_agent"})
        old = policy.of(project)
        new = {**old, "jour_fixe_moderators": order}
        if new != old:
            from sqlalchemy import update

            conn.execute(
                update(t.project).where(t.project.c.id == project.id).values(**policy.columns(new))
            )
            rules.bump(
                conn,
                project,
                "policy_changed",
                ["all"],
                {"old": old, "new": new, "reason": body.reason},
                actor=caller.actor(mine.id),
            )
        return idempotency.Outcome(
            200, "jour_fixe_moderators", project.id, moderators_view(conn, project.id)
        )

    return idempotency.run(engine_of(request), request, caller, action)


# --- rounds ------------------------------------------------------------------------------------


@router.get("/projects/{slug}/jour-fixe/rounds")
def list_rounds(
    slug: str,
    request: Request,
    caller: AnyCaller,
    status: str | None = None,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        c = t.jour_fixe_round.c
        query = select(t.jour_fixe_round).where(c.project_id == mine.project.id)
        if status is not None:
            query = query.where(c.status.in_([s for s in status.split(",") if s]))
        bound = paging.scope(status=status)
        if cursor is not None:
            after_at, after_id = paging.uncursor(cursor, bound)
            query = query.where(
                or_(c.scheduled_for < after_at, and_(c.scheduled_for == after_at, c.id < after_id))
            )
        rows = conn.execute(
            query.order_by(c.scheduled_for.desc(), c.id.desc()).limit(limit + 1)
        ).all()
        page = rows[:limit]
        active = _active(conn, mine.project.id)
        next_cursor = (
            paging.cursor(page[-1].scheduled_for, page[-1].id, bound) if len(rows) > limit else None
        )
        return JSONResponse(
            {"items": [views.full(r, slug, active) for r in page], "next_cursor": next_cursor}
        )


def _observer_round(conn: Connection, caller: Caller, slug: str, round_id: str) -> dict[str, Any]:
    """An agent's owner outside the project reads a round its agent takes part in, as the
    minimal projection; to anyone else the project does not exist (§20.7)."""
    project = conn.execute(select(t.project).where(t.project.c.slug == slug)).first()
    if project is None or caller.kind != "human":
        raise not_found()
    row = conn.execute(
        select(t.jour_fixe_round).where(
            t.jour_fixe_round.c.id == round_id, t.jour_fixe_round.c.project_id == project.id
        )
    ).first()
    if row is None:
        raise not_found()
    active = _active(conn, project.id)
    agents = [
        i["member_id"] for i in row.invited if i["kind"] == "agent" and i["member_id"] in active
    ]
    owned = conn.execute(
        select(t.agent_profile.c.id).where(
            t.agent_profile.c.id.in_(agents or ["-"]),
            t.agent_profile.c.owner_id == caller.human_id,
        )
    ).first()
    if owned is None:
        raise not_found()
    return views.minimal(row, slug, active)


@router.get("/projects/{slug}/jour-fixe/rounds/{round_id}")
def get_round(slug: str, round_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        try:
            mine = membership(conn, caller, slug)
        except ApiError as missing:
            if missing.status != 404:
                raise
            return JSONResponse(_observer_round(conn, caller, slug, round_id))
        mine.require("project:read")
        row = _round(conn, mine.project.id, round_id)
        return JSONResponse(views.full(row, slug, _active(conn, mine.project.id)))


@router.post("/projects/{slug}/jour-fixe/rounds")
def start(slug: str, body: StartIn, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("jour_fixe:start")
        project = events.lock_project(conn, mine.project.id)
        if rounds.manual_starts_today(conn, project.id) >= rounds.MANUAL_PER_DAY:
            raise rate_limited(3600)
        row = rounds.open_round(
            conn,
            project,
            trigger="manual",
            scheduled_for=clock.now(),
            reason=body.reason,
            actor=caller.actor(mine.id),
        )
        return idempotency.Outcome(201, "jour_fixe_round", row.id, round_view(conn, row.id))

    return idempotency.run(engine_of(request), request, caller, action)


# --- answers ------------------------------------------------------------------------------------


@router.post("/projects/{slug}/jour-fixe/rounds/{round_id}/answers")
def answer(
    slug: str, round_id: str, body: AnswerIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    texts = {f: getattr(body, f) for f in answers.FIELDS}

    def action(conn: Connection) -> tuple[int, dict[str, Any]]:
        mine = membership(conn, caller, slug)
        events.lock_project(conn, mine.project.id)
        row = _round(conn, mine.project.id, round_id)
        return 201, answers.submit(conn, row, mine, texts, body.anonymous)

    if body.anonymous:
        # The idempotency store keeps no record of an anonymous answer (§20.4): the key is
        # accepted and not stored, and a repeat is refused by the tag.
        idempotency.key_for(request, caller)
        with events.transaction(engine_of(request)) as conn:
            status, shown = action(conn)
        return JSONResponse(shown, status_code=status)

    def stored(conn: Connection) -> idempotency.Outcome:
        status, shown = action(conn)
        return idempotency.Outcome(status, "jour_fixe_answer", shown["id"], shown)

    return idempotency.run(engine_of(request), request, caller, stored)


@router.get("/projects/{slug}/jour-fixe/rounds/{round_id}/answers")
def read_answers(
    slug: str,
    round_id: str,
    request: Request,
    caller: AnyCaller,
    mine_only: bool = Query(False, alias="mine"),
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        row = _round(conn, mine.project.id, round_id)
        return JSONResponse({"items": answers.listed(conn, row, mine, mine_only)})


@router.delete("/projects/{slug}/jour-fixe/rounds/{round_id}/answers/mine")
def withdraw_answer(slug: str, round_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    # No idempotency record: a withdrawal leaves nothing that names the author (§20.4).
    with events.transaction(engine_of(request)) as conn:
        mine = membership(conn, caller, slug)
        events.lock_project(conn, mine.project.id)
        row = _round(conn, mine.project.id, round_id)
        return JSONResponse(answers.withdraw(conn, row, mine))
