"""Database-independent substring matching for cards (docs/api.md §6.4)."""

from __future__ import annotations

import unicodedata
from typing import Any


def fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def matches(card: Any, query: str) -> list[str]:
    """The matching fields, in contract order; only the current report is searched."""
    needle = fold(query)
    found = [name for name in ("id", "title", "body") if needle in fold(getattr(card, name) or "")]
    if needle in fold((card.report or {}).get("summary") or ""):
        found.append("report")
    return found
