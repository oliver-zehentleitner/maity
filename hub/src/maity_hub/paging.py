"""Opaque page cursors (docs/api.md §1.4): for lists ordered newest first by (timestamp,
id), and for lists sorted in Python by a key. A cursor is valid for one ordering and one
filter set: `scope` fingerprints them and the cursor carries it."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from maity_hub.errors import invalid

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
        return datetime.fromisoformat(iso), str(row_id)
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
