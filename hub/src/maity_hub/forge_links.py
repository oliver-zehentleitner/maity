"""A human's links to installations of the instance's GitHub App (docs/api.md §11.4).

A human links an installation to their account, not to a project. The link starts
with a `state` the hub hands to the forge: random, kept as its hash only, bound to the
session that started it, valid 15 minutes and used once. The forge sends the browser
back with the installation and an OAuth code. The hub exchanges the code for the user,
reads the installation with the App's key, and links it only when its account is that
user. Listing the installations a user can reach is not enough: a member of an
organisation with access to one repository would pass it.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import clock, forge, github_app
from maity_hub import tables as t
from maity_hub.github_app import GitHubApp
from maity_hub.ids import new_id
from maity_hub.notifications import records

FORGE = "github"
STATE_TTL = timedelta(minutes=15)
REPOSITORIES_SHOWN = 100


class LinkError(Exception):
    """A link that fails its checks: `reason` is `link_state`, `installation_not_yours`,
    `organisation_installation` or `installation_linked` (§11.4)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def start(conn: Connection, app: GitHubApp, human_id: str, session_hash: str) -> str:
    """A new `state` for this human and session; the installation page's URL with it."""
    now = clock.now()
    conn.execute(
        delete(t.forge_link_state).where(
            t.forge_link_state.c.human_id == human_id, t.forge_link_state.c.expires_at <= now
        )
    )
    state = secrets.token_urlsafe(32)
    conn.execute(
        insert(t.forge_link_state).values(
            state_hash=_hash(state),
            human_id=human_id,
            session_hash=session_hash,
            expires_at=now + STATE_TTL,
        )
    )
    return app.install_url(state)


def take_state(conn: Connection, state: str, human_id: str, session_hash: str) -> None:
    """Use the `state` once: it must be this human's, from this session, not expired.
    `LinkError("link_state")` otherwise; a state of another human or session stays."""
    row = conn.execute(
        select(t.forge_link_state)
        .where(t.forge_link_state.c.state_hash == _hash(state))
        .with_for_update()
    ).first()
    if row is None or row.human_id != human_id or row.session_hash != session_hash:
        raise LinkError("link_state")
    conn.execute(
        delete(t.forge_link_state).where(t.forge_link_state.c.state_hash == row.state_hash)
    )
    if row.expires_at <= clock.now():
        raise LinkError("link_state")


def verify(app: GitHubApp, installation_id: int, code: str) -> dict[str, Any]:
    """The installation, read with the App's key, when its account is the user the code
    belongs to; `LinkError` otherwise. Makes forge reads: no connection is held."""
    user = app.user_of_code(code)
    found = app.installation(installation_id)
    if found is None:
        raise LinkError("installation_not_yours")
    account = found["account"]
    if account["type"] != "User":
        raise LinkError("organisation_installation")
    if account["id"] != user["id"]:
        raise LinkError("installation_not_yours")
    return found


def link(conn: Connection, human_id: str, found: dict[str, Any]) -> str:
    """Store the verified installation as this human's link; the link's id. One human at a
    time: an installation linked to another human is `LinkError("installation_linked")`."""
    now = clock.now()
    existing = conn.execute(
        select(t.forge_link)
        .where(t.forge_link.c.forge == FORGE, t.forge_link.c.installation_id == found["id"])
        .with_for_update()
    ).first()
    columns = {
        "account_id": found["account"]["id"],
        "account_login": found["account"]["login"] or "",
        "account_type": found["account"]["type"],
        "repository_selection": found.get("repository_selection") or "selected",
        "status": "suspended" if found.get("suspended") else "active",
        "checked_at": now,
    }
    if existing is not None:
        if existing.human_id != human_id:
            raise LinkError("installation_linked")
        conn.execute(update(t.forge_link).where(t.forge_link.c.id == existing.id).values(columns))
        records.forge_access_changed(conn, human_id, "app", "linked", columns["account_login"])
        link_id: str = existing.id
        return link_id
    link_id = new_id("forge_link")
    conn.execute(
        insert(t.forge_link).values(
            id=link_id,
            human_id=human_id,
            forge=FORGE,
            installation_id=found["id"],
            linked_at=now,
            **columns,
        )
    )
    records.forge_access_changed(conn, human_id, "app", "linked", columns["account_login"])
    return link_id


def unlink(conn: Connection, app: GitHubApp | None, human_id: str, link_id: str) -> bool:
    """Remove the human's own link; False when there is none of theirs with that id."""
    row = conn.execute(
        select(t.forge_link).where(
            t.forge_link.c.id == link_id, t.forge_link.c.human_id == human_id
        )
    ).first()
    if row is None:
        return False
    conn.execute(delete(t.forge_link).where(t.forge_link.c.id == link_id))
    records.forge_access_changed(conn, human_id, "app", "unlinked", row.account_login)
    if app is not None:
        github_app.forget_token(app, row.installation_id)
    return True


def row(conn: Connection, link_id: str) -> Any:
    return conn.execute(select(t.forge_link).where(t.forge_link.c.id == link_id)).one()


def rows(conn: Connection, human_id: str) -> list[Any]:
    return list(
        conn.execute(
            select(t.forge_link)
            .where(t.forge_link.c.human_id == human_id)
            .order_by(t.forge_link.c.linked_at, t.forge_link.c.id)
        )
    )


def shown(app: GitHubApp | None, row: Any) -> tuple[list[str], str | None]:
    """The repositories the installation covers, read with its token when the list is
    asked for, and the status a refused mint found (`suspended`, `removed`), if any.
    Makes forge reads: no connection is held."""
    if app is None or row.status == "removed":
        return [], None
    try:
        return app.repositories(row.installation_id, REPOSITORIES_SHOWN), None
    except github_app.InstallationGoneError as gone:
        return [], gone.state
    except forge.ForgeUnavailableError:
        return [], None


def set_status(conn: Connection, link_id: str, status: str) -> None:
    """The status a mint found; a link that becomes `suspended` or `removed` writes the
    human's account record (§11.4)."""
    row = conn.execute(
        select(t.forge_link).where(t.forge_link.c.id == link_id).with_for_update()
    ).first()
    if row is None:
        return
    conn.execute(
        update(t.forge_link)
        .where(t.forge_link.c.id == link_id)
        .values(status=status, checked_at=clock.now())
    )
    if status != row.status and status in ("suspended", "removed"):
        records.forge_access_changed(conn, row.human_id, "app", status, row.account_login)


def view(row: Any, repositories: list[str], status: str) -> dict[str, Any]:
    return {
        "id": row.id,
        "forge": row.forge,
        "installation_id": row.installation_id,
        "account": {"login": row.account_login, "type": row.account_type},
        "repository_selection": row.repository_selection,
        "repositories_shown": repositories,
        "status": status,
        "linked_at": clock.rfc3339(row.linked_at),
        "checked_at": clock.rfc3339(row.checked_at),
    }
