"""Availability per member, the limit, the policy and the outage (docs/api.md §6.12).

Availability is computed, never set: from the membership's pause, the stored limit
(an agent's on its membership, a human's on the account), the owner's `absence` and
presence. The hub keeps the state it last announced on the membership
(`availability_state`, `availability_since`) and when the current outage began
(`outage_since`), so that `reconcile` announces each end of an outage once, whether a
request or the worker's sweep notices it first.

An outage is the state leaving `available`. A human's `offline` is shown and triggers
nothing (§6.12): for a human only a limit, or the owner's absence, is an outage.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, case, or_, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.events import Actor, emit, lock_project, transaction

log = logging.getLogger(__name__)

ON_UNAVAILABLE = ("wait", "substitute")
DEFAULT_POLICY: dict[str, Any] = {"on_unavailable": "wait", "substitutes": [], "grace_minutes": 15}
MAX_SUBSTITUTES = 8
GRACE_MAX = 1440
LIMIT_AHEAD = timedelta(days=7)  # `until` at most this far ahead (§6.12)
LEASE_HOLD = timedelta(hours=24)  # a limit keeps the member's cards at most this long
REASON_MAX = 200
INTERVAL = 60.0  # seconds between the worker's sweeps
CLOSED_CARD = ("done", "cancelled")


def policy_of(row: Any) -> dict[str, Any]:
    """The membership's `availability_policy`; a row that never set one has the default."""
    stored = row.availability_policy or {}
    return {**DEFAULT_POLICY, **stored, "substitutes": list(stored.get("substitutes", []))}


def _live(until: datetime | None, now: datetime) -> bool:
    return until is not None and until > now


def computed(
    row: Any, presence: str, human: Any | None, project: Any, now: datetime
) -> dict[str, Any]:
    """The state of §6.12's table and what goes with it, before any reader's shaping:
    `{state, until?, source?, harness?, reason?, show_reason_in?}`."""
    if row.agent_id is not None and row.paused_since is not None:
        return {"state": "paused"}
    if row.agent_id is not None and _live(row.limit_until, now):
        return {
            "state": "limited",
            "until": row.limit_until,
            "source": row.limit_source,
            "harness": row.limit_harness,
            "reason": row.limit_reason,
        }
    if row.agent_id is None and human is not None and _live(human.limit_until, now):
        return {
            "state": "limited",
            "until": human.limit_until,
            "source": "self",
            "reason": human.limit_reason,
            "show_reason_in": list(human.limit_show_reason_in or []),
        }
    if row.agent_id is None and row.role == "owner" and _live(project.absence_until, now):
        return {"state": "limited", "until": project.absence_until, "source": "absence"}
    if presence == "offline":
        return {"state": "offline"}
    return {"state": "available"}


def in_outage(row: Any, state: str) -> bool:
    if row.agent_id is None:
        return state == "limited"
    return state != "available"


def _since(row: Any, found: dict[str, Any], now: datetime) -> datetime:
    """When the state was entered: the announced moment once `reconcile` has stored it,
    until then the best the row says."""
    if row.availability_state == found["state"] and row.availability_since is not None:
        since: datetime = row.availability_since
        return since
    if found["state"] == "paused" and row.paused_since is not None:
        paused: datetime = row.paused_since
        return paused
    if found["state"] == "limited" and found.get("source") != "absence":
        limit_since: datetime | None = row.limit_since if row.agent_id else None
        if limit_since is not None:
            return limit_since
    return now


def view(
    row: Any, presence: str, human: Any | None, project: Any, *, own: bool = False
) -> dict[str, Any]:
    """`availability` of a member view. A human's `reason` only in a project its limit
    names in `show_reason_in`, or to the human itself (`own`, `GET /me`)."""
    now = clock.now()
    found = computed(row, presence, human, project, now)
    shown: dict[str, Any] = {
        "state": found["state"],
        "since": clock.rfc3339(_since(row, found, now)),
    }
    if found["state"] != "limited":
        return shown
    shown["until"] = clock.rfc3339(found["until"])
    shown["source"] = found["source"]
    if row.agent_id is not None:
        shown["harness"] = found.get("harness")
        shown["reason"] = found.get("reason")
    elif found.get("reason") is not None and (own or project.slug in found["show_reason_in"]):
        shown["reason"] = found["reason"]
    return shown


# --- who is told --------------------------------------------------------------------------


def coordinator_ids(conn: Connection, project: Any) -> set[int]:
    """The membership rows that coordinate (§6.1): the named agent, or under the default
    `role:admin` the project's agent admins."""
    if project.coordinator == "role:admin":
        query = select(t.membership.c.id).where(
            t.membership.c.project_id == project.id,
            t.membership.c.active.is_(True),
            t.membership.c.agent_id.isnot(None),
            t.membership.c.role == "admin",
        )
    else:
        query = select(t.membership.c.id).where(
            t.membership.c.project_id == project.id,
            t.membership.c.active.is_(True),
            t.membership.c.agent_id == project.coordinator,
        )
    return set(conn.execute(query).scalars())


def coordinator_token(project: Any) -> str:
    if project.coordinator == "role:admin":
        return "role:admin"
    return f"member:{project.coordinator}"


def _owner_member(conn: Connection, row: Any) -> str | None:
    """For an agent, its human's member id when the human is a member of the project."""
    if row.agent_id is None:
        return None
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == row.agent_id)
    ).scalar_one()
    member = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == row.project_id,
            t.membership.c.human_id == owner,
            t.membership.c.active.is_(True),
        )
    ).first()
    return str(owner) if member is not None else None


def changed_audience(conn: Connection, row: Any, project: Any) -> list[str]:
    """`member_availability_changed` (§8.2): the member's boss, its human, the admins, the
    coordinator; the owners too when the member is the coordinator."""
    from maity_hub.views import principal_id  # views reads this module for its fields

    audience: list[str] = []
    boss = principal_id(conn, row.reports_to)
    if boss is not None:
        audience.append(f"member:{boss}")
    owner = _owner_member(conn, row)
    if owner is not None:
        audience.append(f"member:{owner}")
    audience.append("role:admin")
    audience.append(coordinator_token(project))
    if row.id in coordinator_ids(conn, project):
        audience.append("role:owner")
    return list(dict.fromkeys(audience))


# --- announcing ---------------------------------------------------------------------------


def _presences(conn: Connection, rows: Sequence[Any]) -> dict[int, str]:
    from maity_hub.views import member_views  # views reads this module for its fields

    return {row.id: v["presence"] for row, v in zip(rows, member_views(conn, rows), strict=True)}


def _humans(conn: Connection, rows: Sequence[Any]) -> dict[str, Any]:
    ids = {r.human_id for r in rows if r.human_id is not None}
    if not ids:
        return {}
    return {h.id: h for h in conn.execute(select(t.human).where(t.human.c.id.in_(ids)))}


def _cover(row: Any, outage_since: datetime | None, now: datetime) -> str | None:
    """`cover` of the event: null while within the grace; past it what the policy does.
    Cover by a substitute is not built yet (§6.12): `substitute` reads as waiting."""
    if outage_since is None:
        return None
    grace = timedelta(minutes=policy_of(row)["grace_minutes"])
    if now - outage_since < grace:
        return None
    return "wait"


def reconcile(
    conn: Connection, rows: Sequence[Any], actor: Actor | None = None
) -> list[dict[str, Any]]:
    """Store each row's state as it is now and announce an outage's start and end.
    Returns the events' payloads, for tests and callers that report them.

    The rows are read again under their projects' locks, so that a request and the
    sweep noticing the same change announce it once."""
    for project_id in sorted({r.project_id for r in rows}):
        lock_project(conn, project_id)
    ids = [r.id for r in rows]
    if not ids:
        return []
    rows = conn.execute(
        select(t.membership)
        .where(t.membership.c.id.in_(ids), t.membership.c.active.is_(True))
        .order_by(t.membership.c.id)
    ).all()
    if not rows:
        return []
    now = clock.now()
    presences = _presences(conn, rows)
    humans = _humans(conn, rows)
    projects: dict[str, Any] = {}
    announced = []
    for row in rows:
        project = projects.get(row.project_id)
        if project is None:
            project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
            projects[row.project_id] = project
        found = computed(row, presences[row.id], humans.get(row.human_id), project, now)
        state = found["state"]
        if row.availability_state is None and row.agent_id is not None:
            # An agent's first look after the migration or the join is a baseline, not
            # news. A human starts available: only a limit or an absence takes them out.
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == row.id)
                .values(
                    availability_state=state,
                    availability_since=_since(row, found, now),
                    outage_since=now if in_outage(row, state) else None,
                )
            )
            continue
        previous = row.availability_state or "available"
        if state == previous:
            continue
        since = _since(row, found, now)
        values: dict[str, Any] = {"availability_state": state, "availability_since": since}
        was_out = row.outage_since is not None
        is_out = in_outage(row, state)
        payload = None
        if is_out and not was_out:
            values["outage_since"] = now
            payload = _payload(row, found, since, _cover(row, now, now))
        elif was_out and not is_out:
            values["outage_since"] = None
            payload = _payload(row, found, since, _cover(row, row.outage_since, now))
        conn.execute(update(t.membership).where(t.membership.c.id == row.id).values(**values))
        if payload is not None:
            emit(
                conn,
                row.project_id,
                "member_availability_changed",
                changed_audience(conn, row, project),
                payload,
                actor=actor,
                subject=("member", payload["member_id"]),
            )
            announced.append(payload)
    return announced


def _payload(row: Any, found: dict[str, Any], since: datetime, cover: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "member_id": row.agent_id or row.human_id,
        "state": found["state"],
        "since": clock.rfc3339(since),
    }
    if found["state"] == "limited":
        payload["until"] = clock.rfc3339(found["until"])
        payload["source"] = found["source"]
    payload["cover"] = cover
    return payload


def reconcile_ids(conn: Connection, membership_ids: Sequence[int], actor: Actor | None) -> None:
    rows = conn.execute(select(t.membership).where(t.membership.c.id.in_(membership_ids))).all()
    reconcile(conn, rows, actor)


def human_memberships(conn: Connection, human_id: str) -> list[int]:
    return list(
        conn.execute(
            select(t.membership.c.id)
            .where(t.membership.c.human_id == human_id, t.membership.c.active.is_(True))
            .order_by(t.membership.c.id)
        ).scalars()
    )


# --- the limit ----------------------------------------------------------------------------


def hold_leases(conn: Connection, membership_ids: Sequence[int], until: datetime) -> None:
    """Extend the leases a member holds when a limit is stored (§6.12): to `until` plus
    the grace, never past 24 hours after the outage began. A lease already longer stays."""
    rows = conn.execute(select(t.membership).where(t.membership.c.id.in_(membership_ids))).all()
    for row in rows:
        start = row.outage_since or clock.now()
        target = min(until + timedelta(minutes=policy_of(row)["grace_minutes"]), start + LEASE_HOLD)
        conn.execute(
            update(t.card)
            .where(
                t.card.c.claim_holder == row.id,
                t.card.c.status.notin_(CLOSED_CARD),
                or_(t.card.c.lease_until.is_(None), t.card.c.lease_until < target),
            )
            .values(lease_until=target)
        )


def hold_cap(conn: Connection, membership_id: int, now: datetime) -> datetime | None:
    """While a limit (or the owner's absence) holds the member's leases, the latest a
    lease may reach: 24 hours after the outage began. None when nothing holds them."""
    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).first()
    if row is None:
        return None
    human = None
    if row.human_id is not None:
        human = conn.execute(select(t.human).where(t.human.c.id == row.human_id)).one()
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    # A limit that exists holds, whether or not a pause shows first; a pause alone
    # holds nothing. Presence decides nothing here.
    held = _live(row.limit_until, now) if row.agent_id is not None else False
    if row.agent_id is None and human is not None:
        held = _live(human.limit_until, now) or (
            row.role == "owner" and _live(project.absence_until, now)
        )
    if not held:
        return None
    start: datetime = row.outage_since or now
    return start + LEASE_HOLD


def renewed_lease(conn: Connection, membership_id: int, now: datetime, lease_seconds: int) -> Any:
    """The `lease_until` an ordinary call renews a member's leases to (§6.5): `now` plus
    the lease, and while a limit holds them never shorter than the hold and never past
    its 24-hour cap (§6.12). A value or an SQL expression on the card row."""
    target = now + timedelta(seconds=lease_seconds)
    cap = hold_cap(conn, membership_id, now)
    if cap is None:
        return target
    target = min(target, cap)
    return case((t.card.c.lease_until > target, t.card.c.lease_until), else_=target)


def set_agent_limit(
    conn: Connection,
    row: Any,
    until: datetime | None,
    *,
    source: str,
    harness: str | None,
    reason: str | None,
    placement_id: str | None,
    actor: Actor | None,
) -> None:
    """Store, replace or (`until` None) clear an agent membership's limit, announce what it
    changes and, when stored, hold its leases."""
    now = clock.now()
    lock_project(conn, row.project_id)  # the lock the expiry reads under
    values: dict[str, Any] = (
        {
            "limit_until": until,
            "limit_since": now,
            "limit_source": source,
            "limit_harness": harness,
            "limit_reason": reason,
            "limit_placement_id": placement_id,
        }
        if until is not None
        else NO_LIMIT
    )
    conn.execute(update(t.membership).where(t.membership.c.id == row.id).values(**values))
    reconcile_ids(conn, [row.id], actor)
    if until is not None:
        hold_leases(conn, [row.id], until)


NO_LIMIT: dict[str, Any] = {
    "limit_until": None,
    "limit_since": None,
    "limit_source": None,
    "limit_harness": None,
    "limit_reason": None,
    "limit_placement_id": None,
}


def set_human_limit(
    conn: Connection,
    human_id: str,
    until: datetime | None,
    *,
    reason: str | None,
    show_reason_in: list[str],
    actor_of: Any,
) -> None:
    """A human's limit applies to every membership of the account (§6.12). `actor_of`
    gives the event actor per membership row id."""
    now = clock.now()
    conn.execute(
        update(t.human)
        .where(t.human.c.id == human_id)
        .values(
            limit_until=until,
            limit_since=now if until is not None else None,
            limit_reason=reason if until is not None else None,
            limit_show_reason_in=show_reason_in if until is not None else None,
        )
    )
    ids = human_memberships(conn, human_id)
    for membership_id in ids:
        reconcile_ids(conn, [membership_id], actor_of(membership_id))
    if until is not None:
        hold_leases(conn, ids, until)


def absence_changed(conn: Connection, project: Any, until: datetime | None, actor: Actor) -> None:
    """The owner's absence makes the owner `limited` (§6.1, §6.12); with an `until` it
    holds the owner's leases as a stored limit does."""
    owners = list(
        conn.execute(
            select(t.membership)
            .where(
                t.membership.c.project_id == project.id,
                t.membership.c.role == "owner",
                t.membership.c.human_id.isnot(None),
                t.membership.c.active.is_(True),
            )
            .order_by(t.membership.c.id)
        ).all()
    )
    reconcile(conn, owners, actor)
    if until is not None:
        hold_leases(conn, [o.id for o in owners], until)


def runner_reported(
    conn: Connection, placement: Any, state: str, retry_at: datetime | None, actor: Actor
) -> None:
    """A placement's report (§15.7): `rate_limited` stores the agent's limit with
    `source: runner`; a later report of the same placement that is not clears it."""
    row = conn.execute(
        select(t.membership).where(t.membership.c.id == placement.membership_id)
    ).first()
    if row is None or row.active is not True:
        return
    if state == "rate_limited" and retry_at is not None:
        set_agent_limit(
            conn,
            row,
            retry_at,
            source="runner",
            harness=placement.harness,
            reason="quota",
            placement_id=placement.id,
            actor=actor,
        )
    elif row.limit_placement_id == placement.id:
        set_agent_limit(
            conn,
            row,
            None,
            source="runner",
            harness=None,
            reason=None,
            placement_id=None,
            actor=actor,
        )


def placement_closed(conn: Connection, placement: Any, actor: Actor | None) -> None:
    """A closed placement takes the limit it set with it (§15.7, Stopping)."""
    if placement.membership_id is None:
        return
    row = conn.execute(
        select(t.membership).where(t.membership.c.id == placement.membership_id)
    ).first()
    if row is not None and row.limit_placement_id == placement.id:
        set_agent_limit(
            conn,
            row,
            None,
            source="runner",
            harness=None,
            reason=None,
            placement_id=None,
            actor=actor,
        )


# --- the sweep ----------------------------------------------------------------------------


def _has_active_placement(conn: Connection, membership_id: int) -> bool:
    return (
        conn.execute(
            select(t.placement.c.id).where(
                t.placement.c.membership_id == membership_id, t.placement.c.active.is_(True)
            )
        ).first()
        is not None
    )


def due_limits(conn: Connection, project_id: str) -> list[Any]:
    """The agent memberships whose limit's `until` has passed."""
    return list(
        conn.execute(
            select(t.membership)
            .where(
                t.membership.c.project_id == project_id,
                t.membership.c.active.is_(True),
                t.membership.c.limit_until.isnot(None),
                t.membership.c.limit_until <= clock.now(),
            )
            .order_by(t.membership.c.id)
        ).all()
    )


def end_limit(conn: Connection, project: Any, row: Any) -> bool:
    """Clear one passed limit as it was read, and tell the coordinator and the agent's
    human (`member_limit_ended`) when no placement restarts the agent. A limit renewed,
    cleared or replaced since the read is not this one's: nothing happens, False."""
    cleared = conn.execute(
        update(t.membership)
        .where(t.membership.c.id == row.id, t.membership.c.limit_until == row.limit_until)
        .values(**NO_LIMIT)
    ).rowcount
    if cleared != 1:
        return False
    if not _has_active_placement(conn, row.id):
        audience = [coordinator_token(project)]
        owner = _owner_member(conn, row)
        if owner is not None:
            audience.append(f"member:{owner}")
        emit(
            conn,
            project.id,
            "member_limit_ended",
            audience,
            {
                "member_id": row.agent_id,
                "until": clock.rfc3339(row.limit_until),
                "harness": row.limit_harness,
            },
            subject=("member", row.agent_id),
        )
    return True


def expire_limits(conn: Connection, project_id: str) -> None:
    """At `until` the hub clears the limit (§6.12). Read under the lock every limit
    write takes; the clearing compares `until` all the same, so that a second replica
    or a write that slipped in clears and announces nothing."""
    project = lock_project(conn, project_id)
    for row in due_limits(conn, project_id):
        end_limit(conn, project, row)


def expire_human_limits(conn: Connection) -> list[str]:
    """Clear the humans' limits whose `until` has passed; returns whose."""
    now = clock.now()
    due = conn.execute(
        select(t.human.c.id, t.human.c.limit_until).where(
            t.human.c.limit_until.isnot(None), t.human.c.limit_until <= now
        )
    ).all()
    cleared = []
    for human_id, until in due:
        # Compared with the `until` read: a limit declared again since stays.
        won = conn.execute(
            update(t.human)
            .where(t.human.c.id == human_id, t.human.c.limit_until == until)
            .values(
                limit_until=None, limit_since=None, limit_reason=None, limit_show_reason_in=None
            )
        ).rowcount
        if won == 1:
            cleared.append(human_id)
    return cleared


def sweep(engine: Engine) -> None:
    """Expire passed limits and announce what time alone changed: a limit or an absence
    ending, an agent's session going away. One transaction per project."""
    with transaction(engine) as conn:
        expire_human_limits(conn)
        project_ids = list(conn.execute(select(t.project.c.id).order_by(t.project.c.id)).scalars())
    for project_id in project_ids:
        try:
            with transaction(engine) as conn:
                expire_limits(conn, project_id)
                rows = conn.execute(
                    select(t.membership)
                    .where(
                        t.membership.c.project_id == project_id,
                        t.membership.c.active.is_(True),
                    )
                    .order_by(t.membership.c.id)
                ).all()
                reconcile(conn, rows)
        except Exception:  # one project's failure must not stop the others
            log.exception("the availability sweep of %s failed", project_id)


class Worker:
    """Runs `sweep` in the background (§6.12: the hub acts at `until` on its own)."""

    def __init__(self, engine: Engine, interval: float | None = None) -> None:
        self.engine = engine
        self.interval = INTERVAL if interval is None else interval  # read now: tests set it
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-availability", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                sweep(self.engine)
            except Exception:
                log.exception("the availability sweep failed")


# --- a member leaves ----------------------------------------------------------------------


def member_removed(conn: Connection, project_id: str, removed: Any, actor: Actor | None) -> None:
    """Reset the seats that name a removed member (§6.2): the coordinator seats to their
    defaults in one `policy_changed`, and the member out of every `substitutes` list, a
    `substitute` policy left with none becoming `wait`."""
    from maity_hub import policy, rules  # rules reads the views, which read this module
    from maity_hub.views import member_view

    removed_id = removed.agent_id or removed.human_id
    project = conn.execute(select(t.project).where(t.project.c.id == project_id)).one()
    old = policy.of(project)
    new = dict(old)
    if project.coordinator == removed_id:
        new["coordinator"] = "role:admin"
    if project.coordinator_substitute == removed_id:
        new["coordinator_substitute"] = None
    if new != old:
        conn.execute(
            update(t.project).where(t.project.c.id == project_id).values(**policy.columns(new))
        )
        rules.bump(
            conn,
            project,
            "policy_changed",
            ["all"],
            {"old": old, "new": new, "reason": "member_removed"},
            actor=actor,
        )
    rows = conn.execute(
        select(t.membership)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.active.is_(True),
            t.membership.c.availability_policy.isnot(None),
        )
        .order_by(t.membership.c.id)
    ).all()
    for row in rows:
        current = policy_of(row)
        if removed_id not in current["substitutes"]:
            continue
        left = [s for s in current["substitutes"] if s != removed_id]
        changed = {**current, "substitutes": left}
        if not left:
            changed["on_unavailable"] = "wait"
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == row.id)
            .values(availability_policy=changed)
        )
        after = conn.execute(select(t.membership).where(t.membership.c.id == row.id)).one()
        view = member_view(conn, after)
        emit(
            conn,
            project_id,
            "member_updated",
            ["all"],
            {**view, "changed": ["availability_policy"]},
            actor=actor,
            subject=("member", view["id"]),
        )
