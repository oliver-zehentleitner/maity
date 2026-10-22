"""Runners as their owners and the dashboard see them (docs/api.md §15.2, §15.3).

A runner is a caller of its own, owned by a human; its presence is computed
like a member's (§5.3) from its last call and its open long-poll, never
stored. The routes are in `routes/runners.py`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from maity_hub import clock, listening
from maity_hub import tables as t
from maity_hub.views import AWAY, ONLINE, ts


def listening_key(runner_id: str) -> str:
    """The runner's long-poll registers under this key (§15.8)."""
    return f"runner:{runner_id}"


def presence(row: Any, is_listening: bool) -> str:
    if is_listening:
        return "online"
    if row.last_seen_at is None:
        return "offline"
    age = clock.now() - row.last_seen_at
    if age <= ONLINE:
        return "online"
    if age <= AWAY:
        return "away"
    return "offline"


def latest_credential(conn: Connection, runner_id: str) -> Any:
    return conn.execute(
        select(t.runner_credential)
        .where(t.runner_credential.c.runner_id == runner_id)
        .order_by(t.runner_credential.c.created_at.desc(), t.runner_credential.c.id.desc())
        .limit(1)
    ).first()


def live_credential_id(conn: Connection, runner_id: str) -> str | None:
    found: str | None = conn.execute(
        select(t.runner_credential.c.id).where(
            t.runner_credential.c.runner_id == runner_id,
            t.runner_credential.c.live.is_(True),
        )
    ).scalar()
    return found


def runner_view(conn: Connection, row: Any, viewer_id: str) -> dict[str, Any]:
    credential = latest_credential(conn, row.id)
    if credential is None:
        state = "none"
    elif credential.revoked_at is None:
        state = "active"
    else:
        state = "revoked"
    is_listening = listening.is_listening(listening_key(row.id))
    view: dict[str, Any] = {
        "id": row.id,
        "name": row.name,
        "owner_id": row.owner_id,
        "presence": presence(row, is_listening),
        "listening": is_listening,
        "last_seen_at": ts(row.last_seen_at),
        "credential_state": state,
        "version": row.version,
        "capabilities": row.capabilities,
        # The projects it is attached to; attachments come with §15.4.
        "projects": [],
        "created_at": ts(row.created_at),
        "updated_at": ts(row.updated_at),
        "removed_at": ts(row.removed_at),
    }
    if viewer_id == row.owner_id:  # the record, never the value; the owner's only
        view["credential"] = (
            None
            if credential is None
            else {
                "id": credential.id,
                "created_at": ts(credential.created_at),
                "last_used_at": ts(credential.last_used_at),
                "revoked_at": ts(credential.revoked_at),
                "revoked_reason": credential.revoked_reason,
            }
        )
    return view


def load_runner(conn: Connection, runner_id: str, viewer_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.runner).where(t.runner.c.id == runner_id)).one()
    return runner_view(conn, row, viewer_id)


def enrollment_view(row: Any) -> dict[str, Any]:
    """Nothing that opens it: no URL, no token, no code (§15.2)."""
    return {
        "id": row.id,
        "runner_id": row.runner_id,
        "name": row.name,
        "attach": row.attach,
        "created_at": ts(row.created_at),
        "expires_at": ts(row.expires_at),
        "used_at": ts(row.used_at),
        "burned": row.burned_at is not None,
        "revoked_at": ts(row.revoked_at),
    }
