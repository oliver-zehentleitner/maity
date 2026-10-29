"""Cover by a substitute (docs/api.md §6.12): a member out beyond its grace under the
`substitute` policy hands its open work to the first available member of its cover
order, visibly; on return what the substitute touched stays with it, the rest goes back.

`start` and `end` are called from `availability.reconcile`, under the project lock; the
cover set and the moves are one transaction with the announcement.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, and_, or_, select, update

from maity_hub import clock, proposals
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.errors import ApiError
from maity_hub.events import Actor, emit
from maity_hub.scopes import has_scope, in_admin_team

HELD = ("in_progress", "blocked", "review")  # the cards a member holds that cover moves


def _principal(row: Any) -> str:
    return str(row.agent_id or row.human_id)


def _kind(row: Any) -> str:
    return "agent" if row.agent_id else "human"


def _handle(conn: Connection, row: Any) -> str:
    if row.agent_id:
        found = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == row.agent_id)
        ).scalar_one()
    else:
        found = conn.execute(
            select(t.human.c.handle).where(t.human.c.id == row.human_id)
        ).scalar_one()
    return str(found)


def cover_order(conn: Connection, project: Any, row: Any) -> list[Any]:
    """The policy's `substitutes`, expanded: `role:<role>` is that role's agent members by
    handle, `trust:admin` the admin agents (§2.3), a human only when named; never the
    member itself, each once. Every entry is checked again as it stands now: one that
    has become a guest or a proxy since the policy was set does not cover (§6.12)."""
    from maity_hub import availability

    members = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project.id, t.membership.c.active.is_(True)
        )
    ).all()
    by_principal = {_principal(m): m for m in members}
    order: list[Any] = []
    for entry in availability.policy_of(row)["substitutes"]:
        if entry.startswith("role:"):
            role = entry.removeprefix("role:")
            agents = [m for m in members if m.agent_id and m.role == role]
            order += sorted(agents, key=lambda m: _handle(conn, m))
        elif entry == "trust:admin":
            agents = [m for m in members if m.agent_id and in_admin_team(m.trust, m.role)]
            order += sorted(agents, key=lambda m: _handle(conn, m))
        elif entry in by_principal:
            order.append(by_principal[entry])
    seen: set[int] = set()
    shown = []
    for member in order:
        if member.trust == "guest" or member.role == "proxy":
            continue  # never a substitute, whatever the policy said when it was set
        if member.id != row.id and member.id not in seen:
            seen.add(member.id)
            shown.append(member)
    return shown


def available(conn: Connection, project: Any, rows: list[Any], now: datetime) -> list[Any]:
    """Those of `rows` that are `available` and not themselves covered."""
    from maity_hub import availability

    if not rows:
        return []
    presences = availability.presences_of(conn, rows)
    humans = availability.humans_of(conn, rows)
    return [
        r
        for r in rows
        if r.cover_state is None
        and availability.computed(r, presences[r.id], humans.get(r.human_id), project, now)["state"]
        == "available"
    ]


# --- who may take what -----------------------------------------------------------------------


# The scopes that hold each done authority (§6.4): a substitute holding one of them never
# takes a `review` card it would then review or test itself.
DONE_SCOPES = {
    "reviewer": ("tasks:review",),
    "tester": ("tasks:test",),
    "reviewer_and_tester": ("tasks:review", "tasks:test"),
    "admin": ("tasks:admin",),
}


def may_take_card(conn: Connection, project: Any, card: Any, sub: Any) -> bool:
    """A card with an open takeover (an objection hold included) stays with the covered
    member: the takeover's `from` is not rewritten under it (§6.12, §6.19). Never its own
    review: a `review` card moves to the substitute as its author, and never to one that
    holds the done authority, with its own trust and role (§6.12)."""
    from maity_hub import takeovers

    if takeovers.open_on(conn, card.id) is not None:
        return False
    if card.status != "review":
        return True
    held = DONE_SCOPES.get(project.done_authority, ())
    return not any(has_scope(sub.trust, sub.role, _kind(sub), scope) for scope in held)


def may_take_request(project: Any, request: Any, covered: Any, sub: Any) -> bool:
    """A substitute answers as the addressee would, with its own trust and role; cover
    moves no scope (§6.12, §2.3)."""
    from maity_hub import inbox

    if sub.id in (request.asked_by, request.on_behalf_of):
        return False  # never its own question
    klass = getattr(request, "class")
    # Every request to the project's owner — `owner`, `trust:owner` or their member id —
    # is an owner decision and moves only to a human (§6.12).
    to_owner = (
        request.to_kind == "owner"
        or (request.to_kind == "role" and request.to_role == "trust:owner")
        or (covered.trust == "owner" and covered.human_id is not None)
    )
    if (to_owner or covered.agent_id is None and klass in ("consent", "contract")) and sub.agent_id:
        return False  # an owner decision, or what only a human may do
    # The scope an answer needs: a proposal's kind may ask for more than requests:answer
    # (`proposals.Answerer`), and a substitute who could not answer is skipped.
    rule = proposals.answerer(request)
    scope = rule.scope if rule is not None else "requests:answer"
    if (klass == "consent" or rule is not None) and not has_scope(
        sub.trust, sub.role, _kind(sub), scope
    ):
        return False
    if rule is not None and rule.humans_only and sub.agent_id:
        return False
    return inbox.needs_a_human(request, Membership(project, sub, _kind(sub))) is None


# --- the cover set ---------------------------------------------------------------------------


def _cover_set(conn: Connection, project: Any, row: Any) -> tuple[list[Any], list[Any]]:
    cards = conn.execute(
        select(t.card)
        .where(
            t.card.c.project_id == project.id,
            t.card.c.cover.is_(None),
            or_(
                and_(t.card.c.claim_holder == row.id, t.card.c.status.in_(HELD)),
                and_(
                    t.card.c.assigned_to == row.id,
                    t.card.c.status == "open",
                    t.card.c.claim_holder.is_(None),
                ),
            ),
        )
        .order_by(t.card.c.created_at, t.card.c.id)
    ).all()
    addressed = [t.request.c.to_member == row.id]
    if row.trust == "owner" and row.human_id is not None:
        addressed += [
            t.request.c.to_kind == "owner",
            and_(t.request.c.to_kind == "role", t.request.c.to_role == "trust:owner"),
        ]
    requests = conn.execute(
        select(t.request)
        .where(
            t.request.c.project_id == project.id,
            t.request.c.status == "open",
            t.request.c.personal.is_(False),
            t.request.c.cover.is_(None),
            or_(*addressed),
        )
        .order_by(t.request.c.created_at, t.request.c.id)
    ).all()
    return list(cards), list(requests)


def _instance(conn: Connection, sub: Any) -> str | None:
    """The instance a claim moves to; None when the team leaves it open (then the
    substitute takes no held card)."""
    from maity_hub import instances

    try:
        return instances.resolve(conn, sub, None, "holder")
    except ApiError:
        raise _NoInstance from None


class _NoInstance(Exception):
    pass


def start(conn: Connection, row: Any, actor: Actor | None) -> str:
    """Hand the covered member's open work to its cover order. Returns the event's
    `cover`: `substitute`, or `none_available` (retried when a listed member returns)."""
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    now = clock.now()
    ready = available(conn, project, cover_order(conn, project, row), now)
    if not ready:
        _set_state(conn, row, "none_available", None, None)
        return "none_available"
    for_id = _principal(row)
    since = clock.rfc3339(now)
    moved: dict[int, dict[str, list[str]]] = {}
    left: list[str] = []
    cards, requests = _cover_set(conn, project, row)
    for card in cards:
        holds = card.claim_holder == row.id
        for sub in ready:
            if not may_take_card(conn, project, card, sub):
                continue
            try:
                instance = _instance(conn, sub) if holds else None
            except _NoInstance:
                continue
            _move_card(conn, project, card, row, sub, holds, instance, since, actor)
            moved.setdefault(sub.id, {"tasks": [], "requests": []})["tasks"].append(card.id)
            break
        else:
            left.append(card.id)
    for request in requests:
        for sub in ready:
            if may_take_request(project, request, row, sub):
                cover = {"for": for_id, "by": _principal(sub), "since": since}
                conn.execute(
                    update(t.request).where(t.request.c.id == request.id).values(cover=cover)
                )
                moved.setdefault(sub.id, {"tasks": [], "requests": []})["requests"].append(
                    request.id
                )
                break
        else:
            left.append(request.id)
    first = next((s for s in ready if s.id in moved), ready[0])
    _set_state(conn, row, "covered", first.id, now)
    subs = {s.id: s for s in ready}
    for sub_id in moved or {first.id: {"tasks": [], "requests": []}}:
        items = moved.get(sub_id, {"tasks": [], "requests": []})
        emit(
            conn,
            project.id,
            "cover_started",
            _audience(conn, row, subs[sub_id]),
            {
                "member_id": for_id,
                "substitute_id": _principal(subs[sub_id]),
                "tasks": items["tasks"],
                "requests": items["requests"],
                "left": left if sub_id == first.id else [],
            },
            actor=actor,
            subject=("member", for_id),
        )
    return "substitute"


def _move_card(
    conn: Connection,
    project: Any,
    card: Any,
    covered: Any,
    sub: Any,
    holds: bool,
    instance: str | None,
    since: str,
    actor: Actor | None,
) -> None:
    cover = {
        "for": _principal(covered),
        "by": _principal(sub),
        "since": since,
        "moved": "claim" if holds else "assignment",
        "instance": card.claim_instance,  # the covered holder's, for the return
        "touched": False,
    }
    now = clock.now()
    values: dict[str, Any] = {"cover": cover, "updated_at": now}
    if holds:
        # Claims move, they are not dropped: holder and session change, the lease
        # restarts, checkpoint and branch stay on the card.
        values.update(
            claim_holder=sub.id,
            claim_instance=instance,
            claim_session_id=None,
            lease_until=now + timedelta(seconds=project.lease_seconds),
        )
    else:
        from maity_hub.routes.tasks import _assigned_instance

        # The substitute's team distribution picks the instance, as on an assignment.
        values.update(assigned_to=sub.id, assigned_instance=_assigned_instance(conn, sub.id))
    conn.execute(update(t.card).where(t.card.c.id == card.id).values(**values))
    _announce_card(conn, project, card.id, actor)


def _announce_card(conn: Connection, project: Any, card_id: str, actor: Actor | None) -> None:
    from maity_hub.routes.tasks import audience  # tasks reads availability for its gate
    from maity_hub.views import principal_id

    card = conn.execute(select(t.card).where(t.card.c.id == card_id)).one()
    emit(
        conn,
        project.id,
        "task_assigned",
        audience(conn, card),
        {
            "assignee": principal_id(conn, card.assigned_to),
            "assigned_instance": card.assigned_instance,
            "holder": principal_id(conn, card.claim_holder),
            "instance": card.claim_instance,
            "lease_until": clock.rfc3339(card.lease_until) if card.lease_until else None,
            "project_state": project.state,
            "reason": "cover",
        },
        actor=actor,
        subject=("task", card.id),
    )


def _audience(conn: Connection, covered: Any, sub: Any) -> list[str]:
    from maity_hub.views import principal_id

    audience = [f"member:{_principal(covered)}", f"member:{_principal(sub)}"]
    boss = principal_id(conn, covered.reports_to)
    if boss is not None:
        audience.append(f"member:{boss}")
    audience.append("role:admin")
    return list(dict.fromkeys(audience))


def _set_state(
    conn: Connection, row: Any, state: str | None, by: int | None, since: datetime | None
) -> None:
    conn.execute(
        update(t.membership)
        .where(t.membership.c.id == row.id)
        .values(cover_state=state, cover_by=by, cover_since=since)
    )


def wait(conn: Connection, row: Any) -> str:
    _set_state(conn, row, "wait", None, None)
    return "wait"


# --- the return ------------------------------------------------------------------------------


def end(conn: Connection, row: Any, actor: Actor | None) -> None:
    """The member is back: what the substitute touched stays with it, the rest returns;
    `cover` is cleared on both, and one `cover_ended` goes out per substitute (§6.12)."""
    state, since, first = row.cover_state, row.cover_since, row.cover_by
    _set_state(conn, row, None, None, None)
    if state != "covered" or since is None:
        return
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    for_id, this_cover = _principal(row), clock.rfc3339(since)
    now = clock.now()
    members_by_principal = {
        _principal(m): m.id
        for m in conn.execute(select(t.membership).where(t.membership.c.project_id == project.id))
    }
    # per substitute: (kept, returned) card ids and request ids
    cards_of: dict[str, tuple[list[str], list[str]]] = {}
    requests_of: dict[str, tuple[list[str], list[str]]] = {}
    for card in conn.execute(
        select(t.card)
        .where(t.card.c.project_id == project.id, t.card.c.cover.isnot(None))
        .order_by(t.card.c.id)
    ).all():
        cover = card.cover
        if cover.get("for") != for_id or cover.get("since") != this_cover:
            continue
        kept, returned = cards_of.setdefault(cover["by"], ([], []))
        values: dict[str, Any] = {"cover": None}
        sub_id = members_by_principal.get(cover["by"])
        moved = cover.get("moved")
        still_with_sub = (
            card.claim_holder == sub_id if moved == "claim" else card.assigned_to == sub_id
        )
        if not still_with_sub:
            # Reassigned or taken over since: the cover relation ended there, and a third
            # party's claim or assignment is never overwritten.
            conn.execute(update(t.card).where(t.card.c.id == card.id).values(**values))
            continue
        if cover.get("touched") or card.status in ("done", "cancelled"):
            kept.append(card.id)
        else:
            returned.append(card.id)
            values["updated_at"] = now
            if cover.get("moved") == "claim" and card.claim_holder is not None:
                values.update(
                    claim_holder=row.id,
                    claim_instance=cover.get("instance"),
                    claim_session_id=None,
                    lease_until=now + timedelta(seconds=project.lease_seconds),
                )
            elif cover.get("moved") == "assignment":
                values.update(assigned_to=row.id, assigned_instance=None)
        conn.execute(update(t.card).where(t.card.c.id == card.id).values(**values))
        if card.id in returned:
            _announce_card(conn, project, card.id, actor)
    for request in conn.execute(
        select(t.request)
        .where(t.request.c.project_id == project.id, t.request.c.cover.isnot(None))
        .order_by(t.request.c.id)
    ).all():
        cover = request.cover
        if cover.get("for") != for_id or cover.get("since") != this_cover:
            continue
        kept, returned = requests_of.setdefault(cover["by"], ([], []))
        # An answered request was touched; an open one simply loses `cover`.
        (kept if request.status != "open" else returned).append(request.id)
        conn.execute(update(t.request).where(t.request.c.id == request.id).values(cover=None))
    members = {
        _principal(m): m
        for m in conn.execute(select(t.membership).where(t.membership.c.project_id == project.id))
    }
    covering = conn.execute(select(t.membership).where(t.membership.c.id == row.id)).one()
    substitutes = sorted(set(cards_of) | set(requests_of))
    if not substitutes and first is not None:  # nothing moved: the one told it started
        first_row = conn.execute(select(t.membership).where(t.membership.c.id == first)).one()
        substitutes = [_principal(first_row)]
    for by in substitutes:
        card_kept, card_back = cards_of.get(by, ([], []))
        request_kept, request_back = requests_of.get(by, ([], []))
        emit(
            conn,
            project.id,
            "cover_ended",
            _audience(conn, covering, members[by]),
            {
                "member_id": for_id,
                "substitute_id": by,
                "tasks": card_kept + card_back,
                "requests": request_kept + request_back,
                "kept": card_kept + request_kept,
                "returned": card_back + request_back,
            },
            actor=actor,
            subject=("member", for_id),
        )


# --- touching -----------------------------------------------------------------------------


def touch(conn: Connection, card: Any, principal: str) -> None:
    """The substitute worked on a card it was handed: it stays with it on return."""
    cover = card.cover
    if cover is None or cover.get("by") != principal or cover.get("touched"):
        return
    conn.execute(
        update(t.card).where(t.card.c.id == card.id).values(cover={**cover, "touched": True})
    )


def routed(conn: Connection, membership_id: int | None) -> tuple[int | None, dict[str, Any] | None]:
    """Area routing while a cover runs (§6.12): a new card for the covered member goes
    to its substitute, with `cover` set. Returns the assignee and the card's cover."""
    if membership_id is None:
        return None, None
    row = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    if row.cover_state != "covered" or row.cover_by is None:
        return membership_id, None
    sub = conn.execute(select(t.membership).where(t.membership.c.id == row.cover_by)).one()
    return sub.id, {
        "for": _principal(row),
        "by": _principal(sub),
        "since": clock.rfc3339(row.cover_since),
        "moved": "assignment",
        "instance": None,
        "touched": False,
    }


def view(cover: dict[str, Any] | None) -> dict[str, Any] | None:
    """`cover` as cards and requests show it: `{for, by, since}`."""
    if cover is None:
        return None
    return {"for": cover["for"], "by": cover["by"], "since": cover["since"]}
