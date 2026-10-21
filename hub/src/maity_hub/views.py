"""Rows as the API shows them."""

from __future__ import annotations

from typing import Any


def human_member(row: Any) -> dict[str, Any]:
    return {"id": row.id, "kind": "human", "handle": row.handle, "display_name": row.display_name}


def agent_member(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": "agent",
        "handle": row.handle,
        "display_name": row.display_name,
        "owner_id": row.owner_id,
    }
