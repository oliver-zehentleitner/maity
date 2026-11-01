"""Who watches a card (docs/api.md §6.4): a member's own watch, stored in `card_watch`, and the
watch that comes with a card of theirs depending on it, computed and never stored."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, or_, select

from maity_hub import tables as t

# A dependent card watches only while it is open; cards.CLOSED, which imports events.
_CLOSED = ("done", "cancelled")


def _dependents(card_ids: Sequence[str]) -> Any:
    """The open cards that depend on `card_ids`, with what they depend on."""
    return (
        select(t.card_edge.c.to_card, t.card.c.assigned_to, t.card.c.claim_holder)
        .join(t.card, t.card.c.id == t.card_edge.c.from_card)
        .where(
            t.card_edge.c.to_card.in_(card_ids),
            t.card_edge.c.kind == "depends_on",
            t.card.c.status.not_in(_CLOSED),
        )
    )


def implied(conn: Connection, card_ids: Sequence[str], membership_id: int) -> set[str]:
    """The cards among `card_ids` a card this member holds or is assigned depends on."""
    if not card_ids:
        return set()
    query = _dependents(card_ids).where(
        or_(t.card.c.assigned_to == membership_id, t.card.c.claim_holder == membership_id)
    )
    return {row.to_card for row in conn.execute(query)}


def watching(conn: Connection, card_ids: Sequence[str], membership_id: int) -> set[str]:
    """The cards among `card_ids` this member watches, either way."""
    if not card_ids:
        return set()
    own = conn.execute(
        select(t.card_watch.c.card_id).where(
            t.card_watch.c.membership_id == membership_id, t.card_watch.c.card_id.in_(card_ids)
        )
    ).scalars()
    return set(own) | implied(conn, card_ids, membership_id)


def at_write(conn: Connection, card_id: str) -> list[int]:
    """The memberships watching the card now, for an event's private list (§6.4). A watch ends
    with the membership."""
    found = set(
        conn.execute(select(t.card_watch.c.membership_id).where(t.card_watch.c.card_id == card_id))
        .scalars()
        .all()
    )
    for row in conn.execute(_dependents([card_id])):
        found |= {row.assigned_to, row.claim_holder} - {None}
    if not found:
        return []
    return sorted(
        conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.id.in_(found), t.membership.c.removed_at.is_(None)
            )
        ).scalars()
    )
