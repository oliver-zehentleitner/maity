"""Jour fixe series (docs/api.md §20.1): a project's several jour fixes, each with a topic, a
circle of who takes part, its own schedule and the members holding the right to moderate it.

A series with `circle: owner` is its `circle_owner`'s own: kept by that human, seen by them,
their agents, and the series' moderators and pending moderators; the humans with
`project:admin` see only that it exists, so that they can delete it. The other series are
kept by the humans with `project:admin` and read by every member.
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import Connection, delete, func, insert, select, update

from maity_hub import clock, rules
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.errors import ApiError, invalid, not_found
from maity_hub.events import Actor
from maity_hub.ids import new_id
from maity_hub.jourfixe import schedule
from maity_hub.scopes import has_scope

CIRCLES = ("owner", "humans", "all")
EVERYONE = ["all"]
MAX_SERIES = 10
TOPIC_MAX = 300
SCHEDULE_FIELDS = (
    "recurrence",
    "time",
    "timezone",
    "answer_window_minutes",
    "step_window_minutes",
    "report_window_hours",
)
Sight = Literal["full", "existence"]


def keeper_refused() -> ApiError:
    """`forbidden` for anyone but the series' keepers (§20.1)."""
    return ApiError(
        403, "forbidden", "only the series' keepers do that", {"reason": "not_series_keeper"}
    )


# --- reading ----------------------------------------------------------------------------------


def of_project(conn: Connection, project_id: str) -> list[Any]:
    return list(
        conn.execute(
            select(t.jour_fixe_series)
            .where(t.jour_fixe_series.c.project_id == project_id)
            .order_by(t.jour_fixe_series.c.created_at, t.jour_fixe_series.c.id)
        ).all()
    )


def find(conn: Connection, project_id: str, series_id: str) -> Any:
    row = conn.execute(
        select(t.jour_fixe_series).where(
            t.jour_fixe_series.c.project_id == project_id, t.jour_fixe_series.c.id == series_id
        )
    ).first()
    if row is None:
        raise not_found()
    return row


def schedule_of(series: Any) -> dict[str, Any]:
    """The schedule `jourfixe.schedule` reads: the config with the `enabled` flag."""
    return {**schedule.filled(series.config or {}), "enabled": bool(series.enabled)}


def grants(conn: Connection, series_id: str) -> list[Any]:
    """The series' moderator rows with each member's principal id, oldest grant first."""
    m, g = t.membership.c, t.jour_fixe_moderator.c
    return list(
        conn.execute(
            select(t.jour_fixe_moderator, m.agent_id, m.human_id, m.active)
            .join(t.membership, m.id == g.membership_id)
            .where(g.series_id == series_id)
            .order_by(g.granted_at, g.membership_id)
        ).all()
    )


def moderators(conn: Connection, series_id: str) -> list[int]:
    """The active memberships holding the right to moderate the series (§20.2)."""
    return [r.membership_id for r in grants(conn, series_id) if r.state == "active" and r.active]


def _agent_owner(conn: Connection, agent_id: str | None) -> str | None:
    if agent_id is None:
        return None
    owner: str | None = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar()
    return owner


def is_keeper(series: Any, mine: Membership) -> bool:
    """Who creates, changes and deletes the series (§20.1): its `circle_owner`, or for the
    other circles a human with `project:admin`. Never an agent."""
    if mine.kind != "human":
        return False
    if series.circle == "owner":
        return bool(mine.principal_id == series.circle_owner)
    return mine.may("project:admin")


def may_delete(series: Any, mine: Membership) -> bool:
    """A keeper, and for an owner's series also a human with `project:admin` (§20.1)."""
    return is_keeper(series, mine) or (mine.kind == "human" and mine.may("project:admin"))


def sight(conn: Connection, series: Any, mine: Membership) -> Sight | None:
    """How much of the series the member sees (§20.1, "Who sees a series")."""
    if series.circle != "owner":
        return "full"
    if mine.principal_id == series.circle_owner:
        return "full"
    if mine.kind == "agent" and _agent_owner(conn, mine.principal_id) == series.circle_owner:
        return "full"
    if any(r.membership_id == mine.id for r in grants(conn, series.id)):
        return "full"
    if mine.kind == "human" and mine.may("project:admin"):
        return "existence"
    return None


def view(conn: Connection, series: Any, seen: Sight = "full") -> dict[str, Any]:
    config = schedule.filled(series.config or {})
    shown: dict[str, Any] = {
        "id": series.id,
        "circle": series.circle,
        "circle_owner": series.circle_owner,
        "enabled": bool(series.enabled),
        "recurrence": config["recurrence"],
        "time": config["time"],
        "timezone": config["timezone"],
    }
    if seen == "existence":  # the admins of an owner's series: that it exists, not its topic
        return shown
    rows = grants(conn, series.id)

    def entry(r: Any) -> dict[str, Any]:
        return {
            "member_id": r.agent_id or r.human_id,
            "granted_by": r.granted_by,
            "granted_at": clock.rfc3339(r.granted_at),
        }

    return {
        **shown,
        "topic": series.topic,
        "answer_window_minutes": config["answer_window_minutes"],
        "step_window_minutes": config["step_window_minutes"],
        "report_window_hours": config["report_window_hours"],
        "moderators": [entry(r) for r in rows if r.state == "active" and r.active],
        "pending_moderators": [entry(r) for r in rows if r.state == "pending" and r.active],
        "created_by": series.created_by,
        "created_at": clock.rfc3339(series.created_at),
    }


def _human_admins(conn: Connection, project_id: str) -> list[str]:
    m = t.membership.c
    rows = conn.execute(
        select(m.human_id, m.trust, m.role_base).where(
            m.project_id == project_id, m.active.is_(True), m.human_id.isnot(None)
        )
    ).all()
    return [r.human_id for r in rows if has_scope(r.trust, r.role_base, "human", "project:admin")]


def keeper_tokens(conn: Connection, series: Any) -> list[str]:
    """The series' keepers as an audience (§20.9): its `circle_owner`, or the humans with
    `project:admin`."""
    if series.circle == "owner":
        return [f"member:{series.circle_owner}"] if series.circle_owner else []
    return [f"member:{human}" for human in _human_admins(conn, series.project_id)]


def seen_by(conn: Connection, series: Any) -> list[str]:
    """Who may see the series, as an audience: everyone, or for an owner's series its
    `circle_owner`, that owner's agents in the project, and its moderators (§20.1)."""
    if series.circle != "owner":
        return list(EVERYONE)
    m, a = t.membership.c, t.agent_profile.c
    agents = conn.execute(
        select(m.agent_id)
        .join(t.agent_profile, a.id == m.agent_id)
        .where(
            m.project_id == series.project_id,
            m.active.is_(True),
            a.owner_id == series.circle_owner,
        )
    ).scalars()
    granted = [r.agent_id or r.human_id for r in grants(conn, series.id) if r.active]
    members = dict.fromkeys([series.circle_owner, *agents, *granted])
    return [f"member:{who}" for who in members if who]


# --- writing ----------------------------------------------------------------------------------


def _is_member(conn: Connection, project_id: str, human_id: str) -> bool:
    return (
        conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.project_id == project_id,
                t.membership.c.human_id == human_id,
                t.membership.c.active.is_(True),
            )
        ).first()
        is not None
    )


def _checked(fields: dict[str, Any], enabled: bool) -> dict[str, Any]:
    """The schedule as stored, or `invalid` naming every field that is wrong."""
    config = schedule.filled({k: v for k, v in fields.items() if k in SCHEDULE_FIELDS})
    found = schedule.errors({**config, "enabled": enabled})
    if found:
        raise invalid(found)
    return config


def _announce(
    conn: Connection,
    project: Any,
    series: Any,
    change: str,
    actor: Actor | None,
    by: str | None,
    member_id: str | None = None,
    audience: list[str] | None = None,
) -> None:
    payload: dict[str, Any] = {"series_id": series.id, "change": change, "by": by}
    if member_id is not None:
        payload["member_id"] = member_id
    rules.bump(
        conn,
        project,
        "jour_fixe_series_changed",
        audience if audience is not None else seen_by(conn, series),
        payload,
        actor=actor,
        subject=("jour_fixe_series", series.id),
    )


def create(
    conn: Connection, project: Any, mine: Membership, fields: dict[str, Any], actor: Actor
) -> Any:
    """`POST …/jour-fixe/series` (§20.1), by a human: an owner's series for themselves, or with
    `project:admin` one of the other circles."""
    if mine.kind != "human":
        raise keeper_refused()
    circle = fields.get("circle")
    owner = fields.get("circle_owner")
    if circle == "owner":
        if owner is None:
            raise invalid({"circle_owner": "required"})
        if not _is_member(conn, project.id, owner):
            raise invalid({"circle_owner": "not_a_member"})
        if owner != mine.principal_id:
            raise keeper_refused()
    else:
        if owner is not None:
            raise invalid({"circle_owner": "not_for_circle"})
        if not mine.may("project:admin"):
            raise keeper_refused()
    existing = of_project(conn, project.id)
    if len(existing) >= MAX_SERIES:
        raise invalid({"series": "too_many"})
    topic = str(fields["topic"]).strip()
    if circle == "owner" and any(
        s.circle == "owner" and s.circle_owner == owner and s.topic == topic for s in existing
    ):
        raise invalid({"topic": "taken"})
    enabled = bool(fields.get("enabled", False))
    config = _checked(fields, enabled)
    now = clock.now()
    series_id = new_id("jour_fixe_series")
    conn.execute(
        insert(t.jour_fixe_series).values(
            id=series_id,
            project_id=project.id,
            topic=topic,
            circle=circle,
            circle_owner=owner,
            enabled=enabled,
            config=config,
            anchor=now,
            last_slot=now,
            created_by=mine.principal_id,
            created_at=now,
        )
    )
    row = find(conn, project.id, series_id)
    _announce(conn, project, row, "created", actor, mine.principal_id)
    return row


def update_series(
    conn: Connection,
    project: Any,
    series: Any,
    mine: Membership,
    fields: dict[str, Any],
    actor: Actor,
) -> Any:
    """`PATCH …/jour-fixe/series/{jfs}` (§20.1): the fields it names; `circle` and
    `circle_owner` are fixed. A changed schedule counts its weeks from now."""
    if not is_keeper(series, mine):
        raise keeper_refused()
    fixed: dict[str, Any] = {n: "fixed" for n in ("circle", "circle_owner") if n in fields}
    if fixed:
        raise invalid(fixed)
    values: dict[str, Any] = {}
    if "topic" in fields:
        values["topic"] = str(fields["topic"]).strip()
    enabled = bool(fields.get("enabled", series.enabled))
    if "enabled" in fields:
        values["enabled"] = enabled
    given = {k: v for k, v in fields.items() if k in SCHEDULE_FIELDS}
    config = _checked({**(series.config or {}), **given}, enabled)
    if config != schedule.filled(series.config or {}):
        values["config"] = config
    if given or ("enabled" in fields and enabled and not series.enabled):
        now = clock.now()  # no slot before the change is caught up (§20.1)
        values.update(anchor=now, last_slot=now)
    if values:
        conn.execute(
            update(t.jour_fixe_series).where(t.jour_fixe_series.c.id == series.id).values(**values)
        )
    row = find(conn, project.id, series.id)
    _announce(conn, project, row, "updated", actor, mine.principal_id)
    return row


def delete_series(
    conn: Connection, project: Any, series: Any, mine: Membership, actor: Actor
) -> dict[str, Any]:
    """`DELETE …/jour-fixe/series/{jfs}` (§20.1): `200` with its final state. A round of it
    that is not yet final runs to its end; its rounds keep their `series_id` for reading."""
    if not may_delete(series, mine):
        raise keeper_refused()
    final = view(conn, series)
    audience = seen_by(conn, series)
    conn.execute(
        delete(t.jour_fixe_moderator).where(t.jour_fixe_moderator.c.series_id == series.id)
    )
    conn.execute(delete(t.jour_fixe_opt_out).where(t.jour_fixe_opt_out.c.series_id == series.id))
    conn.execute(
        delete(t.jour_fixe_recipient).where(t.jour_fixe_recipient.c.series_id == series.id)
    )
    conn.execute(
        update(t.jour_fixe_round)
        .where(t.jour_fixe_round.c.series_id == series.id)
        .values(series_id=None)
    )
    conn.execute(delete(t.jour_fixe_series).where(t.jour_fixe_series.c.id == series.id))
    _announce(conn, project, series, "deleted", actor, mine.principal_id, audience=audience)
    return final


def grant_at_once(
    conn: Connection, project: Any, series: Any, mine: Membership, member: Any, actor: Actor
) -> Any:
    """The grants that take effect at once (§20.2): a human to themselves for a series they
    keep, a keeper to their own agent. The two-consent path is filed elsewhere."""
    owner = _agent_owner(conn, member.agent_id)
    to_self = member.agent_id is None and member.human_id == mine.principal_id
    own_agent = member.agent_id is not None and owner == mine.principal_id
    if not is_keeper(series, mine) or not (to_self or own_agent):
        raise keeper_refused()
    now = clock.now()
    exists = conn.execute(
        select(func.count())
        .select_from(t.jour_fixe_moderator)
        .where(
            t.jour_fixe_moderator.c.series_id == series.id,
            t.jour_fixe_moderator.c.membership_id == member.id,
        )
    ).scalar_one()
    if exists:
        conn.execute(
            update(t.jour_fixe_moderator)
            .where(
                t.jour_fixe_moderator.c.series_id == series.id,
                t.jour_fixe_moderator.c.membership_id == member.id,
            )
            .values(state="active", owner_consent=True, keeper_consent=True)
        )
    else:
        conn.execute(
            insert(t.jour_fixe_moderator).values(
                series_id=series.id,
                membership_id=member.id,
                state="active",
                granted_by=mine.principal_id,
                granted_at=now,
                owner_consent=True,
                keeper_consent=True,
            )
        )
    principal = member.agent_id or member.human_id
    _announce(conn, project, series, "moderator_granted", actor, mine.principal_id, principal)
    return find(conn, project.id, series.id)


def end_right(
    conn: Connection, project: Any, series: Any, mine: Membership, member: Any, actor: Actor
) -> Any:
    """`DELETE …/series/{jfs}/moderators/{member_id}` (§20.2): by the agent's owner, the member
    itself, the granter, or a keeper; ends the right or withdraws a pending grant."""
    row = next((r for r in grants(conn, series.id) if r.membership_id == member.id), None)
    if row is None:
        raise not_found()
    principal = member.agent_id or member.human_id
    allowed = mine.principal_id in (
        principal,
        row.granted_by,
        _agent_owner(conn, member.agent_id),
    ) or is_keeper(series, mine)
    if not allowed:
        raise keeper_refused()
    conn.execute(
        delete(t.jour_fixe_moderator).where(
            t.jour_fixe_moderator.c.series_id == series.id,
            t.jour_fixe_moderator.c.membership_id == member.id,
        )
    )
    _announce(conn, project, series, "moderator_ended", actor, mine.principal_id, principal)
    return find(conn, project.id, series.id)
