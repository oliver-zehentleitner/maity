"""Database-independent substring matching for cards (docs/api.md §6.4)."""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t


def fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def note_bodies(conn: Connection, card_ids: Iterable[str]) -> dict[str, list[str]]:
    """Per card the bodies of its notes in every state, a redacted one left out (§6.4);
    one query for a batch of cards."""
    wanted = list(dict.fromkeys(card_ids))
    found: dict[str, list[str]] = {card_id: [] for card_id in wanted}
    if not wanted:
        return found
    for card_id, body in conn.execute(
        select(t.card_note.c.card_id, t.card_note.c.body).where(
            t.card_note.c.card_id.in_(wanted), t.card_note.c.redacted.is_(False)
        )
    ):
        found[card_id].append(body or "")
    return found


def matches(card: Any, query: str, notes: Sequence[str] = ()) -> list[str]:
    """The matching fields, in contract order; only the current report is searched."""
    needle = fold(query)
    found = [name for name in ("id", "title", "body") if needle in fold(getattr(card, name) or "")]
    if any(needle in fold(body) for body in notes):
        found.append("note")
    if needle in fold((card.report or {}).get("summary") or ""):
        found.append("report")
    return found
