"""An outsider's claim request (docs/api.md §6.5, "An outsider's claim").

The claim of an agent with trust `outside` takes no card by itself under
`policy.outside_claims` `human` or `agent`: it files one waiting request on the card, and a
confirmer of the project confirms or declines it through a checked call. Everything that
decides about a request lives here, so that every path asks the same rules:

- `confirmers` and `is_confirmer`: who confirms now ("Who confirms");
- `refuse_own_claim`: the two checks of the outsider's own claim and the card's pending
  request, in their order; `file` files the request (`claim_requested`);
- `confirm`: the re-check, then the card for the request's instance (`task_claimed` with
  `confirmed_by`); a failed re-check declines the request in a transaction that commits
  although the call answers `409` (`Declined`, `run`);
- `decline`: one settlement for every decline, a confirmer's, another call's and the hub's
  (`claim_declined`, the settling `task_updated`, the owner's notice, the lapse request
  withdrawn);
- `refuse_placement`: the owner of an outsider's agent places it on no card, whatever path;
- `sweep`: the minute worker's pass, the lapse and the hub's own declines.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Engine, func, insert, select, update

from maity_hub import clock, instances, policy
from maity_hub import tables as t
from maity_hub.errors import ApiError, not_found
from maity_hub.events import Actor, emit, lock_project, transaction
from maity_hub.ids import new_id
from maity_hub.scopes import OUTSIDE, has_scope

log = logging.getLogger(__name__)

# A confirmer's reasons (§6.5, "The confirmation and the decline"); the hub's and another
# call's are the conflicts of the re-check and of "Settled by another call".
CONFIRMER_REASONS = ("declined", "not_a_fit", "duplicate")
RECHECK_ORDER = ("taken", "gone", "isolated", "not_public", "not_open_to_outsiders")
LAPSE_KIND = "claim_request_lapse"
LAPSE_REPLIES = [
    {"id": "confirm", "label": "Confirm the claim"},
    {"id": "decline", "label": "Decline the claim"},
]


# --- reading ----------------------------------------------------------------------------


def is_outside(row: Any) -> bool:
    """An agent with trust `outside` (§2.3), whose claim is a request."""
    return bool(row is not None and row.trust == OUTSIDE)


def pending(conn: Connection, card_id: str) -> Any | None:
    """The card's waiting request, at most one by the table's key."""
    c = t.claim_request.c
    return conn.execute(
        select(t.claim_request).where(c.task_id == card_id, c.pending.is_(True))
    ).first()


def view(conn: Connection, row: Any) -> dict[str, Any]:
    """`{id, member_id, instance, requested_at}`, the item of the card's `claim_requests`."""
    from maity_hub.views import principal_id

    return {
        "id": row.id,
        "member_id": principal_id(conn, row.member_id),
        "instance": row.instance,
        "requested_at": clock.rfc3339(row.requested_at),
    }


def owner_of(conn: Connection, member: Any) -> str | None:
    """The human who owns the agent membership `member`, None for a human's."""
    if member.agent_id is None:
        return None
    owner: str | None = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == member.agent_id)
    ).scalar()
    return owner


def _member(conn: Connection, membership_id: int) -> Any:
    return conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()


def is_public(conn: Connection, project: Any) -> bool:
    """The project is public for outsiders (§2.3), the predicate the claim and the re-check
    ask; an archived or otherwise closed one is not."""
    from maity_hub import public_projects  # the public pages' modules, as `access` reads them

    if project.state in policy.CLOSED_STATES:
        return False
    return project.id in public_projects.public_for_outsiders(conn, [project.id])


def opens_card(project: Any, card: Any) -> bool:
    """`policy.looking_for_coders` opens the card to an outsider's agent (§6.1, §6.5)."""
    looking = policy.looking_for_coders(project)
    if looking == "all":
        return True
    if looking == "per_card":
        return bool(card.open_to_outsiders)
    return False


def owner_claims(conn: Connection, project_id: str, owner_id: str) -> int:
    """The claims all the agents of `owner_id` have in the project (§6.5), held and pending
    together, all their instances and expired leases included."""
    held = conn.execute(
        select(func.count())
        .select_from(t.card)
        .join(t.membership, t.membership.c.id == t.card.c.claim_holder)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.card.c.project_id == project_id, t.agent_profile.c.owner_id == owner_id)
    ).scalar_one()
    c = t.claim_request.c
    waiting = conn.execute(
        select(func.count())
        .select_from(t.claim_request)
        .where(c.project_id == project_id, c.owner_id == owner_id, c.pending.is_(True))
    ).scalar_one()
    return int(held) + int(waiting)


def _cap(project: Any) -> ApiError:
    return ApiError(
        403,
        "forbidden",
        "the outsider's agents hold or wait for as many cards as the project allows",
        {"reason": "outside_claims_max", "max": project.outside_claims_max},
    )


# --- who confirms -----------------------------------------------------------------------


def _passes_filter(row: Any, owner_id: str | None, mode: str) -> bool:
    """A confirmer never has trust `outside`, is not isolated, is no proxy and is not the
    requesting agent's owner or one of that owner's agents; under `human` only a human."""
    if row is None or not row.active or row.trust == OUTSIDE or row.isolated_since is not None:
        return False
    if row.role_base == "proxy" or row.role == "proxy":
        return False
    if mode == "human" and row.agent_id is not None:
        return False
    return not (owner_id is not None and owner_id in (row.human_id, row.agent_owner))


def _mode(project: Any) -> str:
    """The confirmers `outside_claims` names now: under `direct` those of `agent`."""
    mode = policy.outside_claims(project)
    return "agent" if mode == "direct" else mode


def _rows(conn: Connection, project_id: str, where: Any = None) -> list[Any]:
    query = (
        select(t.membership, t.agent_profile.c.owner_id.label("agent_owner"))
        .select_from(
            t.membership.outerjoin(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        )
        .where(t.membership.c.project_id == project_id, t.membership.c.active.is_(True))
    )
    if where is not None:
        query = query.where(where)
    return list(conn.execute(query).all())


def _seats(conn: Connection, project: Any) -> set[int]:
    """The member seated in `policy.coordinator`, and the substitute while it stands in."""
    from maity_hub import availability

    seats = set(availability.coordinator_ids(conn, project))
    stand_in = project.coordinator_substitute
    if stand_in is not None and availability.substitute_stands_in(conn, project):
        seats |= {r.id for r in _rows(conn, project.id) if stand_in in (r.agent_id, r.human_id)}
    return seats


def confirmers(conn: Connection, project: Any, owner_id: str | None) -> list[Any]:
    """The confirmers of a request by an agent of `owner_id` now (§6.5, "Who confirms"):
    the coordinator seat and the standing-in substitute, and every holder of `tasks:admin`,
    each through the filter; the rows by membership id."""
    mode = _mode(project)
    seats = _seats(conn, project)
    found = []
    for row in _rows(conn, project.id):
        kind = "agent" if row.agent_id is not None else "human"
        admin = has_scope(row.trust, row.role_base, kind, "tasks:admin")
        if not (admin or row.id in seats):
            continue
        if _passes_filter(row, owner_id, mode):
            found.append(row)
    return sorted(found, key=lambda r: r.id)


def tokens(conn: Connection, rows: Iterable[Any]) -> list[str]:
    return [f"member:{r.agent_id or r.human_id}" for r in rows]


def _owned_by(conn: Connection, mine: Any, owner_id: str | None) -> bool:
    """The caller is the human who owns the requesting agent, or one of that human's agents."""
    if owner_id is None:
        return False
    if mine.kind == "human":
        return bool(mine.row.human_id == owner_id)
    return owner_of(conn, mine.row) == owner_id


def not_a_confirmer() -> ApiError:
    return ApiError(
        403,
        "forbidden",
        "only a confirmer of the project confirms or declines an outsider's claim",
        {"reason": "not_a_confirmer"},
    )


def is_confirmer(conn: Connection, mine: Any, owner_id: str | None) -> bool:
    """Whether the calling `Membership` confirms now: never through a bridge, never by
    `line:lead` alone, and never for its own owner's agent."""
    if getattr(mine, "bridged", False):
        return False
    if _owned_by(conn, mine, owner_id):
        return False
    project = mine.project
    row = next((r for r in _rows(conn, project.id, t.membership.c.id == mine.id)), None)
    if row is None:
        return False
    admin = mine.may("tasks:admin")
    if not (admin or row.id in _seats(conn, project)):
        return False
    return _passes_filter(row, owner_id, _mode(project))


# --- the owner's placement --------------------------------------------------------------


def refuse_placement(conn: Connection, mine: Any, target: Any) -> None:
    """The human who owns an outsider's agent places it on no card (§6.5, "Who confirms"):
    an `assign` naming it, a claim with `holder` naming it, a `PATCH` whose `assigned_to`
    names it, whether or not a request waits."""
    if not is_outside(target) or mine.kind != "human":
        return
    if owner_of(conn, target) == mine.row.human_id:
        raise not_a_confirmer()


# --- the outsider's own claim ------------------------------------------------------------


def refuse_own_claim(conn: Connection, mine: Any, card: Any) -> Any | None:
    """The two checks of an outsider's own claim, then the card's pending request (§6.5):
    `not_open_to_outsiders`, `outside_claims_max`, then the same agent's waiting request
    (returned, for a `202` with it unchanged) or another agent's (`already_claimed` with
    `pending: true`). None when the claim goes on."""
    project = mine.project
    if not is_public(conn, project) or not opens_card(project, card):
        raise ApiError(
            403,
            "forbidden",
            "this card is not open to outsiders' agents",
            {"reason": "not_open_to_outsiders"},
        )
    waiting = pending(conn, card.id)
    own = waiting is not None and waiting.member_id == mine.id
    cap = project.outside_claims_max
    if cap is not None:
        owner = owner_of(conn, mine.row)
        counted = owner_claims(conn, project.id, owner) if owner is not None else 0
        if own:
            counted -= 1  # its claim here is that request again
        if counted >= cap:
            raise _cap(project)
    if waiting is None:
        return None
    if own:
        return waiting
    raise ApiError(
        409,
        "already_claimed",
        f"a claim request waits on {card.id}",
        {"pending": True},
    )


def file(conn: Connection, mine: Any, card: Any, actor: Actor) -> Any:
    """File the waiting request of the calling instance (§6.5, "The claim request") and
    emit `claim_requested` to the confirmers of this moment and the requesting instance."""
    project = mine.project
    owner = owner_of(conn, mine.row)
    assert owner is not None
    now = clock.now().replace(microsecond=0)  # the hub's time to the second (Q18)
    request_id = new_id("claim_request")
    conn.execute(
        insert(t.claim_request).values(
            id=request_id,
            project_id=project.id,
            task_id=card.id,
            member_id=mine.id,
            instance=mine.instance or "",
            owner_id=owner,
            status="pending",
            pending=True,
            requested_at=now,
            lapses_at=now + timedelta(minutes=project.takeover_window_minutes),
        )
    )
    row = conn.execute(select(t.claim_request).where(t.claim_request.c.id == request_id)).one()
    shown = view(conn, row)
    audience = [
        *tokens(conn, confirmers(conn, project, owner)),
        instances.token(mine.principal_id, mine.instance),
    ]
    emit(
        conn,
        project.id,
        "claim_requested",
        list(dict.fromkeys(audience)),
        {"task_id": card.id, "claim_request": shown},
        actor=actor,
        subject=("task", card.id),
    )
    return row


# --- the re-check and the confirmation ----------------------------------------------------


class Declined(Exception):
    """A confirmation whose re-check failed: the request is declined with `reason` in a
    transaction of its own (`run`), and the call answers `409 conflict`."""

    def __init__(
        self, request_id: str, reason: str, decided_by: int | None, actor: Actor | None, cap: Any
    ) -> None:
        super().__init__(reason)
        self.request_id = request_id
        self.reason = reason
        self.decided_by = decided_by
        self.actor = actor
        self.cap = cap

    def error(self) -> ApiError:
        details: dict[str, Any] = {"reason": self.reason}
        if self.reason == "outside_claims_max":
            details["max"] = self.cap
        return ApiError(409, "conflict", "the claim no longer holds; it is declined", details)

    def settle(self, conn: Connection) -> None:
        row = conn.execute(
            select(t.claim_request).where(t.claim_request.c.id == self.request_id)
        ).first()
        if row is None:
            return
        lock_project(conn, row.project_id)
        decline(conn, row, self.reason, self.decided_by, self.actor)


def run[Answer](engine: Engine, step: Callable[[], Answer]) -> Answer:
    """`step` (an `idempotency.run`), with a `Declined` from it settled afterwards in its own
    transaction: the decline stands although the call answers `409`."""
    try:
        return step()
    except Declined as declined:
        with transaction(engine) as conn:
            declined.settle(conn)
        raise declined.error() from None


def recheck(conn: Connection, project: Any, card: Any, req: Any) -> str | None:
    """The conflicts of a confirmation, in their order (§6.5, "The re-check"): the first
    that applies, or None."""
    member = _member(conn, req.member_id)
    if (
        card.status != "open"
        or card.claim_holder is not None
        or (
            project.claim_policy == "assign-only"
            and card.assigned_to is not None
            and card.assigned_to != req.member_id
        )
    ):
        return "taken"
    if not member.active:
        return "gone"
    try:
        instances.require_active(conn, member, req.instance, "instance")
    except ApiError:
        return "gone"
    if member.isolated_since is not None:
        return "isolated"
    if not is_public(conn, project):
        return "not_public"
    if not opens_card(project, card):
        return "not_open_to_outsiders"
    cap = project.outside_claims_max
    if cap is not None and owner_claims(conn, project.id, req.owner_id) > cap:
        return "outside_claims_max"
    return None


def refuse_confirmer(conn: Connection, mine: Any, card: Any) -> None:
    """Step 3 of `…/claim/confirm` and `…/claim/decline`, before the request is looked up:
    the caller confirms now. The owner of the card's waiting request, and its agents, is
    refused so too; the request is on the card for every reader to see."""
    waiting = pending(conn, card.id)
    owner = waiting.owner_id if waiting is not None else None
    if not is_confirmer(conn, mine, owner):
        raise not_a_confirmer()


def named(conn: Connection, card: Any, request_id: Any) -> Any:
    """Step 4: `request_id` names the card's pending request, else `not_found`."""
    waiting = pending(conn, card.id)
    if waiting is None or waiting.id != request_id:
        raise not_found()
    return waiting


def confirm(
    conn: Connection,
    project: Any,
    card: Any,
    req: Any,
    by: Any,
    by_instance: str | None,
    actor: Actor,
) -> Any:
    """The re-check, then the card for the request's instance as if its own claim had taken
    it now (§6.5): `task_claimed` with `confirmed_by`, then the status's `task_updated`
    naming `claim_requests`. `by` is the confirming membership row. Returns the card."""
    from maity_hub.routes import tasks as task_routes  # the routes import this module
    from maity_hub.views import principal_id

    reason = recheck(conn, project, card, req)
    if reason is not None:
        raise Declined(req.id, reason, by.id, actor, project.outside_claims_max)
    # Refusals that leave it pending (§6.5): a paused agent or instance, a suspended owner.
    task_routes._refuse_paused(conn, req.member_id, req.instance)
    audience_extra = tokens(conn, confirmers(conn, project, req.owner_id))
    now = clock.now()
    lease_until = now + timedelta(seconds=project.lease_seconds)
    won = conn.execute(
        update(t.card)
        .where(t.card.c.id == card.id, t.card.c.claim_holder.is_(None), t.card.c.status == "open")
        .values(
            claim_holder=req.member_id,
            claim_instance=req.instance,
            claim_session_id=None,  # the instance's next call moves it to its session
            claim_since=now,
            lease_until=lease_until,
            status="in_progress",
            updated_at=now,
            changed_by_credential=actor.credential_id,
            changed_via=actor.via,
        )
    ).rowcount
    if won != 1:
        raise Declined(req.id, "taken", by.id, actor, None)
    _settle(conn, req, "confirmed", None, by.id)
    card = task_routes._card(conn, card.id)
    emit(
        conn,
        project.id,
        "task_claimed",
        task_routes.audience(conn, card),
        {
            "holder": principal_id(conn, req.member_id),
            "instance": req.instance,
            "lease_until": clock.rfc3339(lease_until),
            "project_state": project.state,
            "confirmed_by": {"member_id": by.agent_id or by.human_id, "instance": by_instance},
        },
        actor=actor,
        subject=("task", card.id),
    )
    task_routes.status_moved(
        conn, card, project.state, actor, settled=audience_extra
    )  # to in_progress, `claim_requests: []`
    _withdraw_lapse(conn, req, "claim_request_confirmed")
    return card


def _settle(
    conn: Connection, req: Any, status: str, reason: str | None, decided_by: int | None
) -> bool:
    done = conn.execute(
        update(t.claim_request)
        .where(t.claim_request.c.id == req.id, t.claim_request.c.pending.is_(True))
        .values(
            status=status,
            pending=None,
            reason=reason,
            decided_by=decided_by,
            decided_at=clock.now(),
        )
    ).rowcount
    return done == 1


def _withdraw_lapse(conn: Connection, req: Any, reason: str) -> None:
    """The open decision request of a lapsed request, withdrawn in the same transaction."""
    if req.lapse_request_id is None:
        return
    from maity_hub.routes.requests import close_request  # requests imports this module

    close_request(conn, req.lapse_request_id, "withdrawn", None, reason=reason)


def decline(
    conn: Connection,
    req: Any,
    reason: str,
    decided_by: int | None,
    actor: Actor | None,
    *,
    task_updated: bool = True,
) -> list[str] | None:
    """Settle `req` as declined with `reason` (§6.5): `claim_declined` to the requesting
    instance, the `task_updated` of `claim_requests` to the card's readers and the
    confirmers of this moment (unless the caller's own `task_updated` names it, `False`:
    then it gets those confirmers' tokens back), the owner's notice, and the lapse request
    withdrawn. None when it was settled already."""
    from maity_hub.views import principal_id

    project = conn.execute(select(t.project).where(t.project.c.id == req.project_id)).one()
    extra = tokens(conn, confirmers(conn, project, req.owner_id))
    if not _settle(conn, req, "declined", reason, decided_by):
        return None
    by = None
    if decided_by is not None:
        decider = _member(conn, decided_by)
        by = {
            "member_id": decider.agent_id or decider.human_id,
            "instance": (
                _actor_instance(conn, actor)
                if decider.agent_id is not None and actor is not None
                else None
            ),
        }
    requester = principal_id(conn, req.member_id)
    assert requester is not None
    emit(
        conn,
        project.id,
        "claim_declined",
        [instances.token(requester, req.instance)],
        {"task_id": req.task_id, "request_id": req.id, "reason": reason, "decided_by": by},
        actor=actor,
        subject=("task", req.task_id),
    )
    if task_updated:
        settled_event(conn, project, req.task_id, extra, actor)
    _withdraw_lapse(conn, req, "claim_request_declined")
    notice(conn, project, req, reason, decided_by)
    return extra


def _actor_instance(conn: Connection, actor: Actor) -> str | None:
    if actor.credential_id is None:
        return None
    found: str | None = conn.execute(
        select(t.credential.c.instance).where(t.credential.c.id == actor.credential_id)
    ).scalar()
    return found


def settled_event(
    conn: Connection, project: Any, card_id: str, extra: list[str], actor: Actor | None
) -> None:
    """The `task_updated` that settles a request (§6.5, "The claim request"): `fields:
    ["claim_requests"]`, to the card's readers and the confirmers of that moment."""
    from maity_hub.routes import tasks as task_routes

    card = task_routes._card(conn, card_id)
    emit(
        conn,
        project.id,
        "task_updated",
        list(dict.fromkeys([*task_routes.audience(conn, card), *extra])),
        {
            "id": card.id,
            "fields": ["claim_requests"],
            "claim_requests": [],
            "history": [],
            "project_state": project.state,
        },
        actor=actor,
        subject=("task", card.id),
    )


def notice(conn: Connection, project: Any, req: Any, reason: str, decided_by: int | None) -> None:
    """The outside owner's notice (§6.5): a personal `info` request to the agent's owner,
    `claim_notice: {claim_request_id, reason, decided_by}`, no free text."""
    from maity_hub.routes.requests import file_hub_notice

    member = _member(conn, req.member_id)
    title_row = conn.execute(select(t.card.c.title).where(t.card.c.id == req.task_id)).scalar()
    lead = (
        "Claim request waiting for the project's admins"
        if reason == "expired"
        else "Claim request declined"
    )
    handle = None
    if decided_by is not None:
        decider = _member(conn, decided_by)
        if decider.agent_id is not None:
            handle = conn.execute(
                select(t.agent_profile.c.handle).where(t.agent_profile.c.id == decider.agent_id)
            ).scalar()
        else:
            handle = conn.execute(
                select(t.human.c.handle).where(t.human.c.id == decider.human_id)
            ).scalar()
    file_hub_notice(
        conn,
        project.id,
        member.id,
        member.agent_id,
        f"{lead}: {title_row}",
        None,
        task_id=req.task_id,
        claim_notice={"claim_request_id": req.id, "reason": reason, "decided_by": handle},
    )


# --- settled by another call (§6.5) -------------------------------------------------------


def taken(
    conn: Connection, card_id: str, by: int | None, actor: Actor | None, **kw: Any
) -> list[str] | None:
    """A member's own claim, an admin's claim with `holder` naming another member, or an
    `assign` to another member: the card's waiting request is declined with `taken`."""
    waiting = pending(conn, card_id)
    if waiting is None:
        return None
    return decline(conn, waiting, "taken", by, actor, **kw)


def member_left(conn: Connection, membership_id: int, reason: str, actor: Actor | None) -> None:
    """The requesting agent's isolation (`isolated`) or removal (`gone`): its waiting
    requests are declined by the hub's call, `decided_by` the member whose call it was."""
    c = t.claim_request.c
    rows = conn.execute(
        select(t.claim_request).where(c.member_id == membership_id, c.pending.is_(True))
    ).all()
    for row in rows:
        decline(conn, row, reason, actor.membership_id if actor else None, actor)


def instances_gone(conn: Connection, attached: Iterable[tuple[int, str | None]]) -> None:
    """A revoked, detached or replaced instance: its waiting requests are declined `gone`."""
    c = t.claim_request.c
    for membership_id, instance in attached:
        if instance is None:
            continue
        rows = conn.execute(
            select(t.claim_request).where(
                c.member_id == membership_id, c.instance == instance, c.pending.is_(True)
            )
        ).all()
        for row in rows:
            decline(conn, row, "gone", None, None)


def not_public(conn: Connection, project: Any) -> None:
    """A project no longer public for outsiders: every waiting request is declined
    `not_public`, `decided_by` null (§6.5)."""
    if is_public(conn, project):
        return
    c = t.claim_request.c
    rows = conn.execute(
        select(t.claim_request).where(c.project_id == project.id, c.pending.is_(True))
    ).all()
    for row in rows:
        decline(conn, row, "not_public", None, None)


# --- the lapse and the minute worker (§6.5) -------------------------------------------------


def lapse(conn: Connection, req: Any) -> None:
    """A request that waited `takeover_window_minutes`: one `decision` request to
    `trust:admin` with `confirm` and `decline`, once per claim request, and the owner's
    notice with `expired`. The claim request keeps waiting."""
    from maity_hub import inbox
    from maity_hub.routes.requests import file_lapse

    project = lock_project(conn, req.project_id)
    req = conn.execute(select(t.claim_request).where(t.claim_request.c.id == req.id)).one()
    if not req.pending or req.lapsed_at is not None:
        return
    member = _member(conn, req.member_id)
    request_id = file_lapse(
        conn,
        project.id,
        f"Claim request of {member.agent_id} on {req.task_id}: confirm or decline?",
        {"kind": LAPSE_KIND, "claim_request_id": req.id},
        to=inbox.Addressee("role", role="trust:admin"),
        options=LAPSE_REPLIES,
        task_id=req.task_id,
        claim_request_id=req.id,
        humans_only=policy.outside_claims(project) == "human",
    )
    conn.execute(
        update(t.claim_request)
        .where(t.claim_request.c.id == req.id)
        .values(lapsed_at=clock.now(), lapse_request_id=request_id)
    )
    notice(conn, project, req, "expired", None)


def sweep(engine: Engine) -> None:
    """The minute worker's pass: the hub's declines (a project no longer public, an agent
    isolated or gone, an instance no longer attached), then the lapses."""
    c = t.claim_request.c
    with engine.connect() as conn:
        rows = conn.execute(
            select(c.id, c.project_id).where(c.pending.is_(True)).order_by(c.requested_at, c.id)
        ).all()
    for row in rows:
        try:
            with transaction(engine) as conn:
                project = lock_project(conn, row.project_id)
                req = conn.execute(
                    select(t.claim_request).where(t.claim_request.c.id == row.id)
                ).one()
                if not req.pending:
                    continue
                member = _member(conn, req.member_id)
                reason = None
                if not is_public(conn, project):
                    reason = "not_public"
                elif not member.active:
                    reason = "gone"
                elif member.isolated_since is not None:
                    reason = "isolated"
                else:
                    try:
                        instances.require_active(conn, member, req.instance, "instance")
                    except ApiError:
                        reason = "gone"
                if reason is not None:
                    decline(conn, req, reason, None, None)
                elif req.lapsed_at is None and req.lapses_at <= clock.now():
                    lapse(conn, req)
        except Exception:  # one request's failure must not stop the others
            log.exception("the claim request pass of %s failed", row.id)


def _lapse_answerer(conn: Connection, request: Any, mine: Any) -> str | None:
    """Who answers the lapse request (§6.5, "The lapse"): under `outside_claims: human`, as
    it reads at the answer, a human only; and a confirmer of the claim request now."""
    from maity_hub.access import Membership

    if not isinstance(mine, Membership):
        return None  # a forward's target: the answer asks again
    req = conn.execute(
        select(t.claim_request).where(
            t.claim_request.c.id == (request.proposal or {}).get("claim_request_id")
        )
    ).first()
    if mine.kind == "agent" and policy.outside_claims(mine.project) == "human":
        return "humans_only"
    if req is None or not is_confirmer(conn, mine, req.owner_id):
        return "not_a_confirmer"
    return None


def _settle_lapse(conn: Connection, settled: Any) -> None:
    """An answer to the lapse request runs `…/claim/confirm` or `…/claim/decline` (with
    `reason: declined`) as the answering member, the re-check included. A failed re-check
    raises `proposals.Stale` carrying the decline, which the answer route settles after the
    rollback, so the claim request is declined and the decision withdrawn."""
    from maity_hub import proposals
    from maity_hub.routes import tasks as task_routes

    if settled.outcome == "withdrawn" or settled.closer is None:
        return
    req = conn.execute(
        select(t.claim_request).where(
            t.claim_request.c.id == settled.proposal.get("claim_request_id")
        )
    ).first()
    if req is None or not req.pending:
        raise not_found()
    project = lock_project(conn, req.project_id)
    card = task_routes._card(conn, req.task_id)
    by = _member(conn, settled.closer.membership_id)
    instance = _actor_instance(conn, settled.closer) if by.agent_id is not None else None
    if settled.reply_id == "confirm":
        try:
            confirm(conn, project, card, req, by, instance, settled.closer)
        except Declined as declined:
            raise proposals.Stale(
                declined.error(),
                settled.request.id,
                "claim_request_declined",
                then=declined.settle,
            ) from None
    elif settled.reply_id == "decline":
        # The answer has closed the decision already: the decline's withdrawal finds it so.
        decline(conn, req, "declined", by.id, settled.closer)


def _register() -> None:
    from maity_hub import proposals

    proposals.register(
        LAPSE_KIND,
        _settle_lapse,
        proposals.Answerer(
            scope="requests:answer",
            humans_only=False,
            refusal="only a confirmer answers a claim request's lapse",
            predicate=_lapse_answerer,
            reply_required=True,
        ),
    )


_register()
