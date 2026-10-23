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


def key_cursor(anchor: str, key: Sequence[Any], bound: str) -> str:
    """A cursor for a list in an order the database does not keep (§6.4's card order):
    the last item's id and its sort key, so the next page goes on after it."""
    return _encode(["key", anchor, list(key), bound])


def unkey(text: str, bound: str) -> tuple[str, tuple[Any, ...]]:
    try:
        tag, anchor, key, given = _decode(text)
        if tag != "key" or given != bound or not isinstance(key, list):
            raise ValueError
        return str(anchor), tuple(key)
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None
