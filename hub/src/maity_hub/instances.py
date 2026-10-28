"""Agent instances and the team's rulebook (docs/api.md §6.17, §6.18).

An agent instance is one agent credential of a membership: its `instance` column is
the short id, unique within the membership and never reused. Everything the hub
records about work names the member and the instance; a member id alone addresses
the team.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import Connection, func, select, update

from maity_hub import clock, namespace
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError, invalid, not_found
from maity_hub.events import Actor, emit
from maity_hub.ids import new_instance_id
from maity_hub.models import Strict

INSTANCE_PATTERN = re.compile(r"[2-9a-hjkmnp-z]{4,5}")
MAX_INSTANCES = 16


def address(member_id: str, instance: str) -> str:
    return f"{member_id}#{instance}"


def token(member_id: str, instance: str | None) -> str:
    """The audience token of one instance, or of the team when none is bound (§8.2)."""
    return f"instance:{member_id}#{instance}" if instance else f"member:{member_id}"


def human_paused(member: Any, credential: Any) -> bool:
    """Whether someone other than the agent itself paused this instance (§5.3)."""
    return credential.paused_since is not None and credential.paused_by != member.agent_id


def paused_view(row: Any) -> dict[str, Any] | None:
    """`paused` of a membership or a credential row, which store it alike (§5.3)."""
    if row.paused_since is None:
        return None
    return {
        "reason": row.paused_reason,
        "since": clock.rfc3339(row.paused_since),
        "by": row.paused_by,
    }


def split_address(text: str) -> tuple[str, str | None]:
    """`agt-b#wle2` → (`agt-b`, `wle2`); a member id alone → (`agt-b`, None)."""
    member, sep, instance = text.partition("#")
    return member, (instance if sep else None)


def team(conn: Connection, row: Any) -> dict[str, Any]:
    """The rulebook as the member view and the resume packet carry it (§6.18)."""
    by = None
    if row.team_updated_by is not None:
        handle = conn.execute(
            select(t.human.c.handle).where(t.human.c.id == row.team_updated_by)
        ).scalar()
        by = {"kind": "human", "id": row.team_updated_by, "handle": handle}
    return {
        "max_instances": row.max_instances,
        "distribution": row.distribution,
        "lead_instance": row.lead_instance,
        "wake": row.wake,
        "review_within_team": bool(row.review_within_team),
        "updated_by": by,
        "updated_at": clock.rfc3339(row.team_updated_at) if row.team_updated_at else None,
    }


def taken(conn: Connection, membership_id: int) -> set[str]:
    """Every id the membership ever gave: an id is never reused (§6.17)."""
    return set(
        conn.execute(
            select(t.credential.c.instance).where(t.credential.c.membership_id == membership_id)
        ).scalars()
    )


def next_id(conn: Connection, membership_id: int) -> str:
    return new_instance_id(taken(conn, membership_id))


def active(conn: Connection, membership_id: int) -> list[Any]:
    """The membership's active instances (their credentials), oldest first."""
    return list(
        conn.execute(
            select(t.credential)
            .where(
                t.credential.c.membership_id == membership_id,
                t.credential.c.revoked_at.is_(None),
            )
            .order_by(t.credential.c.created_at, t.credential.c.id)
        )
    )


def active_count(conn: Connection, membership_id: int) -> int:
    return int(
        conn.execute(
            select(func.count())
            .select_from(t.credential)
            .where(
                t.credential.c.membership_id == membership_id,
                t.credential.c.revoked_at.is_(None),
            )
        ).scalar_one()
    )


def refuse_over_quota(conn: Connection, member: Any, adding: int = 1) -> None:
    """`instance_quota` when the team would have more active instances than it may."""
    if active_count(conn, member.id) + adding > member.max_instances:
        raise ApiError(
            409,
            "instance_quota",
            "the team has as many instances as its rulebook allows",
            {"max": member.max_instances},
        )


def require_active(conn: Connection, member: Any, instance: str, field: str) -> Any:
    """The credential of an active instance of `member`, else `invalid` (§6.4)."""
    row = conn.execute(
        select(t.credential).where(
            t.credential.c.membership_id == member.id,
            t.credential.c.instance == instance,
            t.credential.c.revoked_at.is_(None),
        )
    ).first()
    if row is None:
        raise invalid({field: "not_an_instance"})
    return row


def require_replaceable(
    conn: Connection, member: Any, instance: str, field: str, *, revoked: bool = False
) -> Any:
    """The credential of the instance a join replaces. A human's join replaces an active
    instance (`require_active`, §3.1). Only the hub's placement pickup passes `revoked`:
    a rejoin replaces the instance whose credential was revoked (§15.9), and never a live
    sibling, so with `revoked` the instance's credential must be revoked."""
    if not revoked:
        return require_active(conn, member, instance, field)
    row = conn.execute(
        select(t.credential).where(
            t.credential.c.membership_id == member.id,
            t.credential.c.instance == instance,
            t.credential.c.revoked_at.is_not(None),
        )
    ).first()
    if row is None:
        raise invalid({field: "not_an_instance"})
    successor = conn.execute(
        select(t.credential.c.id).where(
            t.credential.c.membership_id == member.id, t.credential.c.replaces == instance
        )
    ).first()
    if successor is not None:  # a human's join replaced it already: one successor only
        raise invalid({field: "already_replaced"})
    return row


def resolve(conn: Connection, member: Any, instance: str | None, field: str) -> str | None:
    """The one instance a member id or an address comes down to (§6.5, §6.19): the
    named one; else the team's only active instance, or its lead under `distribution:
    lead`. A human member has none (`None`). A member id that leaves the choice open,
    or names a team with no active instance, is `invalid` (`instance_required`): an
    agent's claim always names its instance (§6.17)."""
    if member.agent_id is None:
        if instance is not None:
            raise invalid({field: "not_an_instance"})
        return None
    if instance is not None:
        require_active(conn, member, instance, field)
        return instance
    instances = active(conn, member.id)
    if not instances:
        raise invalid({field: "instance_required"}, "the team has no active instance")
    if len(instances) == 1:
        only: str = instances[0].instance
        return only
    if member.distribution == "lead" and member.lead_instance is not None:
        lead: str = member.lead_instance
        return lead
    raise invalid({field: "instance_required"}, "name the instance: the team has several")


ONLINE_SECONDS, AWAY_SECONDS = 120, 2 * 3600


def presence(last_used_at: datetime | None, live: bool, listening: bool) -> str:
    """One instance's presence by the table of §5.3; the membership's pause is applied
    by the caller."""
    if listening:
        return "online"
    if not live or last_used_at is None:
        return "offline"
    age = (clock.now() - last_used_at).total_seconds()
    if age <= ONLINE_SECONDS:
        return "online"
    if age <= AWAY_SECONDS:
        return "away"
    return "offline"


def views(
    conn: Connection,
    members: Iterable[Any],
    handles: dict[str, str],
    *,
    details: bool = False,
    names: dict[str, str] | None = None,
) -> dict[int, list[dict[str, Any]]]:
    """Per agent membership its active instances as the instance view (§6.17), oldest
    first. `details` adds `credential_id`, for the agent's owner and `members:admin`;
    `names` (agent id -> global name, §6.3) adds the instance's `name`."""
    from maity_hub import listening  # the in-process registry of open long-polls

    rows = {m.id: m for m in members if m.agent_id is not None}
    if not rows:
        return {}
    credentials = conn.execute(
        select(t.credential)
        .where(t.credential.c.membership_id.in_(list(rows)), t.credential.c.revoked_at.is_(None))
        .order_by(t.credential.c.created_at, t.credential.c.id)
    ).all()
    sessions = _live_sessions(conn, [c.id for c in credentials])
    latest = _latest_sessions(conn, [c.id for c in credentials if c.id not in sessions])
    claims = _claim_counts(conn, list(rows))
    found: dict[int, list[dict[str, Any]]] = {m: [] for m in rows}
    for c in credentials:
        member = rows[c.membership_id]
        handle = handles[member.agent_id]
        session = sessions.get(c.id)
        shown = session or latest.get(c.id)
        is_listening = session is not None and listening.is_listening(session.id)
        view: dict[str, Any] = {
            "id": c.instance,
            "address": address(member.agent_id, c.instance),
            "label": f"{handle}#{c.instance}",
        }
        if names is not None:
            view["name"] = f"{names[member.agent_id]}#{c.instance}"  # owner/handle#id (§6.3)
        if details:
            view["credential_id"] = c.id
        view.update(
            {
                "harness": shown.harness if shown else None,
                "model": shown.model if shown else None,
                "session": (
                    {
                        "id": session.id,
                        "started_at": clock.rfc3339(session.started_at),
                        "listening": is_listening,
                    }
                    if session
                    else None
                ),
                "presence": (
                    "paused"
                    if member.paused_since is not None or c.paused_since is not None
                    else presence(c.last_used_at, session is not None, is_listening)
                ),
                "last_seen_at": clock.rfc3339(c.last_used_at) if c.last_used_at else None,
                "paused": paused_view(c),
                "lead": member.lead_instance == c.instance,
                "claims": claims.get((member.id, c.instance), 0),
                "replaces": c.replaces,
                "created_at": clock.rfc3339(c.created_at),
                "revoked_at": None,
            }
        )
        found[member.id].append(view)
    if details:
        _shared_workspaces(found, credentials, sessions)
    return found


def _shared_workspaces(
    found: dict[int, list[dict[str, Any]]], credentials: Sequence[Any], sessions: dict[str, Any]
) -> None:
    """`shared_environment` of each instance view: the siblings whose open session
    declares the same workspace (§6.17). A shared home within a team is normal and not
    shown."""
    by_place: dict[tuple[int, str], list[str]] = {}
    for c in credentials:
        session = sessions.get(c.id)
        if session is not None and session.env_workspace:
            by_place.setdefault((c.membership_id, session.env_workspace), []).append(c.instance)
    shared: dict[tuple[int, str], list[str]] = {}
    for (membership_id, _), ids in by_place.items():
        for instance in ids:
            shared.setdefault((membership_id, instance), []).extend(i for i in ids if i != instance)
    for membership_id, views_ in found.items():
        for view in views_:
            view["shared_environment"] = [
                {"instance": other, "level": "workspace"}
                for other in shared.get((membership_id, view["id"]), [])
            ]


def _live_sessions(conn: Connection, credential_ids: list[str]) -> dict[str, Any]:
    """Per credential its open session, if it has one."""
    if not credential_ids:
        return {}
    return {
        s.credential_id: s
        for s in conn.execute(
            select(t.agent_session).where(
                t.agent_session.c.credential_id.in_(credential_ids),
                t.agent_session.c.live.is_(True),
            )
        )
    }


def _claim_counts(conn: Connection, membership_ids: list[int]) -> dict[tuple[int, str], int]:
    """Per (membership, instance) the open cards it holds."""
    claims: dict[tuple[int, str], int] = {}
    for holder, instance, count in conn.execute(
        select(t.card.c.claim_holder, t.card.c.claim_instance, func.count())
        .where(
            t.card.c.claim_holder.in_(membership_ids),
            t.card.c.claim_instance.is_not(None),
            t.card.c.status.notin_(("done", "cancelled")),
        )
        .group_by(t.card.c.claim_holder, t.card.c.claim_instance)
    ):
        claims[(holder, instance)] = count
    return claims


def _latest_sessions(conn: Connection, credential_ids: list[str]) -> dict[str, Any]:
    """Per credential its newest session, for the harness and model of one not open."""
    if not credential_ids:
        return {}
    latest: dict[str, Any] = {}
    for s in conn.execute(
        select(t.agent_session)
        .where(t.agent_session.c.credential_id.in_(credential_ids))
        .order_by(t.agent_session.c.started_at.desc(), t.agent_session.c.id.desc())
    ):
        latest.setdefault(s.credential_id, s)
    return latest


def instances_of(conn: Connection, credential_ids: Iterable[str | None]) -> dict[str, str]:
    """Per credential id its instance id: an event's actor names it (§8.1). One query
    whatever the rows, also none, so that a list costs the same for 3 events and 30."""
    ids = {c for c in credential_ids if c is not None}
    return dict(
        conn.execute(
            select(t.credential.c.id, t.credential.c.instance).where(t.credential.c.id.in_(ids))
        ).all()
    )


def assigned_for(conn: Connection, member: Any, named: str | None) -> str | None:
    """The `assigned_instance` a card assigned to `member` gets (§6.18), on every path
    that assigns it: none under `free`, where any instance claims; the named one under
    `lead`; the named one or the next in turn under `round_robin`. A human has none."""
    if member.agent_id is None or member.distribution == "free":
        return None
    if named is not None:
        return named
    if member.distribution == "round_robin":
        return round_robin(conn, member)
    return None  # under `lead` the lead instance chooses


def round_robin(conn: Connection, member: Any) -> str | None:
    """The next instance after the one last chosen, in order of `created_at`, skipping
    revoked and paused ones and preferring those online (§6.18); `None` when none is
    left, which leaves the card to the team. Remembers the choice."""
    from maity_hub import listening  # the in-process registry of open long-polls

    if member.paused_since is not None:
        return None
    candidates = [c for c in active(conn, member.id) if c.paused_since is None]
    if not candidates:
        return None
    last = (
        conn.execute(
            select(t.credential.c.created_at, t.credential.c.id).where(
                t.credential.c.membership_id == member.id,
                t.credential.c.instance == member.round_robin_last,
            )
        ).first()
        if member.round_robin_last is not None
        else None
    )
    # The rotation goes on after the last one chosen, also when that one has left it,
    # by the key `active()` orders by, so two instances created in one instant still
    # take turns.
    after = [c for c in candidates if last is not None and (c.created_at, c.id) > tuple(last)]
    order = after + [c for c in candidates if c not in after]
    sessions = _live_sessions(conn, [c.id for c in order])
    now = clock.now()

    def online(c: Any) -> bool:
        session = sessions.get(c.id)
        if session is not None and listening.is_listening(session.id):
            return True
        seen = c.last_used_at
        return (
            session is not None
            and seen is not None
            and (now - seen).total_seconds() <= ONLINE_SECONDS
        )

    chosen: str = next((c for c in order if online(c)), order[0]).instance
    conn.execute(
        update(t.membership).where(t.membership.c.id == member.id).values(round_robin_last=chosen)
    )
    return chosen


# --- the team wake (§8.2) ----------------------------------------------------------------


def team_wakes(
    conn: Connection, project_id: str, audience: list[str], actor_membership: int | None
) -> dict[str, list[str]] | None:
    """For each team the audience addresses by `member:` or `role:` whose `wake` rule is
    not `all`, the instances the event wakes: the lead, or the listening instance with
    the fewest claims (ties to the one idle longest); none when nobody of the team
    listens. `None` when no team was narrowed. The actor's own team is never woken by
    its own event, so it is left out."""
    from maity_hub import listening  # the in-process registry of open long-polls

    teams = [
        m
        for m in conn.execute(
            select(t.membership).where(
                t.membership.c.project_id == project_id,
                t.membership.c.removed_at.is_(None),
                t.membership.c.agent_id.is_not(None),
                t.membership.c.wake != "all",
            )
        )
        if m.id != actor_membership
        and (f"member:{m.agent_id}" in audience or f"role:{m.role}" in audience)
    ]
    if not teams:
        return None
    credentials = conn.execute(
        select(t.credential).where(
            t.credential.c.membership_id.in_([m.id for m in teams]),
            t.credential.c.revoked_at.is_(None),
        )
    ).all()
    sessions = _live_sessions(conn, [c.id for c in credentials])
    listening_now = [
        c for c in credentials if c.id in sessions and listening.is_listening(sessions[c.id].id)
    ]
    claims = _claim_counts(conn, [m.id for m in teams]) if listening_now else {}
    chosen: dict[str, list[str]] = {}
    for m in teams:
        mine = [c for c in listening_now if c.membership_id == m.id]
        if m.wake == "lead":
            chosen[m.agent_id] = [c.instance for c in mine if c.instance == m.lead_instance]
            continue
        free = min(
            mine,
            key=lambda c: (claims.get((m.id, c.instance), 0), c.last_used_at or c.created_at),
            default=None,
        )
        chosen[m.agent_id] = [free.instance] if free is not None else []
    return chosen


def refresh_team_wake(conn: Connection, project_id: str) -> None:
    """Keep `project.team_wake` true exactly while one of its teams narrows the wake."""
    narrowed = conn.execute(
        select(t.membership.c.id)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.removed_at.is_(None),
            t.membership.c.wake != "all",
        )
        .limit(1)
    ).first()
    conn.execute(
        update(t.project).where(t.project.c.id == project_id).values(team_wake=narrowed is not None)
    )


# --- the rulebook (§6.18) ---------------------------------------------------------------


class TeamIn(Strict):
    max_instances: int | None = Field(default=None, ge=1, le=MAX_INSTANCES)
    distribution: Literal["free", "lead", "round_robin"] | None = None
    lead_instance: str | None = Field(default=None, max_length=5)
    wake: Literal["all", "lead", "next_free"] | None = None
    review_within_team: bool | None = None


def humans_only() -> ApiError:
    return ApiError(
        403,
        "forbidden",
        "only the human who owns the agent sets its team's rules",
        {"reason": "humans_only"},
    )


def patch_team(
    conn: Connection, caller: Caller, slug: str, member_id: str, team: TeamIn | None
) -> tuple[Any, Membership | None]:
    """`PATCH …/members/{id}` with `team` alone (§6.18): the membership row after the
    change, and the caller's own membership, `None` for an owner outside the project.
    Only the human who owns the agent profile, also when not a member."""
    if team is None:
        raise invalid({"team": "required"})
    target, reader = team_target(conn, caller, slug, member_id)
    _set_team(conn, target, team, caller)
    row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    return row, reader


def team_target(
    conn: Connection, caller: Caller, slug: str, member_id: str
) -> tuple[Any, Membership | None]:
    """The agent membership a profile-owner-only PATCH changes (`team`, §6.18;
    `owner_preferences`, §19.4), with the caller's own: its agent's owner may call
    without being a member; to anyone else who is no member the project does not exist
    (§2.3)."""
    project = namespace.resolve(conn, slug)
    if project is None or caller.kind == "runner":
        raise not_found()
    try:
        target = member_row(conn, project.id, member_id)
    except ApiError:
        target = None
    if target is not None and owns_agent(conn, caller, target):
        try:
            return target, membership(conn, caller, slug)
        except ApiError:
            return target, None
    mine = membership(conn, caller, slug)  # not_found for a stranger
    if target is None:
        raise not_found()
    _require_profile_owner(conn, caller, target)
    return target, mine


def owns_agent(conn: Connection, caller: Caller, target: Any) -> bool:
    if caller.kind != "human" or target.agent_id is None:
        return False
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == target.agent_id)
    ).scalar()
    return bool(owner == caller.human_id)


def _require_profile_owner(conn: Connection, caller: Caller, target: Any) -> None:
    """Only the human who owns the agent profile sets its team's rulebook: not an admin
    who is not that owner, and no agent (§6.18, §2.3)."""
    if caller.kind != "human":
        raise humans_only()
    if target.agent_id is None:
        raise invalid({"team": "agents_only"}, "a team is an agent membership's")
    if not owns_agent(conn, caller, target):
        raise humans_only()


def _set_team(conn: Connection, target: Any, team: TeamIn, caller: Caller) -> None:
    """Apply a subset of the rulebook and emit `member_updated` with `changed: ["team"]`.
    Lowering `max_instances` below the count revokes nothing (§6.18)."""
    from maity_hub import views  # views builds the instance views from this module

    given = team.model_fields_set
    values: dict[str, Any] = {}
    for field in ("max_instances", "distribution", "wake", "review_within_team"):
        if field in given:
            value = getattr(team, field)
            if value is None:
                raise invalid({f"team.{field}": "required"})
            values[field] = value
    if "lead_instance" in given:
        if team.lead_instance is not None:
            if not INSTANCE_PATTERN.fullmatch(team.lead_instance):
                raise invalid({"team.lead_instance": "not_an_instance"})
            require_active(conn, target, team.lead_instance, "team.lead_instance")
        values["lead_instance"] = team.lead_instance
    lead = values.get("lead_instance", target.lead_instance)
    needs_lead = "lead" in (
        values.get("distribution", target.distribution),
        values.get("wake", target.wake),
    )
    if needs_lead and lead is None:
        raise invalid({"team.lead_instance": "required"}, "a lead rule needs a lead instance")
    changed = {k: v for k, v in values.items() if getattr(target, k) != v}
    if not changed:
        return
    conn.execute(
        update(t.membership)
        .where(t.membership.c.id == target.id)
        .values(
            **changed,
            team_updated_by=caller.human_id,
            team_updated_at=clock.now(),
            changed_by_credential=None,
            changed_via=caller.via,
        )
    )
    if "wake" in changed:
        refresh_team_wake(conn, target.project_id)
    row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    emit(
        conn,
        row.project_id,
        "member_updated",
        ["all"],
        {**views.member_view(conn, row), "changed": ["team"]},
        actor=_human_actor(conn, caller, row.project_id),
        subject=("member", row.agent_id),
    )


def _human_actor(conn: Connection, caller: Caller, project_id: str) -> Actor:
    """The human as the actor: through their membership, or none for an owner who is
    not a member of the project."""
    own = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id == caller.human_id,
            t.membership.c.active.is_(True),
        )
    ).scalar()
    return (
        Actor(membership_id=own, via=caller.via) if own is not None else Actor(None, via=caller.via)
    )
