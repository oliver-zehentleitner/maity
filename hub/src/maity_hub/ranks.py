"""A card's place within its status column (docs/api.md §6.4).

`rank` is an opaque string the hub sets: digits and lower-case letters, compared
bytewise, never ending in `0` so that there is always room below a key. Card order
within a status is total: ranked cards first, then unranked ones, each by rank, then
`created_at`, then `id`. Closed cards list by `closed_at`, newest first, then by `id`.

`between(a, b)` is a fractional index: a key strictly between two keys (either may be
None, the open end). A `move` keeps every rank it can and gives new ones only to the
cards that need one for the order to say what the move meant; when keys grow long, the
column is spread out again (`spread`).
"""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise
from typing import Any

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
LONGEST = 24  # past this a move spreads the column out instead of growing a key
SPREAD_WIDTH = 4  # characters per key when a column is spread out


def _midpoint(a: str, b: str | None) -> str:
    """A key strictly between `a` and `b` (`""` and None are the open ends)."""
    if b is not None:
        n = 0
        while (a[n] if n < len(a) else "0") == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _midpoint(a[n:], b[n:])
    low = DIGITS.index(a[0]) if a else 0
    high = DIGITS.index(b[0]) if b is not None else len(DIGITS)
    if high - low > 1:
        return DIGITS[(low + high) // 2]
    if b is not None and len(b) > 1:
        return b[:1]
    return DIGITS[low] + _midpoint(a[1:], None)


def between(a: str | None, b: str | None) -> str:
    if a is not None and b is not None and not a < b:
        raise ValueError(f"no key between {a!r} and {b!r}")
    return _midpoint(a or "", b)


def spread(count: int) -> list[str]:
    """`count` increasing keys of one width, evenly apart."""
    space = len(DIGITS) ** SPREAD_WIDTH
    keys = []
    for i in range(1, count + 1):
        value = i * space // (count + 1)
        digits = []
        for _ in range(SPREAD_WIDTH):
            value, digit = divmod(value, len(DIGITS))
            digits.append(DIGITS[digit])
        keys.append("".join(reversed(digits)).rstrip("0") or "1")
    return keys


CLOSED = ("done", "cancelled")


def column_key(card: Any) -> tuple[Any, ...]:
    """The order within one open status: ranked by rank, then the rest by creation."""
    if card.rank is not None:  # equal ranks (two columns' first keys met) by creation
        return (0, card.rank, card.created_at.isoformat(), card.id)
    return (1, "", card.created_at.isoformat(), card.id)


def board_key(statuses: Sequence[str], card: Any) -> tuple[Any, ...]:
    """The board's order: status column, then the card order of that column; closed
    cards by `closed_at`, newest first."""
    position = statuses.index(card.status) if card.status in statuses else len(statuses)
    if card.status in CLOSED:
        closed = card.closed_at.timestamp() if card.closed_at is not None else 0.0
        return (position, -closed, card.id)
    return (position, *column_key(card))


def place(column: list[Any], card_id: str, index: int) -> dict[str, str]:
    """New ranks after moving `card_id` to `index` of `column` (in card order, the card
    included): the ranks that change, by card id.

    Only the moved card and the unranked cards before it take a rank: ranked cards come
    before unranked ones, so nothing after the moved card needs one. Every other rank
    stays. Each run of cards to rank gets keys between its ranked neighbours. When the
    column's ranks are not strictly increasing (each empty column starts at the same key,
    and a rank travels with a status change) or a key would grow too long, the ranked part
    of the column is spread out instead."""
    order = [c for c in column if c.id != card_id]
    moved = next(c for c in column if c.id == card_id)
    order.insert(index, moved)
    kept = {i: c.rank for i, c in enumerate(order) if c.id != card_id and c.rank is not None}
    in_order = [kept[i] for i in sorted(kept)]
    changed = _between_neighbours(order, kept, index) if _increasing(in_order) else None
    if changed is None or any(len(k) > LONGEST for k in changed.values()):
        ranked = index + 1 + sum(1 for j in kept if j > index)
        keys = spread(ranked)
        changed = {c.id: k for c, k in zip(order[:ranked], keys, strict=True)}
    before = {c.id: c.rank for c in order}
    return {cid: k for cid, k in changed.items() if before[cid] != k}


def _increasing(keys: list[str]) -> bool:
    return all(a < b for a, b in pairwise(keys))


def _between_neighbours(order: list[Any], kept: dict[int, str], index: int) -> dict[str, str]:
    changed: dict[str, str] = {}
    previous: str | None = None
    for i in range(index + 1):
        if i in kept:
            previous = kept[i]
            continue
        upper = next((kept[j] for j in range(i + 1, len(order)) if j in kept), None)
        previous = between(previous, upper)
        changed[order[i].id] = previous
    return changed
