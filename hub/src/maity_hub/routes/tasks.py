"""Cards, claims and leases, checkpoints and completion reports (docs/api.md §6.4–§6.6)."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, and_, false, insert, or_, select, update

from maity_hub import cards, clock, idempotency, releases
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found
from maity_hub.events import emit, lock_project
from maity_hub.ids import new_id
from maity_hub.models import Strict, markdown, title
from maity_hub.policy import CLOSED_STATES, REASON_STATES
from maity_hub.routes.members import AREA
from maity_hub.views import principal_id, task_view

router = APIRouter()

SHA = re.compile(r"[0-9a-f]{7,64}")
PAGE_DEFAULT, PAGE_MAX = 50, 200


class ReleaseIn(Strict):
    version: str = Field(min_length=1, max_length=64)


class ContractIn(Strict):
    arbiter: str | None = None
    watchers: list[str] = Field(default_factory=list, max_length=50)


class TypedPullRequestIn(Strict):
    number: int = Field(ge=1, le=2**31)
    state: Literal["open", "merged", "closed"] | None = None


class ChecklistItemIn(Strict):
    id: str | None = Field(default=None, max_length=32)
    text: str = title()


class ReleasePatchIn(Strict):
    pull_requests_typed: list[TypedPullRequestIn] | None = Field(default=None, max_length=100)
    checklist: list[ChecklistItemIn] | None = Field(default=None, max_length=50)


class ContractPatchIn(Strict):
    state: Literal["proposed", "final"] | None = None
    watchers: list[str] | None = Field(default=None, max_length=50)


class ChecklistTickIn(Strict):
    done: bool


class TaskCreate(Strict):
    title: str = title()
    body: str | None = markdown(default=None)
    kind: str = "task"
    label: str | None = None
    area: str | None = None
    status: str = "open"
    assigned_to: str | None = None
    depends_on: list[str] = Field(default_factory=list, max_length=100)
    ships_with: list[str] = Field(default_factory=list, max_length=100)
    ktw_ref: str | None = Field(default=None, max_length=255)
    release: ReleaseIn | None = None
    contract: ContractIn | None = None
    reason: str | None = markdown(default=None)


class TaskPatch(Strict):
    title: str | None = title(default=None)
    body: str | None = markdown(default=None)
    label: str | None = None
    area: str | None = None
    status: str | None = None
    depends_on: list[str] | None = Field(default=None, max_length=100)
    ships_with: list[str] | None = Field(default=None, max_length=100)
    ktw_ref: str | None = Field(default=None, max_length=255)
    assigned_to: str | None = None
    release: ReleasePatchIn | None = None
    contract: ContractPatchIn | None = None


class ClaimIn(Strict):
    holder: str | None = None
    reason: str | None = markdown(default=None)


class AssignIn(Strict):
    assignee: str


class CheckpointIn(Strict):
    last_step: str = markdown(min_length=1)
    next_step: str = markdown(min_length=1)
    branch: str | None = Field(default=None, max_length=255)
    head: str | None = Field(default=None, max_length=64)


class PullRequestIn(Strict):
    number: int = Field(ge=1)
    url: str = Field(min_length=1, max_length=255)
    head: str = Field(max_length=64)
    state: Literal["open", "merged", "closed"]


class ReportIn(Strict):
    summary: str = markdown(min_length=1)
    head: str = Field(max_length=64)
    branch: str = Field(min_length=1, max_length=255)
    upstream: str | None = Field(default=None, max_length=255)
    remote_head: str = Field(max_length=64)
    pr: PullRequestIn | None = None
    pr_status: Literal["found", "none", "unknown"]
    pr_unknown_reason: str | None = Field(default=None, max_length=1000)
    done: bool = False


def load_task(conn: Connection, card_id: str) -> dict[str, Any]:
    return task_view(conn, _card(conn, card_id))


idempotency.LOADERS["task"] = load_task


def _locked(conn: Connection, mine: Membership) -> Membership:
    """The caller's membership with the project row as read under the project lock."""
    return replace(mine, project=lock_project(conn, mine.project.id))


def _member_id(conn: Connection, mine: Membership, principal: str, field: str) -> int:
    """An active member's membership id; anyone else is `invalid` (§6.4)."""
    try:
        membership_id: int = member_row(conn, mine.project.id, principal).id
    except ApiError:
        raise invalid({field: "not_a_member"}) from None
    return membership_id


def _card(conn: Connection, card_id: str) -> Any:
    return conn.execute(select(t.card).where(t.card.c.id == card_id)).one()


def _project_card(conn: Connection, mine: Membership, card_id: str) -> Any:
    row = conn.execute(
        select(t.card).where(t.card.c.id == card_id, t.card.c.project_id == mine.project.id)
    ).first()
    if row is None:
        raise not_found()
    return row


def _member(row: Any) -> list[str]:
    return [f"member:{row}"] if row else []


def audience(conn: Connection, card: Any, *extra: int | None) -> list[str]:
    """creator, assignee, area owner, holder, and whoever else the event concerns (§8.2)."""
    ids = [card.created_by, card.assigned_to, cards.area_owner(conn, card.project_id, card.area)]
    ids += [card.claim_holder, *extra]
    members: list[str] = []
    for membership_id in ids:
        principal = principal_id(conn, membership_id)
        if principal and f"member:{principal}" not in members:
            members.append(f"member:{principal}")
    for watcher in (card.contract or {}).get("watchers", []):  # contract cards (§6.8)
        if f"member:{watcher}" not in members:
            members.append(f"member:{watcher}")
    return members


def _new_release(conn: Connection, mine: Membership, body: ReleaseIn | None) -> dict[str, Any]:
    """Columns of a new release card (§6.7): one version per project, one in flight."""
    mine.require("releases:write")
    if body is None:
        raise invalid({"release.version": "required"})
    if not releases.SEMVER.fullmatch(body.version):
        raise invalid({"release.version": "not_semver"})
    taken = conn.execute(
        select(t.card.c.id).where(
            t.card.c.project_id == mine.project.id, t.card.c.release_version == body.version
        )
    ).first()
    if taken is not None:
        raise ApiError(
            409, "version_exists", f"a release {body.version} exists", {"release": taken.id}
        )
    open_release = conn.execute(
        select(t.card.c.id).where(
            t.card.c.project_id == mine.project.id, t.card.c.release_in_flight.is_(True)
        )
    ).first()
    if open_release is not None:
        raise ApiError(
            409,
            "release_in_flight",
            "another release is open; close or cancel it first",
            {"release": open_release.id},
        )
    checklist = releases.seed_checklist((mine.project.settings or {}).get("release_checklist", []))
    return {
        "release_version": body.version,
        "release_in_flight": True,
        "release_data": {
            "version": body.version,
            "pull_requests_typed": [],
            "checklist": checklist,
            "ready_announced": False,
        },
    }


def _new_contract(conn: Connection, mine: Membership, body: ContractIn) -> dict[str, Any]:
    arbiter = body.arbiter or mine.project.contract_arbiter
    if arbiter != "role:admin":
        _member_id(conn, mine, arbiter, "contract.arbiter")
    watchers = list(dict.fromkeys(body.watchers))
    for watcher in watchers:
        _member_id(conn, mine, watcher, "contract.watchers")
    return {"arbiter": arbiter, "state": "proposed", "watchers": watchers}


def _is_arbiter(mine: Membership, contract: dict[str, Any]) -> bool:
    arbiter = contract.get("arbiter")
    if arbiter == "role:admin":
        return mine.role == "admin"
    return bool(arbiter == mine.principal_id)


def _closing(card: Any) -> dict[str, Any]:
    """Columns every close sets: blocked by nothing any more (§7), no release in flight."""
    values: dict[str, Any] = {
        "closed_at": clock.now(),
        "status_before_block": None,
        "blocked_by_request": None,
    }
    if card.kind == "release":
        values["release_in_flight"] = None
    return values


def _refuse_unready(conn: Connection, card: Any) -> None:
    if card.kind != "release":
        return
    readiness = releases.release_view(conn, card)["readiness"]
    if not readiness["ready"]:
        raise ApiError(
            409,
            "release_not_ready",
            "the release is not ready; see details.blocking",
            {"blocking": readiness["blocking"]},
        )


def _patched_release(mine: Membership, card: Any, body: ReleasePatchIn) -> dict[str, Any]:
    if card.kind != "release":
        raise invalid({"release": "releases_only"})
    mine.require("releases:write")
    data = dict(card.release_data or {})
    if body.pull_requests_typed is not None:
        typed: dict[int, dict[str, Any]] = {}
        for pr in body.pull_requests_typed:
            typed[pr.number] = {"number": pr.number, "state": pr.state}
        data["pull_requests_typed"] = [typed[n] for n in sorted(typed)]
    if body.checklist is not None:
        # The list replaces the old one; an item keeps its tick when its id is given.
        old = {item["id"]: item for item in data.get("checklist", [])}
        numbers = [int(i.removeprefix("chk-")) for i in old if i.removeprefix("chk-").isdigit()]
        next_number = max(numbers, default=0) + 1
        checklist = []
        for item in body.checklist:
            if item.id is not None:
                if item.id not in old:
                    raise invalid({"release.checklist": f"unknown_item:{item.id}"})
                checklist.append({**old[item.id], "text": item.text})
            else:
                checklist.append(
                    {
                        "id": f"chk-{next_number}",
                        "text": item.text,
                        "done": False,
                        "by": None,
                        "at": None,
                    }
                )
                next_number += 1
        if len({item["id"] for item in checklist}) != len(checklist):
            raise invalid({"release.checklist": "duplicate_id"})
        data["checklist"] = checklist
    return data


def _patched_contract(
    conn: Connection, mine: Membership, card: Any, body: ContractPatchIn
) -> dict[str, Any]:
    if card.kind != "contract":
        raise invalid({"contract": "contracts_only"})
    contract = dict(card.contract or {})
    if body.state is not None and body.state != contract.get("state"):
        if not (_is_arbiter(mine, contract) or mine.may("tasks:admin")):
            raise forbidden("tasks:admin", "only the arbiter moves a contract's state")
        contract["state"] = body.state
    if body.watchers is not None:
        watchers = list(dict.fromkeys(body.watchers))
        for watcher in watchers:
            _member_id(conn, mine, watcher, "contract.watchers")
        contract["watchers"] = watchers
    return contract


def _check_area(area: str | None) -> None:
    if area is not None and (not AREA.fullmatch(area) or "/../" in f"/{area}/"):
        raise invalid({"area": "invalid_path"})


def _check_label(label: str | None) -> None:
    if label is not None and label not in cards.LABELS:
        raise invalid({"label": "unknown"})


def _require_open_project(mine: Membership, reason: str | None) -> dict[str, Any]:
    """`project_closed` in accepted/archived; a reason in freeze/fixes-only (§6.1)."""
    state = mine.project.state
    if state in CLOSED_STATES:
        raise ApiError(409, "project_closed", f"the project is {state}")
    if state in REASON_STATES and not reason:
        raise invalid({"reason": "required"}, f"the project is in {state}: say why")
    return {"project_state": state, "reason": reason}


def _touch_partners(conn: Connection, mine: Membership, caller: Caller, partners: set[str]) -> None:
    """A mirrored `ships_with` edge changed these cards too: say so on them."""
    for partner_id in sorted(partners):
        conn.execute(
            update(t.card)
            .where(t.card.c.id == partner_id)
            .values(
                updated_at=clock.now(),
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        )
        partner = _card(conn, partner_id)
        emit(
            conn,
            mine.project.id,
            "task_updated",
            audience(conn, partner),
            {
                "id": partner_id,
                "ships_with": task_view(conn, partner)["ships_with"],
                "project_state": mine.project.state,
            },
            actor=caller.actor(mine.id),
            subject=("task", partner_id),
        )


def _verification(caller: Caller) -> str:
    return "signed" if caller.via == "signed" else "bearer"


# --- the board -------------------------------------------------------------------


def _cursor(updated_at: datetime, card_id: str) -> str:
    raw = json.dumps([updated_at.isoformat(), card_id])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _uncursor(text: str) -> tuple[datetime, str]:
    try:
        iso, card_id = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
        return datetime.fromisoformat(iso), str(card_id)
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None


@router.get("/projects/{slug}/tasks")
def list_tasks(
    slug: str,
    request: Request,
    caller: AnyCaller,
    status: str = "all",
    kind: str | None = None,
    label: str | None = None,
    holder: str | None = None,
    assigned_to: str | None = None,
    area: str | None = None,
    closed_after: datetime | None = None,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        query = select(t.card).where(t.card.c.project_id == mine.project.id)
        if status != "all":
            wanted = [s for s in status.split(",") if s]
            if any(s not in cards.STATUSES for s in wanted):
                raise invalid({"status": "unknown"})
            query = query.where(t.card.c.status.in_(wanted))
        for column, value in (
            (t.card.c.kind, kind),
            (t.card.c.label, label),
            (t.card.c.area, area),
        ):
            if value is not None:
                query = query.where(column == value)
        for column, member in (
            (t.card.c.claim_holder, holder),
            (t.card.c.assigned_to, assigned_to),
        ):
            if member is not None:
                try:
                    query = query.where(column == member_row(conn, mine.project.id, member).id)
                except ApiError:
                    query = query.where(false())  # not a member: holds and is assigned nothing
        if closed_after is not None:
            if closed_after.tzinfo is None:
                raise invalid({"closed_after": "needs_a_zone"})
            query = query.where(
                or_(t.card.c.closed_at.is_(None), t.card.c.closed_at > closed_after)
            )
        if cursor is not None:
            after_at, after_id = _uncursor(cursor)
            query = query.where(
                or_(
                    t.card.c.updated_at < after_at,
                    and_(t.card.c.updated_at == after_at, t.card.c.id < after_id),
                )
            )
        rows = conn.execute(
            query.order_by(t.card.c.updated_at.desc(), t.card.c.id.desc()).limit(limit + 1)
        ).all()
        page = rows[:limit]
        next_cursor = _cursor(page[-1].updated_at, page[-1].id) if len(rows) > limit else None
        return JSONResponse(
            {"items": [task_view(conn, r) for r in page], "next_cursor": next_cursor}
        )


@router.get("/projects/{slug}/tasks/{card_id}")
def get_task(slug: str, card_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        return JSONResponse(task_view(conn, _project_card(conn, mine, card_id)))


@router.post("/projects/{slug}/tasks")
def create_task(slug: str, body: TaskCreate, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("tasks:write")
        if body.kind not in cards.KINDS:
            raise invalid({"kind": "unknown"})
        if body.status not in cards.CREATE_STATUSES:
            raise invalid({"status": "proposed_or_open"})
        if body.release is not None and body.kind != "release":
            raise invalid({"release": "releases_only"})
        if body.contract is not None and body.kind != "contract":
            raise invalid({"contract": "contracts_only"})
        _check_label(body.label)
        _check_area(body.area)
        mine = _locked(conn, mine)
        state = _require_open_project(mine, body.reason)
        extra: dict[str, Any] = {}
        if body.kind == "release":
            extra = _new_release(conn, mine, body.release)
        elif body.kind == "contract":
            extra = {"contract": _new_contract(conn, mine, body.contract or ContractIn())}
        assigned: int | None
        if body.assigned_to is not None:
            mine.require("tasks:admin")
            assigned = _member_id(conn, mine, body.assigned_to, "assigned_to")
        else:
            # Findings and hand-outs go to the owner of the narrowest area (§6.2).
            assigned = cards.area_owner(conn, mine.project.id, body.area)
        now = clock.now()
        card_id = new_id({"release": "release", "contract": "contract"}.get(body.kind, "task"))
        conn.execute(
            insert(t.card).values(
                **extra,
                id=card_id,
                project_id=mine.project.id,
                kind=body.kind,
                title=body.title,
                body=body.body,
                label=body.label,
                status=body.status,
                area=body.area,
                created_by=mine.id,
                assigned_to=assigned,
                ktw_ref=body.ktw_ref,
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
                created_at=now,
                updated_at=now,
            )
        )
        cards.set_depends_on(conn, mine.project.id, card_id, body.depends_on)
        partners = cards.set_ships_with(conn, mine.project.id, card_id, body.ships_with)
        _touch_partners(conn, mine, caller, partners)
        card = _card(conn, card_id)
        view = task_view(conn, card)
        emit(
            conn,
            mine.project.id,
            "task_created",
            audience(conn, card),
            {**view, **state},
            actor=caller.actor(mine.id),
            subject=("task", card_id),
        )
        return idempotency.Outcome(201, "task", card_id, view)

    return idempotency.run(engine_of(request), request, caller, action)


@router.patch("/projects/{slug}/tasks/{card_id}")
def patch_task(
    slug: str, card_id: str, body: TaskPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    given = body.model_fields_set

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("tasks:write")
        mine = _locked(conn, mine)
        card = _project_card(conn, mine, card_id)
        # A status-only move out of review is done authority's, whoever holds it (§6.4).
        review_move = (
            given == {"status"}
            and card.status == "review"
            and body.status in ("done", "in_progress")
        )
        # So is a state-only move of a contract card the arbiter's (§6.8).
        arbiter_move = (
            given == {"contract"}
            and body.contract is not None
            and body.contract.model_fields_set <= {"state"}
            and card.kind == "contract"
            and _is_arbiter(mine, card.contract or {})
        )
        editor = cards.holds(mine, card) or card.created_by == mine.id or mine.may("tasks:admin")
        if (
            not editor
            and not arbiter_move
            and not (review_move and cards.has_done_authority(mine, card))
        ):
            raise forbidden("tasks:admin", "only the holder, the creator or an admin edits a card")
        values: dict[str, Any] = {}
        for field in ("title", "body", "ktw_ref"):
            if field in given and (field != "title" or body.title is not None):
                values[field] = getattr(body, field)
        if "label" in given:
            _check_label(body.label)
            values["label"] = body.label
        if "area" in given:
            _check_area(body.area)
            values["area"] = body.area
        if "assigned_to" in given:
            mine.require("tasks:admin")
            values["assigned_to"] = (
                _member_id(conn, mine, body.assigned_to, "assigned_to")
                if body.assigned_to
                else None
            )
        if body.release is not None:
            values["release_data"] = _patched_release(mine, card, body.release)
        if body.contract is not None:
            values["contract"] = _patched_contract(conn, mine, card, body.contract)
        depends_changed = body.depends_on is not None and cards.set_depends_on(
            conn, mine.project.id, card.id, body.depends_on
        )
        partners: set[str] = set()
        if body.ships_with is not None:
            partners = cards.set_ships_with(conn, mine.project.id, card.id, body.ships_with)
        if "status" in given and body.status is not None and body.status != card.status:
            if body.status not in cards.STATUSES:
                raise invalid({"status": "unknown"})
            cards.check_transition(mine, card, body.status)
            if body.status == "done":
                cards.refuse_open_dependencies(conn, card.id)
                _refuse_unready(conn, card)
            values["status"] = body.status
            if body.status in cards.CLOSED:
                values.update(_closing(card))
        changed = {k: v for k, v in values.items() if getattr(card, k) != v}
        edges_changed = depends_changed or bool(partners)
        if not changed and not edges_changed:
            return idempotency.Outcome(200, "task", card.id, task_view(conn, card))
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card.id)
            .values(
                **changed,
                updated_at=clock.now(),
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        )
        card = _card(conn, card.id)
        view = task_view(conn, card)
        payload = {k: view[k] for k in changed if k in view}
        if depends_changed:
            payload["depends_on"] = view["depends_on"]
        if partners:
            payload["ships_with"] = view["ships_with"]
        if "release_data" in changed:
            payload["release"] = view["release"]
        _touch_partners(conn, mine, caller, partners)
        emit(
            conn,
            mine.project.id,
            "task_updated",
            audience(conn, card),
            {**payload, "id": card.id, "project_state": mine.project.state},
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        releases.recheck(conn, mine.project.id)
        return idempotency.Outcome(200, "task", card.id, task_view(conn, _card(conn, card.id)))

    return idempotency.run(engine_of(request), request, caller, action)


# --- claims and leases (§6.5) ----------------------------------------------------------


@router.post("/projects/{slug}/tasks/{card_id}/claim")
def claim(
    slug: str, card_id: str, body: ClaimIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("tasks:write")
        mine = _locked(conn, mine)
        state = _require_open_project(mine, body.reason)
        card = _project_card(conn, mine, card_id)
        holder_id = mine.id
        session_id = caller.session_id
        if body.holder is not None and body.holder != mine.principal_id:
            mine.require("tasks:admin")
            holder_id = _member_id(conn, mine, body.holder, "holder")
            session_id = None  # the holder's next call moves it to its session
        if card.claim_holder is not None:
            raise _already_claimed(conn, card)
        if card.status != "open":
            raise cards.invalid_transition(card.status, "in_progress")
        if mine.project.claim_policy == "assign-only" and card.assigned_to != holder_id:
            raise ApiError(409, "assign_only", "this project hands cards out by assignment")
        now = clock.now()
        lease_until = now + timedelta(seconds=mine.project.lease_seconds)
        # The claim: one conditional UPDATE, the row count decides (§6.5).
        won = conn.execute(
            update(t.card)
            .where(
                t.card.c.id == card.id, t.card.c.claim_holder.is_(None), t.card.c.status == "open"
            )
            .values(
                claim_holder=holder_id,
                claim_session_id=session_id,
                claim_since=now,
                lease_until=lease_until,
                status="in_progress",
                updated_at=now,
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        ).rowcount
        if won != 1:
            raise _already_claimed(conn, _card(conn, card.id))
        card = _card(conn, card.id)
        emit(
            conn,
            mine.project.id,
            "task_claimed",
            audience(conn, card),
            {
                "holder": principal_id(conn, holder_id),
                "lease_until": clock.rfc3339(lease_until),
                **state,
            },
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        return idempotency.Outcome(200, "task", card.id, task_view(conn, card))

    return idempotency.run(engine_of(request), request, caller, action)


def _already_claimed(conn: Connection, card: Any) -> ApiError:
    if card.claim_holder is None:  # not held after all: it left `open` some other way
        return cards.invalid_transition(card.status, "in_progress")
    holder = principal_id(conn, card.claim_holder)
    expired = card.lease_until is not None and card.lease_until <= clock.now()
    return ApiError(
        409,
        "already_claimed",
        f"{card.id} is claimed by {holder}",
        {"holder": holder, "lease_until": clock.rfc3339(card.lease_until), "expired": expired},
    )


def _lease_active(card: Any) -> ApiError:
    return ApiError(
        409,
        "lease_active",
        "the holder's lease has not expired",
        {"lease_until": clock.rfc3339(card.lease_until) if card.lease_until else None},
    )


def _lease_expired(card: Any) -> bool:
    return card.lease_until is not None and card.lease_until <= clock.now()


@router.post("/projects/{slug}/tasks/{card_id}/release")
def release(slug: str, card_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine = _locked(conn, mine)
        card = _project_card(conn, mine, card_id)
        if card.claim_holder is None:
            raise ApiError(409, "not_holder", "the card is not claimed")
        if not cards.holds(mine, card):
            mine.require("tasks:admin")
            if not _lease_expired(card):
                raise ApiError(
                    409,
                    "lease_active",
                    "the holder's lease has not expired",
                    {"lease_until": clock.rfc3339(card.lease_until)},
                )
        old_holder = card.claim_holder
        now = clock.now()
        # Conditional: a renewal by the holder a moment ago must not be wiped.
        still = [t.card.c.claim_holder == old_holder]
        if not cards.holds(mine, card):
            still.append(t.card.c.lease_until <= now)
        released = conn.execute(
            update(t.card)
            .where(t.card.c.id == card.id, *still)
            .values(
                claim_holder=None,
                claim_session_id=None,
                claim_since=None,
                lease_until=None,
                status="open" if card.status not in cards.CLOSED else card.status,
                status_before_block=None,
                blocked_by_request=None,
                updated_at=now,
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        )
        if released.rowcount != 1:
            raise _lease_active(_card(conn, card.id))
        card = _card(conn, card.id)
        emit(
            conn,
            mine.project.id,
            "task_released",
            audience(conn, card, old_holder),
            {
                "holder": None,
                "lease_until": None,
                "project_state": mine.project.state,
                "reason": None,
            },
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        return idempotency.Outcome(200, "task", card.id, task_view(conn, card))

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{slug}/tasks/{card_id}/assign")
def assign(
    slug: str, card_id: str, body: AssignIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("tasks:admin")
        mine = _locked(conn, mine)
        card = _project_card(conn, mine, card_id)
        assignee = _member_id(conn, mine, body.assignee, "assignee")
        now = clock.now()
        values: dict[str, Any] = {"assigned_to": assignee}
        old_holder = card.claim_holder
        if card.claim_holder is not None and card.claim_holder != assignee:
            if not _lease_expired(card):
                raise ApiError(
                    409,
                    "lease_active",
                    "the holder's lease has not expired",
                    {"lease_until": clock.rfc3339(card.lease_until)},
                )
            # An expired claim moves to the assignee (§6.4).
            values.update(
                claim_holder=assignee,
                claim_session_id=None,
                claim_since=now,
                lease_until=now + timedelta(seconds=mine.project.lease_seconds),
            )
        moves_claim = "claim_holder" in values
        still = (
            [t.card.c.claim_holder == old_holder, t.card.c.lease_until <= now]
            if moves_claim
            else []
        )
        assigned = conn.execute(
            update(t.card)
            .where(t.card.c.id == card.id, *still)
            .values(
                **values,
                updated_at=now,
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        )
        if assigned.rowcount != 1:  # the holder renewed in the meantime
            raise _lease_active(_card(conn, card.id))
        old_assignee = card.assigned_to
        card = _card(conn, card.id)
        emit(
            conn,
            mine.project.id,
            "task_assigned",
            audience(conn, card, old_holder, old_assignee),
            {
                "assignee": principal_id(conn, assignee),
                "holder": principal_id(conn, card.claim_holder),
                "lease_until": clock.rfc3339(card.lease_until) if card.lease_until else None,
                "project_state": mine.project.state,
                "reason": None,
            },
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        return idempotency.Outcome(200, "task", card.id, task_view(conn, card))

    return idempotency.run(engine_of(request), request, caller, action)


# --- checkpoint and report (§6.4, §6.6) -------------------------------------------------


def _holder_card(conn: Connection, mine: Membership, card_id: str) -> Any:
    card = _project_card(conn, mine, card_id)
    if not cards.holds(mine, card):
        raise ApiError(409, "not_holder", "only the holder of the card may do this")
    return card


@router.post("/projects/{slug}/tasks/{card_id}/checkpoint")
def checkpoint(
    slug: str, card_id: str, body: CheckpointIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    if body.head is not None and not SHA.fullmatch(body.head):
        raise invalid({"head": "not_a_sha"})

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine = _locked(conn, mine)
        card = _holder_card(conn, mine, card_id)
        now = clock.now()
        point = {
            "last_step": body.last_step,
            "next_step": body.next_step,
            "branch": body.branch,
            "head": body.head,
            "verification": _verification(caller),
            "updated_at": clock.rfc3339(now),
        }
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card.id)
            .values(
                checkpoint=point,
                updated_at=now,
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        )
        card = _card(conn, card.id)
        emit(
            conn,
            mine.project.id,
            "task_checkpoint",
            _member(principal_id(conn, card.claim_holder)),
            point,
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        return idempotency.Outcome(200, "task", card.id, task_view(conn, card))

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{slug}/tasks/{card_id}/report")
def report(
    slug: str, card_id: str, body: ReportIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    _check_report(body)

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine = _locked(conn, mine)
        card = _holder_card(conn, mine, card_id)
        if card.status not in ("in_progress", "blocked", "review"):
            raise cards.invalid_transition(card.status, "review")
        if body.done:
            # Refused as a whole, nothing stored: the agent reports again without done.
            if not cards.has_done_authority(mine, card):
                raise forbidden(
                    cards.authority_scope(mine), "done needs done authority; report without done"
                )
            cards.refuse_open_dependencies(conn, card.id)
            _refuse_unready(conn, card)
        now = clock.now()
        stored = {
            "summary": body.summary,
            "head": body.head,
            "branch": body.branch,
            "upstream": body.upstream,
            "remote_head": body.remote_head,
            "pr": body.pr.model_dump() if body.pr else None,
            "pr_status": body.pr_status,
            "pr_unknown_reason": body.pr_unknown_reason,
            "verification": _verification(caller),
            "reported_by": mine.principal_id,
            "session_id": caller.session_id,
            "reported_at": clock.rfc3339(now),
            # Filled by the probe in the background; never awaited inside a write.
            "observed": None,
            "mismatch": None,
        }
        values: dict[str, Any] = {"report": stored}
        if body.done:
            values.update({**_closing(card), "status": "done", "closed_at": now})
        elif card.status == "blocked":
            values["status_before_block"] = "review"  # the answer restores review (§7)
        else:
            values["status"] = "review"
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card.id)
            .values(
                **values,
                updated_at=now,
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        )
        card = _card(conn, card.id)
        targets = _member(principal_id(conn, card.claim_holder)) + _member(
            principal_id(conn, card.created_by)
        )
        emit(
            conn,
            mine.project.id,
            "task_reported",
            list(dict.fromkeys(targets)) + ["role:reviewer", "role:admin"],
            stored,
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        releases.recheck(conn, mine.project.id)
        return idempotency.Outcome(200, "task", card.id, task_view(conn, _card(conn, card.id)))

    return idempotency.run(engine_of(request), request, caller, action)


def _check_report(body: ReportIn) -> None:
    errors: dict[str, str] = {}
    for field in ("head", "remote_head"):
        if not SHA.fullmatch(getattr(body, field)):
            errors[field] = "not_a_sha"
    if body.pr is not None and not SHA.fullmatch(body.pr.head):
        errors["pr.head"] = "not_a_sha"
    if not errors and body.head != body.remote_head:
        errors["remote_head"] = "differs_from_head"
    if (body.pr_status == "found") != (body.pr is not None):
        errors["pr_status"] = "does_not_match_pr"
    if body.pr_status == "unknown" and not body.pr_unknown_reason:
        errors["pr_unknown_reason"] = "required"
    if errors:
        raise invalid(errors)


# --- release checklist (§6.7) --------------------------------------------------------------


@router.post("/projects/{slug}/tasks/{card_id}/checklist/{item_id}")
def tick_checklist(
    slug: str,
    card_id: str,
    item_id: str,
    body: ChecklistTickIn,
    request: Request,
    caller: AnyCaller,
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine = _locked(conn, mine)
        card = _project_card(conn, mine, card_id)
        if card.kind != "release":
            raise not_found()
        if not (cards.holds(mine, card) or mine.may("releases:write")):
            raise forbidden("releases:write", "only the holder or a releaser ticks the checklist")
        if card.status in cards.CLOSED:
            raise cards.invalid_transition(card.status, card.status)
        data = dict(card.release_data or {})
        checklist = [dict(item) for item in data.get("checklist", [])]
        item = next((i for i in checklist if i["id"] == item_id), None)
        if item is None:
            raise not_found()
        if item["done"] == body.done:
            return idempotency.Outcome(200, "task", card.id, task_view(conn, card))
        now = clock.now()
        item.update(
            done=body.done,
            by=mine.principal_id if body.done else None,
            at=clock.rfc3339(now) if body.done else None,
        )
        data["checklist"] = checklist
        conn.execute(
            update(t.card)
            .where(t.card.c.id == card.id)
            .values(
                release_data=data,
                updated_at=now,
                changed_by_credential=caller.credential_id,
                changed_via=caller.via,
            )
        )
        card = _card(conn, card.id)
        view = task_view(conn, card)
        emit(
            conn,
            mine.project.id,
            "task_updated",
            audience(conn, card),
            {"id": card.id, "release": view["release"], "project_state": mine.project.state},
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        releases.recheck(conn, mine.project.id)
        return idempotency.Outcome(200, "task", card.id, task_view(conn, _card(conn, card.id)))

    return idempotency.run(engine_of(request), request, caller, action)
