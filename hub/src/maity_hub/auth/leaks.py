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
from maity_hub.auth.caller import is_runner_credential
from maity_hub.events import emit
from maity_hub.runners import attached_project_ids, human_actor

REASON = "leaked_in_payload"


# A body full of credential-shaped strings is refused all the same; only this
# many distinct ids are looked up, in one query, so it cannot cost thousands.
MAX_IDS = 16


def revoke_leaked(conn: Connection, found: list[credentials.Presented]) -> list[str]:
    """Revoke every verified credential in `found`; returns their ids."""
    secrets_by_id: dict[str, set[str]] = {}
    for presented in found:
        if presented.credential_id in secrets_by_id or len(secrets_by_id) < MAX_IDS:
            secrets_by_id.setdefault(presented.credential_id, set()).add(presented.secret)
    if not secrets_by_id:
        return []
    runner_ids = sorted(i for i in secrets_by_id if is_runner_credential(i))
    revoked = _revoke_leaked_runners(conn, runner_ids, secrets_by_id)
    rows = conn.execute(
        select(
            t.credential.c.id,
            t.credential.c.verifier,
            t.credential.c.revoked_at,
            t.membership.c.project_id,
            t.membership.c.agent_id,
            t.agent_profile.c.owner_id,
        )
        .join(t.membership, t.membership.c.id == t.credential.c.membership_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.credential.c.id.in_(sorted(set(secrets_by_id) - set(runner_ids))))
    ).all()
    for row in rows:
        if row.revoked_at is not None:
            continue
        if not any(
            credentials.secret_matches(secret, row.verifier) for secret in secrets_by_id[row.id]
        ):
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


def _revoke_leaked_runners(
    conn: Connection, ids: list[str], secrets_by_id: dict[str, set[str]]
) -> list[str]:
    """A runner credential is revoked like an agent's (§15.1)."""
    if not ids:
        return []
    rows = conn.execute(
        select(
            t.runner_credential.c.id,
            t.runner_credential.c.verifier,
            t.runner_credential.c.revoked_at,
        ).where(t.runner_credential.c.id.in_(ids))
    ).all()
    revoked = []
    for row in rows:
        if row.revoked_at is not None:
            continue
        if not any(
            credentials.secret_matches(secret, row.verifier) for secret in secrets_by_id[row.id]
        ):
            continue
        revoke_runner_credential(conn, row.id, REASON, by=None)
        revoked.append(row.id)
    return revoked


def revoke_runner_credential(
    conn: Connection, credential_id: str, reason: str | None, by: str | None
) -> bool:
    """Revoke a runner credential and end its live session; False when it was revoked
    already. Every project the runner is attached to learns it from its own
    `runner_credential_revoked` (§15.10); the runner's long-poll ends on its next pass."""
    now = clock.now()
    revoked = conn.execute(
        update(t.runner_credential)
        .where(
            t.runner_credential.c.id == credential_id,
            t.runner_credential.c.revoked_at.is_(None),
        )
        .values(revoked_at=now, revoked_by=by, revoked_reason=reason, live=None)
    ).rowcount
    if revoked != 1:
        return False
    conn.execute(
        update(t.runner_session)
        .where(
            t.runner_session.c.credential_id == credential_id,
            t.runner_session.c.live.is_(True),
        )
        .values(live=None, ended_at=now)
    )
    runner_id = conn.execute(
        select(t.runner_credential.c.runner_id).where(t.runner_credential.c.id == credential_id)
    ).scalar_one()
    for project_id in attached_project_ids(conn, runner_id):
        emit(
            conn,
            project_id,
            "runner_credential_revoked",
            ["role:owner"],
            {"runner_id": runner_id, "credential_id": credential_id, "reason": reason},
            actor=human_actor(conn, project_id, by),
            subject=("runner", runner_id),
        )
    return True
