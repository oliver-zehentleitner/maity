"""A credential found in a request payload (docs/api.md §2.2).

Every match is refused. A match that is a real credential — the id exists
and the secret verifies — is revoked at once, its live session ends, and
the owner and the admins learn it from two events that never carry the
value. A string that merely looks like a credential changes nothing, so
nobody revokes a credential with its public id and a guessed secret.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection, select

from maity_hub import tables as t
from maity_hub.auth import credentials, verifiers
from maity_hub.auth.caller import is_runner_credential
from maity_hub.auth.revocation import revoke, revoke_runner_credential
from maity_hub.events import emit

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
        if not _verifies("credential", row, secrets_by_id[row.id]):
            continue
        revoke(conn, row.id, REASON, by=None)
        payload = {"credential_id": row.id, "reason": REASON}
        subject = ("credential", row.id)
        emit(
            conn,
            row.project_id,
            "credential_revoked",
            [f"member:{row.agent_id}", "trust:owner"],
            payload,
            subject=subject,
        )
        emit(
            conn,
            row.project_id,
            "credential_in_payload",
            [f"member:{row.owner_id}", "trust:owner", "trust:admin"],
            {"credential_id": row.id},
            subject=subject,
        )
        revoked.append(row.id)
    return revoked


def _verifies(table: verifiers.Table, row: Any, secrets: set[str]) -> bool:
    verifier = verifiers.usable(table, row.id, row.verifier)
    return verifier is not None and any(
        credentials.secret_matches(secret, verifier) for secret in secrets
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
        if not _verifies("runner_credential", row, secrets_by_id[row.id]):
            continue
        revoke_runner_credential(conn, row.id, REASON, by=None)
        revoked.append(row.id)
    return revoked
