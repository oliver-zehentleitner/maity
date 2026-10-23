"""The rules of cards: statuses, transitions, done authority, edges, routing (docs/api.md §6.4).

Pure functions and small queries; the routes in `routes/tasks.py` apply them
inside one transaction.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, delete, insert, select

from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.errors import ApiError, invalid

KINDS = ("task", "maintenance_round", "release", "contract")
LABELS = ("fix", "feature", "chore")
STATUSES = ("proposed", "open", "in_progress", "blocked", "review", "done", "cancelled")
CLOSED = ("done", "cancelled")
CREATE_STATUSES = ("proposed", "open")


def invalid_transition(current: str, wanted: str) -> ApiError:
    return ApiError(
        409,
        "invalid_transition",
        f"a card cannot go from {current} to {wanted} this way",
        {"from": current, "to": wanted},
    )


def holds(mine: Membership, card: Any) -> bool:
    """The holder is the holding instance (§6.4): a sibling of the team does not hold."""
    if card.claim_holder != mine.id:
        return False
    return mine.instance is None or card.claim_instance in (None, mine.instance)


def sibling_holds(mine: Membership, card: Any) -> bool:
    """Another instance of the caller's own team holds the card."""
    return card.claim_holder == mine.id and not holds(mine, card)


def has_done_authority(mine: Membership, card: Any) -> bool:
    """Who moves a card to done, by `policy.done_authority` (§6.1)."""
    authority = mine.project.done_authority
    if authority == "holder":
        return holds(mine, card)
    if authority == "reviewer":
        return mine.may("tasks:review")
    return mine.may("tasks:admin")


def check_transition(mine: Membership, card: Any, wanted: str) -> None:
    """A `PATCH {status}`: the transition table of §6.4."""
    current = card.status
    if wanted == current:
        return
    if wanted == "cancelled" and current not in CLOSED:
        if mine.may("tasks:admin") or (current == "open" and card.created_by == mine.id):
            return
        raise ApiError(
            403, "forbidden", "cancelling this card needs tasks:admin", {"scope": "tasks:admin"}
        )
    simple = {("proposed", "open"), ("open", "proposed")}
    if (current, wanted) in simple:
        return
    if (current, wanted) in {("review", "done"), ("review", "in_progress")}:
        if has_done_authority(mine, card):
            return
        raise ApiError(
            403, "forbidden", "this needs done authority", {"scope": authority_scope(mine)}
        )
    if (current, wanted) == ("in_progress", "done") and mine.project.done_authority == "holder":
        if holds(mine, card):
            return
        raise ApiError(409, "not_holder", "only the holder moves this card to done")
    raise invalid_transition(current, wanted)


def authority_scope(mine: Membership) -> str:
    return {"reviewer": "tasks:review", "admin": "tasks:admin"}.get(
        mine.project.done_authority, "tasks:write"
    )


def open_dependencies(conn: Connection, card_id: str) -> list[str]:
    rows = conn.execute(
        select(t.card.c.id, t.card.c.status)
        .join(t.card_edge, t.card_edge.c.to_card == t.card.c.id)
        .where(t.card_edge.c.from_card == card_id, t.card_edge.c.kind == "depends_on")
    ).all()
    return sorted(r.id for r in rows if r.status not in CLOSED)


def refuse_open_dependencies(conn: Connection, card_id: str) -> None:
    pending = open_dependencies(conn, card_id)
    if pending:
        raise ApiError(
            409, "dependencies_open", "cards this one depends on are not done", {"open": pending}
        )


def check_edge_targets(conn: Connection, project_id: str, field: str, ids: list[str]) -> None:
    if not ids:
        return
    found = set(
        conn.execute(
            select(t.card.c.id).where(t.card.c.project_id == project_id, t.card.c.id.in_(ids))
        ).scalars()
    )
    if found != set(ids):
        raise invalid({field: "unknown_task"}, "an edge names a card that is not in this project")


def would_cycle(conn: Connection, card_id: str, depends_on: list[str]) -> bool:
    """True when `card_id` depending on `depends_on` closes a loop."""
    seen: set[str] = set()
    frontier = list(depends_on)
    while frontier:
        current = frontier.pop()
        if current == card_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        frontier += list(
            conn.execute(
                select(t.card_edge.c.to_card).where(
                    t.card_edge.c.from_card == current, t.card_edge.c.kind == "depends_on"
                )
            ).scalars()
        )
    return False


def _edges(conn: Connection, card_id: str, kind: str) -> set[str]:
    return set(
        conn.execute(
            select(t.card_edge.c.to_card).where(
                t.card_edge.c.from_card == card_id, t.card_edge.c.kind == kind
            )
        ).scalars()
    )


def set_depends_on(conn: Connection, project_id: str, card_id: str, ids: list[str]) -> bool:
    """Replace the card's dependencies; True when they changed."""
    ids = list(dict.fromkeys(ids))
    if set(ids) == _edges(conn, card_id, "depends_on"):
        return False
    if card_id in ids:
        raise invalid({"depends_on": "self"}, "a card cannot depend on itself")
    check_edge_targets(conn, project_id, "depends_on", ids)
    if would_cycle(conn, card_id, ids):
        raise invalid({"depends_on": "cycle"}, "these dependencies would form a cycle")
    conn.execute(
        delete(t.card_edge).where(
            t.card_edge.c.from_card == card_id, t.card_edge.c.kind == "depends_on"
        )
    )
    for target in ids:
        conn.execute(
            insert(t.card_edge).values(from_card=card_id, to_card=target, kind="depends_on")
        )
    return True


def set_ships_with(conn: Connection, project_id: str, card_id: str, ids: list[str]) -> set[str]:
    """`ships_with` is symmetric: the hub mirrors every edge on the other card (§6.4).

    Returns the other cards whose `ships_with` changed with it.
    """
    ids = list(dict.fromkeys(ids))
    before = _edges(conn, card_id, "ships_with")
    if set(ids) == before:
        return set()
    if card_id in ids:
        raise invalid({"ships_with": "self"}, "a card cannot ship with itself")
    check_edge_targets(conn, project_id, "ships_with", ids)
    if (
        ids
        and conn.execute(
            select(t.card.c.id).where(t.card.c.id.in_([card_id, *ids]), t.card.c.kind == "release")
        ).first()
    ):
        # A release ships cards; it is never one of the cards shipped together (§6.7).
        raise invalid({"ships_with": "release_card"}, "ships_with never names a release card")
    both = (t.card_edge.c.from_card == card_id) | (t.card_edge.c.to_card == card_id)
    conn.execute(delete(t.card_edge).where(both, t.card_edge.c.kind == "ships_with"))
    for other in ids:
        for a, b in ((card_id, other), (other, card_id)):
            conn.execute(insert(t.card_edge).values(from_card=a, to_card=b, kind="ships_with"))
    return before ^ set(ids)


def area_owner(conn: Connection, project_id: str, area: str | None) -> int | None:
    """The membership owning the narrowest area that contains `area` (§6.2 routing)."""
    if not area:
        return None
    rows = conn.execute(
        select(t.membership.c.id, t.membership.c.areas, t.membership.c.joined_at)
        .where(t.membership.c.project_id == project_id, t.membership.c.active.is_(True))
        .order_by(t.membership.c.joined_at, t.membership.c.id)
    ).all()
    best: tuple[int, int] | None = None  # (length of the owning area, membership id)
    for row in rows:
        for owned in row.areas:
            if _contains(owned, area) and (best is None or len(owned) > best[0]):
                best = (len(owned), row.id)
    return best[1] if best else None


def _contains(owned: str, area: str) -> bool:
    if owned == "/":
        return True
    owned_dir = owned if owned.endswith("/") else owned + "/"
    return area == owned or area.startswith(owned_dir) or area + "/" == owned_dir
