"""Placements: the desired state the hub asks of a runner, and what the runner reports
(docs/api.md §15.5–15.7).

A placement says that agent N should run on runner R with harness X in clone Z. Its
row carries the desired spec, the runner's latest report and the closing rules; the
history is in the events. Every function here runs inside the caller's transaction,
under the project lock, and emits what it changed.

Closing has two ways (§15.5). *At once* sets `active` to NULL. *Uniform* sets
`desired: stopped` and remembers the reason in `closing`; the runner's next terminal
report closes it, or it closes at once when the runner never acted on it or has no
live credential to report with.
"""

from __future__ import annotations

import fnmatch
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import availability, avatars, clock, events, mentions
from maity_hub import tables as t
from maity_hub.errors import ApiError
from maity_hub.events import Actor
from maity_hub.ids import new_id
from maity_hub.policy import CLOSED_STATES
from maity_hub.runners import attached_project_ids, human_actor, live_credential_id
from maity_hub.runners import audience as runner_audience
from maity_hub.views import principal_id, ts

HARNESSES = ("claude-code", "codex", "opencode", "pi", "hermes", "kimi", "cline", "omp", "stub")
MODES = ("interactive", "supervised")
STATES = (
    "pending",
    "starting",
    "running",
    "stopping",
    "stopped",
    "exited",
    "failed",
    "rate_limited",
)
# reason -> the states it comes with (§15.7)
REASONS: dict[str, tuple[str, ...]] = {
    "capacity": ("pending",),
    "awaiting_operator": ("pending",),
    "harness_refused": ("failed",),
    "repository_refused": ("failed",),
    "project_refused": ("failed",),
    "harness_missing": ("failed",),
    "clone_failed": ("failed",),
    "workspace_in_use": ("failed",),
    "join_failed": ("failed",),
    "crash_loop": ("failed",),
    "quota": ("rate_limited", "exited", "failed"),
    "agent_credential_revoked": ("failed",),
    "oom_killed": ("failed", "exited"),
    "evicted": ("failed", "exited"),
    "image_pull": ("failed", "exited"),
    "stopped_by_hub": ("stopped",),
    "adopted": ("running",),
    "orphaned": ("stopped",),
}
# detail -> ("reason", r) or ("state", s): what it comes with (§15.7)
_JOIN_DETAILS = (
    "code_invalid",
    "expired",
    "not_found",
    "rate_limited",
    "insecure_transport",
    "pickup_not_allowed",
    "pickup_used",
    "network",
    "credential_missing",
)
DETAILS: dict[str, tuple[str, str]] = {
    "binary_not_found": ("reason", "harness_missing"),
    "version_failed": ("reason", "harness_missing"),
    **{d: ("reason", "join_failed") for d in _JOIN_DETAILS},
    "origin_mismatch": ("reason", "workspace_in_use"),
    "other_agent": ("reason", "workspace_in_use"),
    "workspace_unrecorded": ("reason", "workspace_in_use"),
    "locked_by_process": ("reason", "workspace_in_use"),
    "stale_index_lock": ("state", "starting"),
    "sandbox_unavailable": ("state", "running"),
    "hot_loop": ("reason", "crash_loop"),
    "mode_unsupported": ("reason", "harness_refused"),
    "model_unsupported": ("reason", "harness_refused"),
    "reset_unknown": ("state", "rate_limited"),
}
RUNNING_STATES = ("starting", "running", "stopping")
# Closing at once tells a running agent, except where it never ran or cannot listen:
# a refused or withdrawn proposal, and a removed membership (§15.10).
STOP_TOLD = ("removed", "detached", "project_archived", "runner_removed", "runner_revoked")
CLOSED_LIST_DAYS = 30
SPEC_FIELDS = ("harness", "mode", "model", "target", "stop_grace_seconds")


class Refusal(ApiError):
    """A rule of §15.5 or §15.7 refuses the call, wherever the rule is checked."""


# --- reading ---------------------------------------------------------------------------


def row(conn: Connection, placement_id: str) -> Any:
    return conn.execute(select(t.placement).where(t.placement.c.id == placement_id)).one()


def open_request_id(conn: Connection, placement_id: str) -> str | None:
    found: str | None = conn.execute(
        select(t.request.c.id).where(
            t.request.c.placement_id == placement_id, t.request.c.status == "open"
        )
    ).scalar()
    return found


def terminal(report: dict[str, Any] | None) -> bool:
    """`stopped`, `failed`, or a final `exited` (§15.5)."""
    if report is None:
        return False
    state = report.get("state")
    return state in ("stopped", "failed") or (state == "exited" and report.get("retry_at") is None)


def is_current(placement: Any) -> bool:
    """`reported_current` (§15.5): computed, never stored."""
    report = placement.reported
    return report is not None and report.get("observed_generation") == placement.generation


def _agent(conn: Connection, placement: Any) -> dict[str, Any]:
    if placement.membership_id is not None:
        found = conn.execute(
            select(t.agent_profile.c.id, t.agent_profile.c.handle, t.agent_profile.c.display_name)
            .join(t.membership, t.membership.c.agent_id == t.agent_profile.c.id)
            .where(t.membership.c.id == placement.membership_id)
        ).one()
        return {
            "id": found.id,
            "handle": found.handle,
            "name": _name(conn, placement, found.handle),
            "display_name": found.display_name,
            "avatar_url": avatars.urls(conn, [found.id])[found.id],
        }
    return {  # a profile still to be created has no picture yet (§6.10)
        "id": None,
        "handle": placement.new_handle,
        "name": _name(conn, placement, placement.new_handle),
        "display_name": (placement.new_profile or {}).get("display_name"),
        "avatar_url": None,
    }


def _name(conn: Connection, placement: Any, handle: str) -> str:
    """The agent's global name (§6.3): the runner view shows it outside one project."""
    owner = profile_owner(conn, placement)
    owner_handle: str = conn.execute(
        select(t.human.c.handle).where(t.human.c.id == owner)
    ).scalar_one()
    return mentions.global_name(owner_handle, handle)


def profile_owner_of(conn: Connection, values: dict[str, Any]) -> str:
    """The owner of the profile a new placement's membership runs."""
    owner: str = conn.execute(
        select(t.agent_profile.c.owner_id)
        .join(t.membership, t.membership.c.agent_id == t.agent_profile.c.id)
        .where(t.membership.c.id == values["membership_id"])
    ).scalar_one()
    return owner


def profile_owner(conn: Connection, placement: Any) -> str:
    """The human who owns the agent profile; for a profile still to be made, its creator."""
    if placement.membership_id is None:
        creator: str = placement.created_by
        return creator
    owner: str = conn.execute(
        select(t.agent_profile.c.owner_id)
        .join(t.membership, t.membership.c.agent_id == t.agent_profile.c.id)
        .where(t.membership.c.id == placement.membership_id)
    ).scalar_one()
    return owner


def _runner(conn: Connection, runner_id: str) -> Any:
    return conn.execute(select(t.runner).where(t.runner.c.id == runner_id)).one()


def _continues(conn: Connection, placement: Any) -> bool:
    if placement.membership_id is None:
        return False
    return (
        conn.execute(
            select(t.placement.c.id).where(
                t.placement.c.membership_id == placement.membership_id,
                t.placement.c.runner_id == placement.runner_id,
                t.placement.c.clone == placement.clone,
                t.placement.c.active.is_(None),
                t.placement.c.id != placement.id,
            )
        ).first()
        is not None
    )


def _principal(conn: Connection, membership_id: int | None) -> str | None:
    return None if membership_id is None else principal_id(conn, membership_id)


def view(conn: Connection, placement: Any, *, viewer_id: str, briefing: bool) -> dict[str, Any]:
    """The placement as humans and agents read it (§15.5). `viewer_id` decides the
    runner owner's fields; `briefing` whether a profile still to be made shows it."""
    runner = _runner(conn, placement.runner_id)
    project_slug = conn.execute(
        select(t.project.c.slug).where(t.project.c.id == placement.project_id)
    ).scalar_one()
    approved = placement.approval_status
    found: dict[str, Any] = {
        "id": placement.id,
        "project": project_slug,
        "agent": _agent(conn, placement),
        "runner": {"id": runner.id, "name": runner.name},
        "target": placement.target,
        "harness": placement.harness,
        "mode": placement.mode,
        "model": placement.model,
        "workspace": {
            "clone": placement.clone,
            "branch": placement.branch,
            "continues_existing": _continues(conn, placement),
        },
        "desired": placement.desired,
        "generation": placement.generation,
        "rejoin": placement.rejoin,
        "stop_grace_seconds": placement.stop_grace_seconds,
        "approval": {
            "status": approved,
            "request_id": open_request_id(conn, placement.id),
            "pending_change": placement.pending_change,
        },
        "credential_id": placement.credential_id,
        "reported_current": is_current(placement),
        "active": placement.active is True,
        "closed_at": ts(placement.closed_at),
        "closed_reason": placement.closed_reason,
        "created_by": placement.created_by,
        "proposed_by": _principal(conn, placement.proposed_by),
        "created_at": ts(placement.created_at),
        "updated_by": placement.updated_by,
        "updated_at": ts(placement.updated_at),
        "reported": _shown_report(placement.reported),
    }
    if placement.membership_id is None and briefing:
        found["briefing"] = (placement.new_profile or {}).get("briefing")
    if viewer_id == runner.owner_id:
        found["session_hint"] = placement.session_hint
        found["logs_hint"] = f"maity runner logs {placement.id}"
    return found


def _shown_report(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {k: v for k, v in report.items() if k not in ("seq", "session_hint")}


def for_runner(conn: Connection, placement: Any) -> dict[str, Any]:
    """A placement as its runner reads it (§15.8): never the briefing, the approval or
    who created it."""
    project = conn.execute(
        select(t.project.c.slug, t.project.c.repository_url).where(
            t.project.c.id == placement.project_id
        )
    ).one()
    agent = _agent(conn, placement)
    return {
        "id": placement.id,
        "project": project.slug,
        "generation": placement.generation,
        "desired": placement.desired,
        "agent": {
            "id": agent["id"],
            "handle": agent["handle"],
            "member": placement.membership_id is not None,
            "credential_expected": placement.credential_id is not None,
        },
        "harness": placement.harness,
        "mode": placement.mode,
        "model": placement.model,
        "target": placement.target,
        "workspace": {
            "clone": placement.clone,
            "branch": placement.branch,
            "repository": project.repository_url,
        },
        "rejoin": placement.rejoin,
        "stop_grace_seconds": placement.stop_grace_seconds,
        "seq": placement.reported_seq,
    }


def runner_reads(conn: Connection, runner_id: str) -> list[Any]:
    """The placements a runner reads (§15.8): active and approved. A detached runner's
    closing placements are among them until each is closed."""
    return list(
        conn.execute(
            select(t.placement)
            .where(
                t.placement.c.runner_id == runner_id,
                t.placement.c.active.is_(True),
                t.placement.c.approval_status == "approved",
            )
            .order_by(t.placement.c.created_at, t.placement.c.id)
        ).all()
    )


def reading_projects(conn: Connection, runner_id: str) -> list[str]:
    """The projects a runner reads: attached ones, and those with an active placement of
    it (§15.8)."""
    attached = set(attached_project_ids(conn, runner_id))
    with_placements = set(
        conn.execute(
            select(t.placement.c.project_id).where(
                t.placement.c.runner_id == runner_id, t.placement.c.active.is_(True)
            )
        ).scalars()
    )
    return sorted(attached | with_placements)


def active_count(conn: Connection, project_id: str, runner_id: str | None = None) -> int:
    query = select(func.count()).where(
        t.placement.c.project_id == project_id, t.placement.c.active.is_(True)
    )
    if runner_id is not None:
        query = query.where(t.placement.c.runner_id == runner_id)
    count: int = conn.execute(query).scalar_one()
    return count


def request_summary(conn: Connection, placement_id: str | None) -> dict[str, Any] | None:
    """`placement` inline in the request view (§15.11)."""
    if placement_id is None:
        return None
    placement = row(conn, placement_id)
    runner = _runner(conn, placement.runner_id)
    spec = {**view_spec(placement), **(placement.pending_change or {})}
    return {
        "id": placement.id,
        "agent": _agent(conn, placement),
        "runner_name": runner.name,
        "harness": spec["harness"],
        "model": spec["model"],
        "mode": spec["mode"],
        "target": spec["target"],
        "isolation": _isolation(runner.capabilities, spec["target"]),
    }


def _isolation(capabilities: dict[str, Any] | None, target: str | None) -> dict[str, Any] | None:
    targets = (capabilities or {}).get("targets") or []
    if target is None and len(targets) == 1:
        isolation: dict[str, Any] | None = targets[0].get("isolation")
        return isolation
    for found in targets:
        if found.get("name") == target:
            chosen: dict[str, Any] | None = found.get("isolation")
            return chosen
    return None


def view_spec(placement: Any) -> dict[str, Any]:
    """The fields a change of spec may touch, as the placement has them now."""
    return {name: getattr(placement, name) for name in SPEC_FIELDS}


# --- what a runner offers (§15.3) ----------------------------------------------------------


def check_offered(
    runner: Any, harness: str, mode: str, model: str | None, target: str | None
) -> None:
    """Refuse a spec outside what the runner last advertised; never a grant (§15.3)."""
    capabilities = runner.capabilities or {}
    offers = [h for h in capabilities.get("harnesses") or [] if h.get("available")]
    names = {x.get("name") for x in capabilities.get("targets") or []}
    offer = next((h for h in offers if h.get("id") == harness), None)
    ok = (
        offer is not None
        and mode in (offer.get("modes") or [])
        and (model is None or model in (offer.get("models") or []))
        and (target is None or (target in names and target in (offer.get("targets") or [])))
    )
    if not ok:
        offered = [{k: h.get(k) for k in ("id", "modes", "models", "targets")} for h in offers]
        raise Refusal(
            409,
            "harness_not_offered",
            "the runner does not offer this harness, mode, model or target",
            {"offered": offered},
        )


def default_mode(runner: Any, harness: str) -> str | None:
    for offer in (runner.capabilities or {}).get("harnesses") or []:
        if offer.get("id") == harness:
            found: str | None = offer.get("default_mode")
            return found
    return None


def check_repository(runner: Any, repository_url: str | None) -> None:
    """The project's repository must match one of the runner's advertised patterns."""
    if repository_url is None:
        raise Refusal(409, "repository_not_offered", "the project has no repository")
    name = repository_url.removeprefix("https://").rstrip("/")
    patterns = (runner.capabilities or {}).get("repositories") or []
    if not any(fnmatch.fnmatchcase(name, p) for p in patterns if isinstance(p, str)):
        raise Refusal(
            409, "repository_not_offered", "the runner does not offer the project's repository"
        )


# --- events ---------------------------------------------------------------------------------


def _payload(placement: Any) -> dict[str, Any]:
    return {
        "placement_id": placement.id,
        "generation": placement.generation,
        "desired": placement.desired,
        "harness": placement.harness,
        "target": placement.target,
        "approval": {"status": placement.approval_status},
        "closed_reason": placement.closed_reason,
    }


def _audience(conn: Connection, placement: Any, *, runner: bool) -> list[str]:
    names = [f"member:{placement.created_by}", f"member:{profile_owner(conn, placement)}"]
    if runner and placement.approval_status == "approved":
        names.insert(0, runner_audience(placement.runner_id))
    return list(dict.fromkeys(names))


def announce(
    conn: Connection,
    placement_id: str,
    kind: str,
    actor: Actor | None,
    reason: str | None = None,
) -> None:
    """`placement_created` or `placement_updated`: never the briefing, a hint or a code."""
    placement = row(conn, placement_id)
    payload = _payload(placement)
    if reason is not None:
        payload["reason"] = reason
    events.emit(
        conn,
        placement.project_id,
        kind,
        _audience(conn, placement, runner=True),
        payload,
        actor=actor,
        subject=("placement", placement.id),
    )


def _stop_requested(conn: Connection, placement: Any, actor: Actor | None, by: str | None) -> None:
    """Tell the agent it is about to be stopped, so it can checkpoint (§15.10)."""
    if placement.membership_id is None:
        return
    agent_id = _principal(conn, placement.membership_id)
    events.emit(
        conn,
        placement.project_id,
        "agent_stop_requested",
        [f"member:{agent_id}"],
        {"placement_id": placement.id, "grace_seconds": placement.stop_grace_seconds, "by": by},
        actor=actor,
        subject=("placement", placement.id),
    )


# --- changing --------------------------------------------------------------------------------


def _write(conn: Connection, placement_id: str, by: str | None, **values: Any) -> Any:
    conn.execute(
        update(t.placement)
        .where(t.placement.c.id == placement_id)
        .values(**values, updated_by=by, updated_at=clock.now())
    )
    return row(conn, placement_id)


def create(
    conn: Connection, values: dict[str, Any], actor: Actor | None, reason: str | None
) -> Any:
    placement_id = new_id("placement")
    now = clock.now()
    try:
        with conn.begin_nested():
            conn.execute(
                insert(t.placement).values(
                    id=placement_id,
                    generation=1,
                    rejoin=False,
                    reported_seq=0,
                    created_at=now,
                    updated_at=now,
                    active=True,
                    **values,
                )
            )
    except IntegrityError:  # the checks passed, a concurrent placement got there first
        raise Refusal(409, "placement_exists", "an active placement holds this") from None
    announce(conn, placement_id, "placement_created", actor, reason)
    return row(conn, placement_id)


def carried_credential(
    conn: Connection, membership_id: int, runner_id: str, clone: str
) -> str | None:
    """The latest closed placement of (membership, runner, clone) passes its unrevoked
    credential on (§15.5)."""
    latest = conn.execute(
        select(t.placement.c.credential_id)
        .where(
            t.placement.c.membership_id == membership_id,
            t.placement.c.runner_id == runner_id,
            t.placement.c.clone == clone,
            t.placement.c.active.is_(None),
        )
        .order_by(t.placement.c.closed_at.desc())
        .limit(1)
    ).scalar()
    if latest is None:
        return None
    revoked = conn.execute(
        select(t.credential.c.revoked_at).where(t.credential.c.id == latest)
    ).scalar()
    return None if revoked is not None else latest


def set_desired(
    conn: Connection,
    placement: Any,
    desired: str,
    actor: Actor | None,
    by: str | None,
    *,
    tell_agent: bool = True,
) -> Any:
    if placement.desired == desired:
        return placement
    changed = _write(conn, placement.id, by, desired=desired)
    if desired == "stopped":
        revoke_unused_joins(conn, t.join_link.c.placement_id == placement.id)
        if terminal(placement.reported) and is_current(placement):
            end_outage(conn, changed, "the agent was stopped")  # nothing left to stop
    if desired == "stopped" and tell_agent:
        _stop_requested(conn, changed, actor, by)
    announce(conn, placement.id, "placement_updated", actor)
    return changed


def change_spec(
    conn: Connection,
    placement: Any,
    change: dict[str, Any],
    actor: Actor | None,
    by: str | None,
    reason: str | None = None,
) -> Any:
    """Apply a change of the spec: a new generation, so a running agent restarts on it."""
    changed = _write(conn, placement.id, by, generation=placement.generation + 1, **change)
    announce(conn, placement.id, "placement_updated", actor, reason)
    return changed


def propose_change(conn: Connection, placement: Any, change: dict[str, Any], by: str) -> Any:
    """An agent's change of spec under `consent`: stored beside the running spec until it
    is settled; the runner keeps the current generation (§15.6)."""
    return _write(conn, placement.id, by, pending_change=change)


def approve(conn: Connection, placement: Any, actor: Actor | None, by: str | None) -> Any:
    approved = _write(conn, placement.id, by, approval_status="approved")
    announce(conn, placement.id, "placement_updated", actor)
    return approved


def restart(
    conn: Connection, placement: Any, rejoin: bool, actor: Actor | None, by: str | None
) -> Any:
    changed = _write(
        conn,
        placement.id,
        by,
        generation=placement.generation + 1,
        desired="running",
        rejoin=rejoin or placement.rejoin,
    )
    announce(conn, placement.id, "placement_updated", actor)
    return changed


def close_now(
    conn: Connection,
    placement: Any,
    closed_reason: str,
    actor: Actor | None,
    by: str | None,
    *,
    desired: str = "stopped",
) -> Any:
    if placement.active is None:
        return placement
    end_outage(conn, placement, "the placement was closed")
    if placement.desired == "running" and closed_reason in STOP_TOLD:
        # Every change to `desired: stopped` tells the agent (§15.10), a close at once too.
        _stop_requested(conn, placement, actor, by)
    closed = _write(
        conn,
        placement.id,
        by,
        active=None,
        desired=desired,
        closed_at=clock.now(),
        closed_reason=closed_reason,
        closing=None,
    )
    revoke_unused_joins(conn, t.join_link.c.placement_id == placement.id)
    announce(conn, placement.id, "placement_updated", actor)
    availability.placement_closed(conn, closed, actor)
    return closed


def close_uniform(
    conn: Connection, placement: Any, closed_reason: str, actor: Actor | None, by: str | None
) -> Any:
    """Close the uniform way (§15.5): stop it and close on the runner's terminal report,
    or at once when nobody will report."""
    if placement.active is None:
        return placement
    nobody_reports = (
        placement.reported is None
        or placement.approval_status != "approved"
        or live_credential_id(conn, placement.runner_id) is None
        # After a terminal report nothing runs that a stop could end.
        or (terminal(placement.reported) and is_current(placement))
    )
    if nobody_reports:
        return close_now(conn, placement, closed_reason, actor, by)
    # Deleted, or its project archived (§15.7): over now, not when the runner reports.
    end_outage(conn, placement, "the placement is closing")
    stopping = placement.desired != "stopped"
    changed = _write(conn, placement.id, by, desired="stopped", closing=closed_reason)
    if stopping:
        _stop_requested(conn, changed, actor, by)
    announce(conn, placement.id, "placement_updated", actor)
    return changed


def active_rows(conn: Connection, *conditions: Any) -> list[Any]:
    return list(
        conn.execute(
            select(t.placement)
            .where(t.placement.c.active.is_(True), *conditions)
            .order_by(t.placement.c.created_at, t.placement.c.id)
        ).all()
    )


# --- hooks from other parts of the hub ------------------------------------------------------


def credential_revoked(conn: Connection, credential_id: str, by: str | None) -> None:
    """Revoking the agent credential a placement names stops it, in the same transaction,
    without closing it (§15.5). The agent cannot read a stop request any more."""
    for placement in active_rows(conn, t.placement.c.credential_id == credential_id):
        set_desired(conn, placement, "stopped", None, by, tell_agent=False)


def forget_boss(conn: Connection, project_id: str, membership_id: int) -> None:
    """A removed member is no longer the boss of a profile an active placement will
    create: its stored `reports_to` becomes null (§6.2). No event and no `generation`:
    the stored join fields are in no view and the runner never reads them."""
    for row in active_rows(conn, t.placement.c.project_id == project_id):
        profile = row.new_profile or {}
        if profile.get("reports_to") == membership_id:
            conn.execute(
                update(t.placement)
                .where(t.placement.c.id == row.id)
                .values(new_profile={**profile, "reports_to": None})
            )


def membership_removed(conn: Connection, membership_id: int, actor: Actor | None, by: str) -> None:
    for placement in active_rows(conn, t.placement.c.membership_id == membership_id):
        withdraw_open_request(conn, placement, "the membership was removed", actor)
        close_now(conn, placement, "membership_removed", actor, by)
    # Its proposals go with it, a placement's and every other kind's (`proposals`): a go
    # must not approve what nobody proposes now.
    proposed = conn.execute(
        select(t.request).where(
            t.request.c.asked_by == membership_id,
            t.request.c.status == "open",
            or_(t.request.c.placement_id.isnot(None), t.request.c.proposal.isnot(None)),
        )
    ).all()
    for request in proposed:
        from maity_hub.routes.requests import close_request

        close_request(conn, request.id, "withdrawn", actor, reason="the proposer was removed")
        settle(conn, request, "withdrawn", actor, by)


def runner_removed(conn: Connection, runner_id: str, by: str) -> list[str]:
    """Close every placement of a removed runner at once; returns those whose last report
    said they were still running (`still_running`, §15.3)."""
    revoke_unused_joins(conn, t.join_link.c.runner_id == runner_id)
    still = []
    for placement in active_rows(conn, t.placement.c.runner_id == runner_id):
        if (placement.reported or {}).get("state") in RUNNING_STATES:
            still.append(placement.id)
        actor = human_actor(conn, placement.project_id, by)
        withdraw_open_request(conn, placement, "the runner was removed", actor)
        close_now(conn, placement, "runner_removed", actor, by)
    return still


def detached(
    conn: Connection, project_id: str, runner_id: str, actor: Actor | None, by: str
) -> None:
    for placement in active_rows(
        conn, t.placement.c.project_id == project_id, t.placement.c.runner_id == runner_id
    ):
        withdrawn = withdraw_open_request(conn, placement, "the runner was detached", actor)
        if withdrawn and placement.approval_status != "approved":
            close_now(conn, placement, "detached", actor, by)  # never seen by the runner
            continue
        close_uniform(conn, row(conn, placement.id), "detached", actor, by)


def project_archived(conn: Connection, project_id: str, actor: Actor | None, by: str) -> None:
    for placement in active_rows(conn, t.placement.c.project_id == project_id):
        withdrawn = withdraw_open_request(conn, placement, "the project was archived", actor)
        if withdrawn and placement.approval_status != "approved":
            close_now(conn, placement, "project_archived", actor, by)  # never seen by the runner
            continue
        close_uniform(conn, row(conn, placement.id), "project_archived", actor, by)


def revoke_unused_joins(conn: Connection, *where: Any) -> None:
    """Revoke the runner pickups (§15.9) that `where` selects and nobody exchanged yet: a
    stopped or closed placement, or a runner without its credential, mints no agent. The
    exchange checks the placement and the runner again under the lock as well."""
    j = t.join_link.c
    conn.execute(
        update(t.join_link)
        .where(j.placement_id.is_not(None), j.used_at.is_(None), j.revoked_at.is_(None), *where)
        .values(revoked_at=clock.now())
    )


def runner_credential_gone(conn: Connection, runner_id: str, by: str | None) -> None:
    """A runner without a live credential reports nothing: what was closing closes now.
    Its unused pickups end with the credential that fetched them (§15.9)."""
    revoke_unused_joins(conn, t.join_link.c.runner_id == runner_id)
    for placement in active_rows(
        conn, t.placement.c.runner_id == runner_id, t.placement.c.closing.isnot(None)
    ):
        close_now(conn, placement, placement.closing, None, by)


# --- consent (§15.6) ------------------------------------------------------------------------


def withdraw_open_request(
    conn: Connection, placement: Any, reason: str, actor: Actor | None
) -> bool:
    """Withdraw the placement's open consent request, if any; True when there was one.
    The placement side is the caller's to settle."""
    from maity_hub.routes.requests import close_request

    request_id = open_request_id(conn, placement.id)
    if request_id is None:
        return False
    close_request(conn, request_id, "withdrawn", actor, reason=reason)
    if placement.pending_change is not None:
        _write(conn, placement.id, None, pending_change=None)
    return True


def answer_open_request(conn: Connection, placement: Any, actor: Actor, by: str) -> None:
    """A human with the right acted on a proposed creation: their action is their go."""
    from maity_hub.routes.requests import close_request

    request_id = open_request_id(conn, placement.id)
    if request_id is not None:
        close_request(conn, request_id, "go", actor, by=by)


def settle(
    conn: Connection, request: Any, outcome: str, actor: Actor | None, by: str | None
) -> None:
    """A consent request that carries a placement was answered (`go`; any other answer
    counts as `no`) or withdrawn: settle the placement in the same transaction (§15.6)."""
    if request.placement_id is None:
        return
    placement = row(conn, request.placement_id)
    if placement.active is None:
        return
    if outcome == "go":
        _still_allowed(conn, placement)
    if placement.pending_change is not None:  # a proposed change of the spec
        change = dict(placement.pending_change)
        cleared = _write(conn, placement.id, by, pending_change=None)
        if outcome == "go":
            change_spec(conn, cleared, change, actor, by)
        else:
            announce(conn, placement.id, "placement_updated", actor)
        return
    if placement.approval_status != "pending":
        return
    if outcome == "go":
        approve(conn, placement, actor, by)
    elif outcome == "withdrawn":
        close_now(conn, placement, "withdrawn", actor, by)
    else:
        _write(conn, placement.id, by, approval_status="refused")
        close_now(conn, row(conn, placement.id), "refused", actor, by)


def _still_allowed(conn: Connection, placement: Any) -> None:
    """A `go` approves what the rules allow now, not what they allowed when it was
    proposed: the runner still has a live credential and offers the spec, and the project
    is still open. Otherwise the answer is refused and the request stays open."""
    if live_credential_id(conn, placement.runner_id) is None:
        raise Refusal(409, "runner_revoked", "the runner has no live credential")
    project = conn.execute(select(t.project).where(t.project.c.id == placement.project_id)).one()
    if project.state in CLOSED_STATES:
        raise Refusal(409, "project_closed", f"the project is {project.state}")
    spec = {**view_spec(placement), **(placement.pending_change or {})}
    runner = _runner(conn, placement.runner_id)
    check_offered(runner, spec["harness"], spec["mode"], spec["model"], spec["target"])
    check_repository(runner, project.repository_url)


def consent_summary(fields: dict[str, Any]) -> str:
    """One `field: value` line per field, readable where the structured view is missing."""
    return "\n".join(f"{name}: {_one_line(value)}" for name, value in fields.items())


def _one_line(value: Any) -> str:
    """A value as one line: a reason cannot add lines that read as fields."""
    return "-" if value is None else " ".join(str(value).split()) or "-"


# --- reports (§15.7, §15.8) ------------------------------------------------------------------


def clamp_since(since: datetime, previous: dict[str, Any] | None, now: datetime) -> datetime:
    floor = None
    if previous is not None and previous.get("reported_at"):
        floor = datetime.fromisoformat(previous["reported_at"].replace("Z", "+00:00"))
    if floor is not None and since < floor:
        return floor
    return min(since, now)


def report(conn: Connection, placement: Any, body: dict[str, Any], actor: Actor) -> Any:
    """A status report, as a compare-and-set on `seq`. Returns the placement after it."""
    if placement.active is None or body["seq"] <= placement.reported_seq:
        return placement
    if body["observed_generation"] > placement.generation:
        raise Refusal(
            409,
            "stale_generation",
            "the report names a generation the hub never issued",
            {"generation": placement.generation},
        )
    now = clock.now()
    current = body["observed_generation"] == placement.generation
    fields = {
        "state": body["state"],
        "reason": body.get("reason"),
        "detail": body.get("detail"),
        "exit_code": body.get("exit_code"),
        "observed_generation": body["observed_generation"],
        "restarts": body["restarts"],
        "retry_at": _stamp(body.get("retry_at")),
        "crash_count": body.get("crash_count"),
        "crash_window_seconds": body.get("crash_window_seconds"),
        "deadline_at": _stamp(body.get("deadline_at")),
        "since": clock.rfc3339(clamp_since(body["since"], placement.reported, now)),
        "target": body["target"],
        "reported_at": clock.rfc3339(now),
    }
    values: dict[str, Any] = {"reported_seq": body["seq"]}
    if current:
        values["reported"] = fields
        values["session_hint"] = body.get("session_hint")
    conn.execute(update(t.placement).where(t.placement.c.id == placement.id).values(**values))
    events.emit(
        conn,
        placement.project_id,
        "placement_reported",
        _audience(conn, placement, runner=False),
        {
            "placement_id": placement.id,
            **{
                k: fields[k]
                for k in (
                    "state",
                    "reason",
                    "detail",
                    "exit_code",
                    "observed_generation",
                    "restarts",
                    "retry_at",
                )
            },
        },
        actor=actor,
        subject=("placement", placement.id),
    )
    if current:
        # A rate limit is the agent's limit (§6.12, §15.7); the next other report ends it.
        availability.runner_reported(conn, placement, body["state"], body.get("retry_at"), actor)
    after = row(conn, placement.id)
    if current:
        outage_reported(conn, after, fields)
        after = row(conn, after.id)
    if current and after.closing is not None and terminal(fields):
        return close_now(conn, after, after.closing, actor, None)
    return after


# --- outages (§15.7) -------------------------------------------------------------------------


def stops_the_agent(report: dict[str, Any]) -> bool:
    """`failed` with any reason, or `exited` with `quota`: the runner will not start the
    agent again by itself. `rate_limited` restarts at `retry_at` and opens nothing."""
    return report["state"] == "failed" or (
        report["state"] == "exited" and report.get("reason") == "quota"
    )


def outage_reported(conn: Connection, placement: Any, report: dict[str, Any]) -> None:
    """A current report opens an outage, or ends one (§15.7). The same outage reported
    again files nothing; a report the stop asked for is no outage."""
    if report["state"] == "running":
        end_outage(conn, placement, "the agent runs again")
    elif placement.desired == "stopped" and terminal(report):
        end_outage(conn, placement, "the agent was stopped")
    elif (
        stops_the_agent(report)
        and placement.desired == "running"
        and placement.outage_since is None
        and placement.membership_id is not None  # a profile still to be made has no owner
    ):
        _open_outage(conn, placement, report)


def _open_outage(conn: Connection, placement: Any, report: dict[str, Any]) -> None:
    from maity_hub.routes.requests import file_hub_notice

    agent = conn.execute(
        select(t.agent_profile.c.id, t.agent_profile.c.handle)
        .join(t.membership, t.membership.c.agent_id == t.agent_profile.c.id)
        .where(t.membership.c.id == placement.membership_id)
    ).one()
    runner_name = conn.execute(
        select(t.runner.c.name).where(t.runner.c.id == placement.runner_id)
    ).scalar()
    reason = _one_line(report.get("reason"))
    why = reason if report.get("detail") is None else f"{reason}, {_one_line(report['detail'])}"
    request_id = file_hub_notice(
        conn,
        placement.project_id,
        placement.membership_id,
        agent.id,
        f"{agent.handle} on {runner_name or placement.id} stopped: {reason}",
        f"Placement {placement.id} on runner {runner_name or '-'} reported {report['state']}"
        f" ({why}) at {report['reported_at']} (UTC); restarts {report['restarts']}.",
    )
    conn.execute(
        update(t.placement)
        .where(t.placement.c.id == placement.id)
        .values(outage_since=clock.now(), outage_request_id=request_id)
    )


def end_outage(conn: Connection, placement: Any, reason: str) -> None:
    """End the placement's open outage and withdraw its notice when still open; the next
    failing report opens a new one."""
    if placement.outage_since is None:
        return
    from maity_hub.routes.requests import withdraw_hub_notice

    withdraw_hub_notice(conn, placement.outage_request_id, reason)
    conn.execute(
        update(t.placement)
        .where(t.placement.c.id == placement.id)
        .values(outage_since=None, outage_request_id=None)
    )


def _stamp(value: datetime | None) -> str | None:
    return None if value is None else clock.rfc3339(value)


def recently_closed() -> datetime:
    return clock.now() - timedelta(days=CLOSED_LIST_DAYS)
