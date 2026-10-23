"""Takeovers: one member or agent instance taking a held card from another
(docs/api.md §6.19).

A takeover is `open` while the holder may answer within the window; `accept` or the
window's end transfers the card, an objection puts it into `objected`, and the
requester may withdraw. Time moves takeovers on in two places that settle alike: the
lazy path on each takeover call, and the worker that sweeps due ones. Both run under
the project lock with a conditional UPDATE on the status, so a takeover is never
transferred twice. The routes are in `routes/takeovers.py`; the card routes call
`guard_move` and `reconcile` here.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, insert, select, update

from maity_hub import clock, instances
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.auth.caller import Caller
from maity_hub.errors import ApiError, forbidden, invalid
from maity_hub.events import Actor, emit, lock_project, transaction
from maity_hub.ids import new_id

log = logging.getLogger(__name__)

OPEN = ("open", "objected", "escalated")
CLOSED = ("transferred", "withdrawn", "refused", "cancelled")


# --- the view ----------------------------------------------------------------------------


def view(conn: Connection, row: Any) -> dict[str, Any]:
    from maity_hub.views import principal_ids  # views reads this module's table only

    members = conn.execute(
        select(t.membership.c.id, t.membership.c.agent_id, t.membership.c.human_id).where(
            t.membership.c.id.in_(
                [m for m in (row.from_member, row.to_member, row.requested_by) if m is not None]
            )
        )
    ).all()
    principals = principal_ids(conn, [m.id for m in members])
    agents = {m.id for m in members if m.agent_id is not None}
    requested_by = None
    if row.requested_by is not None:
        requested_by = {
            "kind": "agent" if row.requested_by in agents else "human",
            "member_id": principals[row.requested_by],
            "instance": row.requested_instance,
        }
    return {
        "id": row.id,
        "task_id": row.task_id,
        "from": {"member_id": principals[row.from_member], "instance": row.from_instance},
        "to": {"member_id": principals[row.to_member], "instance": row.to_instance},
        "requested_by": requested_by,
        "reason": row.reason,
        "status": row.status,
        "window_minutes": row.window_minutes,
        "window_ends_at": clock.rfc3339(row.window_ends_at),
        "objection": row.objection,
        "request_id": row.request_id,
        "override": row.override,
        "outcome": row.outcome,
        "created_at": clock.rfc3339(row.created_at),
        "closed_at": clock.rfc3339(row.closed_at) if row.closed_at else None,
    }


def load(conn: Connection, takeover_id: str) -> Any:
    return conn.execute(select(t.takeover).where(t.takeover.c.id == takeover_id)).one()


def open_on(conn: Connection, card_id: str) -> Any:
    """The card's open takeover, if it has one: there is at most one (§6.19)."""
    return conn.execute(
        select(t.takeover).where(t.takeover.c.task_id == card_id, t.takeover.c.status.in_(OPEN))
    ).first()


def _row(conn: Connection, membership_id: int) -> Any:
    return conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()


def _principal(conn: Connection, membership_id: int | None) -> str | None:
    from maity_hub.views import principal_id

    return principal_id(conn, membership_id)


def _token(conn: Connection, membership_id: int | None, instance: str | None) -> list[str]:
    principal = _principal(conn, membership_id)
    return [instances.token(principal, instance)] if principal else []


def _parties(conn: Connection, row: Any) -> list[str]:
    """The holding instance, the receiver and the requester (§8.2)."""
    tokens = [
        *_token(conn, row.from_member, row.from_instance),
        *_token(conn, row.to_member, row.to_instance),
        *_token(conn, row.requested_by, row.requested_instance),
    ]
    return list(dict.fromkeys(tokens))


def _creator(conn: Connection, card_id: str) -> list[str]:
    created_by = conn.execute(select(t.card.c.created_by).where(t.card.c.id == card_id)).scalar()
    return _token(conn, created_by, None)


# --- opening -----------------------------------------------------------------------------


def humans_only() -> ApiError:
    return ApiError(
        403, "forbidden", "a card a human holds is never taken over", {"reason": "humans_only"}
    )


def refuse_human_holder(conn: Connection, card: Any) -> None:
    """A card a human holds is not taken over: `humans_only` for every caller (§6.19)."""
    if card.claim_holder is not None and _row(conn, card.claim_holder).agent_id is None:
        raise humans_only()


def takeover_open(row: Any) -> ApiError:
    return ApiError(409, "takeover_open", "a takeover of this card is open", {"takeover": row.id})


def _receiver(conn: Connection, mine: Membership, to: str | None) -> tuple[Any, str | None]:
    """The membership and the instance `to` comes down to (§6.19): by default the
    caller's own instance; an address names one; a member id is resolved by the team's
    rules, the next one under `round_robin`."""
    if to is None:
        return mine.row, mine.instance
    principal, named = instances.split_address(to)
    from maity_hub.access import member_row

    try:
        target = member_row(conn, mine.project.id, principal)
    except ApiError:
        raise invalid({"to": "not_a_member"}) from None
    if named is None and target.agent_id is not None and target.distribution == "round_robin":
        chosen = instances.round_robin(conn, target)
        if chosen is not None:
            return target, chosen
    return target, instances.resolve(conn, target, named, "to")


def open_takeover(
    conn: Connection, mine: Membership, caller: Caller, card: Any, reason: str, to: str | None
) -> tuple[Any, int]:
    """Open a takeover of `card` (§6.19): `201` with an open one, or `200` with one
    already transferred when the lease has run out or a human admin takes it."""
    if card.claim_holder is None:
        raise ApiError(409, "not_claimed", "nobody holds this card: claim or assign it instead")
    holder = _row(conn, card.claim_holder)
    refuse_human_holder(conn, card)
    current = open_on(conn, card.id)
    if current is not None:
        raise takeover_open(current)
    receiver, instance = _receiver(conn, mine, to)
    if (receiver.id, instance) != (mine.id, mine.instance) and not _may_name(
        mine, holder, receiver
    ):
        raise forbidden(
            "tasks:admin", "naming someone else needs tasks:admin, or the lead of the holding team"
        )
    if (receiver.id, instance) == (card.claim_holder, card.claim_instance):
        raise invalid({"to": "holds_it"}, "the card is already theirs")
    now = clock.now()
    window = mine.project.takeover_window_minutes
    takeover_id = new_id("takeover")
    conn.execute(
        insert(t.takeover).values(
            id=takeover_id,
            project_id=mine.project.id,
            task_id=card.id,
            from_member=card.claim_holder,
            from_instance=card.claim_instance,
            to_member=receiver.id,
            to_instance=instance,
            requested_by=mine.id,
            requested_instance=mine.instance,
            reason=reason,
            status="open",
            window_minutes=window,
            window_ends_at=now + timedelta(minutes=window),
            created_at=now,
        )
    )
    row = load(conn, takeover_id)
    actor = caller.actor(mine.id)
    expired = card.lease_until is not None and card.lease_until <= now
    if caller.kind == "human" and mine.may("tasks:admin"):
        transfer(conn, row, "immediate", actor, by=mine.principal_id, reason=reason)
        return load(conn, takeover_id), 200
    if expired:
        transfer(conn, row, "lease_expired", actor, by=mine.principal_id, reason=reason)
        return load(conn, takeover_id), 200
    emit(
        conn,
        row.project_id,
        "takeover_opened",
        list(dict.fromkeys([*_parties(conn, row), *_creator(conn, card.id)])),
        view(conn, row),
        actor=actor,
        subject=("task", card.id),
    )
    return row, 201


def _may_name(mine: Membership, holder: Any, receiver: Any) -> bool:
    """Naming someone else as `to` needs `tasks:admin`, or being the lead instance of
    the holding team with `to` an instance of that team (§6.19)."""
    if mine.may("tasks:admin"):
        return True
    return (
        mine.id == holder.id
        and mine.instance is not None
        and mine.instance == holder.lead_instance
        and receiver.id == holder.id
    )


# --- moving and closing --------------------------------------------------------------------


def transfer(
    conn: Connection,
    row: Any,
    how: str,
    actor: Actor | None,
    *,
    by: str | None,
    reason: str | None = None,
    override: dict[str, Any] | None = None,
) -> bool:
    """Move the card to `to` with a fresh lease and close the takeover `transferred`
    (§6.19). Conditional on both: a takeover already closed, or a card no longer held by
    `from`, is not moved again; the latter cancels the takeover. False when nothing
    moved."""
    from maity_hub.routes.tasks import audience  # the card events' audience

    now = clock.now()
    outcome = {"how": how, "by": by, "reason": reason, "at": clock.rfc3339(now)}
    values: dict[str, Any] = {"status": "transferred", "outcome": outcome, "closed_at": now}
    if override is not None:
        values["override"] = override
    closed = conn.execute(
        update(t.takeover)
        .where(t.takeover.c.id == row.id, t.takeover.c.status.in_(OPEN))
        .values(**values)
    ).rowcount
    if closed != 1:
        return False
    lease = conn.execute(
        select(t.project.c.lease_seconds).where(t.project.c.id == row.project_id)
    ).scalar_one()
    holder_instance = (
        t.card.c.claim_instance.is_(None)
        if row.from_instance is None
        else t.card.c.claim_instance == row.from_instance
    )
    moved = conn.execute(
        update(t.card)
        .where(
            t.card.c.id == row.task_id, t.card.c.claim_holder == row.from_member, holder_instance
        )
        .values(
            claim_holder=row.to_member,
            claim_instance=row.to_instance,
            claim_session_id=None,
            claim_since=now,
            lease_until=now + timedelta(seconds=lease),
            assigned_to=row.to_member,
            assigned_instance=row.to_instance,
            updated_at=now,
            changed_by_credential=actor.credential_id if actor else None,
            changed_via=actor.via if actor else None,
        )
    ).rowcount
    if moved != 1:
        # The card left `from` some other way in the meantime (§6.19).
        conn.execute(
            update(t.takeover)
            .where(t.takeover.c.id == row.id)
            .values(status="cancelled", outcome={**outcome, "how": "cancelled"})
        )
        _closed(conn, load(conn, row.id), actor)
        return False
    card = conn.execute(select(t.card).where(t.card.c.id == row.task_id)).one()
    project_state = conn.execute(
        select(t.project.c.state).where(t.project.c.id == row.project_id)
    ).scalar_one()
    emit(
        conn,
        row.project_id,
        "task_claimed",
        audience(conn, card, (row.from_member, row.from_instance)),
        {
            "holder": _principal(conn, row.to_member),
            "instance": row.to_instance,
            "lease_until": clock.rfc3339(card.lease_until),
            "project_state": project_state,
            "takeover_id": row.id,
            "from": {"member_id": _principal(conn, row.from_member), "instance": row.from_instance},
        },
        actor=actor,
        subject=("task", row.task_id),
    )
    _closed(conn, load(conn, row.id), actor)
    return True


def close(
    conn: Connection,
    row: Any,
    status: str,
    how: str,
    actor: Actor | None,
    *,
    by: str | None,
    reason: str | None = None,
) -> bool:
    """Close an open takeover without moving the card: `withdrawn`, `refused` or
    `cancelled` (§6.19). False when it was closed already."""
    now = clock.now()
    closed = conn.execute(
        update(t.takeover)
        .where(t.takeover.c.id == row.id, t.takeover.c.status.in_(OPEN))
        .values(
            status=status,
            outcome={"how": how, "by": by, "reason": reason, "at": clock.rfc3339(now)},
            closed_at=now,
        )
    ).rowcount
    if closed != 1:
        return False
    _closed(conn, load(conn, row.id), actor)
    return True


def _closed(conn: Connection, row: Any, actor: Actor | None) -> None:
    audience = [*_parties(conn, row), *_creator(conn, row.task_id)]
    if row.request_id is not None or row.override is not None:
        audience.append("role:admin")
    emit(
        conn,
        row.project_id,
        "takeover_closed",
        list(dict.fromkeys(audience)),
        view(conn, row),
        actor=actor,
        subject=("task", row.task_id),
    )


# --- the holder's answer, the requester's withdrawal, an override ---------------------------


def refuse_closed(row: Any) -> None:
    if row.status not in OPEN:
        raise ApiError(409, "takeover_closed", "this takeover is closed", {"status": row.status})


def is_holder(mine: Membership, row: Any) -> bool:
    return bool(mine.id == row.from_member and mine.instance == row.from_instance)


def is_requester(mine: Membership, row: Any) -> bool:
    return bool(mine.id == row.requested_by and mine.instance == row.requested_instance)


def respond(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    row: Any,
    *,
    accept: bool,
    reasons: str | None,
) -> None:
    """The holding instance accepts (→ `transferred`) or objects with reasons
    (→ `objected`, and the second window towards an escalation starts)."""
    if not is_holder(mine, row):
        raise ApiError(
            409,
            "not_holder",
            "only the holding instance answers a takeover",
            {"instance": row.from_instance},
        )
    actor = caller.actor(mine.id)
    if accept:
        if row.status not in ("open", "objected"):
            raise invalid({"accept": "not_now"}, "an escalated takeover is decided by the admins")
        _answered(conn, row, actor, {"accept": True})
        transfer(conn, row, "accepted", actor, by=mine.principal_id)
        return
    if row.status != "open":
        raise invalid({"object": "not_open"}, "only an open takeover takes an objection")
    now = clock.now()
    objection = {
        "reasons": reasons,
        "at": clock.rfc3339(now),
        "by": {"kind": "agent", "id": mine.principal_id, "member_id": mine.principal_id},
    }
    conn.execute(
        update(t.takeover)
        .where(t.takeover.c.id == row.id, t.takeover.c.status == "open")
        .values(
            status="objected",
            objection=objection,
            escalate_at=now + timedelta(minutes=row.window_minutes),
        )
    )
    _answered(conn, load(conn, row.id), actor, {"objection": objection})


def _answered(conn: Connection, row: Any, actor: Actor, answer: dict[str, Any]) -> None:
    emit(
        conn,
        row.project_id,
        "takeover_answered",
        _parties(conn, row),
        {**view(conn, row), **answer},
        actor=actor,
        subject=("task", row.task_id),
    )


def withdraw(
    conn: Connection, mine: Membership, caller: Caller, row: Any, reason: str | None
) -> None:
    if not is_requester(mine, row):
        raise forbidden(message="only the requester withdraws a takeover")
    close(
        conn,
        row,
        "withdrawn",
        "withdrawn",
        caller.actor(mine.id),
        by=mine.principal_id,
        reason=reason,
    )


def admin_team(mine: Membership, row: Any) -> bool:
    """The members with the role `admin` and the `owner`, never a `proxy`, and never a
    party: `from`, `to` and the requester, all instances of them (§6.19)."""
    if mine.role not in ("admin", "owner"):
        return False
    return mine.id not in (row.from_member, row.to_member, row.requested_by)


def override(conn: Connection, mine: Membership, caller: Caller, row: Any, reason: str) -> None:
    """An emergency transfer of an open takeover by the admin team (§6.19). An admin
    agent only when every agent involved is owned by its own owner."""
    if not admin_team(mine, row):
        raise ApiError(
            403,
            "forbidden",
            "only the admin team, not a party, overrides a takeover",
            {"reason": "party_to_takeover" if _party(mine, row) else "admin_team_only"},
        )
    if caller.kind == "agent" and not _same_owner(conn, mine, row):
        raise ApiError(
            403,
            "forbidden",
            "another owner's agents are involved: a human of the admin team overrides",
            {"reason": "humans_only"},
        )
    if row.status != "open":
        raise invalid({"status": "not_open"}, "a disputed takeover is decided by escalation")
    now = clock.now()
    record = {"by": mine.principal_id, "reason": reason, "at": clock.rfc3339(now)}
    actor = caller.actor(mine.id)
    emit(
        conn,
        row.project_id,
        "takeover_overridden",
        list(dict.fromkeys([*_parties(conn, row), "role:admin", "role:owner"])),
        {**view(conn, row), "override": record},
        actor=actor,
        subject=("task", row.task_id),
    )
    transfer(conn, row, "override", actor, by=mine.principal_id, reason=reason, override=record)


def _party(mine: Membership, row: Any) -> bool:
    return mine.id in (row.from_member, row.to_member, row.requested_by)


def _same_owner(conn: Connection, mine: Membership, row: Any) -> bool:
    """Every agent among holder, receiver and requester is owned by the caller's owner."""
    owners = {
        owner
        for owner, agent in conn.execute(
            select(t.agent_profile.c.owner_id, t.membership.c.agent_id)
            .join(t.membership, t.membership.c.agent_id == t.agent_profile.c.id)
            .where(
                t.membership.c.id.in_(
                    [m for m in (row.from_member, row.to_member, row.requested_by) if m]
                )
            )
        )
        if agent is not None
    }
    own = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == mine.principal_id)
    ).scalar()
    return owners <= {own}


# --- the card routes' side ----------------------------------------------------------------


def guard_move(conn: Connection, mine: Membership, card: Any) -> None:
    """An agent's `assign`, `release` or `PATCH assigned_to` that would take a card from
    its holder (§6.19): never from a human, not while a takeover is open, and not while
    the holder's lease is active (`takeover_required`). A human's moves keep the rules of
    §6.5."""
    if card.claim_holder is None or mine.kind != "agent":
        return
    holder = _row(conn, card.claim_holder)
    if holder.agent_id is None:
        raise humans_only()
    current = open_on(conn, card.id)
    if current is not None:
        raise takeover_open(current)
    if card.lease_until is not None and card.lease_until > clock.now():
        raise ApiError(
            409,
            "takeover_required",
            "the holder's lease is active: open a takeover instead",
            {"holder": holder.agent_id, "instance": card.claim_instance},
        )


def record_lease_expired(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    before: Any,
    to: tuple[int, str | None],
) -> None:
    """An agent's move of a card whose lease ran out is in the history as a takeover,
    closed at once (`transferred`, `lease_expired`)."""
    now = clock.now()
    window = mine.project.takeover_window_minutes
    takeover_id = new_id("takeover")
    conn.execute(
        insert(t.takeover).values(
            id=takeover_id,
            project_id=mine.project.id,
            task_id=before.id,
            from_member=before.claim_holder,
            from_instance=before.claim_instance,
            to_member=to[0],
            to_instance=to[1],
            requested_by=mine.id,
            requested_instance=mine.instance,
            reason="the holder's lease had run out",
            status="transferred",
            window_minutes=window,
            window_ends_at=now,
            outcome={
                "how": "lease_expired",
                "by": mine.principal_id,
                "reason": None,
                "at": clock.rfc3339(now),
            },
            created_at=now,
            closed_at=now,
        )
    )
    _closed(conn, load(conn, takeover_id), caller.actor(mine.id))


def reconcile(conn: Connection, card_id: str, actor: Actor | None, *, decided: bool) -> None:
    """After a card write: an open takeover whose card is no longer held by `from` is
    closed — `cancelled`, or with `how: decided` when a human with `tasks:admin` moved
    it (§6.19)."""
    row = open_on(conn, card_id)
    if row is None:
        return
    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
    still_held = (card.claim_holder, card.claim_instance) == (row.from_member, row.from_instance)
    if still_held and card.status not in ("done", "cancelled"):
        return
    close(
        conn,
        row,
        "cancelled",
        "decided" if decided else "cancelled",
        actor,
        by=None,
    )


def membership_removed(conn: Connection, membership_id: int, actor: Actor | None) -> None:
    """A removed member is no party any more: its open takeovers, as holder, receiver
    or requester, are cancelled (§6.19)."""
    c = t.takeover.c
    rows = conn.execute(
        select(t.takeover).where(
            c.status.in_(OPEN),
            (c.from_member == membership_id)
            | (c.to_member == membership_id)
            | (c.requested_by == membership_id),
        )
    ).all()
    for row in rows:
        close(conn, row, "cancelled", "cancelled", actor, by=None)


# --- time ----------------------------------------------------------------------------------


def settle(conn: Connection, project_id: str, now: datetime | None = None) -> None:
    """Move on what time decides in one project: an open takeover whose window ended is
    transferred (`window_elapsed`). Under the project lock, so the worker and a request
    settle alike."""
    now = now or clock.now()
    lock_project(conn, project_id)
    due = conn.execute(
        select(t.takeover).where(
            t.takeover.c.project_id == project_id,
            t.takeover.c.status == "open",
            t.takeover.c.window_ends_at <= now,
        )
    ).all()
    for row in due:
        transfer(conn, row, "window_elapsed", None, by=None)


def due_projects(conn: Connection) -> list[str]:
    now = clock.now()
    return list(
        conn.execute(
            select(t.takeover.c.project_id)
            .where(t.takeover.c.status == "open", t.takeover.c.window_ends_at <= now)
            .distinct()
        ).scalars()
    )


def sweep(engine: Engine) -> None:
    with engine.connect() as conn:
        projects = due_projects(conn)
    for project_id in projects:
        try:
            with transaction(engine) as conn:
                settle(conn, project_id)
        except Exception:  # one project's failure must not stop the others
            log.exception("settling the takeovers of %s failed", project_id)


INTERVAL = 30.0


class Worker:
    """Settles takeovers whose window ended, in the background, one thread per process."""

    def __init__(self, engine: Engine, interval: float = INTERVAL) -> None:
        self.engine = engine
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-takeovers", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            sweep(self.engine)
