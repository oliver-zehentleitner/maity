"""A credential found in a request payload (docs/api.md §2.2).

Every match is refused. A match that is a real credential — the id exists
and the secret verifies — is revoked at once, its live session ends, and
the owner and the admins learn it from two events that never carry the
value. A string that merely looks like a credential changes nothing, so
nobody revokes a credential with its public id and a guessed secret.
"""

from __future__ import annotations

from sqlalchemy import Connection, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import credentials
from maity_hub.events import emit

REASON = "leaked_in_payload"


def revoke_leaked(conn: Connection, found: list[credentials.Presented]) -> list[str]:
    """Revoke every verified credential in `found`; returns their ids."""
    revoked = []
    for presented in found:
        row = conn.execute(
            select(
                t.credential.c.id,
                t.credential.c.verifier,
                t.credential.c.revoked_at,
                t.membership.c.id.label("membership_id"),
                t.membership.c.project_id,
                t.membership.c.agent_id,
                t.agent_profile.c.owner_id,
            )
            .join(t.membership, t.membership.c.id == t.credential.c.membership_id)
            .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
            .where(t.credential.c.id == presented.credential_id)
        ).first()
        if row is None or row.revoked_at is not None:
            continue
        if not credentials.secret_matches(presented.secret, row.verifier):
            continue
        revoke(conn, row.id, REASON, by=None)
        payload = {"credential_id": row.id, "reason": REASON}
        subject = ("credential", row.id)
        emit(
            conn,
            row.project_id,
            "credential_revoked",
            [f"member:{row.agent_id}", "role:owner"],
            payload,
            subject=subject,
        )
        emit(
            conn,
            row.project_id,
            "credential_in_payload",
            [f"member:{row.owner_id}", "role:owner", "role:admin"],
            {"credential_id": row.id},
            subject=subject,
        )
        revoked.append(row.id)
    return revoked


def revoke(conn: Connection, credential_id: str, reason: str, by: str | None) -> None:
    """Revoke a credential and end its live session."""
    now = clock.now()
    conn.execute(
        update(t.credential)
        .where(t.credential.c.id == credential_id, t.credential.c.revoked_at.is_(None))
        .values(revoked_at=now, revoked_by=by, revoked_reason=reason)
    )
    conn.execute(
        update(t.agent_session)
        .where(t.agent_session.c.credential_id == credential_id, t.agent_session.c.live.is_(True))
        .values(live=None, ended_at=now)
    )
