"""Agent instances and the team's rulebook (docs/api.md §6.17, §6.18).

An agent instance is one agent credential of a membership: its `instance` column is
the short id, unique within the membership and never reused. Everything the hub
records about work names the member and the instance; a member id alone addresses
the team.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import Connection, func, select, update

from maity_hub import clock
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
    conn: Connection, members: Iterable[Any], handles: dict[str, str], *, details: bool = False
) -> dict[int, list[dict[str, Any]]]:
    """Per agent membership its active instances as the instance view (§6.17), oldest
    first. `details` adds `credential_id`, for the agent's owner and `members:admin`."""
    from maity_hub import listening  # the in-process registry of open long-polls

    rows = {m.id: m for m in members if m.agent_id is not None}
    if not rows:
        return {}
    credentials = conn.execute(
        select(t.credential)
        .where(t.credential.c.membership_id.in_(list(rows)), t.credential.c.revoked_at.is_(None))
        .order_by(t.credential.c.created_at, t.credential.c.id)
    ).all()
    sessions = {
        s.credential_id: s
        for s in conn.execute(
            select(t.agent_session).where(
                t.agent_session.c.credential_id.in_([c.id for c in credentials]),
                t.agent_session.c.live.is_(True),
            )
        )
    }
    latest = _latest_sessions(conn, [c.id for c in credentials if c.id not in sessions])
    claims: dict[tuple[int, str], int] = {}
    for holder, instance, count in conn.execute(
        select(t.card.c.claim_holder, t.card.c.claim_instance, func.count())
        .where(
            t.card.c.claim_holder.in_(list(rows)),
            t.card.c.claim_instance.is_not(None),
            t.card.c.status.notin_(("done", "cancelled")),
        )
        .group_by(t.card.c.claim_holder, t.card.c.claim_instance)
    ):
        claims[(holder, instance)] = count
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
                    if member.paused_since is not None
                    else presence(c.last_used_at, session is not None, is_listening)
                ),
                "last_seen_at": clock.rfc3339(c.last_used_at) if c.last_used_at else None,
                "paused": None,
                "lead": member.lead_instance == c.instance,
                "claims": claims.get((member.id, c.instance), 0),
                "replaces": c.replaces,
                "created_at": clock.rfc3339(c.created_at),
                "revoked_at": None,
            }
        )
        found[member.id].append(view)
    return found


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
    target, reader = _team_target(conn, caller, slug, member_id)
    _set_team(conn, target, team, caller)
    row = conn.execute(select(t.membership).where(t.membership.c.id == target.id)).one()
    return row, reader


def _team_target(
    conn: Connection, caller: Caller, slug: str, member_id: str
) -> tuple[Any, Membership | None]:
    """The membership whose rulebook a team-only PATCH changes, with the caller's own:
    its agent's owner may call without being a member (§6.18); to anyone else who is no
    member the project does not exist (§2.3)."""
    project = conn.execute(select(t.project).where(t.project.c.slug == slug)).first()
    if project is None or caller.kind == "runner":
        raise not_found()
    try:
        target = member_row(conn, project.id, member_id)
    except ApiError:
        target = None
    if target is not None and _owns_agent(conn, caller, target):
        try:
            return target, membership(conn, caller, slug)
        except ApiError:
            return target, None
    mine = membership(conn, caller, slug)  # not_found for a stranger
    if target is None:
        raise not_found()
    _require_profile_owner(conn, caller, target)
    return target, mine


def _owns_agent(conn: Connection, caller: Caller, target: Any) -> bool:
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
    if not _owns_agent(conn, caller, target):
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
