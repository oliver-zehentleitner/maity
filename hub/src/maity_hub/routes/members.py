"""Members of a project and their credentials (docs/api.md §6.2, §5.3, §10)."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, case, select, update

from maity_hub import clock, idempotency, placements, rules
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, member_row_or_removed, membership
from maity_hub.auth.caller import Caller
from maity_hub.auth.leaks import revoke
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, forbidden, invalid, not_found
from maity_hub.events import emit, lock_project
from maity_hub.models import Strict, markdown
from maity_hub.scopes import ROLES
from maity_hub.views import credential_view, human_paused, member_view, member_views

router = APIRouter()

CAPABILITIES = ("tag",)
# A repository path; nothing that could leave a code span in the join page.
AREA = re.compile(r"[A-Za-z0-9._/-]{1,255}")
REVOKED_LISTED = timedelta(days=30)


class PausedIn(Strict):
    reason: str = markdown(min_length=1)


class MemberPatch(Strict):
    role: str | None = None
    reports_to: str | None = None
    areas: list[str] | None = Field(default=None, max_length=50)
    capabilities: list[str] | None = Field(default=None, max_length=20)
    paused: PausedIn | None = None
    briefing: str | None = markdown(default=None)


class RevokeIn(Strict):
    reason: str | None = markdown(default=None)


def load_member(conn: Connection, membership_id: str) -> dict[str, Any]:
    """The answer of a member write. Only an admin or the member itself writes one,
    and both may read the briefing (§6.2)."""
    row = conn.execute(select(t.membership).where(t.membership.c.id == int(membership_id))).one()
    return member_view(conn, row, briefing=True)


def load_credential(conn: Connection, credential_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.credential).where(t.credential.c.id == credential_id)).one()
    return credential_view(conn, row)


idempotency.LOADERS["member"] = idempotency.plain(load_member)
idempotency.LOADERS["credential"] = idempotency.plain(load_credential)


def validate_assignment(
    conn: Connection,
    project_id: str,
    *,
    kind: str,
    role: str | None,
    reports_to: str | None,
    areas: list[str] | None,
    capabilities: list[str] | None,
    member: int | None = None,
) -> dict[str, Any]:
    """Columns for role, reports_to, areas, capabilities; `invalid` naming every bad field.
    `member` is the membership being assigned, for the cycle check; None for a new one."""
    errors: dict[str, str] = {}
    values: dict[str, Any] = {}
    if role is not None:
        if role not in ROLES:
            errors["role"] = "unknown"
        elif role == "owner" and kind != "human":
            errors["role"] = "owner_is_human"
        values["role"] = role
    if reports_to is not None:
        try:
            values["reports_to"] = member_row(conn, project_id, reports_to).id
        except ApiError:
            errors["reports_to"] = "not_a_member"
        else:
            if member is not None and member in _chain(conn, values["reports_to"]):
                errors["reports_to"] = "cycle"
    if areas is not None:
        if any(not AREA.fullmatch(a) or a.startswith("..") or "/../" in f"/{a}/" for a in areas):
            errors["areas"] = "invalid_path"
        values["areas"] = list(dict.fromkeys(areas))
    if capabilities is not None:
        if any(c not in CAPABILITIES for c in capabilities):
            errors["capabilities"] = "unknown"
        values["capabilities"] = list(dict.fromkeys(capabilities))
    if errors:
        raise invalid(errors)
    return values


def _chain(conn: Connection, membership_id: int) -> set[int]:
    """The member and everyone it reports up to (§6.2)."""
    seen: set[int] = set()
    current: int | None = membership_id
    while current is not None and current not in seen:
        seen.add(current)
        current = conn.execute(
            select(t.membership.c.reports_to).where(
                t.membership.c.id == current, t.membership.c.active.is_(True)
            )
        ).scalar()
    return seen


def _owners(conn: Connection, project_id: str) -> int:
    return len(
        conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.project_id == project_id,
                t.membership.c.role == "owner",
                t.membership.c.active.is_(True),
            )
        ).all()
    )


@router.get("/projects/{slug}/members")
def list_members(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        rows = conn.execute(
            select(t.membership).where(
                t.membership.c.project_id == mine.project.id, t.membership.c.active.is_(True)
            )
        ).all()
        admin = mine.may("members:admin")
        owned = _owned_agents(conn, mine)
        views = member_views(
            conn,
            rows,
            briefing=lambda r: admin or r.id == mine.id,
            details=lambda r: admin or r.agent_id in owned,
        )
        views.sort(key=lambda v: (v["kind"] != "human", v["handle"]))
        return JSONResponse({"items": views, "next_cursor": None})


@router.get("/projects/{slug}/members/{member_id}")
def get_member(slug: str, member_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        row = member_row(conn, mine.project.id, member_id)
        own = row.id == mine.id
        admin = mine.may("members:admin")
        details = admin or row.agent_id in _owned_agents(conn, mine)
        return JSONResponse(member_view(conn, row, briefing=own or admin, details=details))


def _owned_agents(conn: Connection, mine: Any) -> set[str]:
    """The agent profiles a human caller owns: their members' `owner` and
    `credentials` are theirs to see (§6.2)."""
    if mine.kind != "human":
        return set()
    return set(
        conn.execute(
            select(t.agent_profile.c.id).where(t.agent_profile.c.owner_id == mine.principal_id)
        ).scalars()
    )


@router.patch("/projects/{slug}/members/{member_id}")
def patch_member(
    slug: str, member_id: str, body: MemberPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    given = body.model_fields_set

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("members:admin")
        target = member_row(conn, mine.project.id, member_id)
        kind = "agent" if target.agent_id else "human"
        if body.reports_to is not None:
            # Two PATCHes naming each other must not both pass the cycle check.
            lock_project(conn, mine.project.id)
        values = validate_assignment(
            conn,
            mine.project.id,
            kind=kind,
            role=body.role,
            reports_to=body.reports_to,
            areas=body.areas,
            capabilities=body.capabilities,
            member=target.id,
        )
        if "reports_to" in given and body.reports_to is None:
            values["reports_to"] = None
        if "briefing" in given:
            values["briefing"] = body.briefing or None
        demotes = values.get("role", "owner") != "owner" and target.role == "owner"
        if demotes and _owners(conn, mine.project.id) <= 1:
            raise invalid({"role": "last_owner"}, "the last owner cannot be demoted")
        changed = {k: v for k, v in values.items() if getattr(target, k) != v}
        if changed:
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == target.id)
                .values(
                    **changed, changed_by_credential=caller.credential_id, changed_via=caller.via
                )
            )
            row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
            view = member_view(conn, row)  # to everyone: never the briefing
            if {"role", "areas"} & changed.keys():
                # The member's role brief is part of the rules: a bump (§6.9).
                rules.bump(
                    conn,
                    mine.project,
                    "member_updated",
                    ["all"],
                    view,
                    actor=caller.actor(mine.id),
                    subject=("member", member_id),
                )
            else:
                emit(
                    conn,
                    mine.project.id,
                    "member_updated",
                    ["all"],
                    view,
                    actor=caller.actor(mine.id),
                    subject=("member", member_id),
                )
        if "paused" in given:
            if target.agent_id is None:
                # A human's absence is the project's `absence` (§6.1, §5.3).
                raise invalid({"paused": "agents_only"}, "paused is for agent members")
            set_paused(conn, mine, target, body.paused.reason if body.paused else None, caller)
        return idempotency.Outcome(200, "member", str(target.id), load_member(conn, str(target.id)))

    return idempotency.run(engine_of(request), request, caller, action)


def set_paused(
    conn: Connection, mine: Membership, target: Any, reason: str | None, caller: Caller
) -> None:
    """Set or clear `paused` (§5.3). Setting it tells the member itself (its long-poll
    wakes), `reports_to` and the admins; lifting a pause someone else set tells them
    the same way, with `paused: null`."""
    now = clock.now()
    lifts_a_human_pause = reason is None and human_paused(target)
    conn.execute(
        update(t.membership)
        .where(t.membership.c.id == target.id)
        .values(
            paused_reason=reason,
            paused_since=now if reason else None,
            paused_by=caller.principal_id if reason else None,
        )
    )
    if reason is None and not lifts_a_human_pause:
        return
    row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    view = member_view(conn, row)
    audience = [f"member:{view['id']}", "role:admin"]
    if view["reports_to"]:
        audience.insert(1, f"member:{view['reports_to']}")
    emit(
        conn,
        mine.project.id,
        "session_paused",
        audience,
        {"session": view.get("session"), "paused": view["paused"]},
        actor=caller.actor(mine.id),
        subject=("member", view["id"]),
    )


@router.delete("/projects/{slug}/members/{member_id}")
def remove_member(slug: str, member_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("members:admin")
        target = member_row_or_removed(conn, mine.project.id, member_id)
        if target.active is None:  # removed already: DELETE is idempotent (§6.2)
            return idempotency.Outcome(
                200, "member", str(target.id), load_member(conn, str(target.id))
            )
        if target.role == "owner" and _owners(conn, mine.project.id) <= 1:
            raise invalid({"member": "last_owner"}, "the last owner cannot be removed")
        now = clock.now()
        credentials = (
            conn.execute(
                select(t.credential.c.id).where(
                    t.credential.c.membership_id == target.id, t.credential.c.revoked_at.is_(None)
                )
            )
            .scalars()
            .all()
        )
        for credential_id in credentials:
            revoke(conn, credential_id, "member_removed", by=caller.principal_id)
        placements.membership_removed(conn, target.id, caller.actor(mine.id), caller.principal_id)
        conn.execute(
            update(t.card)
            .where(
                t.card.c.claim_holder == target.id, t.card.c.status.notin_(("done", "cancelled"))
            )
            .values(
                claim_holder=None,
                claim_session_id=None,
                claim_since=None,
                lease_until=None,
                status=case((t.card.c.status == "in_progress", "open"), else_=t.card.c.status),
                updated_at=now,
            )
        )
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == target.id)
            .values(active=None, removed_at=now, changed_via=caller.via)
        )
        removed = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
        view = member_view(conn, removed)  # to everyone: never the briefing
        emit(
            conn,
            mine.project.id,
            "member_updated",
            ["all"],
            view,
            actor=caller.actor(mine.id),
            subject=("member", member_id),
        )
        # The chain never names a former member: nor does a join still to be used.
        reported = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.reports_to == target.id, t.membership.c.active.is_(True)
            )
        ).scalars()
        for report_id in sorted(reported):
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == report_id)
                .values(
                    reports_to=None,
                    changed_by_credential=caller.credential_id,
                    changed_via=caller.via,
                )
            )
            row = conn.execute(select(t.membership).where(t.membership.c.id == report_id)).one()
            report = member_view(conn, row)
            emit(
                conn,
                mine.project.id,
                "member_updated",
                ["all"],
                report,
                actor=caller.actor(mine.id),
                subject=("member", report["id"]),
            )
        conn.execute(
            update(t.join_link)
            .where(t.join_link.c.reports_to == target.id, t.join_link.c.used_at.is_(None))
            .values(reports_to=None)
        )
        # The answer goes to the admin who removed it, like a repeated DELETE's.
        return idempotency.Outcome(200, "member", str(target.id), load_member(conn, str(target.id)))

    return idempotency.run(engine_of(request), request, caller, action)


def _may_manage_credentials(
    conn: Connection, mine: Membership, caller: Caller, target: Any
) -> None:
    """`credentials:admin`, or the human who owns the agent (§10)."""
    if mine.may("credentials:admin"):
        return
    if caller.kind == "human" and target.agent_id is not None:
        owner = conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == target.agent_id)
        ).scalar()
        if owner == caller.human_id:
            return
    raise forbidden("credentials:admin")


@router.get("/projects/{slug}/members/{member_id}/credentials")
def list_credentials(
    slug: str, member_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        target = member_row_or_removed(conn, mine.project.id, member_id)
        _may_manage_credentials(conn, mine, caller, target)
        since = clock.now() - REVOKED_LISTED
        rows = conn.execute(
            select(t.credential).where(
                t.credential.c.membership_id == target.id,
                t.credential.c.revoked_at.is_(None) | (t.credential.c.revoked_at > since),
            )
        ).all()
        rows = sorted(rows, key=lambda r: (r.revoked_at is not None, r.created_at), reverse=False)
        return JSONResponse(
            {"items": [credential_view(conn, r) for r in rows], "next_cursor": None}
        )


@router.post("/projects/{slug}/credentials/{credential_id}/revoke")
def revoke_credential(
    slug: str, credential_id: str, body: RevokeIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        row = conn.execute(
            select(t.credential, t.membership.c.project_id, t.membership.c.agent_id)
            .join(t.membership, t.membership.c.id == t.credential.c.membership_id)
            .where(t.credential.c.id == credential_id)
        ).first()
        if row is None or row.project_id != mine.project.id:
            raise not_found()
        target = conn.execute(
            select(t.membership).where(t.membership.c.id == row.membership_id)
        ).one()
        _may_manage_credentials(conn, mine, caller, target)
        if row.revoked_at is None:
            reason = body.reason or "revoked"
            revoke(conn, credential_id, reason, by=caller.principal_id)
            emit(
                conn,
                mine.project.id,
                "credential_revoked",
                [f"member:{row.agent_id}", "role:owner"],
                {"credential_id": credential_id, "reason": reason},
                actor=caller.actor(mine.id),
                subject=("credential", credential_id),
            )
        return idempotency.Outcome(
            200, "credential", credential_id, load_credential(conn, credential_id)
        )

    return idempotency.run(engine_of(request), request, caller, action)
