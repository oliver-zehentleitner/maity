"""Opaque page cursors for lists ordered newest first by (timestamp, id) (docs/api.md §1.4)."""

from __future__ import annotations

import base64
import json
from datetime import datetime

from maity_hub.errors import invalid


def cursor(at: datetime, row_id: str) -> str:
    raw = json.dumps([at.isoformat(), row_id])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def position_cursor(position: int) -> str:
    """A cursor for a list in an order the database does not keep (§6.4's card order):
    the position of the next item."""
    raw = json.dumps(["at", position])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def unposition(text: str) -> int:
    try:
        tag, position = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
        if tag != "at" or not isinstance(position, int) or position < 0:
            raise ValueError
        return position
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None


def uncursor(text: str) -> tuple[datetime, str]:
    try:
        iso, row_id = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
        return datetime.fromisoformat(iso), str(row_id)
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None
