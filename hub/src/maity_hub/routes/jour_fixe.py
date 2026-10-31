"""The jour fixe's endpoints (docs/api.md §20.9), part 1: the overview, the series and their
moderators, the rounds, the manual start of a series, and the answers."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, and_, or_, select

from maity_hub import clock, events, group_chats, idempotency, namespace, paging
from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of, reader_of
from maity_hub.errors import ApiError, invalid, not_found, rate_limited
from maity_hub.jourfixe import (
    answers,
    exchange,
    moderators,
    redaction,
    rounds,
    series,
    triage,
    views,
)
from maity_hub.models import Strict
from maity_hub.models import markdown as text_field
from maity_hub.namespace import ProjectRoute

router = APIRouter(route_class=ProjectRoute)

PAGE_DEFAULT, PAGE_MAX = 50, 200


class StartIn(Strict):
    reason: str = text_field(min_length=1)


class SeriesIn(Strict):
    """A series as written (§20.1); `PATCH` sends only the fields it changes."""

    topic: str | None = Field(default=None, min_length=1, max_length=300)
    circle: Literal["owner", "humans", "all"] | None = None
    circle_owner: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None
    recurrence: dict[str, Any] | None = None
    time: str | None = Field(default=None, max_length=5)
    timezone: str | None = Field(default=None, max_length=64)
    answer_window_minutes: int | None = None
    step_window_minutes: int | None = None
    report_window_hours: int | None = None
    reason: str = text_field(min_length=1)


class GrantIn(Strict):
    member_id: str = Field(min_length=1, max_length=64)
    reason: str = text_field(min_length=1)


class AnswerIn(Strict):
    went_well: str | None = Field(default=None, max_length=answers.TEXT_MAX)
    went_badly: str | None = Field(default=None, max_length=answers.TEXT_MAX)
    would_help: str | None = Field(default=None, max_length=answers.TEXT_MAX)
    anonymous: bool = False


class ItemIn(Strict):
    text: str = Field(min_length=1, max_length=exchange.ITEM_BYTES)
    from_: str = Field(alias="from", min_length=1, max_length=64)


class ProposalIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=exchange.REASON_BYTES)


class TopicIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    summary: str | None = Field(default=None, max_length=exchange.SUMMARY_BYTES)
    items: list[ItemIn] = Field(default_factory=list, max_length=20)
    proposals: list[ProposalIn] = Field(default_factory=list, max_length=20)


class StatementIn(Strict):
    topics: list[TopicIn] = Field(min_length=1, max_length=20)


class PostIn(Strict):
    step: Literal["response", "reply", "rejoinder", "further"]
    topic_id: str = Field(min_length=1, max_length=16)
    body: str = Field(min_length=1, max_length=exchange.POST_BYTES)
    to: list[str] | None = Field(default=None, max_length=50)
    in_reply_to: list[str] | None = Field(default=None, max_length=50)


class StepIn(Strict):
    reason: str = text_field(min_length=1)
    members: list[str] | None = Field(default=None, min_length=1, max_length=50)
    topics: list[str] | None = Field(default=None, min_length=1, max_length=20)


class BasisIn(Strict):
    rules_version: int = Field(ge=1)
    human_id: str = Field(min_length=1, max_length=64)
    preferences_version: int


class DecisionIn(Strict):
    outcome: Literal["adopt", "reject"]
    reason: str = text_field(min_length=1)
    basis: BasisIn


class FindingIn(Strict):
    topic_id: str | None = Field(default=None, max_length=16)
    text: str = Field(min_length=1, max_length=triage.FINDING_BYTES)


class ReportProposalIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=triage.REASON_BYTES)
    topic_id: str | None = Field(default=None, max_length=16)
    statement_proposal_id: str | None = Field(default=None, max_length=16)
    triage: Literal["decided", "to_owner"]
    humans_only: bool = False
    decision: DecisionIn | None = None


class ReportIn(Strict):
    summary: str | None = Field(default=None, max_length=triage.SUMMARY_BYTES)
    findings: list[FindingIn] = Field(default_factory=list, max_length=triage.FINDINGS_MAX)
    proposals: list[ReportProposalIn] = Field(default_factory=list, max_length=triage.PROPOSALS_MAX)


def _now(conn: Connection, rows: list[Any]) -> dict[str, set[str]]:
    """Per round its current participants (§20.7)."""
    return exchange.participants_now(conn, rows)


def _readers(conn: Connection, rows: list[Any]) -> dict[str, set[str]]:
    """Per round who reads a redaction's reason in its thread (§8.5)."""
    found = group_chats.reason_readers(conn, [r.conversation_id for r in rows if r.conversation_id])
    return {r.id: found.get(r.conversation_id, set()) for r in rows}


def _views(conn: Connection, rows: list[Any], slug: str, reader: Any) -> list[dict[str, Any]]:
    now, readers = _now(conn, rows), _readers(conn, rows)
    return [views.full(r, slug, now[r.id], reader, readers[r.id]) for r in rows]


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
    slug = namespace.name_of(conn, row.project_id)
    return _views(conn, [row], slug, None)[0]  # a replay: no reader, no reason


def answer_view(conn: Connection, answer_id: str) -> dict[str, Any]:
    """A named answer's replay: what its first call answered (an anonymous one has none)."""
    row = conn.execute(select(t.jour_fixe_answer).where(t.jour_fixe_answer.c.id == answer_id)).one()
    return {"round_id": row.round_id, "anonymous": False, "id": row.id}


def series_view(conn: Connection, series_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.jour_fixe_series).where(t.jour_fixe_series.c.id == series_id)).one()
    return series.view(conn, row)


def _member_now(conn: Connection, project_id: str, request: Request) -> Any:
    """A replay answers only a caller who may read the project now: a removed member
    gets `not_found`, as on any read (as conversations' replays do)."""
    slug = namespace.name_of(conn, project_id)
    mine = membership(conn, request.state.caller, str(slug))
    mine.require("project:read")
    return mine


def _round_project(conn: Connection, round_id: str) -> str:
    found: str = conn.execute(
        select(t.jour_fixe_round.c.project_id).where(t.jour_fixe_round.c.id == round_id)
    ).scalar_one()
    return found


def _replay_round(conn: Connection, round_id: str, request: Request) -> dict[str, Any]:
    _member_now(conn, _round_project(conn, round_id), request)
    return round_view(conn, round_id)


def _replay_answer(conn: Connection, answer_id: str, request: Request) -> dict[str, Any]:
    round_id = conn.execute(
        select(t.jour_fixe_answer.c.round_id).where(t.jour_fixe_answer.c.id == answer_id)
    ).scalar_one()
    _member_now(conn, _round_project(conn, round_id), request)
    return answer_view(conn, answer_id)


def _replay_series(conn: Connection, series_id: str, request: Request) -> dict[str, Any]:
    return series_view(conn, series_id)


idempotency.LOADERS["jour_fixe_round"] = _replay_round
idempotency.LOADERS["jour_fixe_answer"] = _replay_answer
idempotency.LOADERS["jour_fixe_series"] = _replay_series


def _replay_grant(conn: Connection, series_id: str, request: Request) -> dict[str, Any]:
    """A replayed `202`: the series as it stands now, and the grant's consent requests."""
    row = conn.execute(select(t.jour_fixe_series).where(t.jour_fixe_series.c.id == series_id)).one()
    ids = [
        r.owner_request_id or r.keeper_request_id
        for r in series.grants(conn, series_id)
        if r.state == "pending"
    ]
    return {"series": series.view(conn, row), "requests": [i for i in ids if i]}


idempotency.LOADERS["jour_fixe_grant"] = _replay_grant


def _last_reported(conn: Connection, series_id: str) -> Any | None:
    return conn.execute(
        select(t.jour_fixe_round)
        .where(
            t.jour_fixe_round.c.series_id == series_id,
            t.jour_fixe_round.c.status == "reported",
        )
        .order_by(t.jour_fixe_round.c.scheduled_for.desc())
    ).first()


@router.get("/projects/{owner}/{slug}/jour-fixe")
def overview(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    """Every series the caller may see, with its next slot, its round not yet reported and
    its newest reported one (§20.9)."""
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        now = clock.now()
        shown = []
        for row in series.of_project(conn, mine.project.id):
            seen = series.sight(conn, row, mine)
            if seen is None:
                continue
            entry = series.view(conn, row, seen)
            slot = rounds.next_at(row, now)
            entry["next_at"] = clock.rfc3339(slot) if slot is not None else None
            if seen == "full":
                running, last = rounds.current(conn, row.id), _last_reported(conn, row.id)
                found = [r for r in (running, last) if r is not None]
                views_of = dict(
                    zip([r.id for r in found], _views(conn, found, slug, mine), strict=True)
                )
                entry["current_round"] = views_of[running.id] if running else None
                entry["last_round"] = views_of[last.id] if last else None
            shown.append(entry)
        return JSONResponse({"series": shown})


@router.get("/projects/{owner}/{slug}/jour-fixe/series")
def list_series(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        items = []
        for row in series.of_project(conn, mine.project.id):
            seen = series.sight(conn, row, mine)
            if seen is not None:
                items.append(series.view(conn, row, seen))
        return JSONResponse({"items": items})


def _fields(body: SeriesIn) -> dict[str, Any]:
    return {k: getattr(body, k) for k in body.model_fields_set if k != "reason"}


def _visible(conn: Connection, mine: Any, series_id: str) -> Any:
    """The series, or `not_found` when the caller may not see it (§20.1)."""
    row = series.find(conn, mine.project.id, series_id)
    if series.sight(conn, row, mine) is None:
        raise not_found()
    return row


@router.post("/projects/{owner}/{slug}/jour-fixe/series")
def create_series(slug: str, body: SeriesIn, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        project = events.lock_project(conn, mine.project.id)
        if body.topic is None:
            raise invalid({"topic": "required"})
        if body.circle is None:
            raise invalid({"circle": "required"})
        row = series.create(conn, project, mine, _fields(body), caller.actor(mine.id))
        return idempotency.Outcome(201, "jour_fixe_series", row.id, series.view(conn, row))

    return idempotency.run(engine_of(request), request, caller, action)


@router.patch("/projects/{owner}/{slug}/jour-fixe/series/{series_id}")
def patch_series(
    slug: str, series_id: str, body: SeriesIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        project = events.lock_project(conn, mine.project.id)
        row = _visible(conn, mine, series_id)
        row = series.update_series(conn, project, row, mine, _fields(body), caller.actor(mine.id))
        return idempotency.Outcome(200, "jour_fixe_series", row.id, series.view(conn, row))

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/projects/{owner}/{slug}/jour-fixe/series/{series_id}")
def delete_series(
    slug: str, series_id: str, body: StartIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    with events.transaction(engine_of(request)) as conn:
        mine = membership(conn, caller, slug)
        project = events.lock_project(conn, mine.project.id)
        row = _visible(conn, mine, series_id)
        return JSONResponse(series.delete_series(conn, project, row, mine, caller.actor(mine.id)))


def _member(conn: Connection, project_id: str, member_id: str) -> Any:
    row = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project_id,
            or_(t.membership.c.agent_id == member_id, t.membership.c.human_id == member_id),
            t.membership.c.active.is_(True),
        )
    ).first()
    if row is None:
        raise invalid({"member_id": "not_a_member"})
    return row


@router.post("/projects/{owner}/{slug}/jour-fixe/series/{series_id}/moderators")
def grant_moderator(
    slug: str, series_id: str, body: GrantIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        project = events.lock_project(conn, mine.project.id)
        row = _visible(conn, mine, series_id)
        member = _member(conn, project.id, body.member_id)
        status, shown = moderators.grant(
            conn, project, row, mine, caller, member, caller.actor(mine.id)
        )
        if status == 202:
            return idempotency.Outcome(202, "jour_fixe_grant", row.id, shown)
        return idempotency.Outcome(201, "jour_fixe_series", row.id, shown)

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/projects/{owner}/{slug}/jour-fixe/series/{series_id}/moderators/{member_id}")
def end_moderator(
    slug: str, series_id: str, member_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    with events.transaction(engine_of(request)) as conn:
        mine = membership(conn, caller, slug)
        project = events.lock_project(conn, mine.project.id)
        row = _visible(conn, mine, series_id)
        member = conn.execute(
            select(t.membership).where(
                t.membership.c.project_id == project.id,
                or_(t.membership.c.agent_id == member_id, t.membership.c.human_id == member_id),
            )
        ).first()
        if member is None:
            raise not_found()
        row = series.end_right(conn, project, row, mine, member, caller.actor(mine.id))
        return JSONResponse(series.view(conn, row))


# --- rounds ------------------------------------------------------------------------------------


@router.get("/projects/{owner}/{slug}/jour-fixe/rounds")
def list_rounds(
    slug: str,
    request: Request,
    caller: AnyCaller,
    status: str | None = None,
    series_id: str | None = Query(default=None, alias="series"),
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
        if series_id is not None:
            query = query.where(c.series_id == series_id)
        bound = paging.scope(status=status, series=series_id)
        if cursor is not None:
            after_at, after_id = paging.uncursor(cursor, bound)
            query = query.where(
                or_(c.scheduled_for < after_at, and_(c.scheduled_for == after_at, c.id < after_id))
            )
        rows = conn.execute(
            query.order_by(c.scheduled_for.desc(), c.id.desc()).limit(limit + 1)
        ).all()
        page = rows[:limit]
        next_cursor = (
            paging.cursor(page[-1].scheduled_for, page[-1].id, bound) if len(rows) > limit else None
        )
        return JSONResponse(
            {"items": _views(conn, list(page), slug, mine), "next_cursor": next_cursor}
        )


def _observer_round(conn: Connection, caller: Caller, slug: str, round_id: str) -> dict[str, Any]:
    """An agent's owner outside the project reads a round its agent takes part in, as the
    minimal projection; to anyone else the project does not exist (§20.7)."""
    project = namespace.resolve(conn, slug)
    if project is None or caller.kind != "human":
        raise not_found()
    row = conn.execute(
        select(t.jour_fixe_round).where(
            t.jour_fixe_round.c.id == round_id, t.jour_fixe_round.c.project_id == project.id
        )
    ).first()
    if row is None:
        raise not_found()
    active = _now(conn, [row])[row.id]
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
    # Never a participant of the thread, so never a reader of a redaction's reason.
    return views.minimal(row, slug, active)


@router.get("/projects/{owner}/{slug}/jour-fixe/rounds/{round_id}")
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
        return JSONResponse(_views(conn, [row], slug, mine)[0])


@router.post("/projects/{owner}/{slug}/jour-fixe/series/{series_id}/rounds")
def start(
    slug: str, series_id: str, body: StartIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    """A round of the series now, by its keepers and moderators (§20.1)."""

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        project = events.lock_project(conn, mine.project.id)
        row_series = _visible(conn, mine, series_id)
        if not series.is_keeper(row_series, mine) and mine.id not in series.moderators(
            conn, row_series.id
        ):
            raise series.keeper_refused()
        if row_series.circle == "owner" and not series.owner_member(conn, row_series):
            raise ApiError(
                409, "jour_fixe_state", "the series' owner left", {"reason": "circle_owner_gone"}
            )
        if rounds.manual_starts_today(conn, row_series.id) >= rounds.MANUAL_PER_DAY:
            raise rate_limited(3600)
        row = rounds.open_round(
            conn,
            project,
            row_series,
            trigger="manual",
            scheduled_for=clock.now(),
            reason=body.reason,
            actor=caller.actor(mine.id),
        )
        return idempotency.Outcome(201, "jour_fixe_round", row.id, round_view(conn, row.id))

    return idempotency.run(engine_of(request), request, caller, action)


# --- answers ------------------------------------------------------------------------------------


@router.post("/projects/{owner}/{slug}/jour-fixe/rounds/{round_id}/answers")
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


@router.get("/projects/{owner}/{slug}/jour-fixe/rounds/{round_id}/answers")
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


@router.delete("/projects/{owner}/{slug}/jour-fixe/rounds/{round_id}/answers/mine")
def withdraw_answer(slug: str, round_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    # No idempotency record: a withdrawal leaves nothing that names the author (§20.4).
    with events.transaction(engine_of(request)) as conn:
        mine = membership(conn, caller, slug)
        events.lock_project(conn, mine.project.id)
        row = _round(conn, mine.project.id, round_id)
        return JSONResponse(answers.withdraw(conn, row, mine))


# --- the statement and the exchange (§20.5) -----------------------------------------------------


@router.post("/projects/{owner}/{slug}/jour-fixe/rounds/{round_id}/statement")
def statement(
    slug: str, round_id: str, body: StatementIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        row = _round(conn, mine.project.id, round_id)
        topics = [topic.model_dump(by_alias=True) for topic in body.topics]
        exchange.submit_statement(conn, row, mine, topics, caller.actor(mine.id))
        return idempotency.Outcome(201, "jour_fixe_round", row.id, round_view(conn, row.id))

    return idempotency.run(engine_of(request), request, caller, action)


def _replay_post(conn: Connection, ref: str, request: Request) -> dict[str, Any]:
    """A post's replay (`<round id>/<post id>`), for a member only, as it shows now."""
    round_id, post_id = ref.split("/", 1)
    row = conn.execute(select(t.jour_fixe_round).where(t.jour_fixe_round.c.id == round_id)).one()
    mine = _member_now(conn, row.project_id, request)
    found: dict[str, Any] = next(p for p in row.posts if p["id"] == post_id)
    return views.post(found, mine, _readers(conn, [row])[row.id])


idempotency.LOADERS["jour_fixe_post"] = _replay_post


@router.post("/projects/{owner}/{slug}/jour-fixe/rounds/{round_id}/posts")
def post(
    slug: str, round_id: str, body: PostIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        row = _round(conn, mine.project.id, round_id)
        made = exchange.submit_post(conn, row, mine, body.model_dump(), caller.actor(mine.id))
        return idempotency.Outcome(
            201, "jour_fixe_post", f"{row.id}/{made['id']}", views.post(made)
        )

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{owner}/{slug}/jour-fixe/rounds/{round_id}/steps")
def further_step(
    slug: str, round_id: str, body: StepIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        row = _round(conn, mine.project.id, round_id)
        exchange.add_step(conn, row, mine, body.reason, body.members, body.topics)
        return idempotency.Outcome(201, "jour_fixe_round", row.id, round_view(conn, row.id))

    return idempotency.run(engine_of(request), request, caller, action)


# --- the report (§20.6) -------------------------------------------------------------------------


def report_view(conn: Connection, round_id: str) -> dict[str, Any]:
    """The round, and what its report filed: the requests and the cards opened."""
    row = conn.execute(select(t.jour_fixe_round).where(t.jour_fixe_round.c.id == round_id)).one()
    proposals = (row.report or {}).get("proposals", [])
    return {
        "round": round_view(conn, round_id),
        "requests": [p["request_id"] for p in proposals if p["request_id"]],
        "tasks": [p["task_id"] for p in proposals if p["task_id"]],
    }


def _replay_report(conn: Connection, round_id: str, request: Request) -> dict[str, Any]:
    _member_now(conn, _round_project(conn, round_id), request)
    return report_view(conn, round_id)


idempotency.LOADERS["jour_fixe_report"] = _replay_report


@router.post("/projects/{owner}/{slug}/jour-fixe/rounds/{round_id}/report")
def report(
    slug: str, round_id: str, body: ReportIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    fg = reader_of(request)

    def action(conn: Connection) -> idempotency.Outcome:
        events.lock_project(conn, membership(conn, caller, slug).project.id)
        # The caller's membership and role as of the lock: a demotion or a removal that
        # commits first decides whether it may still decide (§20.6).
        mine = membership(conn, caller, slug)
        row = _round(conn, mine.project.id, round_id)
        triage.submit_report(conn, row, mine, body.model_dump(), caller.actor(mine.id), fg)
        return idempotency.Outcome(200, "jour_fixe_report", row.id, report_view(conn, row.id))

    return idempotency.run(engine_of(request), request, caller, action)


# --- redaction (§20.8) ----------------------------------------------------------------------------


class RedactIn(Strict):
    target: str = Field(min_length=1, max_length=64)
    reason: str = text_field(min_length=1)


@router.post("/projects/{owner}/{slug}/jour-fixe/rounds/{round_id}/redact")
def redact(
    slug: str, round_id: str, body: RedactIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        events.lock_project(conn, membership(conn, caller, slug).project.id)
        mine = membership(conn, caller, slug)  # its role as of the lock
        row = _round(conn, mine.project.id, round_id)
        redaction.redact(conn, row, mine, body.target, body.reason, caller.actor(mine.id))
        shown = _views(conn, [_round(conn, mine.project.id, round_id)], slug, mine)[0]
        return idempotency.Outcome(200, "jour_fixe_round", row.id, shown)

    return idempotency.run(engine_of(request), request, caller, action)
