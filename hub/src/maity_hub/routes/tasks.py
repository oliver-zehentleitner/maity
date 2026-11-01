"""Cards, claims and leases, checkpoints and completion reports (docs/api.md §6.4–§6.6)."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, field_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import Connection, and_, false, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import (
    availability,
    card_search,
    card_watches,
    cards,
    clock,
    contract_text,
    cover,
    idempotency,
    instances,
    line,
    mentions,
    merged,
    moderation,
    namespace,
    paging,
    ranks,
    releases,
    seats,
    takeovers,
    ticker,
)
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth.caller import Caller
from maity_hub.board import history
from maity_hub.board import links as card_links
from maity_hub.deps import AnyCaller, engine_of, reader_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found
from maity_hub.events import Actor, emit, lock_project
from maity_hub.forge import Forge
from maity_hub.ids import new_id
from maity_hub.models import Strict, Written, markdown, title
from maity_hub.namespace import ProjectRoute
from maity_hub.policy import CLOSED_STATES, REASON_STATES, keep_the_why_effective
from maity_hub.routes.members import AREA
from maity_hub.scopes import in_admin_team, role_tokens
from maity_hub.views import (
    human_paused,
    paused,
    principal_id,
    task_view,
    task_views,
)

router = APIRouter(route_class=ProjectRoute)

SHA = re.compile(r"[0-9a-f]{7,64}")
FULL_SHA = re.compile(r"[0-9a-f]{40}")  # a report's heads are compared whole
PAGE_DEFAULT, PAGE_MAX = 50, 200


class ReleaseIn(Strict):
    version: str = Field(min_length=1, max_length=64)


class ContractIn(Strict):
    arbiter: str | None = None
    watchers: list[str] = Field(default_factory=list, max_length=50)
    path: str = contract_text.DEFAULT_PATH  # where the contract's text lives (§6.8)
    section: str | None = None


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
    path: str | None = None
    section: str | None = None  # null clears it


class ChecklistTickIn(Strict):
    done: bool


class TaskCreate(Written):
    title: str = title()
    body: str | None = markdown(default=None)
    kind: str = "task"
    label: str | None = None
    area: str | None = None
    status: str = "open"
    assigned_to: str | None = None
    depends_on: list[str] = Field(default_factory=list, max_length=100)
    ships_with: list[str] = Field(default_factory=list, max_length=100)
    parent: str | None = Field(default=None, max_length=40)
    related: list[str] = Field(default_factory=list, max_length=100)
    ktw_ref: str | None = Field(default=None, max_length=255)
    release: ReleaseIn | None = None
    contract: ContractIn | None = None
    links: list[card_links.LinkIn] = Field(default_factory=list, max_length=20)  # §6.13
    reason: str | None = markdown(default=None)


class TaskPatch(Written):
    title: str | None = title(default=None)
    body: str | None = markdown(default=None)
    label: str | None = None
    area: str | None = None
    status: str | None = None
    approve: Literal["review", "test"] | None = None  # §6.4, under `reviewer_and_tester`
    approvals: Any = None  # the hub's alone
    depends_on: list[str] | None = Field(default=None, max_length=100)
    ships_with: list[str] | None = Field(default=None, max_length=100)
    parent: str | None = Field(default=None, max_length=40)
    related: list[str] | None = Field(default=None, max_length=100)
    ktw_ref: str | None = Field(default=None, max_length=255)
    assigned_to: str | None = None
    release: ReleasePatchIn | None = None
    contract: ContractPatchIn | None = None

    @field_validator("approvals", mode="before")
    @classmethod
    def _approvals_read_only(cls, _value: Any) -> Any:
        raise PydanticCustomError("read_only", "the hub sets the approvals")


class ClaimIn(Strict):
    holder: str | None = None
    reason: str | None = markdown(default=None)


class AssignIn(Strict):
    assignee: str
    instance: str | None = Field(default=None, max_length=5)  # sets assigned_instance (§6.18)


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


class ReportIn(Written):
    summary: str = markdown(min_length=1)
    head: str | None = Field(default=None, max_length=64)
    branch: str | None = Field(default=None, min_length=1, max_length=255)
    upstream: str | None = Field(default=None, max_length=255)
    remote_head: str | None = Field(default=None, max_length=64)
    pr: PullRequestIn | None = None
    pr_status: Literal["found", "none", "unknown"]
    pr_unknown_reason: str | None = Field(default=None, max_length=1000)
    # False for a result that is not code: a review, a draft, a decision (§6.6).
    code: bool = True
    done: bool = False
    # §6.23: validated in code, pydantic's error types are not the contract's reasons.
    why: Any = None


def load_task(conn: Connection, card_id: str, request: Request) -> dict[str, Any]:
    """The card for a replayed write, with the replaying caller's own `watching`."""
    card = _card(conn, card_id)
    caller = getattr(request.state, "caller", None)
    viewer = None
    if caller is not None:
        slug = namespace.name_of(conn, card.project_id)
        viewer = membership(conn, caller, slug)
    return task_view(conn, card, reader_of(request), viewer)


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


def _target_id(conn: Connection, mine: Membership, principal: str, field: str) -> int:
    """`_member_id` for a member a card names as its assignee or arbiter: never a guest,
    which is no target (§2.3 "Guest")."""
    try:
        row = member_row(conn, mine.project.id, principal)
    except ApiError:
        raise invalid({field: "not_a_member"}) from None
    if row.trust == "guest":
        raise invalid({field: "guest"}, "a guest is never a target")
    membership_id: int = row.id
    return membership_id


def _line_lead(mine: Membership) -> bool:
    return not mine.may("tasks:admin") and mine.may("line:lead")


def _require_assigner(conn: Connection, mine: Membership, *touched: int | None) -> None:
    """`tasks:admin`, or `line:lead` with every member the move touches the caller or in
    its reach (`not_in_line` otherwise, §2.3 "The manager"). The caller holds the
    project lock, so the reach is the one the write lands on."""
    if _line_lead(mine):
        line.require_reach(conn, mine, *touched)
        return
    mine.require("tasks:admin")


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


Party = int | tuple[int | None, str | None] | None  # a membership, or one with its instance


def audience(conn: Connection, card: Any, *extra: Party) -> list[str]:
    """creator, assignee, area owner, holder, and whoever else the event concerns (§8.2).
    The holder is its holding instance's token, an assignee with `assigned_instance`
    that instance's; the team still reads them, only the waking narrows."""
    parties: list[Party] = [
        card.created_by,
        (card.assigned_to, card.assigned_instance),
        cards.area_owner(conn, card.project_id, card.area),
        (card.claim_holder, card.claim_instance),
        *extra,
    ]
    members: list[str] = []
    for party in parties:
        membership_id, instance = party if isinstance(party, tuple) else (party, None)
        principal = principal_id(conn, membership_id)
        token = instances.token(principal, instance) if principal else None
        if token and token not in members:
            members.append(token)
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
            "next_item": len(checklist) + 1,
            "ready_announced": False,
        },
    }


def _release_conflict(error: IntegrityError, body: ReleaseIn | None) -> Exception:
    text = str(error.orig)
    version = body.version if body else None
    if "release_in_flight" in text:
        return ApiError(
            409, "release_in_flight", "another release is open; close or cancel it first"
        )
    if "release_version" in text:
        return ApiError(409, "version_exists", f"a release {version} exists")
    return error


def _new_contract(conn: Connection, mine: Membership, body: ContractIn) -> dict[str, Any]:
    policy_arbiter = seats.routed_arbiter(conn, mine.project)  # an isolated seat is routed past
    arbiter = body.arbiter or policy_arbiter
    if arbiter != policy_arbiter:
        mine.require("tasks:admin")  # naming another arbiter than the policy's (§6.8)
    if arbiter != "trust:admin":
        _target_id(conn, mine, arbiter, "contract.arbiter")
    watchers = list(dict.fromkeys(body.watchers))
    for watcher in watchers:
        _member_id(conn, mine, watcher, "contract.watchers")
    _check_contract_place(body.path, body.section)
    return {
        "arbiter": arbiter,
        "state": "proposed",
        "watchers": watchers,
        "path": body.path,
        "section": body.section,
    }


def _check_contract_place(path: str | None, section: str | None) -> None:
    """`path` repository-relative, `section` one heading number (§6.8)."""
    errors: dict[str, str] = {}
    if path is not None and (reason := contract_text.path_error(path)):
        errors["contract.path"] = reason
    if section is not None and (reason := contract_text.section_error(section)):
        errors["contract.section"] = reason
    if errors:
        raise invalid(errors)


def _is_arbiter(conn: Connection, mine: Membership, contract: dict[str, Any]) -> bool:
    # A card naming an isolated agent is arbitrated by the seat's default (§6.2).
    arbiter = contract.get("arbiter")
    if arbiter is not None:
        arbiter = seats.routed_arbiter(conn, mine.project, arbiter)
    if arbiter == "trust:admin":
        return in_admin_team(mine.trust, mine.role)
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


def _refuse_paused(conn: Connection, membership_id: int, instance: str | None = None) -> None:
    """A member a human paused takes no new work: no claims, no new cards (§5.3); nor
    does an instance a human paused, while its siblings carry on. An agent's own pause
    is a declaration and refuses nothing."""
    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    suspension = moderation.suspension_of(conn, row)
    if suspension is not None:  # a suspended account's memberships act as paused (§16.8)
        raise ApiError(
            409,
            "paused",
            "this member's account is suspended; it takes no new work",
            {"paused": suspension},
        )
    if human_paused(row):
        raise ApiError(
            409,
            "paused",
            "this member is paused; it takes no new work until the pause is lifted",
            {"paused": paused(row)},
        )
    if instance is None:
        return
    held = conn.execute(
        select(t.credential).where(
            t.credential.c.membership_id == membership_id, t.credential.c.instance == instance
        )
    ).first()
    if held is not None and instances.human_paused(row, held):
        raise ApiError(
            409,
            "paused",
            "this instance is paused; it takes no new work until the pause is lifted",
            {"paused": instances.paused_view(held), "instance": instance},
        )


def _refuse_closed_release(card: Any) -> None:
    """A closed release is the record of what shipped (§6.7)."""
    if card.kind == "release" and card.status in cards.CLOSED:
        raise cards.invalid_transition(card.status, card.status)


def _refuse_unready(conn: Connection, card: Any, fg: Forge, release_data: Any = None) -> None:
    """`release_not_ready`, judged on the card as it will be stored."""
    if card.kind != "release":
        return
    if release_data is not None:
        card = SimpleNamespace(**{**card._mapping, "release_data": release_data})
    readiness = releases.release_view(conn, card, fg)["readiness"]
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
    _refuse_closed_release(card)
    data = dict(card.release_data or {})
    if body.pull_requests_typed is not None:
        typed: dict[int, dict[str, Any]] = {}
        for pr in body.pull_requests_typed:
            typed[pr.number] = {"number": pr.number, "state": pr.state}
        data["pull_requests_typed"] = [typed[n] for n in sorted(typed)]
    if body.checklist is not None:
        # The list replaces the old one; an item keeps its tick when its id is given.
        old = {item["id"]: item for item in data.get("checklist", [])}
        # A counter, never max+1: a removed id is not given out again.
        next_number = int(data["next_item"])
        checklist = []
        for item in body.checklist:
            if item.id is not None:
                if item.id not in old:
                    raise invalid({"release.checklist": f"unknown_item:{item.id}"})
                checklist.append({**old[item.id], "text": item.text})
            else:
                checklist.append(releases.checklist_item(next_number, item.text))
                next_number += 1
        if len({item["id"] for item in checklist}) != len(checklist):
            raise invalid({"release.checklist": "duplicate_id"})
        data["checklist"], data["next_item"] = checklist, next_number
    return data


def _patched_contract(
    conn: Connection, mine: Membership, card: Any, body: ContractPatchIn
) -> dict[str, Any]:
    if card.kind != "contract":
        raise invalid({"contract": "contracts_only"})
    contract = dict(card.contract or {})
    if body.state is not None and body.state != contract.get("state"):
        if not (_is_arbiter(conn, mine, contract) or mine.may("tasks:admin")):
            raise forbidden("tasks:admin", "only the arbiter moves a contract's state")
        contract["state"] = body.state
    if body.watchers is not None:
        watchers = list(dict.fromkeys(body.watchers))
        for watcher in watchers:
            _member_id(conn, mine, watcher, "contract.watchers")
        contract["watchers"] = watchers
    given = body.model_fields_set
    if "path" in given and body.path is None:
        raise invalid({"contract.path": "not_a_path"})
    _check_contract_place(body.path, body.section)
    if body.path is not None:
        contract["path"] = body.path
    if "section" in given:
        contract["section"] = body.section
    return contract


def _check_area(area: str | None) -> None:
    if area is not None and (not AREA.fullmatch(area) or "/../" in f"/{area}/"):
        raise invalid({"area": "invalid_path"})


def _revision(card: Any) -> int | None:
    revision: int | None = (card.report or {}).get("revision")
    return revision


def _signatures(mine: Membership, card: Any, body: TaskPatch) -> dict[str, Any] | None:
    """The signatures after a `review→done` under `reviewer_and_tester`, else None."""
    if not (card.status == "review" and body.status == "done"):
        return None
    if not cards.two_signatures(mine.project):
        return None
    return cards.sign(mine, card, body.approve, _revision(card))


def _check_label(label: str | None) -> None:
    if label is not None and label not in cards.LABELS:
        raise invalid({"label": "unknown"})


def _require_open_project(mine: Membership, reason: str | None) -> dict[str, Any]:
    """`project_closed` in archived; a reason in plan and review (§6.1)."""
    state = mine.project.state
    if state in CLOSED_STATES:
        raise ApiError(409, "project_closed", f"the project is {state}")
    if state in REASON_STATES and not reason:
        raise invalid({"reason": "required"}, f"the project is in {state}: say why")
    return {"project_state": state, "reason": reason}


def _touch_partners(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    partners: set[str],
    fg: Forge,
    field: str = "ships_with",
) -> None:
    """Announce mirrored edges with one batch of partner views."""
    if not partners:
        return
    conn.execute(
        update(t.card)
        .where(t.card.c.id.in_(partners))
        .values(
            updated_at=clock.now(),
            changed_by_credential=caller.credential_id,
            changed_via=caller.via,
        )
    )
    rows = conn.execute(select(t.card).where(t.card.c.id.in_(partners)).order_by(t.card.c.id)).all()
    views = {view["id"]: view for view in task_views(conn, rows, fg)}
    for partner in rows:
        partner_id = partner.id
        emit(
            conn,
            mine.project.id,
            "task_updated",
            audience(conn, partner),
            {
                "id": partner_id,
                "fields": [field],
                field: views[partner_id][field],
                "history": [],  # the mirrored edge is the hub's; the edit is on the other card
                "project_state": mine.project.state,
            },
            actor=caller.actor(mine.id),
            subject=("task", partner_id),
        )


def _verification(caller: Caller) -> str:
    return "signed" if caller.via == "signed" else "bearer"


def _touch_parents(
    conn: Connection, mine: Membership, caller: Caller, parents: set[str], fg: Forge
) -> None:
    """Counts are computed, announced on the parent, and never card history."""
    for parent_id in sorted(parents):
        conn.execute(update(t.card).where(t.card.c.id == parent_id).values(updated_at=clock.now()))
        parent = _card(conn, parent_id)
        emit(
            conn,
            mine.project.id,
            "task_updated",
            audience(conn, parent),
            {
                "id": parent_id,
                "fields": ["children"],
                "children": task_view(conn, parent, fg)["children"],
                "history": [],
                "project_state": mine.project.state,
            },
            actor=caller.actor(mine.id),
            subject=("task", parent_id),
        )


def _subtasks_proposed() -> ApiError:
    return ApiError(
        403, "forbidden", "subtasks wait for an admin to open them", {"reason": "subtasks_proposed"}
    )


# --- the board -------------------------------------------------------------------


@router.get("/projects/{owner}/{slug}/tasks")
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
    parent: str | None = None,
    closed_after: datetime | None = None,
    order: Literal["board", "updated"] = "board",
    q: str | None = Query(default=None, min_length=1, max_length=200),
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    fg = reader_of(request)
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
            (t.card.c.parent, parent),
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
        bound = paging.scope(
            status=status, kind=kind, label=label, holder=holder, assigned_to=assigned_to,
            area=area, parent=parent, closed_after=closed_after, order=order,
            **({"q": q} if q is not None else {}),
        )  # fmt: skip
        matched: dict[str, list[str]] = {}

        def matching(rows: Sequence[Any]) -> list[Any]:
            if q is None:
                return list(rows)
            result = []
            notes = card_search.note_bodies(conn, (row.id for row in rows))
            for row in rows:
                hit = card_search.matches(row, q, notes[row.id])
                if hit:
                    matched[row.id] = hit
                    result.append(row)
            return result

        def views(rows: Sequence[Any]) -> list[dict[str, Any]]:
            shown = task_views(conn, rows, fg, mine)
            if q is not None:
                for item in shown:
                    item["match"] = matched[item["id"]]
            return shown

        if order == "board":
            # The board's order (§6.4) is not one the database keeps: sorted here, a
            # project's cards at a time, and paged after the last item shown.
            def key(row: Any) -> tuple[Any, ...]:
                return ranks.board_key(cards.STATUSES, row)

            ordered = sorted(matching(conn.execute(query).all()), key=key)
            if cursor is not None:
                ordered = _after(ordered, *paging.unkey(cursor, bound), key)
            shown = ordered[:limit]
            following = None
            if len(ordered) > limit:
                last, column = shown[-1], key(shown[-1])[0]
                in_column = [r.id for r in shown if key(r)[0] == column]
                first_not_shown = ordered[limit]
                following = paging.key_cursor(
                    (last.id, key(last)),
                    (first_not_shown.id, key(first_not_shown)),
                    in_column,
                    bound,
                )
            return JSONResponse({"items": views(shown), "next_cursor": following})
        if cursor is not None:
            after_at, after_id = paging.uncursor(cursor, bound)
            query = query.where(
                or_(
                    t.card.c.updated_at < after_at,
                    and_(t.card.c.updated_at == after_at, t.card.c.id < after_id),
                )
            )
        query = query.order_by(t.card.c.updated_at.desc(), t.card.c.id.desc())
        if q is None:
            query = query.limit(limit + 1)
        rows = matching(conn.execute(query).all())
        page = rows[:limit]
        next_cursor = (
            paging.cursor(page[-1].updated_at, page[-1].id, bound) if len(rows) > limit else None
        )
        return JSONResponse({"items": views(page), "next_cursor": next_cursor})


def _after(
    ordered: list[Any],
    anchor: tuple[str, tuple[Any, ...]],
    following: tuple[str, tuple[Any, ...]],
    shown: frozenset[str],
    key: Callable[[Any], tuple[Any, ...]],
) -> list[Any]:
    """The cards after the ones a page showed, never ending early while a card that did
    not move is still unshown. A move ranks unranked cards on the way and spreads a column
    out, which changes their keys but never the order of the cards that did not move. So
    the page goes on after the last card shown where it still sits in its column; else
    from the first card not shown, if it has not moved at all (same key); else from the
    top of the last card's column again, without the cards this page showed."""
    places = {row.id: i for i, row in enumerate(ordered)}
    anchor_id, was = anchor
    if anchor_id in places and key(ordered[places[anchor_id]])[0] == was[0]:
        return ordered[places[anchor_id] + 1 :]
    following_id, next_was = following
    if following_id in places and key(ordered[places[following_id]]) == next_was:
        return ordered[places[following_id] :]
    try:
        return [r for r in ordered if key(r)[0] >= was[0] and r.id not in shown]
    except TypeError:  # a key of another shape: not a cursor this list gave
        raise invalid({"cursor": "invalid"}) from None


@router.get("/projects/{owner}/{slug}/tasks/{card_id}")
def get_task(slug: str, card_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    fg = reader_of(request)
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        return JSONResponse(task_view(conn, _project_card(conn, mine, card_id), fg, mine))


# A card's fields as its creation records them (§6.15).
CREATED = (
    "kind",
    "title",
    "body",
    "label",
    "status",
    "area",
    "assigned_to",
    "depends_on",
    "ships_with",
    "parent",
    "related",
    "ktw_ref",
    "contract",
    "links",
    "imported_from",
)


@router.post("/projects/{owner}/{slug}/tasks")
def create_task(slug: str, body: TaskCreate, request: Request, caller: AnyCaller) -> JSONResponse:
    fg = reader_of(request)

    def action(conn: Connection) -> idempotency.Outcome:
        return create_card(conn, caller, slug, body, fg)

    response = idempotency.run(engine_of(request), request, caller, action)
    if body.links:
        from maity_hub.routes.board import observe_soon  # board builds on this module

        observe_soon(request, slug, response)
    return response


def create_card(
    conn: Connection,
    caller: Caller,
    slug: str,
    body: TaskCreate,
    fg: Forge,
    *,
    imported_from: dict[str, Any] | None = None,
    observed: dict[str, Any] | None = None,
) -> idempotency.Outcome:
    """`POST …/tasks` and the import (§6.14): one card with its links, its creation's
    history entry and `task_created`. An import passes `imported_from` and the
    observation of its one link, read before the transaction."""
    mine = membership(conn, caller, slug)
    mine.require("tasks:write")
    if body.kind not in cards.KINDS:
        raise invalid({"kind": "unknown"})
    if body.kind == "setup":
        raise invalid({"kind": "hub_only"}, "only the hub creates a setup card (§6.21)")
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
    _refuse_paused(conn, mine.id, mine.instance)  # a paused agent opens no new work
    if imported_from is not None:
        _refuse_imported_twice(conn, mine, imported_from["forge_url"])
    extra: dict[str, Any] = {}
    if body.kind == "release":
        extra = _new_release(conn, mine, body.release)
    elif body.kind == "contract":
        extra = {"contract": _new_contract(conn, mine, body.contract or ContractIn())}
    assigned: int | None
    if body.assigned_to is not None:
        assigned = _target_id(conn, mine, body.assigned_to, "assigned_to")
        _require_assigner(conn, mine, assigned)
        availability.refuse_coordinator_out(conn, mine, "new assignments")
    else:
        # Findings and hand-outs go to the owner of the narrowest area (§6.2), and while
        # that owner is covered to its substitute (§6.12): the hub's routing, not an
        # agent's assignment, so the coordinator gate does not apply.
        assigned = cards.area_owner(conn, mine.project.id, body.area)
        assigned, routed_cover = cover.routed(conn, assigned)
        if routed_cover is not None:
            extra = {**extra, "cover": routed_cover}
    assigned_instance = _assigned_instance(conn, assigned)
    found = mentions.resolve(conn, mine.project.id, body.body, "body")
    now = clock.now()
    card_id = new_id({"release": "release", "contract": "contract"}.get(body.kind, "task"))
    status = body.status
    if (
        body.parent is not None
        and mine.project.subtasks == "proposed"
        and not mine.may("tasks:admin")
    ):
        if "status" in body.model_fields_set and status == "open":
            raise _subtasks_proposed()
        status = "proposed"
    cards.check_subtask_graph(
        conn,
        mine.project.id,
        card_id,
        kind=body.kind,
        parent=body.parent,
        depends_on=body.depends_on,
        fields={"parent"} if body.parent is not None else {"depends_on"},
    )
    try:
        # The pre-checks hold under the project lock; the constraints are the backstop.
        with conn.begin_nested():
            conn.execute(
                insert(t.card).values(
                    **extra,
                    id=card_id,
                    project_id=mine.project.id,
                    kind=body.kind,
                    title=body.title,
                    body=body.body,
                    mentions=found,
                    label=body.label,
                    status=status,
                    parent=body.parent,
                    area=body.area,
                    created_by=mine.id,
                    assigned_to=assigned,
                    assigned_instance=assigned_instance,
                    ktw_ref=body.ktw_ref,
                    imported_from=imported_from,
                    changed_by_credential=caller.credential_id,
                    changed_via=caller.via,
                    created_at=now,
                    updated_at=now,
                )
            )
    except IntegrityError as error:
        raise _release_conflict(error, body.release) from None
    cards.set_depends_on(conn, mine.project.id, card_id, body.depends_on)
    partners = cards.set_ships_with(conn, mine.project.id, card_id, body.ships_with)
    _touch_partners(conn, mine, caller, partners, fg)
    related = cards.set_symmetric(conn, mine.project.id, card_id, body.related, "related")
    _touch_partners(conn, mine, caller, related, fg, "related")
    card = _card(conn, card_id)
    for link in body.links:
        card_links.add(conn, card, link, mine.project.repository_url, mine.id)
    if observed is not None:  # the import's one link, observed from the same read
        conn.execute(
            update(t.card_link).where(t.card_link.c.card_id == card_id).values(observed=observed)
        )
    view = task_view(conn, card, fg)
    # One history entry for the creation, with the card's fields as created (§6.15).
    fields = [name for name in CREATED if name in view and view[name] not in (None, [])]
    entry = history.created(
        conn, card_id, {name: view[name] for name in fields}, caller.actor(mine.id)
    )
    seq = emit(
        conn,
        mine.project.id,
        "task_created",
        audience(conn, card),
        {
            **{k: v for k, v in view.items() if k != "body"},  # never in an event
            "fields": fields,
            "history": [entry],
            **state,
        },
        actor=caller.actor(mine.id),
        subject=("task", card_id),
    )
    history.stamp(conn, [entry], seq)
    if body.parent is not None:
        _touch_parents(conn, mine, caller, {body.parent}, fg)
    _ping(conn, mine, caller, card, found, "body", before=[])
    releases.recheck(conn, mine.project.id, fg)  # a release may be ready from the start
    watching = bool(card_watches.watching(conn, [card_id], mine.id))  # by its dependencies
    return idempotency.Outcome(201, "task", card_id, {**view, "watching": watching})


def _refuse_imported_twice(conn: Connection, mine: Membership, forge_url: str) -> None:
    """An issue a card not done or cancelled was imported from is `already_linked`
    (§6.14); after that card closes, a new import is allowed."""
    rows = conn.execute(
        select(t.card.c.id, t.card.c.imported_from).where(
            t.card.c.project_id == mine.project.id,
            t.card.c.imported_from.isnot(None),
            t.card.c.status.notin_(cards.CLOSED),
        )
    ).all()
    for row in rows:
        # GitHub's owner and repository names ignore case: one issue, one URL.
        if str(row.imported_from.get("forge_url", "")).lower() == forge_url.lower():
            raise ApiError(
                409, "already_linked", "a card was imported from this issue", {"task": row.id}
            )


@router.patch("/projects/{owner}/{slug}/tasks/{card_id}")
def patch_task(
    slug: str, card_id: str, body: TaskPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    fg = reader_of(request)
    given = body.model_fields_set

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("tasks:write")
        mine = _locked(conn, mine)
        card = _project_card(conn, mine, card_id)
        new_assignee: int | None = None
        if "assigned_to" in given and body.assigned_to:
            new_assignee = _target_id(conn, mine, body.assigned_to, "assigned_to")
        # No agent assigns away, cancels or sets back to open a card a human holds
        # (§2.3): before any gate. `done` stays done authority's (§6.4).
        assigns_away = "assigned_to" in given and new_assignee not in (
            card.assigned_to,
            card.claim_holder,
        )
        drops = "status" in given and body.status in ("cancelled", "open")
        if assigns_away or (drops and body.status != card.status):
            _refuse_against_a_human(conn, mine, card)
        # A status-only move out of review is done authority's, whoever holds it (§6.4).
        review_move = (
            given - {"approve"} == {"status"}
            and card.status == "review"
            and body.status in ("done", "in_progress")
        )
        # So is a state-only move of a contract card the arbiter's (§6.8).
        arbiter_move = (
            given == {"contract"}
            and body.contract is not None
            and body.contract.model_fields_set <= {"state"}
            and card.kind == "contract"
            and _is_arbiter(conn, mine, card.contract or {})
        )
        # And the release fields are any releaser's, holder or not (§6.7).
        release_edit = (
            given == {"release"} and card.kind == "release" and mine.may("releases:write")
        )
        editor = cards.holds(mine, card) or card.created_by == mine.id or mine.may("tasks:admin")
        # `assigned_to` alone is also a manager's within its reach (§2.3 "The manager").
        line_assign = given == {"assigned_to"} and _line_lead(mine)
        if (
            not editor
            and not line_assign
            and not arbiter_move
            and not release_edit
            and not (review_move and cards.has_done_authority(mine, card))
        ):
            raise forbidden("tasks:admin", "only the holder, the creator or an admin edits a card")
        if "approve" in given and not (
            review_move and body.status == "done" and cards.two_signatures(mine.project)
        ):
            raise invalid({"approve": "not_applicable"})
        values: dict[str, Any] = {}
        parent = body.parent if "parent" in given else card.parent
        wanted_status = body.status if body.status is not None else card.status
        opens_child = (card.status == "proposed" and wanted_status == "open") or (
            parent != card.parent and wanted_status != "proposed"
        )
        if (
            parent is not None
            and mine.project.subtasks == "proposed"
            and not mine.may("tasks:admin")
            and opens_child
        ):
            raise _subtasks_proposed()
        graph_fields = given & {"parent", "depends_on"}
        if graph_fields:
            cards.check_subtask_graph(
                conn,
                mine.project.id,
                card.id,
                kind=card.kind,
                parent=parent,
                depends_on=body.depends_on,
                fields=graph_fields,
            )
        if "parent" in given:
            values["parent"] = parent
            # The graph above sees both changes; the existing dependency helper below
            # must also see the new parent gate, not the old one.
            conn.execute(update(t.card).where(t.card.c.id == card.id).values(parent=parent))
        for field in ("title", "body", "ktw_ref"):
            if field in given and (field != "title" or body.title is not None):
                values[field] = getattr(body, field)
        found = None
        if "body" in values:
            found = mentions.resolve(conn, mine.project.id, values["body"], "body")
            values["mentions"] = found
        if "label" in given:
            _check_label(body.label)
            values["label"] = body.label
        if "area" in given:
            _check_area(body.area)
            values["area"] = body.area
        if "assigned_to" in given:
            _require_assigner(conn, mine, new_assignee, card.assigned_to, card.claim_holder)
            availability.refuse_coordinator_out(conn, mine, "new assignments")
            if assigns_away and not cards.holds(mine, card):
                takeovers.guard_move(conn, mine, card)
            values["assigned_to"] = new_assignee
            if values["assigned_to"] != card.assigned_to:
                # The new team's distribution decides, as on every assignment (§6.18).
                values["assigned_instance"] = _assigned_instance(conn, values["assigned_to"])
        if body.release is not None:
            values["release_data"] = _patched_release(mine, card, body.release)
        if body.contract is not None:
            values["contract"] = _patched_contract(conn, mine, card, body.contract)
        if body.depends_on is not None:
            _refuse_closed_release(card)
        before = (
            cards.edges(conn, card.id)
            if body.depends_on is not None
            or body.ships_with is not None
            or body.related is not None
            else None
        )
        depends_changed = body.depends_on is not None and cards.set_depends_on(
            conn, mine.project.id, card.id, body.depends_on
        )
        partners: set[str] = set()
        if body.ships_with is not None:
            partners = cards.set_ships_with(conn, mine.project.id, card.id, body.ships_with)
        related: set[str] = set()
        if body.related is not None:
            related = cards.set_symmetric(conn, mine.project.id, card.id, body.related, "related")
        if "status" in given and body.status is not None and body.status != card.status:
            if body.status not in cards.STATUSES:
                raise invalid({"status": "unknown"})
            if card.status == "cancelled":  # a card moderation cancelled stays so (§16.8)
                moderation.refuse_held(conn, "card", card.id, "remove")
            cards.check_transition(mine, card, body.status)
            if body.status == "done":
                cards.refuse_open_dependencies(conn, card.id)
                _refuse_unready(conn, card, fg, values.get("release_data"))
            signed = _signatures(mine, card, body)
            if signed is not None:
                values["approvals"] = signed
            if card.status == "review" and body.status == "in_progress":
                values["approvals"] = None  # a signature covers the work it was given on (§6.4)
            if signed is None or cards.signed_by_two(signed, _revision(card)):
                values["status"] = body.status
                if body.status in cards.CLOSED:
                    values.update(_closing(card))
        previous_mentions = card.mentions or []
        changed = {k: v for k, v in values.items() if getattr(card, k) != v}
        edges_changed = depends_changed or bool(partners) or bool(related)
        if not changed and not edges_changed:
            return idempotency.Outcome(200, "task", card.id, task_view(conn, card, fg, mine))
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
        before_card = card
        if "status" in changed:
            cover.touch(conn, before_card, mine.principal_id)
        card = _card(conn, card.id)
        view = task_view(conn, card, fg)
        payload = {k: view[k] for k in changed if k in view and k != "body"}  # never body
        fields = [k for k in changed if k in view]
        extra: list[tuple[str, Any, Any]] = []
        for name, moved in (
            ("depends_on", depends_changed),
            ("ships_with", bool(partners)),
            ("related", bool(related)),
        ):
            if moved and before is not None and before[name] != view[name]:
                payload[name] = view[name]
                fields.append(name)
                extra.append((name, before[name], view[name]))
        if "release_data" in changed:
            payload["release"] = view["release"]
            fields.append("release")
        if "contract" in changed:
            was, now = before_card.contract or {}, view["contract"] or {}
            for name in ("state", "path", "section"):
                if was.get(name) != now.get(name):
                    extra.append((f"contract.{name}", was.get(name), now.get(name)))
        entries = history.record(
            conn,
            before_card,
            changed,
            caller.actor(mine.id),
            shown={
                "assigned_to": (
                    principal_id(conn, before_card.assigned_to),
                    principal_id(conn, card.assigned_to),
                )
            },
            extra=extra,
        )
        _touch_partners(conn, mine, caller, partners, fg)
        _touch_partners(conn, mine, caller, related, fg, "related")
        seq = emit(
            conn,
            mine.project.id,
            "task_updated",
            audience(conn, card),
            {
                **payload,
                "id": card.id,
                "fields": sorted(set(fields)),
                "history": entries,
                "project_state": mine.project.state,
            },
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        history.stamp(conn, entries, seq)
        if changed.get("status") == "review":
            merged.returned_to_review(conn, card.id)  # a merge remembered is told now (§6.6)
        touched_parents: set[str] = set()
        if "parent" in changed:
            touched_parents.update(p for p in (before_card.parent, card.parent) if p is not None)
        elif (
            "status" in changed
            and card.parent is not None
            and ((before_card.status in cards.CLOSED) != (card.status in cards.CLOSED))
        ):
            touched_parents.add(card.parent)
        _touch_parents(conn, mine, caller, touched_parents, fg)
        if found is not None:
            _ping(conn, mine, caller, card, found, "body", before=previous_mentions)
        if changed.get("status") in cards.CLOSED:
            takeovers.reconcile(conn, card.id, caller.actor(mine.id), decided=False)
        if card.kind == "release" and changed.get("status") in cards.CLOSED:
            releases.close(conn, card.id, fg)  # after the write's own event: release_ready last
        if card.kind == "release" and changed.get("status") == "done":
            # The card as this write left it: its title and version as they are now.
            ticker.on_release_done(
                conn, mine.project, _card(conn, card.id), caller.actor(mine.id), mine.principal_id
            )
        releases.recheck(conn, mine.project.id, fg)
        return idempotency.Outcome(
            200, "task", card.id, task_view(conn, _card(conn, card.id), fg, mine)
        )

    return idempotency.run(engine_of(request), request, caller, action)


def cancel_by_moderation(conn: Connection, card_id: str, actor: Actor, fg: Forge) -> None:
    """`remove` on a card (§16.8): cancelled as a `PATCH {status: cancelled}` would cancel
    it, whoever holds it; a closed card stays as it is."""
    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).first()
    if card is None or card.status in cards.CLOSED:
        return
    project = lock_project(conn, card.project_id)
    changed = {"status": "cancelled", **_closing(card)}
    conn.execute(
        update(t.card)
        .where(t.card.c.id == card.id)
        .values(**changed, updated_at=clock.now(), changed_by_credential=None, changed_via=None)
    )
    after = _card(conn, card.id)
    view = task_view(conn, after, fg)
    entries = history.record(conn, card, changed, actor)
    seq = emit(
        conn,
        project.id,
        "task_updated",
        audience(conn, after),
        {
            **{k: view[k] for k in changed if k in view},
            "id": card.id,
            "fields": sorted(k for k in changed if k in view),
            "history": entries,
            "project_state": project.state,
        },
        actor=actor,
        subject=("task", card.id),
    )
    history.stamp(conn, entries, seq)
    if card.parent is not None:
        conn.execute(
            update(t.card).where(t.card.c.id == card.parent).values(updated_at=clock.now())
        )
        parent = _card(conn, card.parent)
        emit(
            conn,
            project.id,
            "task_updated",
            audience(conn, parent),
            {
                "id": parent.id,
                "fields": ["children"],
                "children": task_view(conn, parent, fg)["children"],
                "history": [],
                "project_state": project.state,
            },
            actor=actor,
            subject=("task", parent.id),
        )
    takeovers.reconcile(conn, card.id, actor, decided=False)
    if card.kind == "release":
        releases.close(conn, card.id, fg)
    releases.recheck(conn, project.id, fg)


def _ping(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    card: Any,
    found: list[dict[str, Any]],
    field: str,
    *,
    before: list[dict[str, Any]],
) -> None:
    """`mentioned` to the members a card body or a report summary newly mentions (§8.6):
    not again for a member the body mentioned before this write, never to the writer."""
    known = set(mentions.members(before))
    new = [m for m in mentions.members(found) if m not in known and m != mine.principal_id]
    if not new:
        return
    mentions.charge(conn, mine.id, len(new))
    emit(
        conn,
        mine.project.id,
        "mentioned",
        mentions.tokens(
            conn, mine.project.id, found, new
        ),  # an instance mention pings that instance (§8.6)
        {
            "task": {"id": card.id, "title": card.title, "status": card.status},
            "field": field,
            "mentions": [m for m in found if m["member_id"] in new],
        },
        actor=caller.actor(mine.id),
        subject=("task", card.id),
    )


# --- claims and leases (§6.5) ----------------------------------------------------------


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/claim")
def claim(
    slug: str, card_id: str, body: ClaimIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    fg = reader_of(request)

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("tasks:write")
        mine = _locked(conn, mine)
        state = _require_open_project(mine, body.reason)
        card = _project_card(conn, mine, card_id)
        holder_id = mine.id
        instance = mine.instance
        session_id = caller.session_id
        if body.holder is not None and body.holder not in (
            mine.principal_id,
            instances.address(mine.principal_id, mine.instance or ""),
        ):
            mine.require("tasks:admin")
            availability.refuse_coordinator_out(conn, mine, "new assignments")
            principal, named = instances.split_address(body.holder)
            holder_id = _target_id(conn, mine, principal, "holder")  # never a guest (§2.3)
            holder_row = conn.execute(
                select(t.membership).where(t.membership.c.id == holder_id)
            ).one()
            # An address names the instance; a member id must come down to one (§6.5).
            instance = instances.resolve(conn, holder_row, named, "holder")
            session_id = None  # the holder's next call moves it to its session
        _refuse_paused(conn, holder_id, instance)  # also when an admin claims on its behalf
        if card.claim_holder is not None:
            raise _already_claimed(conn, card)
        if holder_id == mine.id and card.assigned_to == mine.id:
            _refuse_other_instance(mine, card)
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
                claim_instance=instance,
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
        cover.touch(conn, card, mine.principal_id)  # a substitute claimed what it was handed
        card = _card(conn, card.id)
        emit(
            conn,
            mine.project.id,
            "task_claimed",
            audience(conn, card),
            {
                "holder": principal_id(conn, holder_id),
                "instance": instance,
                "lease_until": clock.rfc3339(lease_until),
                **state,
            },
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        status_moved(conn, card, mine.project.state, caller.actor(mine.id))  # to in_progress
        return idempotency.Outcome(200, "task", card.id, task_view(conn, card, fg, mine))

    return idempotency.run(engine_of(request), request, caller, action)


def status_moved(conn: Connection, card: Any, project_state: str, actor: Any) -> None:
    """The `task_updated` of a status moved under an event of another kind (a claim, a release,
    a report, a request that blocks or unblocks the card, a holder's isolation or removal): the
    one a card's watchers are reached by (§6.4, §8.2). It follows the event that caused the
    move. `actor` is None where no member acts."""
    emit(
        conn,
        card.project_id,
        "task_updated",
        audience(conn, card),
        {
            "id": card.id,
            "fields": ["status"],
            "status": card.status,
            "history": [],  # the event beside this one is the record of the change
            "project_state": project_state,
        },
        actor=actor,
        subject=("task", card.id),
    )


def _refuse_other_instance(mine: Membership, card: Any) -> None:
    """A card assigned to the caller's team goes to the instance the team's
    distribution chose: another instance gets `instance_assigned`, and so does any
    instance but the lead under `lead` while none is chosen yet (§6.18)."""
    if mine.instance is None:
        return
    chosen = card.assigned_instance
    if chosen is None and mine.row.distribution == "lead":
        if mine.row.lead_instance == mine.instance:
            return
    elif chosen is None or chosen == mine.instance:
        return
    raise ApiError(
        409,
        "instance_assigned",
        "this card is meant for another instance of your team",
        {"assigned_instance": chosen},
    )


def _already_claimed(conn: Connection, card: Any) -> ApiError:
    if card.claim_holder is None:  # not held after all: it left `open` some other way
        return cards.invalid_transition(card.status, "in_progress")
    holder = principal_id(conn, card.claim_holder)
    expired = card.lease_until is not None and card.lease_until <= clock.now()
    return ApiError(
        409,
        "already_claimed",
        f"{card.id} is claimed by {holder}",
        {
            "holder": holder,
            "instance": card.claim_instance,
            "lease_until": clock.rfc3339(card.lease_until),
            "expired": expired,
        },
    )


def _not_holder(card: Any) -> ApiError:
    """The holding instance's siblings learn which instance holds it (§6.4)."""
    return ApiError(
        409,
        "not_holder",
        "only the holder of the card may do this",
        {"instance": card.claim_instance},
    )


def _lease_active(card: Any) -> ApiError:
    return ApiError(
        409,
        "lease_active",
        "the holder's lease has not expired",
        {"lease_until": clock.rfc3339(card.lease_until) if card.lease_until else None},
    )


def _refuse_against_a_human(conn: Connection, mine: Membership, card: Any) -> None:
    """No agent, whatever its role, takes over, assigns away, releases, cancels or sets
    back to open a card a human holds, lease or no lease (§2.3 "What no agent may do");
    checked before the scope and before the lease, so that nothing says more to it."""
    if mine.kind != "agent" or card.claim_holder is None:
        return
    holder = conn.execute(
        select(t.membership.c.human_id).where(t.membership.c.id == card.claim_holder)
    ).scalar()
    if holder is not None:
        raise humans_only("an agent never takes, assigns away, releases or drops a human's card")


def _lease_expired(card: Any) -> bool:
    return card.lease_until is not None and card.lease_until <= clock.now()


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/release")
def release(slug: str, card_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    fg = reader_of(request)

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine = _locked(conn, mine)
        card = _project_card(conn, mine, card_id)
        if card.claim_holder is None:
            raise ApiError(409, "not_holder", "the card is not claimed")
        takes = not cards.holds(mine, card)
        if takes:
            _refuse_against_a_human(conn, mine, card)
            lead = _leads_its_team(mine, card)
            if cards.sibling_holds(mine, card) and not (mine.may("tasks:admin") or lead):
                raise _not_holder(card)
            if not lead:
                # A manager releases an expired claim held in its reach (§2.3).
                _require_assigner(conn, mine, card.claim_holder)
            # An agent takes a card only through a takeover while the lease runs (§6.19).
            takeovers.guard_move(conn, mine, card)
            if not _lease_expired(card):
                raise ApiError(
                    409,
                    "lease_active",
                    "the holder's lease has not expired",
                    {"lease_until": clock.rfc3339(card.lease_until)},
                )
        before = card
        old_holder = (card.claim_holder, card.claim_instance)
        now = clock.now()
        # Conditional: a renewal by the holder a moment ago must not be wiped.
        still = [t.card.c.claim_holder == old_holder[0]]
        if not cards.holds(mine, card):
            still.append(t.card.c.lease_until <= now)
        released = conn.execute(
            update(t.card)
            .where(t.card.c.id == card.id, *still)
            .values(
                claim_holder=None,
                claim_instance=None,
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
        if card.status != before.status:
            status_moved(conn, card, mine.project.state, caller.actor(mine.id))
        _after_move(conn, mine, caller, before, takes, (mine.id, mine.instance))
        return idempotency.Outcome(200, "task", card.id, task_view(conn, card, fg, mine))

    return idempotency.run(engine_of(request), request, caller, action)


class MoveIn(Strict):
    before: str | None = None
    after: str | None = None
    to: Literal["top", "bottom"] | None = None


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/move")
def move(
    slug: str, card_id: str, body: MoveIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    """Places a card within its status column (§6.4): before or after a neighbour, or at
    the top or the bottom. Ranks change only where the order needs them to; every card
    whose rank changes is announced."""
    fg = reader_of(request)
    given = [k for k in ("before", "after", "to") if getattr(body, k) is not None]
    if len(given) != 1:
        raise invalid({"move": "one_of_before_after_to"}, "give exactly one of before, after, to")

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("tasks:admin")
        # The column as it is when the move runs, under the project's lock (§6.4).
        mine = _locked(conn, mine)
        if mine.project.state in CLOSED_STATES:
            raise ApiError(409, "project_closed", f"the project is {mine.project.state}")
        card = _project_card(conn, mine, card_id)
        column = sorted(
            conn.execute(
                select(t.card).where(
                    t.card.c.project_id == mine.project.id, t.card.c.status == card.status
                )
            ).all(),
            key=ranks.column_key,
        )
        others = [c.id for c in column if c.id != card.id]
        if body.to is not None:
            index = 0 if body.to == "top" else len(others)
        else:
            neighbour_id = body.before or body.after
            assert neighbour_id is not None
            field = "before" if body.before is not None else "after"
            neighbour = _project_card(conn, mine, neighbour_id)  # not_found when missing
            if neighbour.id == card.id or neighbour.status != card.status:
                raise invalid({field: "not_in_this_column"}, "a neighbour in the same column")
            index = others.index(neighbour.id) + (1 if field == "after" else 0)
        for changed_id, rank in sorted(ranks.place(column, card.id, index).items()):
            conn.execute(update(t.card).where(t.card.c.id == changed_id).values(rank=rank))
            emit(
                conn,
                mine.project.id,
                "task_updated",
                audience(conn, _card(conn, changed_id)),
                {
                    "id": changed_id,
                    "fields": ["rank"],
                    "rank": rank,
                    "history": [],  # a move is layout, not history (§6.15)
                    "project_state": mine.project.state,
                },
                actor=caller.actor(mine.id),
                subject=("task", changed_id),
            )
        return idempotency.Outcome(
            200, "task", card.id, task_view(conn, _card(conn, card.id), fg, mine)
        )

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/assign")
def assign(
    slug: str, card_id: str, body: AssignIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    fg = reader_of(request)

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine = _locked(conn, mine)
        card = _project_card(conn, mine, card_id)
        assignee = _target_id(conn, mine, body.assignee, "assignee")
        if card.claim_holder not in (None, assignee):
            # Before the scope: no agent, whatever its role, assigns it away (§2.3).
            _refuse_against_a_human(conn, mine, card)
        if mine.may("tasks:admin"):
            pass
        elif _leads_within_team(mine, card, body.assignee):
            # The lead hands out its team's cards nobody holds; a held card moves only
            # through a takeover (§6.18, §6.19), a human's never (§2.3).
            if card.claim_holder is not None:
                raise _held(conn, card)
        else:
            # A manager moves a card among itself and its reach, an expired claim
            # included (§2.3 "The manager"): every member it touches in the reach.
            _require_assigner(conn, mine, assignee, card.assigned_to, card.claim_holder)
        availability.refuse_coordinator_out(conn, mine, "new assignments")  # after the right
        assignee_row = conn.execute(select(t.membership).where(t.membership.c.id == assignee)).one()
        takes = card.claim_holder is not None and card.claim_holder != assignee
        if body.instance is not None:
            instances.require_active(conn, assignee_row, body.instance, "instance")
            if assignee_row.distribution == "free" and not takes:
                # Under `free` any instance claims and none is assigned (§6.18); the
                # instance only names where an expired claim lands.
                raise invalid(
                    {"instance": "distribution_free"},
                    "the team's distribution is free: no instance is assigned",
                )
        if body.instance is None and card.assigned_to == assignee:
            # The same team again: its instance stays; a new turn only for a new team.
            chosen = card.assigned_instance
        else:
            chosen = instances.assigned_for(conn, assignee_row, body.instance)
        now = clock.now()
        values: dict[str, Any] = {"assigned_to": assignee, "assigned_instance": chosen}
        old_holder = (card.claim_holder, card.claim_instance)
        old_assignee = (card.assigned_to, card.assigned_instance)
        if (
            card.claim_holder == assignee
            and chosen is not None
            and card.claim_instance not in (None, chosen)
        ):
            # Moving `assigned_instance` away from the holding instance is a takeover
            # (§6.18): `POST …/takeover`, never `assign`.
            raise _held(conn, card)
        before = card
        if takes:
            # An agent takes a card only through a takeover while the lease runs (§6.19).
            takeovers.guard_move(conn, mine, card)
            if not _lease_expired(card):
                raise ApiError(
                    409,
                    "lease_active",
                    "the holder's lease has not expired",
                    {"lease_until": clock.rfc3339(card.lease_until)},
                )
            # An expired claim moves to the assignee (§6.4): a claim on its behalf.
            # Held by exactly one instance: named, or the one the team's rules give,
            # else `instance_required` as on a claim (§6.17, §6.5).
            instance = chosen or instances.resolve(conn, assignee_row, body.instance, "instance")
            _refuse_paused(conn, assignee, instance)
            values.update(
                claim_holder=assignee,
                claim_instance=instance,
                claim_session_id=None,
                claim_since=now,
                lease_until=now + timedelta(seconds=mine.project.lease_seconds),
            )
        moves_claim = "claim_holder" in values
        still = (
            [t.card.c.claim_holder == old_holder[0], t.card.c.lease_until <= now]
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
        if assignee != card.assigned_to:
            # Not stamped onto `task_assigned`: §8.2 gives that event no `history`, and its
            # value is a member id, which carries nothing a redaction would need to reach.
            history.record(
                conn,
                card,
                {"assigned_to": assignee},
                caller.actor(mine.id),
                shown={
                    "assigned_to": (
                        principal_id(conn, card.assigned_to),
                        principal_id(conn, assignee),
                    )
                },
            )
        card = _card(conn, card.id)
        emit(
            conn,
            mine.project.id,
            "task_assigned",
            audience(conn, card, old_holder, old_assignee),
            {
                "assignee": principal_id(conn, assignee),
                "assigned_instance": card.assigned_instance,
                "holder": principal_id(conn, card.claim_holder),
                "instance": card.claim_instance,
                "lease_until": clock.rfc3339(card.lease_until) if card.lease_until else None,
                "project_state": mine.project.state,
                "reason": None,
            },
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        _after_move(conn, mine, caller, before, takes, (assignee, card.claim_instance))
        return idempotency.Outcome(200, "task", card.id, task_view(conn, card, fg, mine))

    return idempotency.run(engine_of(request), request, caller, action)


# --- checkpoint and report (§6.4, §6.6) -------------------------------------------------


def _assigned_instance(conn: Connection, membership_id: int | None) -> str | None:
    """`assigned_instance` for a card assigned to a member without naming one (§6.18)."""
    if membership_id is None:
        return None
    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    return instances.assigned_for(conn, row, None)


def _held(conn: Connection, card: Any) -> ApiError:
    """A held card that would move by `assign`: a human's never moves (§2.3), another's
    only through a takeover (§6.19)."""
    holder = conn.execute(select(t.membership).where(t.membership.c.id == card.claim_holder)).one()
    if holder.agent_id is None:
        return ApiError(
            403,
            "forbidden",
            "a card a human holds moves only by that human",
            {"reason": "humans_only"},
        )
    return ApiError(
        409,
        "takeover_required",
        "the card is held: it moves only through a takeover",
        {"holder": holder.agent_id, "instance": card.claim_instance},
    )


def _leads_its_team(mine: Membership, card: Any) -> bool:
    """The calling instance is the lead of the team that holds the card (§6.19)."""
    return (
        mine.instance is not None
        and card.claim_holder == mine.id
        and mine.row.lead_instance == mine.instance
    )


def _after_move(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    before: Any,
    took: bool,
    to: tuple[int, str | None],
) -> None:
    """What a card write that may have taken the card from its holder leaves in the
    takeover history (§6.19): an agent's move after the lease ran out is recorded as a
    `lease_expired` takeover, and an open takeover the card left is closed —
    `decided` when a human with `tasks:admin` moved it."""
    if took and mine.kind == "agent":
        takeovers.record_lease_expired(conn, mine, caller, before, to)
    decided = took and mine.kind == "human" and mine.may("tasks:admin")
    takeovers.reconcile(conn, before.id, caller.actor(mine.id), decided=decided)


def _leads_within_team(mine: Membership, card: Any, assignee: str) -> bool:
    """The lead instance of a team under `distribution: lead` hands out the cards
    assigned to its own team, among its own instances (§6.18)."""
    return (
        mine.instance is not None
        and mine.row.distribution == "lead"
        and mine.row.lead_instance == mine.instance
        and card.assigned_to == mine.id
        and assignee == mine.principal_id
    )


def _holder_card(conn: Connection, mine: Membership, card_id: str) -> Any:
    card = _project_card(conn, mine, card_id)
    if cards.sibling_holds(mine, card):
        raise _not_holder(card)
    if not cards.holds(mine, card):
        raise ApiError(409, "not_holder", "only the holder of the card may do this")
    return card


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/checkpoint")
def checkpoint(
    slug: str, card_id: str, body: CheckpointIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    fg = reader_of(request)
    if body.head is not None and not SHA.fullmatch(body.head):
        raise invalid({"head": "not_a_sha"})

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine = _locked(conn, mine)
        card = _holder_card(conn, mine, card_id)
        cover.touch(conn, card, mine.principal_id)
        now = clock.now()
        point = {
            "last_step": body.last_step,
            "next_step": body.next_step,
            "branch": body.branch,
            "head": body.head,
            "verification": _verification(caller),
            "instance": mine.instance,
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
        return idempotency.Outcome(200, "task", card.id, task_view(conn, card, fg, mine))

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/report")
def report(
    slug: str, card_id: str, body: ReportIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    fg = reader_of(request)
    _check_report(body)

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine = _locked(conn, mine)
        _check_why(body, mine.project)
        card = _project_card(conn, mine, card_id)
        already_done = card.status == "done"
        if already_done:
            previous = card.report or {}
            pr = previous.get("pr") or {}
            observed = previous.get("observed") or {}
            state = observed.get("pr_state") or pr.get("state")
            if (
                previous.get("reported_by") != mine.principal_id
                or previous.get("pr_status") != "found"
                or state != "open"
            ):
                raise cards.invalid_transition(card.status, "review")
            if body.pr is None or body.pr.number != pr.get("number"):
                raise invalid({"pr": "different_pull_request"})
        elif card.status == "cancelled":
            raise cards.invalid_transition(card.status, "review")
        else:
            card = _holder_card(conn, mine, card_id)
            cover.touch(conn, card, mine.principal_id)
            if card.status not in ("in_progress", "blocked", "review"):
                raise cards.invalid_transition(card.status, "review")
        closing = body.done and not already_done
        was_closed = card.status in cards.CLOSED
        previous_report = card.report or {}
        revision = (previous_report.get("revision") or 1) + 1 if card.report else 1
        if closing:
            # Refused as a whole, nothing stored: the agent reports again without done.
            if not cards.has_done_authority(mine, card):
                raise forbidden(
                    cards.authority_scope(mine), "done needs done authority; report without done"
                )
            # Closing by report is a review too: not of another instance's work (§6.18).
            cards.refuse_same_team_review(mine, card)
            cards.refuse_open_dependencies(conn, card.id)
            _refuse_unready(conn, card, fg)
        # Every report clears the signatures; under `reviewer_and_tester` a `done` fills at
        # most the caller's own on the new revision and never closes (§6.4, §6.6). A caller
        # holding both has no `approve` here to say which, so it fills neither.
        signatures: dict[str, Any] | None = None
        if closing and cards.two_signatures(mine.project):
            closing = False
            if not (mine.may("tasks:review") and mine.may("tasks:test")):
                empty = SimpleNamespace(approvals=None)
                signatures = cards.sign(mine, empty, None, revision)
        found = mentions.resolve(conn, mine.project.id, body.summary, "summary")
        now = clock.now()
        stored = {
            "summary": body.summary,
            "mentions": found,
            "head": body.head,
            "branch": body.branch,
            "upstream": body.upstream,
            "remote_head": body.remote_head,
            "pr": body.pr.model_dump() if body.pr else None,
            "pr_status": body.pr_status,
            "pr_unknown_reason": body.pr_unknown_reason,
            "verification": _verification(caller),
            "reported_by": mine.principal_id,
            "reported_instance": mine.instance,
            "session_id": caller.session_id,
            "reported_at": clock.rfc3339(now),
            # Filled by the probe in the background; never awaited inside a write.
            "code": body.code,
            "why": body.why,
            "observed": None,
            # A report without code is never probed: nothing to compare (§6.6).
            "mismatch": None if body.code else False,
            "revision": revision,
        }
        values: dict[str, Any] = {
            "report": stored,
            "approvals": signatures,
            # Every instance that ever reported the card: one that reports again does not
            # clear another's work for its own review (§6.18).
            "reported_instances": _reporters(card, mine),
        }
        if isinstance(body.why, dict) and "ref" in body.why and not card.ktw_ref:
            values["ktw_ref"] = body.why["ref"]  # §6.23: the card learns where its why lives
        if not already_done:  # §6.6: a done card keeps its closure and claim.
            if closing:
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
        status_before = card.status
        card = _card(conn, card.id)
        targets = _member(principal_id(conn, card.claim_holder)) + _member(
            principal_id(conn, card.created_by)
        )
        emit(
            conn,
            mine.project.id,
            "task_reported",
            list(dict.fromkeys(targets)) + [*role_tokens("reviewer"), "trust:admin"],
            # The persisted status on both sides, so that a reader tells an entry into
            # review from a refresh (§8.2, §6.22); a blocked card stays blocked.
            {**stored, "status_before": status_before, "status_after": card.status},
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        if card.status != status_before:
            status_moved(conn, card, mine.project.state, caller.actor(mine.id))
        if signatures is not None:
            emit(
                conn,
                mine.project.id,
                "task_updated",
                audience(conn, card),
                {
                    "id": card.id,
                    "fields": ["approvals"],
                    "approvals": signatures,
                    "history": [],
                    "project_state": mine.project.state,
                },
                actor=caller.actor(mine.id),
                subject=("task", card.id),
            )
        _ping(conn, mine, caller, card, found, "report.summary", before=[])
        if card.parent is not None and was_closed != (card.status in cards.CLOSED):
            _touch_parents(conn, mine, caller, {card.parent}, fg)
        if closing:
            takeovers.reconcile(conn, card.id, caller.actor(mine.id), decided=False)
        if closing and card.kind == "release":
            releases.close(conn, card.id, fg)  # after task_reported: release_ready comes last
            ticker.on_release_done(
                conn, mine.project, card, caller.actor(mine.id), mine.principal_id
            )
        releases.recheck(conn, mine.project.id, fg)
        return idempotency.Outcome(
            200, "task", card.id, task_view(conn, _card(conn, card.id), fg, mine)
        )

    response = idempotency.run(engine_of(request), request, caller, action)
    if response.status_code == 200 and request.app.state.probe is not None:
        request.app.state.probe.report_stored(card_id)  # after the commit, never awaited
    return response


GIT_FIELDS = ("head", "branch", "upstream", "remote_head", "pr", "pr_unknown_reason")


def _reporters(card: Any, mine: Membership) -> list[dict[str, Any]]:
    earlier: list[dict[str, Any]] = list(card.reported_instances or [])
    me = {"member_id": mine.principal_id, "instance": mine.instance}
    return [*(r for r in earlier if r != me), me]


WHY_REF = re.compile(r"[^\s#]+\.md#[^\s#]+")
WHY_NONE_MIN = 10
WHY_REF_MAX = 255  # the card's `ktw_ref` column


def _check_why(body: ReportIn, project: Any) -> None:
    """`why` on a report (§6.23): one shape under both policies; the policy decides presence."""
    why = body.why
    if why is None:
        if body.code and keep_the_why_effective(project) == "required":
            raise invalid({"why": "required"})
        return
    if not body.code:
        raise invalid({"why": "not_for_no_code"})
    if isinstance(why, dict) and len(why) == 1:
        ref, none = why.get("ref"), why.get("none")
        if isinstance(ref, str):
            path = ref.split("#", 1)[0]
            if (
                len(ref) <= WHY_REF_MAX
                and WHY_REF.fullmatch(ref)
                and not path.startswith("/")
                and ".." not in path.split("/")
            ):
                return
        elif isinstance(none, str) and len(none.strip()) >= WHY_NONE_MIN:
            return
    raise invalid({"why": "malformed"})


def _check_report(body: ReportIn) -> None:
    errors: dict[str, str] = {}
    if not body.code:
        # No code, no git facts: every one of them null, and no pull request (§6.6).
        errors = {f: "not_with_code_false" for f in GIT_FIELDS if getattr(body, f) is not None}
        if body.pr_status != "none":
            errors["pr_status"] = "not_with_code_false"
        if errors:
            raise invalid(errors)
        return
    for field in ("head", "branch", "remote_head"):
        if getattr(body, field) is None:
            errors[field] = "required"
    if errors:
        raise invalid(errors)
    for field in ("head", "remote_head"):
        if not FULL_SHA.fullmatch(getattr(body, field)):
            errors[field] = "not_a_sha"
    if body.pr is not None and not FULL_SHA.fullmatch(body.pr.head):
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


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/checklist/{item_id}")
def tick_checklist(
    slug: str,
    card_id: str,
    item_id: str,
    body: ChecklistTickIn,
    request: Request,
    caller: AnyCaller,
) -> JSONResponse:
    fg = reader_of(request)

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
            return idempotency.Outcome(200, "task", card.id, task_view(conn, card, fg, mine))
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
        view = task_view(conn, card, fg)
        emit(
            conn,
            mine.project.id,
            "task_updated",
            audience(conn, card),
            {"id": card.id, "release": view["release"], "project_state": mine.project.state},
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        releases.recheck(conn, mine.project.id, fg)
        return idempotency.Outcome(
            200, "task", card.id, task_view(conn, _card(conn, card.id), fg, mine)
        )

    return idempotency.run(engine_of(request), request, caller, action)
