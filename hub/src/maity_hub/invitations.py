"""Invitations for humans (docs/api.md §3.4): what an invitation is, when it admits, and
who hears of it.

An invitation is for one person, one project, one trust and one role; it is used once and it
expires. Whether it still admits — open, its project not closed, its issuer still
holding the authority it needs — is one predicate, used by the page, by accepting and by
registration (§2.7.1), so the three never disagree.

An invitation by handle is bound to one account at issue and has no link: the hub files a
personal `consent` request to that person (§7), the `invitation` proposal kind, and their `go`
accepts it in the transaction of the answer, their `no` declines it. Whoever ends such an
invitation on purpose (a revocation, a void, its expiry, the person's account deleted or their
joining another way) ends the row first and then withdraws the request; `settle` itself ends
only a row that is still open, which is the case of the person's own `no` and withdrawal, and of
a `go` that no longer applies.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, insert, select, update

from maity_hub import clock, maintenance, proposals, worker_runs
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid, rate_limited
from maity_hub.events import Actor, emit, lock_project
from maity_hub.models import HANDLE_PATTERN
from maity_hub.policy import CLOSED_STATES
from maity_hub.ratelimit import Limiter
from maity_hub.scopes import has_scope

log = logging.getLogger(__name__)

TTL_DEFAULT, TTL_MIN, TTL_MAX = 86_400, 60, 604_800
NOTE_MAX = 1024  # bytes of UTF-8
LISTED_FOR = timedelta(days=30)  # a used, revoked, voided or expired one stays listed
PER_PROJECT = Limiter(
    20, 3600, name="invitations.PER_PROJECT"
)  # issued per project per hour (§3.4)
KINDS = (
    "invitation_created",
    "invitation_revoked",
    "invitation_voided",
    "invitation_used",
    "invitation_declined",
)
KIND = "invitation"  # the proposal kind of an invitation by handle's request (§3.4, §7)
# Invitations by handle to one person in 24 hours, across the instance (§3.4).
INVITATIONS_PER_INVITEE_PER_DAY = 10
INTERVAL = 60.0  # the sweep of expired invitations by handle
_HANDLE = re.compile(HANDLE_PATTERN)
# Only the owner invites to these: the roles that themselves invite (§3.4).
# What only a caller with trust `owner` grants (§2.3 "The owner's rights").
OWNER_TRUSTS = ("owner", "admin")


def state(row: Any, now: datetime | None = None) -> str:
    """`used`, `revoked`, `voided`, `declined`, `expired` or `open`."""
    if row.used_at is not None:
        return "used"
    if row.revoked_at is not None:
        return "revoked"
    if row.voided_at is not None:
        return "voided"
    if row.declined_at is not None:
        return "declined"
    if row.expires_at <= (now or clock.now()):
        return "expired"
    return "open"


def view(
    row: Any, project_slug: str, url: str | None = None, handle: str | None = None
) -> dict[str, Any]:
    """The invitation as its issuers see it; `url`, with the token, only when issued, and
    never for an invitation by handle. `handle` is the bound account's handle as it is now
    (`handles_now`); without it, the handle at issue."""
    found = {
        "id": row.id,
        "project": project_slug,
        "trust": row.trust,
        "role": row.role,
        "address": row.address,
        "handle": handle if handle is not None else row.handle,
        "note": row.note,
        "created_by": row.created_by,
        "created_at": clock.rfc3339(row.created_at),
        "expires_at": clock.rfc3339(row.expires_at),
        "used_at": _ts(row.used_at),
        "used_by": row.used_by,
        "revoked_at": _ts(row.revoked_at),
        "voided_at": _ts(row.voided_at),
        "declined_at": _ts(row.declined_at),
        "via": row.via,
    }
    if url is not None:
        found["url"] = url
    return found


def handles_now(conn: Connection, rows: Sequence[Any]) -> dict[str, str]:
    """Per invitation by handle, the bound account's current handle: a rename shows."""
    invitees = {row.invitee_id for row in rows if row.invitee_id is not None}
    if not invitees:
        return {}
    current = dict(
        conn.execute(select(t.human.c.id, t.human.c.handle).where(t.human.c.id.in_(invitees))).all()
    )
    return {row.id: current[row.invitee_id] for row in rows if row.invitee_id in current}


def _ts(value: datetime | None) -> str | None:
    return clock.rfc3339(value) if value is not None else None


def may_issue(trust: str, role: str, issuer_trust: str, issuer_base: str) -> bool:
    """Trust `owner` or `admin`, and the role `proxy`, need the issuer to hold trust
    `owner`; the others `members:admin`. `issuer_base` is the issuer's `role_base`."""
    if trust in OWNER_TRUSTS or role == "proxy":
        return issuer_trust == "owner"
    return has_scope(issuer_trust, issuer_base, "human", "members:admin")


def issuer_holds(conn: Connection, row: Any) -> bool:
    """Whether the issuer is still an active human member with the authority it needs."""
    issuer = conn.execute(
        select(t.membership.c.trust, t.membership.c.role_base).where(
            t.membership.c.project_id == row.project_id,
            t.membership.c.human_id == row.created_by,
            t.membership.c.active.is_(True),
        )
    ).first()
    return issuer is not None and may_issue(row.trust, row.role, issuer.trust, issuer.role_base)


def admits(conn: Connection, row: Any, project: Any, now: datetime | None = None) -> bool:
    """§3.4's predicate: open, its project not closed, its issuer with authority."""
    return (
        state(row, now) == "open" and project.state not in CLOSED_STATES and issuer_holds(conn, row)
    )


def admits_address(conn: Connection, normalized: str, *, lock: bool = False) -> bool:
    """Whether an open, address-bound invitation admits this address to register under
    `closed` or `allowlist` (§2.7.1, §3.4). An invitation without an address admits
    nobody to register.

    With `lock` (completion), the projects of the candidates are locked first, in id
    order, and the invitations read again `FOR UPDATE` under them: a revocation, an
    accept, a project's closing and an issuer's demotion all take the project's lock, so
    each either commits before this read or waits until the account exists. The lock
    order — address, then projects, then invitation rows — is the one every other path
    keeps (none takes an address lock after a project's)."""
    now = clock.now()
    query = select(t.invitation).where(
        t.invitation.c.address_normalized == normalized,
        t.invitation.c.used_at.is_(None),
        t.invitation.c.revoked_at.is_(None),
        t.invitation.c.voided_at.is_(None),
        t.invitation.c.expires_at > now,
    )
    if lock:
        locked = sorted({row.project_id for row in conn.execute(query)})
        for project_id in locked:
            lock_project(conn, project_id)
        # Only the projects locked above decide: an invitation of another project that
        # appears in between was never locked, and admits nothing in this completion.
        query = query.where(t.invitation.c.project_id.in_(locked)).with_for_update()
    rows = conn.execute(query).all()
    for row in rows:
        state = conn.execute(
            select(t.project.c.state).where(t.project.c.id == row.project_id)
        ).scalar()
        if state not in CLOSED_STATES and issuer_holds(conn, row):
            return True
    return False


def account_address(conn: Connection, human_id: str) -> str | None:
    """The account's verified address (§18.4), normalized, or None. An address that is
    only pending, or none at all, is None: with it an address-bound invitation is
    `invitation_address_mismatch`. A `disabled` address was verified and stays the
    account's."""
    return conn.execute(
        select(t.notification_settings.c.address_normalized).where(
            t.notification_settings.c.human_id == human_id,
            t.notification_settings.c.address_status.in_(("verified", "disabled")),
        )
    ).scalar()


def audience(conn: Connection, project_id: str, *also: str) -> list[str]:
    """`member:<id>` of every human `members:admin` holder (§3.4), and `also`."""
    humans = conn.execute(
        select(t.membership.c.human_id)
        .where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id.is_not(None),
            t.membership.c.trust.in_(("owner", "admin")),
            t.membership.c.role != "proxy",  # holds no members:admin (§2.3)
            t.membership.c.active.is_(True),
        )
        .order_by(t.membership.c.joined_at)
    ).scalars()
    found = [f"member:{human_id}" for human_id in humans]
    return found + [token for token in also if token not in found]


def announce(conn: Connection, kind: str, row: Any, actor: Actor, *also: str) -> None:
    """An invitation event: its id, role and whether it is address-bound, never the
    address and never the token (§3.4)."""
    emit(
        conn,
        row.project_id,
        kind,
        audience(conn, row.project_id, *also),
        {
            "id": row.id,
            "trust": row.trust,
            "role": row.role,
            "address_bound": row.address is not None,
            "handle_bound": row.invitee_id is not None,
        },
        actor=actor,
        subject=("invitation", row.id),
    )


def void(conn: Connection, row: Any, actor: Actor | None, reason: str = "issuer") -> None:
    """The issuer lost the authority the invitation needs (`issuer`), or the invited person's
    account is gone (`invitee`): void it, tell the issuer, and withdraw the request of an
    invitation by handle."""
    conn.execute(
        update(t.invitation)
        .where(t.invitation.c.id == row.id)
        .values(voided_at=clock.now(), void_reason=reason)
    )
    after = conn.execute(select(t.invitation).where(t.invitation.c.id == row.id)).one()
    announce(conn, "invitation_voided", after, actor or Actor(None), f"member:{row.created_by}")
    end_request(conn, after, f"invitation_voided:{reason}")


def revoke(conn: Connection, row: Any, actor: Actor) -> None:
    """An open invitation revoked by a `members:admin` holder, under the project's lock."""
    conn.execute(
        update(t.invitation).where(t.invitation.c.id == row.id).values(revoked_at=clock.now())
    )
    after = conn.execute(select(t.invitation).where(t.invitation.c.id == row.id)).one()
    announce(conn, "invitation_revoked", after, actor)
    end_request(conn, after, "invitation_revoked")


def use(conn: Connection, row: Any, human_id: str, actor: Actor) -> None:
    used = conn.execute(
        update(t.invitation)
        .where(t.invitation.c.id == row.id, t.invitation.c.used_at.is_(None))
        .values(used_at=clock.now(), used_by=human_id)
    ).rowcount
    if used != 1:  # under the project's lock this cannot happen; never two uses
        from maity_hub.errors import not_found

        raise not_found()
    after = conn.execute(select(t.invitation).where(t.invitation.c.id == row.id)).one()
    announce(conn, "invitation_used", after, actor)
    end_request(conn, after, "invitation_used")


def end_request(conn: Connection, row: Any, reason: str) -> None:
    """Withdraw the open request of an invitation by handle whose row was just ended. Its
    settlement finds the row ended and changes nothing."""
    if row.request_id is None:
        return
    from maity_hub.routes.requests import close_request

    close_request(conn, row.request_id, "withdrawn", None, reason=reason)


# --- the membership ------------------------------------------------------------------------


def admit(
    conn: Connection,
    row: Any,
    human_id: str,
    via: str | None,
    actor_of: Callable[[int], Actor],
) -> dict[str, Any]:
    """Make the person a member with the invitation's trust and role and mark it used, in
    the caller's transaction under the project's lock, once every check of accept passed
    (§3.4). Their other open invitations by handle to this project end with it. Returns the
    new member's view."""
    from maity_hub import project_roles, restricted, start_tabs
    from maity_hub.views import member_view

    now = clock.now()
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    in_set_before = restricted.resolve(conn, project)  # who enters is told to the set (§6.4)
    result = conn.execute(
        insert(t.membership).values(
            project_id=row.project_id,
            human_id=human_id,
            trust=row.trust,
            role=row.role,
            # A role still named by an open invitation cannot be removed (§2.3).
            role_base=project_roles.base_of(project, row.role),
            areas=[],
            capabilities=[],
            joined_at=now,
            last_seen_at=now,
            changed_via=via,
        )
    )
    key = result.inserted_primary_key
    assert key is not None
    membership_id = int(key[0])
    start_tabs.append(conn, human_id, row.project_id)  # it opens as the last tab (§5.1)
    actor = actor_of(membership_id)
    use(conn, row, human_id, actor)
    joined(conn, row.project_id, human_id, actor, keep=row.id)
    new = conn.execute(select(t.membership).where(t.membership.c.id == membership_id)).one()
    found = member_view(conn, new)
    emit(
        conn,
        row.project_id,
        "member_joined",
        ["all"],
        found,
        actor=actor,
        subject=("member", human_id),
    )
    restricted.entered(
        conn, row.project_id, in_set_before, "joined", restricted.person(conn, membership_id), actor
    )
    return found


def joined(
    conn: Connection, project_id: str, human_id: str, actor: Actor, keep: str | None = None
) -> None:
    """The person became a member of the project: their open invitations by handle to it
    are used up, as an address-bound one is on `already_member` (§3.4), and their requests
    withdrawn. `keep` is the invitation that made them a member."""
    for other in _open_by_handle(conn, project_id, human_id):
        if other.id != keep:
            use(conn, other, human_id, actor)


def _open_by_handle(conn: Connection, project_id: str, human_id: str) -> list[Any]:
    c = t.invitation.c
    rows = conn.execute(
        select(t.invitation)
        .where(
            c.project_id == project_id,
            c.invitee_id == human_id,
            c.used_at.is_(None),
            c.revoked_at.is_(None),
            c.voided_at.is_(None),
            c.declined_at.is_(None),
        )
        .order_by(c.created_at, c.id)
    ).all()
    return [row for row in rows if state(row) == "open"]


# --- issuing by handle ---------------------------------------------------------------------


def invitee(conn: Connection, handle: str, project_id: str) -> Any:
    """The approved, active human whose handle or live alias is `handle` (§6.24), for an
    invitation by handle; else `invalid` with `details.fields.handle` (§3.4): `format`,
    `unknown` (nobody, or a deleted, pending or suspended account, as `GET /people` answers
    `not_found` for those, §6.27), `not_a_person` (an organisation's or an agent's handle),
    `member` (already a member of the project) or `invited` (an open invitation of this
    project already names this person)."""
    from maity_hub import handles

    if not _HANDLE.fullmatch(handle):
        raise invalid({"handle": "format"}, "not a valid handle")
    human_id = handles.human_id_of(conn, handle)
    if human_id is None:
        agent = conn.execute(
            select(t.agent_profile.c.id)
            .where(t.agent_profile.c.handle == handle, t.agent_profile.c.deleted_at.is_(None))
            .limit(1)
        ).first()
        if handles.org_id_of(conn, handle) is not None or agent is not None:
            raise invalid({"handle": "not_a_person"}, "this handle is not a person's")
        raise invalid({"handle": "unknown"}, "no person has this handle")
    found = conn.execute(select(t.human).where(t.human.c.id == human_id)).one()
    if (
        found.deleted_at is not None
        or found.account_status != "active"
        or found.suspended_at is not None
    ):
        raise invalid({"handle": "unknown"}, "no person has this handle")
    member = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == project_id,
            t.membership.c.human_id == human_id,
            t.membership.c.active.is_(True),
        )
    ).first()
    if member is not None:
        raise invalid({"handle": "member"}, "this person is a member already")
    if _open_by_handle(conn, project_id, human_id):
        raise invalid({"handle": "invited"}, "an open invitation names this person already")
    return found


def check_invitee_rate(conn: Connection, human_id: str) -> None:
    """At most `INVITATIONS_PER_INVITEE_PER_DAY` invitations by handle to one person in 24
    hours, counted from the rows under the person's row lock, so two projects at once count
    both; `Retry-After` is when the oldest of them leaves."""
    from maity_hub.notifications import records

    records.lock_human(conn, human_id)
    since = clock.now() - timedelta(hours=24)
    times = list(
        conn.execute(
            select(t.invitation.c.created_at)
            .where(t.invitation.c.invitee_id == human_id, t.invitation.c.created_at > since)
            .order_by(t.invitation.c.created_at.desc())
            .limit(INVITATIONS_PER_INVITEE_PER_DAY)
        ).scalars()
    )
    if len(times) >= INVITATIONS_PER_INVITEE_PER_DAY:
        wait = times[-1] + timedelta(hours=24) - clock.now()
        raise rate_limited(max(1, int(wait.total_seconds()) + 1))


def file_request(
    conn: Connection,
    mine: Any,
    caller: Any,
    invitation_id: str,
    person: Any,
    project_name: str,
    trust: str,
    role: str,
    note: str | None,
) -> str:
    """The personal consent request to the invited person (§3.4, §7), in the inviter's
    name; returns its id."""
    from maity_hub.routes.requests import file_to_human

    inviter = conn.execute(
        select(t.human.c.display_name).where(t.human.c.id == caller.human_id)
    ).scalar()
    summary = (
        f"{inviter} invites you to the project {project_name} as {role} with trust {trust}. "
        "You become a member only if you say go."
    )
    if note:
        summary += f"\n\n{note}"
    return file_to_human(
        conn,
        mine,
        caller,
        person.id,
        f"Join {project_name} as {role} ({trust})"[: t.TITLE],
        summary,
        {
            "kind": KIND,
            "invitation_id": invitation_id,
            "project_id": mine.project.id,
            "to": person.id,
        },
    )


# --- the answer ----------------------------------------------------------------------------


def _stale(request_id: str, error: ApiError, reason: str) -> proposals.Stale:
    return proposals.Stale(error, request_id, reason)


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """`go` accepts with the checks of §3.4's accept; `no`, and the person's own withdrawal,
    decline. A `go` that no longer applies withdraws the request (`proposals.Stale`), and the
    withdrawal settles the row as the facts say: used up for a member already, voided for an
    issuer without the authority, left alone when expired. The answering route holds the
    project's lock."""
    proposal = s.proposal
    row = conn.execute(
        select(t.invitation).where(t.invitation.c.id == proposal["invitation_id"])
    ).first()
    if row is None or state(row) != "open":
        if s.outcome == "go":
            error = ApiError(
                409,
                "invalid_transition",
                "the invitation is no longer open",
                {"reason": "invitation_stale"},
            )
            raise _stale(s.request.id, error, "invitation_stale")
        return
    human_id = proposal["to"]
    member = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == row.project_id,
            t.membership.c.human_id == human_id,
            t.membership.c.active.is_(True),
        )
    ).scalar()
    holds = issuer_holds(conn, row)
    if s.outcome != "go":
        if member is not None:
            use(conn, row, human_id, Actor(member))
        elif not holds:
            void(conn, row, None)
        else:
            conn.execute(
                update(t.invitation)
                .where(t.invitation.c.id == row.id)
                .values(declined_at=clock.now())
            )
            after = conn.execute(select(t.invitation).where(t.invitation.c.id == row.id)).one()
            announce(conn, "invitation_declined", after, Actor(None, human_id=human_id))
        return
    project = conn.execute(select(t.project).where(t.project.c.id == row.project_id)).one()
    if project.state in CLOSED_STATES:  # the request stays open with the invitation
        raise ApiError(409, "project_closed", f"the project is {project.state}")
    if member is not None:
        raise _stale(
            s.request.id,
            invalid({"request": "already_member"}, "you are a member already"),
            "already_member",
        )
    if not holds:
        error = ApiError(
            403,
            "forbidden",
            "the inviter can no longer grant this invitation",
            {"reason": "invitation_void"},
        )
        raise _stale(s.request.id, error, "invitation_void")
    via = s.closer.via if s.closer is not None else None
    admit(conn, row, human_id, via, lambda membership_id: Actor(membership_id, via=via))


def _the_invitee(conn: Connection, request: Any, mine: Any) -> str | None:
    """Only the invited person answers."""
    proposal = proposals.of(request) or {}
    return None if getattr(mine.row, "human_id", None) == proposal.get("to") else "not_the_invitee"


proposals.register(
    KIND,
    settle,
    proposals.Answerer(refusal="the invited person answers an invitation", predicate=_the_invitee),
)


# --- expiry and the account's deletion -----------------------------------------------------


def expire(conn: Connection) -> None:
    """Withdraw the requests of the invitations by handle that expired, each under its
    project's lock, the projects in the order of their ids."""
    c = t.invitation.c
    due = (
        (c.request_id.is_not(None))
        & c.used_at.is_(None)
        & c.revoked_at.is_(None)
        & c.voided_at.is_(None)
        & c.declined_at.is_(None)
        & (c.expires_at <= clock.now())
    )
    open_request = (
        select(t.request.c.id)
        .where(t.request.c.id == c.request_id, t.request.c.status == "open")
        .exists()
    )
    projects = select(c.project_id).where(due, open_request).distinct().order_by(c.project_id)
    for project_id in list(conn.execute(projects).scalars()):
        lock_project(conn, project_id)
        for row in conn.execute(
            select(t.invitation).where(due, open_request, c.project_id == project_id)
        ).all():
            end_request(conn, row, "invitation_expired")


def invitee_deleted(conn: Connection, human_id: str) -> None:
    """The invited person's account is being deleted: their open invitations by handle are
    voided (`invitee`), and their requests withdrawn (§2.9)."""
    projects = (
        select(t.invitation.c.project_id)
        .where(t.invitation.c.invitee_id == human_id)
        .distinct()
        .order_by(t.invitation.c.project_id)
    )
    for project_id in list(conn.execute(projects).scalars()):
        lock_project(conn, project_id)
        for row in _open_by_handle(conn, project_id, human_id):
            void(conn, row, None, "invitee")


def sweep(engine: Engine) -> None:
    from maity_hub.events import transaction

    with transaction(engine) as conn:  # the withdrawal's events wake their readers
        expire(conn)


class Worker:
    """Withdraws the requests of expired invitations by handle, every minute (§3.4)."""

    def __init__(self, engine: Engine, interval: float | None = None) -> None:
        self.engine = engine
        self.interval = INTERVAL if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-invitations", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                if maintenance.running_now(self.engine):
                    continue  # nobody can answer during a window; it decides after (§16.12)
                with worker_runs.claim(self.engine, "invitations", self.interval) as held:
                    if held is not None:
                        sweep(self.engine)
            except Exception:
                log.exception("the sweep of expired invitations by handle failed")
