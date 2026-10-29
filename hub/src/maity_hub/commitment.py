"""The Keep the Why commitment of an agent instance (docs/api.md §6.23).

Under `policy.keep_the_why: required` an instance confirms once that it uses Keep the Why.
The clock starts with its first resume while the policy is `required` and fixes
`acknowledge_by`; the same deadline stands on every later resume until it confirms.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, select, update

from maity_hub import clock, instances, namespace, policy
from maity_hub import tables as t
from maity_hub.events import emit, lock_project, transaction

log = logging.getLogger(__name__)
INTERVAL = 60.0  # seconds between the worker's sweeps

WINDOW = timedelta(minutes=30)  # from the first resume to the deadline
OWNER_AFTER = timedelta(minutes=30)  # from the deadline to the owner's request
ACK = "maity ack keep-the-why"


def required(project: Any) -> bool:
    """The hub checks the commitment: the provider is `keep-the-why` and the policy
    `required` (§6.23)."""
    return bool(project.keep_the_why) and policy.keep_the_why_effective(project) == "required"


def start(
    conn: Connection, project: Any, credential_id: str, session_id: str, now: datetime
) -> None:
    """The first resume of an instance under `required` fixes its deadline; a later one,
    and an instance that confirmed, change nothing."""
    if not required(project):
        return
    conn.execute(
        update(t.credential)
        .where(
            t.credential.c.id == credential_id,
            t.credential.c.ktw_acknowledged_at.is_(None),
            t.credential.c.ktw_acknowledge_by.is_(None),
        )
        .values(ktw_acknowledge_by=now + WINDOW, ktw_session_id=session_id)
    )


def packet(project: Any, credential: Any) -> dict[str, Any]:
    """The commitment part of the packet's `keep_the_why` block (§5.2); empty when the
    hub checks nothing."""
    if not required(project):
        return {}
    confirmed = credential.ktw_acknowledged_at
    return {
        "commitment": "required",
        "acknowledged_at": clock.rfc3339(confirmed) if confirmed else None,
        **(
            {"acknowledge_by": clock.rfc3339(credential.ktw_acknowledge_by)}
            if confirmed is None and credential.ktw_acknowledge_by is not None
            else {}
        ),
        "ack": ACK,
    }


def instance_fields(project: Any, credential: Any) -> dict[str, Any]:
    """`keep_the_why_acknowledged_at` and `keep_the_why_acknowledge_by` of an instance
    view; neither under `optional` (§6.23)."""
    if not required(project):
        return {}
    confirmed = credential.ktw_acknowledged_at
    due = credential.ktw_acknowledge_by
    return {
        "keep_the_why_acknowledged_at": clock.rfc3339(confirmed) if confirmed else None,
        "keep_the_why_acknowledge_by": clock.rfc3339(due) if confirmed is None and due else None,
    }


def unconfirmed(project: Any, instances: list[dict[str, Any]]) -> bool | None:
    """`keep_the_why_unconfirmed` of an agent's member view: whether any instance is past
    its deadline without a confirmation; `None` (not shown) under `optional`."""
    if not required(project):
        return None
    now = clock.rfc3339(clock.now())
    return any(
        i.get("keep_the_why_acknowledge_by") is not None and i["keep_the_why_acknowledge_by"] < now
        for i in instances
    )


def audience(conn: Connection, project_id: str, agent_id: str) -> list[str]:
    """`keep_the_why_acknowledged` (§8.2): the agent's owner when a member of the project,
    and the admins (`trust:admin`, §2.3)."""
    owner = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar()
    is_member = (
        owner is not None
        and conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.project_id == project_id,
                t.membership.c.human_id == owner,
                t.membership.c.active.is_(True),
            )
        ).first()
    )
    return ([f"member:{owner}"] if is_member else []) + ["trust:admin"]


def confirmed(conn: Connection, project: Any, credential: Any, agent_id: str) -> None:
    """What a confirmation ends: the owner's request, when one was filed, is withdrawn
    (§6.23)."""
    from maity_hub.routes.requests import withdraw_hub_notice

    withdraw_hub_notice(conn, credential.ktw_request_id, "the instance confirmed")


def _outstanding(conn: Connection, project_id: str, credential_id: str | None) -> list[Any]:
    """The project's active instances that have not confirmed and have a deadline,
    with what the hub needs to know about their member; one instance when named."""
    query = (
        select(
            t.credential,
            t.membership.c.id.label("member_row"),
            t.membership.c.agent_id.label("agent_id"),
            t.membership.c.active.label("membership_active"),
            t.membership.c.paused_since.label("member_paused"),
            t.agent_profile.c.owner_id.label("owner_id"),
            t.agent_profile.c.handle.label("handle"),
            t.agent_profile.c.deleted_at.label("profile_deleted"),
        )
        .join(t.membership, t.membership.c.id == t.credential.c.membership_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(
            t.membership.c.project_id == project_id,
            t.credential.c.ktw_acknowledged_at.is_(None),
            t.credential.c.ktw_acknowledge_by.isnot(None),
        )
    )
    if credential_id is not None:
        query = query.where(t.credential.c.id == credential_id)
    return list(conn.execute(query))


def _request_owner(conn: Connection, request_id: str) -> tuple[str | None, str | None]:
    row = conn.execute(
        select(t.request.c.status, t.request.c.to_human).where(t.request.c.id == request_id)
    ).first()
    return (None, None) if row is None else (row.status, row.to_human)


def reconcile(
    conn: Connection,
    project: Any,
    now: datetime | None = None,
    credential_id: str | None = None,
) -> None:
    """Bring the project's outstanding commitments in line with what the hub knows
    (§6.23): the reminder at the deadline, the owner's request 30 minutes later, and the
    withdrawal of that request when what it reports has ended. Called by the sweep, by a
    change of the policy or the provider, and by a resume for its own instance, so that a
    reminder missed while no session was open comes at the next resume (§6.23)."""
    from maity_hub.routes.requests import file_hub_notice, withdraw_hub_notice

    now = now or clock.now()
    on = required(project)
    for row in _outstanding(conn, project.id, credential_id):
        ended = (
            not on
            or row.revoked_at is not None
            or not row.membership_active
            or row.profile_deleted is not None
        )
        if ended:
            # Nothing is owed any more: withdraw an open request, and let a later
            # `required` start the clock afresh.
            withdraw_hub_notice(conn, row.ktw_request_id, "the commitment no longer applies")
            if row.revoked_at is None:
                conn.execute(
                    update(t.credential)
                    .where(t.credential.c.id == row.id)
                    .values(ktw_acknowledge_by=None, ktw_reminded_at=None, ktw_request_id=None)
                )
            continue
        due = row.ktw_acknowledge_by
        if now < due:
            continue
        token = instances.token(row.agent_id, row.instance)
        session = conn.execute(
            select(t.agent_session.c.id).where(
                t.agent_session.c.credential_id == row.id, t.agent_session.c.live.is_(True)
            )
        ).scalar()
        if (
            row.ktw_reminded_at is None
            and session is not None
            and row.member_paused is None
            and row.paused_since is None
        ):
            payload = {
                "project": namespace.full_name(conn, project),  # §6.25
                "instance": row.instance,
                "session_id": session,
                "acknowledge_by": clock.rfc3339(due),
            }
            emit(conn, project.id, "keep_the_why_reminder", [token], payload)
            conn.execute(
                update(t.credential).where(t.credential.c.id == row.id).values(ktw_reminded_at=now)
            )
        request_id = row.ktw_request_id
        if request_id is not None:
            status, addressed = _request_owner(conn, request_id)
            if status == "open" and addressed != row.owner_id:
                # The profile changed hands: the new owner is asked, the old one is not.
                withdraw_hub_notice(conn, request_id, "the agent has a new owner")
                request_id = None
        if request_id is None and now >= due + OWNER_AFTER:
            request_id = file_hub_notice(
                conn,
                project.id,
                row.member_row,
                row.agent_id,
                f"{row.handle}#{row.instance} has not confirmed Keep the Why in {project.name}",
                f"The commitment was due at {clock.rfc3339(due)} (UTC); "
                f"session {row.ktw_session_id}.",
            )
            conn.execute(
                update(t.credential)
                .where(t.credential.c.id == row.id)
                .values(ktw_request_id=request_id)
            )


def sweep(engine: Engine) -> None:
    """One pass over the projects that check the commitment, or that still hold an
    outstanding one."""
    with engine.connect() as conn:
        ids = list(
            conn.execute(
                select(t.membership.c.project_id)
                .join(t.credential, t.credential.c.membership_id == t.membership.c.id)
                .where(
                    t.credential.c.ktw_acknowledged_at.is_(None),
                    t.credential.c.ktw_acknowledge_by.isnot(None),
                )
                .distinct()
            ).scalars()
        )
    for project_id in ids:
        with transaction(engine) as conn:
            reconcile(conn, lock_project(conn, project_id))


class Worker:
    """Runs `sweep` in the background (§6.23: the hub's periodic worker, once a minute)."""

    def __init__(self, engine: Engine, interval: float | None = None) -> None:
        self.engine = engine
        self.interval = INTERVAL if interval is None else interval  # read now: tests set it
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-commitment", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                sweep(self.engine)
            except Exception:
                log.exception("the commitment sweep failed")
