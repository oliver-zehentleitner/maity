"""A human's own forge token (docs/api.md §11.4), the second source after the App.

Only a fine-grained token is taken: a classic token reaches a private repository only
with the `repo` scope, which can write, and without it reads no more than the instance
token already does. The forge does not report a fine-grained token's permissions, so
the hub cannot check them; it never writes, whatever the token could do. The token is
checked with the forge (`GET /user`), sealed with `MAITY_SECRET_KEY` and never shown
again: not in an answer, not in an event, not in the log.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import clock, forge, github_app, secretbox
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid

FORGE = "github"
FINE_GRAINED = "github_pat_"


def _field(human_id: str) -> str:
    return f"forge_token:{human_id}"


def login_of(token: str) -> str:
    """The forge account the token belongs to. `invalid` for a token that is not
    fine-grained or that the forge refuses; `ForgeUnavailableError` when it does not
    answer. Makes a forge read: no connection is held."""
    if not token.startswith(FINE_GRAINED):
        raise invalid({"token": "classic_token"}, "only a fine-grained token is taken")
    try:
        user = github_app._call("/user", f"Bearer {token}")
    except forge.ForgeUnavailableError as error:
        if error.status in (401, 403) and not error.rate_limited:
            raise invalid({"token": "rejected"}, "the forge refused the token") from None
        raise
    if not isinstance(user, dict) or not isinstance(user.get("login"), str):
        raise invalid({"token": "rejected"}, "the forge refused the token")
    login: str = user["login"]
    return login


def store(conn: Connection, key: bytes, human_id: str, token: str, login: str) -> None:
    now = clock.now()
    columns = {
        "forge": FORGE,
        "login": login,
        "token_sealed": secretbox.seal(key, _field(human_id), token.encode()),
        "status": "active",
        "set_at": now,
        "checked_at": now,
    }
    exists = conn.execute(
        select(t.forge_token.c.human_id).where(t.forge_token.c.human_id == human_id)
    ).first()
    if exists:
        conn.execute(
            update(t.forge_token).where(t.forge_token.c.human_id == human_id).values(columns)
        )
    else:
        conn.execute(insert(t.forge_token).values(human_id=human_id, **columns))


def remove(conn: Connection, human_id: str) -> bool:
    removed = conn.execute(delete(t.forge_token).where(t.forge_token.c.human_id == human_id))
    return bool(removed.rowcount)


def view(conn: Connection, human_id: str) -> dict[str, Any]:
    """`{configured, login, status, checked_at}`; never the token."""
    row = conn.execute(select(t.forge_token).where(t.forge_token.c.human_id == human_id)).first()
    if row is None:
        return {"configured": False, "login": None, "status": None, "checked_at": None}
    return {
        "configured": True,
        "login": row.login,
        "status": row.status,
        "checked_at": clock.rfc3339(row.checked_at),
    }


def require_key(key: bytes | None) -> bytes:
    if key is None:
        raise ApiError(409, "secret_key_missing", "the instance has no MAITY_SECRET_KEY")
    return key
