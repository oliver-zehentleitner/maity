"""Opaque page cursors (docs/api.md §1.4): for lists ordered newest first by (timestamp,
id), and for lists sorted in Python by a key. A cursor is valid for one ordering and one
filter set: `scope` fingerprints them and the cursor carries it."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from maity_hub import cards
from maity_hub.errors import invalid
from maity_hub.tables import ID

SEQ_MAX = 2**63 - 1  # BIGINT


def scope(**filters: Any) -> str:
    """A short fingerprint of a list's filters and order: a cursor is valid for one."""
    raw = json.dumps(filters, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _encode(value: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


def _decode(text: str) -> Any:
    return json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))


def cursor(at: datetime, row_id: str, bound: str | None = None) -> str:
    """After (`at`, `row_id`); `bound` ties it to a `scope`."""
    return _encode([at.isoformat(), row_id] + ([bound] if bound is not None else []))


def uncursor(text: str, bound: str | None = None) -> tuple[datetime, str]:
    try:
        iso, row_id, *rest = _decode(text)
        if rest != ([bound] if bound is not None else []):
            raise ValueError
        # Most callers bind the id; some carry more than an id in it (a band, a project's
        # name, a handle), so its length is theirs to judge, not the id column's.
        if not _bindable(str(row_id)):
            raise ValueError
        return datetime.fromisoformat(iso), str(row_id)
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None


def after_cursor(key: str, bound: str) -> str:
    """After the item whose sort key is `key`, for a list ordered by a unique text key (a
    handle, §3.1's outsiders)."""
    return _encode(["after", key, bound])


def unafter(text: str, bound: str) -> str:
    try:
        tag, key, given = _decode(text)
        if tag != "after" or given != bound or not isinstance(key, str):
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None


def key_cursor(
    anchor: tuple[str, Sequence[Any]],
    following: tuple[str, Sequence[Any]],
    shown: Sequence[str],
    bound: str,
) -> str:
    """A cursor for a list in an order the database does not keep (§6.4's card order):
    the last item shown and the first one not shown, each with its sort key, and the ids
    the page showed in the last item's column, so the next page can go on after the one,
    from the other, or from the column's top without what it showed."""
    return _encode(
        [
            "key",
            [anchor[0], list(anchor[1])],
            [following[0], list(following[1])],
            list(shown),
            bound,
        ]
    )


def unkey(
    text: str, bound: str
) -> tuple[tuple[str, tuple[Any, ...]], tuple[str, tuple[Any, ...]], frozenset[str]]:
    try:
        tag, (anchor, was), (following, next_was), shown, given = _decode(text)
        if tag != "key" or given != bound or not isinstance(was, list):
            raise ValueError
        if not isinstance(next_was, list) or not isinstance(shown, list):
            raise ValueError
        return (
            (str(anchor), tuple(was)),
            (str(following), tuple(next_was)),
            frozenset(str(i) for i in shown),
        )
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None


def closed_cursor(position: int, closed_at: datetime | None, row_id: str, bound: str) -> str:
    """A cursor after a closed card in §6.4's card order: its column's position, its
    `closed_at` and its id. A closed card's place in its column follows from these alone
    and no move changes it, so, unlike `key_cursor`, it needs no list of the ids shown and
    keeps one size however long the column is (tsk-d4anfsk1e94j)."""
    at = closed_at.isoformat() if closed_at is not None else None
    return _encode(["closed", position, at, row_id, bound])


def unclosed(text: str, bound: str) -> tuple[int, datetime | None, str]:
    try:
        tag, position, iso, row_id, given = _decode(text)
        if tag != "closed" or given != bound:
            raise ValueError
        if not isinstance(position, int) or isinstance(position, bool):
            raise ValueError
        if not 0 <= position < len(cards.STATUSES):  # a column of the board, not any int
            raise ValueError
        if iso is not None and not isinstance(iso, str):
            raise ValueError
        if not isinstance(row_id, str) or not _id_shaped(row_id):
            raise ValueError
        at = datetime.fromisoformat(iso) if iso is not None else None
        if at is not None and at.tzinfo is None:
            raise ValueError  # the hub stores UTC only: a naive time is no cursor it gave
        # In UTC here, as the column stores it: a zone that moves the time out of the
        # datetime range (year 1 at +14:00) is refused, not left to the query's binding.
        utc = at.astimezone(UTC) if at is not None else None
        return position, utc, row_id
    except (ValueError, TypeError, OverflowError):
        raise invalid({"cursor": "invalid"}) from None


def _id_shaped(row_id: str) -> bool:
    """Whether `row_id` could be a card's id: no longer than the id column, no NUL
    (PostgreSQL refuses one in text), and encodable as UTF-8: JSON carries a lone
    surrogate (`"\\ud800"`), which a driver cannot encode to bind it. The hub's ids are not parsed
    (ids.py), so this is no pattern: such an id would only reach the database as an error."""
    return 0 < len(row_id) <= ID and _bindable(row_id)


def id_shaped(value: Any) -> bool:
    """`_id_shaped` for a value a route decodes from a cursor of its own shape."""
    return isinstance(value, str) and _id_shaped(value)


def bindable(value: Any) -> bool:
    """`_bindable` for a value a route decodes from a cursor of its own shape."""
    return isinstance(value, str) and _bindable(value)


def _bindable(text: str) -> bool:
    """Whether `text` can be bound as a query's text on every database: no NUL and
    encodable as UTF-8 (`_id_shaped`). Otherwise the driver fails and the client gets a 500,
    not 400 `invalid` (tsk-tjjgzhepgpdp)."""
    if "\x00" in text:
        return False
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def tag_of(text: str) -> str | None:
    """The kind a tagged cursor names (`key`, `closed`, `seq`), or None for any other text;
    the decode that follows still checks the whole cursor."""
    try:
        value = _decode(text)
    except (ValueError, TypeError):
        return None
    return value[0] if isinstance(value, list) and value and isinstance(value[0], str) else None


def seq_cursor(seq: int, bound: str) -> str:
    """After `seq` in the list's direction; `bound` ties it to a `scope`."""
    return _encode(["seq", seq, bound])


def unseq(text: str, bound: str) -> int:
    try:
        tag, seq, given = _decode(text)
        if tag != "seq" or given != bound or not isinstance(seq, int) or isinstance(seq, bool):
            raise ValueError
        if not 0 <= seq <= SEQ_MAX:
            raise ValueError
        return seq
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None
