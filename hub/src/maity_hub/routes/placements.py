"""Placements as humans and agents create, change and read them (docs/api.md §15.5,
§15.6). The rules are in `maity_hub.placements`; this module decides who may do what.

Three kinds of caller act on a placement. A human with `members:admin` who owns the
runner has *the right*: their action is their own consent. The owner of the agent
profile may stop, start and restart it. An agent with `agents:propose` may stop,
start, restart and delete, and proposes everything else under the project's
`spawn_requests`.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import ColumnElement, Connection, select

from maity_hub import events, handles, idempotency, namespace
from maity_hub import placements as pl
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found
from maity_hub.models import HANDLE_PATTERN, Strict, markdown, title
from maity_hub.namespace import ProjectRoute
from maity_hub.policy import CLOSED_STATES, REASON_STATES
from maity_hub.routes.members import validate_assignment
from maity_hub.routes.requests import file_consent
from maity_hub.runners import active_attachment, live_credential_id
from maity_hub.views import event_views

router = APIRouter(route_class=ProjectRoute)

CLONE_PATTERN = r"^[a-z0-9][a-z0-9-]{0,62}$"
NOT_NULLABLE = frozenset({"desired", "harness", "mode", "stop_grace_seconds"})
REPORTS_DEFAULT, REPORTS_MAX = 10, 50


class AgentRef(Strict):
    id: str | None = None
    handle: str | None = Field(default=None, pattern=HANDLE_PATTERN)
    display_name: str | None = title(default=None)


class WorkspaceIn(Strict):
    clone: str | None = Field(default=None, pattern=CLONE_PATTERN)
    branch: str | None = Field(default=None, min_length=1, max_length=255)


class PlacementCreate(Strict):
    agent: AgentRef
    role: str | None = None
    reports_to: str | None = None
    areas: list[str] | None = Field(default=None, max_length=50)
    capabilities: list[str] | None = Field(default=None, max_length=20)
    briefing: str | None = markdown(default=None)
    runner: str = Field(min_length=1, max_length=64)
    target: str | None = Field(default=None, min_length=1, max_length=200)
    harness: str
    mode: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    workspace: WorkspaceIn = Field(default_factory=WorkspaceIn)
    desired: Literal["running", "stopped"] = "running"
    stop_grace_seconds: int = Field(default=120, ge=0, le=900)
    reason: str | None = markdown(default=None)


class PlacementPatch(Strict):
    desired: Literal["running", "stopped"] | None = None
    harness: str | None = None
    mode: str | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    target: str | None = Field(default=None, min_length=1, max_length=200)
    stop_grace_seconds: int | None = Field(default=None, ge=0, le=900)
    reason: str | None = markdown(default=None)


class RestartIn(Strict):
    rejoin: bool = False


# --- who the caller is to a placement --------------------------------------------------------


def _runner(conn: Connection, runner_id: str) -> Any:
    return conn.execute(select(t.runner).where(t.runner.c.id == runner_id)).first()


def _has_right(mine: Membership, runner: Any) -> bool:
    """`members:admin` and ownership of the runner: the action is its own consent."""
    return (
        mine.kind == "human"
        and mine.may("members:admin")
        and runner is not None
        and runner.owner_id == mine.principal_id
    )


def _proposer(mine: Membership) -> bool:
    return mine.kind == "agent" and mine.may("agents:propose")


def _visible(mine: Membership, placement: Any) -> bool:
    if mine.kind == "human":
        return mine.may("project:read")
    return placement.membership_id == mine.id or mine.may("agents:propose")


def _briefing(mine: Membership, placement: Any) -> bool:
    return mine.may("members:admin") or placement.created_by == mine.principal_id


def _view(conn: Connection, mine: Membership, placement: Any) -> dict[str, Any]:
    return pl.view(
        conn, placement, viewer_id=mine.principal_id, briefing=_briefing(mine, placement)
    )


def _load(conn: Connection, placement_id: str, request: Request) -> dict[str, Any]:
    placement = pl.row(conn, placement_id)
    slug = namespace.name_of(conn, placement.project_id)
    caller: Caller = request.state.caller
    return _view(conn, membership(conn, caller, slug), placement)


idempotency.LOADERS["placement"] = _load


def _placement(conn: Connection, mine: Membership, placement_id: str) -> Any:
    found = conn.execute(
        select(t.placement).where(
            t.placement.c.id == placement_id, t.placement.c.project_id == mine.project.id
        )
    ).first()
    if found is None or not _visible(mine, found):
        raise not_found()
    return found


def _refused(refusal: pl.Refusal) -> ApiError:
    return ApiError(refusal.status, refusal.code, refusal.message, refusal.details)


def _transition(placement: Any) -> None:
    """Closed, or closing the uniform way: no change of spec, no start, no restart."""
    state = "closed" if placement.active is None else "closing" if placement.closing else None
    if state is not None:
        raise ApiError(
            409, "invalid_transition", f"the placement is {state}", {"from": state, "to": None}
        )


def _require_open(project: Any) -> None:
    """`desired: running` in an accepted or archived project is `project_closed` (§15.5)."""
    if project.state in CLOSED_STATES:
        raise ApiError(409, "project_closed", f"the project is {project.state}")


def _require_live(conn: Connection, runner: Any) -> None:
    if live_credential_id(conn, runner.id) is None:
        raise ApiError(409, "runner_revoked", "the runner has no live credential")


def _check_spec(runner: Any, spec: dict[str, Any], repository_url: str | None) -> None:
    if spec["harness"] not in pl.HARNESSES:
        raise invalid({"harness": "unknown"})
    if spec["mode"] not in pl.MODES:
        raise invalid({"mode": "unknown"})
    try:
        pl.check_offered(runner, spec["harness"], spec["mode"], spec["model"], spec["target"])
        pl.check_repository(runner, repository_url)
    except pl.Refusal as refusal:
        raise _refused(refusal) from None


def _exists(conn: Connection, *conditions: Any) -> None:
    found = conn.execute(
        select(t.placement.c.id).where(t.placement.c.active.is_(True), *conditions)
    ).first()
    if found is not None:
        raise ApiError(
            409, "placement_exists", "an active placement holds this", {"placement": found.id}
        )


# --- reading ----------------------------------------------------------------------------------


@router.get("/projects/{owner}/{slug}/placements")
def list_placements(
    slug: str, request: Request, caller: AnyCaller, closed: bool = False
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        shown: ColumnElement[bool] = t.placement.c.active.is_(True)
        if closed:
            shown = shown | (t.placement.c.closed_at >= pl.recently_closed())
        rows = [
            r
            for r in conn.execute(
                select(t.placement).where(t.placement.c.project_id == mine.project.id, shown)
            ).all()
            if _visible(mine, r)
        ]
        views = [_view(conn, mine, r) for r in rows]
        views.sort(key=lambda v: (v["agent"]["handle"] or "", not v["active"], v["id"]))
        return JSONResponse({"items": views, "next_cursor": None})


@router.get("/projects/{owner}/{slug}/placements/{placement_id}")
def get_placement(
    slug: str, placement_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        return JSONResponse(_view(conn, mine, _placement(conn, mine, placement_id)))


@router.get("/projects/{owner}/{slug}/placements/{placement_id}/reports")
def placement_reports(
    slug: str,
    placement_id: str,
    request: Request,
    caller: AnyCaller,
    limit: int = Query(default=REPORTS_DEFAULT, ge=1, le=REPORTS_MAX),
) -> JSONResponse:
    """The last reports, to everyone who may see the placement, whatever the events'
    audience (§15.6)."""
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        placement = _placement(conn, mine, placement_id)
        rows = conn.execute(
            select(t.event)
            .where(
                t.event.c.project_id == mine.project.id,
                t.event.c.subject_type == "placement",
                t.event.c.subject_id == placement.id,
                t.event.c.kind == "placement_reported",
            )
            .order_by(t.event.c.seq.desc())
            .limit(limit)
        ).all()
        # The reader decides what a redaction's reason shows (§8.5).
        return JSONResponse({"items": event_views(conn, rows, mine), "next_cursor": None})


# --- creating -------------------------------------------------------------------------------


@router.post("/projects/{owner}/{slug}/placements")
def create_placement(
    slug: str, body: PlacementCreate, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        project = events.lock_project(conn, mine.project.id)
        mine.require("members:admin" if mine.kind == "human" else "agents:propose")
        runner = _runner(conn, body.runner)
        if runner is None or active_attachment(conn, project.id, runner.id) is None:
            raise ApiError(409, "runner_not_attached", "the runner is not attached here")
        right = _has_right(mine, runner)
        if mine.kind == "human" and not right:
            raise forbidden(message="only the runner's owner places agents on it")
        if not right and project.spawn_requests == "off":
            raise forbidden(message="this project takes no placement proposals")
        if not right and not body.reason:
            raise invalid({"reason": "required"}, "a proposal says why")
        if project.state in REASON_STATES and not body.reason:
            raise invalid({"reason": "required"}, f"the project is in {project.state}: say why")
        # Whatever `desired` says: an active placement in a closed project would never
        # close, and one on a revoked runner never run (§15.5, §15.6).
        _require_open(project)
        _require_live(conn, runner)
        if pl.active_count(conn, project.id) >= project.max_placements:
            raise ApiError(
                409,
                "placement_quota",
                "the project's placements are at its limit",
                {"max": project.max_placements},
            )
        agent_values, handle = _agent_values(conn, mine, body, right)
        clone = body.workspace.clone or handle
        _exists(
            conn,
            t.placement.c.project_id == project.id,
            t.placement.c.runner_id == runner.id,
            t.placement.c.clone == clone,
        )
        spec = {
            "harness": body.harness,
            "mode": body.mode or pl.default_mode(runner, body.harness),
            "model": body.model,
            "target": body.target,
        }
        _check_spec(runner, spec, project.repository_url)
        proposed = not right and project.spawn_requests == "consent"
        credential_id = (
            pl.carried_credential(conn, agent_values["membership_id"], runner.id, clone)
            if agent_values.get("membership_id") is not None
            else None
        )
        values = {
            **agent_values,
            **spec,
            "project_id": project.id,
            "runner_id": runner.id,
            "clone": clone,
            "branch": body.workspace.branch,
            "desired": body.desired,
            "stop_grace_seconds": body.stop_grace_seconds,
            "approval_status": "pending" if proposed else "approved",
            "reason": body.reason,
            "credential_id": credential_id,
            "created_by": mine.principal_id if right else pl.profile_owner_of(conn, agent_values),
            "proposed_by": None if right else mine.id,
        }
        actor = caller.actor(mine.id)
        try:
            placement = pl.create(conn, values, actor, None if right or proposed else body.reason)
        except pl.Refusal as refusal:
            raise _refused(refusal) from None
        if proposed:
            _file(conn, mine, caller, placement, runner, "Start", body.reason, spec)
        return idempotency.Outcome(201, "placement", placement.id, _view(conn, mine, placement))

    return idempotency.run(engine_of(request), request, caller, action)


def _agent_values(
    conn: Connection, mine: Membership, body: PlacementCreate, right: bool
) -> tuple[dict[str, Any], str]:
    """The membership a placement runs, or the profile it will create (humans only)."""
    join_fields = {
        "role": body.role,
        "reports_to": body.reports_to,
        "areas": body.areas,
        "capabilities": body.capabilities,
        "briefing": body.briefing,
    }
    if body.agent.id is not None:
        if body.agent.handle is not None or body.agent.display_name is not None:
            raise invalid({"agent": "id_or_handle"}, "name an agent by id, or create one")
        given = sorted(k for k, v in join_fields.items() if v is not None)
        if given:
            raise invalid(
                {k: "not_with_agent_id" for k in given}, "a placement never changes a membership"
            )
        deleted = conn.execute(
            select(t.agent_profile.c.id).where(
                t.agent_profile.c.id == body.agent.id, t.agent_profile.c.deleted_at.is_not(None)
            )
        ).first()
        if deleted is not None:  # a deleted profile is never placed again (§6.3)
            raise not_found()
        try:
            member = member_row(conn, mine.project.id, body.agent.id)
        except ApiError:
            raise invalid({"agent.id": "not_a_member"}) from None
        if member.agent_id is None:
            raise invalid({"agent.id": "not_an_agent"})
        _exists(conn, t.placement.c.membership_id == member.id)
        handle: str = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == member.agent_id)
        ).scalar_one()
        return {"membership_id": member.id}, handle
    if not right:
        raise invalid({"agent": "id_required"}, "a proposal names an existing member")
    if body.agent.handle is None or body.agent.display_name is None:
        raise invalid({"agent": "id_or_handle"}, "name an agent by id, or give handle and name")
    # The handle or an alias of one of the owner's profiles (§6.24); a placement's reservation
    # of it comes after the project's own `placement_exists` below.
    held = handles.holder(conn, mine.principal_id, body.agent.handle)
    if held is not None and held != "placement":
        raise invalid({"handle": "taken"}, "you already have an agent with this handle")
    _exists(
        conn,
        t.placement.c.project_id == mine.project.id,
        t.placement.c.new_handle == body.agent.handle,
    )
    if held == "placement":  # another project's placement will create a profile with it
        raise invalid(
            {"handle": "taken"}, "a placement of yours will create an agent with this handle"
        )
    assignment = validate_assignment(
        conn,
        mine.project.id,
        kind="agent",
        role=body.role,
        reports_to=body.reports_to,
        areas=body.areas,
        capabilities=body.capabilities,
    )
    profile = {
        "display_name": body.agent.display_name,
        "role": assignment.get("role", "member"),
        "reports_to": assignment.get("reports_to"),
        "areas": assignment.get("areas", []),
        "capabilities": assignment.get("capabilities", []),
        "briefing": body.briefing or None,
    }
    return {"new_handle": body.agent.handle, "new_profile": profile}, body.agent.handle


def _file(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    placement: Any,
    runner: Any,
    verb: str,
    reason: str | None,
    spec: dict[str, Any],
) -> None:
    handle = pl.view(conn, placement, viewer_id="", briefing=False)["agent"]["handle"]
    isolation = pl.request_summary(conn, placement.id)
    summary = pl.consent_summary(
        {
            "agent": handle,
            "runner": runner.name,
            "target": spec.get("target"),
            "tool": spec.get("harness"),
            "model": spec.get("model"),
            "mode": spec.get("mode"),
            "isolation": ((isolation or {}).get("isolation") or {}).get("kind"),
            "reason": reason,
        }
    )
    file_consent(
        conn, mine, caller, f"{verb} {handle} on {runner.name}", summary, placement_id=placement.id
    )


# --- changing -------------------------------------------------------------------------------


@router.patch("/projects/{owner}/{slug}/placements/{placement_id}")
def patch_placement(
    slug: str, placement_id: str, body: PlacementPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    given = body.model_fields_set - {"reason"}
    if not given:
        raise invalid({"body": "empty"}, "say what to change")
    # Only `model` and `target` take null (the runner's default, the runner's choice).
    nulls = {k: "not_nullable" for k in given & NOT_NULLABLE if getattr(body, k) is None}
    if nulls:
        raise invalid(nulls)
    stop_only = given == {"desired"} and body.desired == "stopped"

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        project = events.lock_project(conn, mine.project.id)
        placement = _placement(conn, mine, placement_id)
        runner = _runner(conn, placement.runner_id)
        right = _has_right(mine, runner)
        owner = mine.kind == "human" and pl.profile_owner(conn, placement) == mine.principal_id
        proposer = _proposer(mine)
        spec_change = {k: getattr(body, k) for k in pl.SPEC_FIELDS if k in given}
        if not (right or proposer or (owner and not spec_change)):
            raise forbidden("members:admin" if mine.kind == "human" else "agents:propose")
        if stop_only and (placement.active is None or placement.closing is not None):
            # A stop is never refused (§15.6): closed or closing, it is answered as it is.
            return idempotency.Outcome(200, "placement", placement.id, _view(conn, mine, placement))
        _transition(placement)
        actor = caller.actor(mine.id)
        by = mine.principal_id
        request_open = pl.open_request_id(conn, placement.id) is not None
        if request_open and right:
            if stop_only and placement.approval_status == "pending":
                # Stopping a proposal nobody approved is turning it down, not approving it.
                pl.withdraw_open_request(conn, placement, "stopped by the runner's owner", actor)
                placement = pl.close_now(conn, pl.row(conn, placement.id), "withdrawn", actor, by)
                return idempotency.Outcome(
                    200, "placement", placement.id, _view(conn, mine, placement)
                )
            placement = _settle_by_right(conn, placement, actor, by, approve=True)
        if spec_change:
            new_spec = {**pl.view_spec(placement), **spec_change}
            if "mode" not in spec_change and "harness" in spec_change:
                new_spec["mode"] = placement.mode
            if right:
                _check_spec(runner, new_spec, project.repository_url)
                placement = pl.change_spec(conn, placement, spec_change, actor, by)
            else:
                if request_open:
                    raise _pending(conn, placement)
                if project.spawn_requests == "off":
                    raise forbidden(message="this project takes no placement proposals")
                if not body.reason:
                    raise invalid({"reason": "required"}, "a proposal says why")
                _check_spec(runner, new_spec, project.repository_url)
                if project.spawn_requests == "direct":
                    placement = pl.change_spec(conn, placement, spec_change, actor, by, body.reason)
                else:
                    placement = pl.propose_change(conn, placement, spec_change, by)
                    _file(conn, mine, caller, placement, runner, "Change", body.reason, new_spec)
        if body.desired is not None and "desired" in given:
            if body.desired == "running":
                _require_open(project)
                _require_live(conn, runner)
            placement = pl.set_desired(conn, placement, body.desired, actor, by)
        return idempotency.Outcome(200, "placement", placement.id, _view(conn, mine, placement))

    return idempotency.run(engine_of(request), request, caller, action)


def _pending(conn: Connection, placement: Any) -> ApiError:
    return ApiError(
        409,
        "approval_pending",
        "a consent request for this placement is open",
        {"request": pl.open_request_id(conn, placement.id)},
    )


def _settle_by_right(
    conn: Connection, placement: Any, actor: Any, by: str, *, approve: bool
) -> Any:
    """A human with the right acts on a placement with an open proposal (§15.6): a
    proposed creation is approved in their name, a proposed change withdrawn."""
    if placement.pending_change is not None or not approve:
        pl.withdraw_open_request(conn, placement, "settled by the runner's owner", actor)
        return pl.row(conn, placement.id)
    pl.answer_open_request(conn, placement, actor, by)
    return pl.approve(conn, placement, actor, by)


@router.post("/projects/{owner}/{slug}/placements/{placement_id}/restart")
def restart_placement(
    slug: str, placement_id: str, request: Request, caller: AnyCaller, body: RestartIn | None = None
) -> JSONResponse:
    rejoin = body.rejoin if body else False

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        project = events.lock_project(conn, mine.project.id)
        placement = _placement(conn, mine, placement_id)
        runner = _runner(conn, placement.runner_id)
        right = _has_right(mine, runner)
        owner = mine.kind == "human" and pl.profile_owner(conn, placement) == mine.principal_id
        if not (right or owner or _proposer(mine)):
            raise forbidden("members:admin" if mine.kind == "human" else "agents:propose")
        _transition(placement)
        if rejoin:
            revoked = (
                placement.credential_id is not None
                and conn.execute(
                    select(t.credential.c.revoked_at).where(
                        t.credential.c.id == placement.credential_id
                    )
                ).scalar()
            )
            if not revoked:
                raise invalid({"rejoin": "credential_not_revoked"})
        actor = caller.actor(mine.id)
        if pl.open_request_id(conn, placement.id) is not None:
            if not right:
                raise _pending(conn, placement)
            placement = _settle_by_right(conn, placement, actor, mine.principal_id, approve=True)
        _require_open(project)
        _require_live(conn, runner)
        placement = pl.restart(conn, placement, rejoin, actor, mine.principal_id)
        return idempotency.Outcome(200, "placement", placement.id, _view(conn, mine, placement))

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/projects/{owner}/{slug}/placements/{placement_id}")
def delete_placement(
    slug: str, placement_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        events.lock_project(conn, mine.project.id)
        placement = _placement(conn, mine, placement_id)
        runner = _runner(conn, placement.runner_id)
        if not (_has_right(mine, runner) or _proposer(mine)):
            raise forbidden("members:admin" if mine.kind == "human" else "agents:propose")
        actor = caller.actor(mine.id)
        by = mine.principal_id
        if placement.active is not None:
            withdrawn = pl.withdraw_open_request(
                conn, placement, "the placement was deleted", actor
            )
            never_seen = withdrawn and placement.approval_status != "approved"
            if never_seen or placement.closing is not None:
                # A proposed creation the runner never saw, or the escape when a runner
                # never reports (§15.5).
                placement = pl.close_now(conn, pl.row(conn, placement.id), "removed", actor, by)
            else:  # a withdrawn change of a running placement stops like any other
                placement = pl.close_uniform(conn, pl.row(conn, placement.id), "removed", actor, by)
        return idempotency.Outcome(200, "placement", placement.id, _view(conn, mine, placement))

    return idempotency.run(engine_of(request), request, caller, action)
