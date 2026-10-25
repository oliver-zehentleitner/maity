"""Members of a project and their credentials (docs/api.md §6.2, §5.3, §10)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, case, select, update

from maity_hub import (
    admin_agents,
    availability,
    briefings,
    clock,
    group_chats,
    idempotency,
    instances,
    placements,
    rules,
    seats,
)
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, member_row_or_removed, membership
from maity_hub.auth.caller import Caller
from maity_hub.auth.leaks import revoke
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found
from maity_hub.events import Actor, emit, lock_project
from maity_hub.models import Strict, markdown
from maity_hub.scopes import ROLES
from maity_hub.views import (
    credential_view,
    human_paused,
    member_view,
    member_views,
    principal_id,
)

router = APIRouter()

CAPABILITIES = ("tag",)
# A repository path; nothing that could leave a code span in the join page.
AREA = re.compile(r"[A-Za-z0-9._/-]{1,255}")
REVOKED_LISTED = timedelta(days=30)


class PausedIn(Strict):
    reason: str = markdown(min_length=1)


class AvailabilityPolicyIn(Strict):
    """Fields not named keep their current value (§6.12)."""

    on_unavailable: str | None = None
    substitutes: list[str] | None = Field(default=None, max_length=availability.MAX_SUBSTITUTES)
    grace_minutes: int | None = None


class MemberPausedIn(PausedIn):
    instance: str | None = Field(default=None, max_length=5)  # one agent instance (§5.3)


class MemberPatch(Strict):
    team: instances.TeamIn | None = None
    owner_preferences: bool | None = None
    availability_policy: AvailabilityPolicyIn | None = None
    role: str | None = None
    reports_to: str | None = None
    areas: list[str] | None = Field(default=None, max_length=50)
    capabilities: list[str] | None = Field(default=None, max_length=20)
    paused: MemberPausedIn | None = None
    # Lifting one instance's pause: `{"paused": null, "instance": "<id>"}` (§5.3).
    instance: str | None = Field(default=None, max_length=5)
    briefing: str | None = markdown(default=None)


class RevokeIn(Strict):
    reason: str | None = markdown(default=None)


def _request(conn: Connection, request_id: str) -> dict[str, Any]:
    from maity_hub.routes.requests import load_request  # it imports this module's peers

    return load_request(conn, request_id)


def load_member(conn: Connection, membership_id: str) -> dict[str, Any]:
    """The answer of a member write. Only an admin or the member itself writes one,
    and both may read the briefing (§6.2)."""
    row = conn.execute(select(t.membership).where(t.membership.c.id == int(membership_id))).one()
    return member_view(conn, row, briefing=True)


def load_member_for_team(conn: Connection, membership_id: str, request: Request) -> dict[str, Any]:
    """A replayed rulebook change: the briefing only for a reader with `members:admin`,
    as on the first answer (§6.2, §6.18)."""
    row = conn.execute(select(t.membership).where(t.membership.c.id == int(membership_id))).one()
    slug = conn.execute(
        select(t.project.c.slug).where(t.project.c.id == row.project_id)
    ).scalar_one()
    reader = membership(conn, request.state.caller, slug)
    return member_view(conn, row, briefing=reader.may("members:admin"))


idempotency.LOADERS["member_team"] = load_member_for_team


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
            if member is not None and member in chain(conn, values["reports_to"]):
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


def chain(conn: Connection, membership_id: int) -> set[int]:
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


@router.get("/projects/{slug}/members/{member_id}/briefings")
def list_briefings(slug: str, member_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    """A member's briefing versions, newest first (§6.2): for the agent's owner, a member
    of the project or not, and for a human with `members:admin`."""
    with engine_of(request).begin() as conn:
        project = conn.execute(select(t.project.c.id).where(t.project.c.slug == slug)).first()
        if project is None or caller.kind == "runner":
            raise not_found()
        try:
            target = member_row(conn, project.id, member_id)
        except ApiError:
            target = None
        if target is None or not instances.owns_agent(conn, caller, target):
            mine = membership(conn, caller, slug)  # not_found for a stranger
            if target is None or target.agent_id is None:
                raise not_found()
            if mine.kind != "human" or not mine.may("members:admin"):
                raise forbidden("members:admin", "the agent's owner or an admin reads them")
        return JSONResponse({"items": briefings.history(conn, target.id)})


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


@dataclass(frozen=True)
class Change:
    """Who makes a membership change and how it is recorded: the event's actor, the
    principal a pause names as `by`, the human on whose authority credentials are
    revoked (the approver of an agent's change, §2.3 ᵃ), and the audit columns."""

    project: Any
    actor: Actor
    by: str
    approver: str
    credential_id: str | None
    via: str | None


def change_of(mine: Membership, caller: Caller) -> Change:
    return Change(
        mine.project,
        caller.actor(mine.id),
        mine.principal_id,
        mine.principal_id,
        caller.credential_id,
        caller.via,
    )


def apply_patch(
    conn: Connection,
    change: Change,
    target: Any,
    values: dict[str, Any],
    pause: tuple[bool, str | None],
    *,
    instance: str | None = None,
) -> dict[str, Any]:
    """Write a membership change and announce it; `pause` is (given, reason), for one
    agent instance when `instance` names it. Returns the changed columns with their old
    values, for `member_changed_by_agent`."""
    changed = {k: v for k, v in values.items() if getattr(target, k) != v}
    old = {k: getattr(target, k) for k in changed}
    member_id = principal_id(conn, target.id)
    assert member_id is not None
    if changed:
        columns = {k: v for k, v in changed.items() if k != "briefing"}
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == target.id)
            .values(**columns, changed_by_credential=change.credential_id, changed_via=change.via)
        )
        if "briefing" in changed:
            # A new version, by whoever wrote it (§6.2); its text is never in an event.
            briefings.record(conn, target.id, changed["briefing"], change.by, clock.now())
        row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
        view = member_view(conn, row)  # to everyone: never the briefing
        if "availability_policy" in changed:
            view["changed"] = sorted(changed)
        if "briefing" in changed:
            view |= {"changed": sorted(changed), "briefing_version": row.briefing_version}
        if {"role", "areas"} & changed.keys():
            # The member's role brief is part of the rules: a bump (§6.9).
            rules.bump(
                conn,
                change.project,
                "member_updated",
                ["all"],
                view,
                actor=change.actor,
                subject=("member", member_id),
            )
        else:
            emit(
                conn,
                change.project.id,
                "member_updated",
                ["all"],
                view,
                actor=change.actor,
                subject=("member", member_id),
            )
    given, reason = pause
    if given:
        if target.agent_id is None:
            # A human's absence is the project's `absence` (§6.1, §5.3).
            raise invalid({"paused": "agents_only"}, "paused is for agent members")
        row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
        set_paused(conn, change, row, reason, instance=instance)
    return old


@router.patch("/projects/{slug}/members/{member_id}")
def patch_member(
    slug: str, member_id: str, body: MemberPatch, request: Request, caller: AnyCaller
) -> JSONResponse:
    given = body.model_fields_set

    def action(conn: Connection) -> idempotency.Outcome:
        if "team" in given:
            # The rulebook is the agent's owner's alone, member or not (§6.18): its own
            # path, before the member check, and never mixed with an admin's fields. An
            # agent learns it is a human's call before anything else (§2.3).
            if caller.kind != "human":
                raise instances.humans_only()
            if given != {"team"}:
                raise invalid({"team": "alone"}, "set team on its own")
            target, reader = instances.patch_team(conn, caller, slug, member_id, body.team)
            if reader is None:
                # An owner outside the project sees nothing of it (§1.3): no body.
                return idempotency.Outcome(204, None, None, {})
            view = member_view(conn, target, briefing=reader.may("members:admin"))
            return idempotency.Outcome(200, "member_team", str(target.id), view)
        if "owner_preferences" in given:
            return _owner_preferences(conn, caller, slug, member_id, body, given)
        mine = membership(conn, caller, slug)
        agent_admin = mine.kind == "agent" and mine.role == "admin"
        target = member_row(conn, mine.project.id, member_id)
        if mine.kind == "agent" and target.agent_id is None:  # whatever the agent's role
            raise humans_only("an agent never changes a human's membership")
        if "availability_policy" in given:
            _policy_humans_only(conn, mine, caller, target, body.availability_policy)
        own_policy = given == {"availability_policy"} and target.id == mine.id
        if not agent_admin and not (own_policy and mine.kind == "human"):
            # A human sets their own policy without members:admin (§6.12).
            mine.require("members:admin")
        if agent_admin:
            admin_agents.check_patch(mine, target, body, given)
        new_policy = None
        if "availability_policy" in given:
            new_policy = _availability_policy(conn, mine, target, body.availability_policy)
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
        if new_policy is not None and new_policy != availability.policy_of(target):
            values["availability_policy"] = new_policy
        demotes = values.get("role", "owner") != "owner" and target.role == "owner"
        if demotes and _owners(conn, mine.project.id) <= 1:
            raise invalid({"role": "last_owner"}, "the last owner cannot be demoted")
        if "instance" in given and ("paused" not in given or body.paused is not None):
            raise invalid({"instance": "paused_only"}, "instance goes with paused: null")
        pause = ("paused" in given, body.paused.reason if body.paused else None)
        # One agent instance's pause instead of the membership's (§5.3).
        instance = (body.paused.instance if body.paused else body.instance) if pause[0] else None
        if instance is not None:
            if target.agent_id is None:
                raise invalid({"paused": "agents_only"}, "paused is for agent members")
            held = instances.require_active(conn, target, instance, "instance")
            if agent_admin:
                admin_agents.check_instance_pause(held, mine.principal_id)
        if agent_admin and admin_agents.needs_consent(conn, mine, target, values, pause):
            # The whole PATCH waits for the owner's go (§2.3 ᵃ).
            request_id = admin_agents.propose(
                conn,
                mine,
                caller,
                target,
                {"action": "patch", "values": values, "pause": pause, "instance": instance},
            )
            return idempotency.Outcome(202, "request", request_id, _request(conn, request_id))
        change = change_of(mine, caller)
        old = apply_patch(conn, change, target, values, pause, instance=instance)
        if agent_admin and "role" in old:
            admin_agents.announce(conn, change, target, "role", old["role"], values["role"])
        return idempotency.Outcome(200, "member", str(target.id), load_member(conn, str(target.id)))

    return idempotency.run(engine_of(request), request, caller, action)


def _owner_preferences(
    conn: Connection, caller: Caller, slug: str, member_id: str, body: Any, given: set[str]
) -> idempotency.Outcome:
    """Give an agent its owner's preferences, or take them back (§19.4): the profile's
    owner and nobody else, member of the project or not, as `team` is (§6.18). A live
    reference: the flag, never a copy of the text."""
    if caller.kind != "human":
        raise instances.humans_only()
    if given != {"owner_preferences"} or body.owner_preferences is None:
        raise invalid({"owner_preferences": "alone"}, "set owner_preferences on its own")
    target, reader = instances.team_target(conn, caller, slug, member_id)
    conn.execute(
        update(t.membership)
        .where(t.membership.c.id == target.id)
        .values(owner_preferences=body.owner_preferences)
    )
    row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    if reader is None:
        return idempotency.Outcome(204, None, None, {})
    view = member_view(conn, row, briefing=reader.may("members:admin"))
    return idempotency.Outcome(200, "member_team", str(row.id), view)


def _policy_humans_only(
    conn: Connection, mine: Membership, caller: Caller, target: Any, change: Any
) -> None:
    """Before anything else (§2.3): an agent never decides what happens to a human's
    work, nor that a human takes over work."""
    if caller.kind == "human":
        return
    if target.agent_id is None:
        raise humans_only("a human's availability_policy is set by humans only")
    for entry in (change.substitutes or []) if change is not None else []:
        if entry.startswith("hum-") and _is_member(conn, mine.project.id, entry):
            raise humans_only("only a human names a human as a substitute")


def _is_member(conn: Connection, project_id: str, member_id: str) -> bool:
    try:
        member_row(conn, project_id, member_id)
    except ApiError:
        return False
    return True


def _availability_policy(
    conn: Connection, mine: Membership, target: Any, change: Any
) -> dict[str, Any]:
    """The policy as it will be stored: the fields named over the current ones, `invalid`
    naming every bad field (§6.12)."""
    if change is None:
        return dict(availability.DEFAULT_POLICY)
    policy = availability.policy_of(target)
    for name in ("on_unavailable", "grace_minutes"):
        if getattr(change, name) is not None:
            policy[name] = getattr(change, name)
    if change.substitutes is not None:
        policy["substitutes"] = list(dict.fromkeys(change.substitutes))
    errors = availability.policy_errors(conn, mine.project.id, target, policy)
    if errors:
        raise invalid(errors)
    return policy


def set_paused(
    conn: Connection,
    change: Change,
    target: Any,
    reason: str | None,
    *,
    instance: str | None = None,
) -> None:
    """Set or clear `paused` (§5.3), naming `change.by`: the membership's, or with
    `instance` that agent instance's alone. Setting it tells the member itself (its
    long-poll wakes; for an instance only that instance), `reports_to` and the admins;
    lifting a pause someone else set tells them the same way, with `paused: null`."""
    now = clock.now()
    values = {
        "paused_reason": reason,
        "paused_since": now if reason else None,
        "paused_by": change.by if reason else None,
    }
    if instance is None:
        lifts_a_human_pause = reason is None and human_paused(target)
        conn.execute(update(t.membership).where(t.membership.c.id == target.id).values(**values))
    else:
        held = instances.require_active(conn, target, instance, "instance")
        lifts_a_human_pause = reason is None and instances.human_paused(target, held)
        conn.execute(update(t.credential).where(t.credential.c.id == held.id).values(**values))
    availability.reconcile_ids(conn, [target.id], change.actor)
    if reason is None and not lifts_a_human_pause:
        return
    row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    view = member_view(conn, row)
    payload = {"session": view.get("session"), "paused": view["paused"]}
    audience = [f"member:{view['id']}", "role:admin"]
    if instance is not None:
        shown = next(i for i in view["instances"] if i["id"] == instance)
        payload = {"session": shown["session"], "paused": shown["paused"], "instance": instance}
        audience[0] = instances.token(view["id"], instance)
    if view["reports_to"]:
        audience.insert(1, f"member:{view['reports_to']}")
    emit(
        conn,
        change.project.id,
        "session_paused",
        audience,
        payload,
        actor=change.actor,
        subject=("member", view["id"]),
    )


def apply_remove(conn: Connection, change: Change, target: Any) -> None:
    """Remove a membership (§6.2): its credentials revoked on the approver's authority,
    its claims released, every `reports_to` that names it cleared."""
    from maity_hub import onboarding

    onboarding.member_removed(
        conn, change.project.id, target.agent_id or target.human_id, change.actor
    )
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
        revoke(conn, credential_id, "member_removed", by=change.approver)
    placements.membership_removed(conn, target.id, change.actor, change.approver)
    conn.execute(
        update(t.card)
        .where(t.card.c.claim_holder == target.id, t.card.c.status.notin_(("done", "cancelled")))
        .values(
            claim_holder=None,
            claim_instance=None,
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
        .values(active=None, removed_at=now, changed_via=change.via)
    )
    removed = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    view = member_view(conn, removed)  # to everyone: never the briefing
    emit(
        conn,
        change.project.id,
        "member_updated",
        ["all"],
        view,
        actor=change.actor,
        subject=("member", view["id"]),
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
                changed_by_credential=change.credential_id,
                changed_via=change.via,
            )
        )
        row = conn.execute(select(t.membership).where(t.membership.c.id == report_id)).one()
        report = member_view(conn, row)
        emit(
            conn,
            change.project.id,
            "member_updated",
            ["all"],
            report,
            actor=change.actor,
            subject=("member", report["id"]),
        )
    conn.execute(
        update(t.join_link)
        .where(t.join_link.c.reports_to == target.id, t.join_link.c.used_at.is_(None))
        .values(reports_to=None)
    )
    placements.forget_boss(conn, change.project.id, target.id)
    # Out of every group chat too, which may close one (§6.2, §9.2).
    group_chats.membership_removed(conn, target, change.actor, change.by)
    seats.reset(conn, change.project.id, removed, change.actor)
    instances.refresh_team_wake(conn, change.project.id)  # it may have been the last team


@router.delete("/projects/{slug}/members/{member_id}")
def remove_member(slug: str, member_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        agent_admin = mine.kind == "agent" and mine.role == "admin"
        target = member_row_or_removed(conn, mine.project.id, member_id)
        if mine.kind == "agent" and target.agent_id is None:  # whatever the agent's role
            raise humans_only("an agent never removes a human's membership")
        if not agent_admin:
            mine.require("members:admin")
        if agent_admin:  # before the idempotent answer: it carries the briefing
            admin_agents.check_target(mine, target)
        if target.active is None:  # removed already: DELETE is idempotent (§6.2)
            return idempotency.Outcome(
                200, "member", str(target.id), load_member(conn, str(target.id))
            )
        if agent_admin:
            # An admin agent never removes on the call: the owner gives the go (§2.3 ᵃ).
            request_id = admin_agents.propose(conn, mine, caller, target, {"action": "remove"})
            return idempotency.Outcome(202, "request", request_id, _request(conn, request_id))
        if target.role == "owner" and _owners(conn, mine.project.id) <= 1:
            raise invalid({"member": "last_owner"}, "the last owner cannot be removed")
        apply_remove(conn, change_of(mine, caller), target)
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
