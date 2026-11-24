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

from maity_hub import ids, placements
from maity_hub import runners as runner_rows
from maity_hub import tables as t
from maity_hub.auth import credentials, verifiers
from maity_hub.auth.caller import is_runner_credential
from maity_hub.auth.revocation import projects_of, revoke, revoke_runner_credential
from maity_hub.events import emit, lock_projects

REASON = "leaked_in_payload"


# A body full of credential-shaped strings is refused all the same; only this
# many distinct ids are looked up, in one query, so it cannot cost thousands.
MAX_IDS = 16


def lookups(found: list[credentials.Presented]) -> list[credentials.Presented]:
    """Those of `found` whose id the hub could have made for an agent's or a runner's
    credential (`ids.has_shape`): only they can be a real credential, so only they are worth a
    database lookup. The forge path (`routes/board._refuse_credentials`) opens no transaction
    when none is left and refuses the request all the same; the middleware still opens one
    (`middleware._revoke`, a follow-up of tsk-a4n80ebqyaya)."""
    return [
        presented
        for presented in found
        if ids.has_shape("credential", presented.credential_id)
        or ids.has_shape("runner_credential", presented.credential_id)
    ]


def revoke_leaked(conn: Connection, found: list[credentials.Presented]) -> list[str]:
    """Revoke every verified credential in `found`; returns their ids. An id the hub could not
    have made is never looked up (`lookups`), and takes none of the `MAX_IDS` places."""
    secrets_by_id: dict[str, set[str]] = {}
    for presented in lookups(found):
        if presented.credential_id in secrets_by_id or len(secrets_by_id) < MAX_IDS:
            secrets_by_id.setdefault(presented.credential_id, set()).add(presented.secret)
    if not secrets_by_id:
        return []
    runner_ids = sorted(i for i in secrets_by_id if is_runner_credential(i))
    runners = _leaked_runners(conn, runner_ids, secrets_by_id)
    if runners:
        # The runners' credential and runner rows first, in the order every runner call and
        # the owner's revoke take them (`runners.lock`), and only then their projects: a leak
        # that locked the projects first would wait for an owner's revoke of the same runner
        # that holds its rows and waits for those projects. Holding the runner's row also
        # keeps an attach out until this commits (`routes/runners`), so the projects read
        # below stay its projects. Read again under the lock: a revocation that committed
        # meanwhile already did the work.
        runner_rows.lock(conn, t.runner.c.id.in_(sorted({r.runner_id for r in runners})))
        runners = _still_live(conn, runners)
    rows = conn.execute(
        select(
            t.credential.c.id,
            t.credential.c.verifier,
            t.credential.c.revoked_at,
            t.membership.c.project_id,
            t.membership.c.agent_id,
            t.agent_profile.c.owner_id,
            t.instance_attachment.c.detached_at,
        )
        .select_from(t.credential)
        .join(t.instance_attachment, t.instance_attachment.c.credential_id == t.credential.c.id)
        .join(t.membership, t.membership.c.id == t.instance_attachment.c.membership_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.credential.c.id.in_(sorted(set(secrets_by_id) - set(runner_ids))))
        .order_by(t.credential.c.id, t.instance_attachment.c.id)
    ).all()
    verified = {
        row.id
        for row in rows
        if row.revoked_at is None and _verifies("credential", row, secrets_by_id[row.id])
    }
    # Every project any of these revocations writes in, locked in the order of their ids
    # after the runners' rows and before the first write, so two leaks over overlapping
    # projects cannot deadlock. A
    # runner's are those it is attached to and those of its active placements: one still
    # closing after the runner's detach closes now, in its own project
    # (`placements.runner_credential_gone`).
    affected = projects_of(conn, verified)
    for runner in runners:
        affected.update(placements.reading_projects(conn, runner.runner_id))
    lock_projects(conn, affected)
    revoked: list[str] = []
    for runner in runners:
        revoke_runner_credential(conn, runner.id, REASON, by=None)
        revoked.append(runner.id)
    # One row per project the instance was ever attached to: revoked once whatever its
    # attachments, told in each project it is in now. A project it was detached from hears
    # nothing (§6.17).
    for row in rows:
        if row.id not in verified:
            continue
        if row.id not in revoked:
            revoke(conn, row.id, REASON, by=None)
            revoked.append(row.id)
        if row.detached_at is not None:
            continue
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
    return revoked


def _verifies(table: verifiers.Table, row: Any, secrets: set[str]) -> bool:
    verifier = verifiers.usable(table, row.id, row.verifier)
    return verifier is not None and any(
        credentials.secret_matches(secret, verifier) for secret in secrets
    )


def _still_live(conn: Connection, runners: list[Any]) -> list[Any]:
    """Those of `runners` whose credential is still unrevoked, read under their lock."""
    live = set(
        conn.execute(
            select(t.runner_credential.c.id).where(
                t.runner_credential.c.id.in_([r.id for r in runners]),
                t.runner_credential.c.revoked_at.is_(None),
            )
        ).scalars()
    )
    return [r for r in runners if r.id in live]


def _leaked_runners(
    conn: Connection, ids: list[str], secrets_by_id: dict[str, set[str]]
) -> list[Any]:
    """The runner credentials among `ids` that are live and verify, in the order of their
    ids: each is revoked like an agent's (§15.1)."""
    if not ids:
        return []
    rows = conn.execute(
        select(
            t.runner_credential.c.id,
            t.runner_credential.c.runner_id,
            t.runner_credential.c.verifier,
            t.runner_credential.c.revoked_at,
        )
        .where(t.runner_credential.c.id.in_(ids))
        .order_by(t.runner_credential.c.id)
    ).all()
    return [
        row
        for row in rows
        if row.revoked_at is None and _verifies("runner_credential", row, secrets_by_id[row.id])
    ]
