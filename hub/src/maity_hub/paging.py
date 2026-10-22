"""Opaque page cursors for lists ordered newest first by (timestamp, id) (docs/api.md §1.4)."""

from __future__ import annotations

import base64
import json
from datetime import datetime

from maity_hub.errors import invalid


def cursor(at: datetime, row_id: str) -> str:
    raw = json.dumps([at.isoformat(), row_id])
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def uncursor(text: str) -> tuple[datetime, str]:
    try:
        iso, row_id = json.loads(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
        return datetime.fromisoformat(iso), str(row_id)
    except (ValueError, TypeError):
        raise invalid({"cursor": "invalid"}) from None
