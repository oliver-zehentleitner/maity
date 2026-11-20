"""Database-independent substring matching for cards (docs/api.md §6.4)."""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t

# A card's own text, read a batch of cards at a time; never the whole row (§6.4).
TEXT = (t.card.c.id, t.card.c.title, t.card.c.body, t.card.c.report)


def fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def _fields(card: Any, needle: str) -> list[str]:
    """The matching fields of the card itself, in contract order, `note` left out."""
    found = [name for name in ("id", "title", "body") if needle in fold(getattr(card, name) or "")]
    if needle in fold((card.report or {}).get("summary") or ""):
        found.append("report")
    return found


def _with_note(fields: list[str], note: bool) -> list[str]:
    if not note:
        return list(fields)
    # `note` comes before `report`, after the card's own fields.
    own = [name for name in fields if name != "report"]
    return own + ["note"] + [name for name in fields if name == "report"]


def matches(card: Any, query: str, notes: Sequence[str] = ()) -> list[str]:
    """The matching fields, in contract order; only the current report is searched."""
    needle = fold(query)
    return _with_note(_fields(card, needle), any(needle in fold(body) for body in notes))


class Search:
    """`q` over the cards of one list, a batch at a time (§6.4). A card's own text is read
    only for the cards a page reaches, and its notes only while nothing else of it matched,
    or when it is shown and its `match` must name them; nothing reads every card's text or
    every note at once. `visible`: SQL on `card_note` for the notes the reader may list,
    those outside its hidden windows (`events.outside_window_times`, §6.2)."""

    def __init__(self, conn: Connection, query: str, visible: Any = None) -> None:
        self.conn = conn
        self.needle = fold(query)
        self.visible = visible
        self._fields: dict[str, list[str]] = {}
        self._note: dict[str, bool] = {}

    def keep(self, card_ids: Sequence[str]) -> set[str]:
        """Of `card_ids` the cards that match."""
        unread = [card_id for card_id in card_ids if card_id not in self._fields]
        if unread:
            for row in self.conn.execute(select(*TEXT).where(t.card.c.id.in_(unread))):
                self._fields[row.id] = _fields(row, self.needle)
            for card_id in unread:  # a card gone since its key was read matches nothing
                self._fields.setdefault(card_id, [])
        self._notes([card_id for card_id in card_ids if not self._fields[card_id]])
        return {c for c in card_ids if self._fields[c] or self._note.get(c, False)}

    def places(self, card_ids: Sequence[str]) -> dict[str, list[str]]:
        """`match` of each of `card_ids`, cards `keep` let through."""
        self._notes(card_ids)
        return {c: _with_note(self._fields[c], self._note[c]) for c in card_ids}

    def _notes(self, card_ids: Sequence[str]) -> None:
        """Whether a note of each card matches: its notes in every state, a redacted one
        left out (§6.4), one query for the batch, read row by row."""
        wanted = list(dict.fromkeys(c for c in card_ids if c not in self._note))
        if not wanted:
            return
        for card_id in wanted:
            self._note[card_id] = False
        query = select(t.card_note.c.card_id, t.card_note.c.body).where(
            t.card_note.c.card_id.in_(wanted), t.card_note.c.redacted.is_(False)
        )
        if self.visible is not None:
            query = query.where(self.visible)
        for card_id, body in self.conn.execute(query):
            if not self._note[card_id] and self.needle in fold(body or ""):
                self._note[card_id] = True
