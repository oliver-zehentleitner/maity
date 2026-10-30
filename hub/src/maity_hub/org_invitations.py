"""An organisation's invitations (docs/api.md §6.26, "Adding a member: by invitation, with
their word").

An invitation is a row (`org_invitation`) and, when its handle names a human who can be
invited, a personal `consent` request to that human with no project and the organisation
(`request.org_id`): the `org_invitation` proposal kind. The `go` makes the human a member in
the transaction of the answer; the `no`, and the human's own withdrawal, end the invitation.
The request is filed to the human, and what the inviter sees is the same whether or not the
handle names one: no request id, the handle exactly as typed.

Everything here runs under the organisation's row lock (`orgs.lock`). Whoever closes an
invitation on purpose (a revocation, the loss of the inviter's role, the organisation's
deletion, a `go` that supersedes it) closes the row first, with its reason, and then
withdraws the request; `settle` only closes a row that is still open, which is the case of the
invited human's own `no` and withdrawal.
"""

from __future__ import annotations

import logging
import re
import threading
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Engine, insert, select, update

from maity_hub import clock, orgs, proposals
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid, not_found, rate_limited
from maity_hub.ids import new_id
from maity_hub.models import HANDLE_PATTERN
from maity_hub.views import ts

log = logging.getLogger(__name__)

KIND = "org_invitation"
LIFETIME = timedelta(days=14)
PER_DAY = 20  # invitations per organisation per 24 hours (§1.7)
INTERVAL = 60.0
_HANDLE = re.compile(HANDLE_PATTERN)


# --- reading -------------------------------------------------------------------------------


def view(conn: Connection, invitation: Any) -> dict[str, Any]:
    inviter = conn.execute(
        select(t.human.c.handle).where(t.human.c.id == invitation.invited_by)
    ).scalar_one()
    return {
        "id": invitation.id,
        "handle": invitation.handle,
        "role": invitation.role,
        "invited_by": {"id": invitation.invited_by, "handle": inviter},
        "created_at": ts(invitation.created_at),
        "expires_at": ts(invitation.expires_at),
    }


def _open(conn: Connection, org_id: str) -> list[Any]:
    return list(
        conn.execute(
            select(t.org_invitation)
            .where(t.org_invitation.c.org_id == org_id, t.org_invitation.c.live.is_(True))
            .order_by(t.org_invitation.c.created_at, t.org_invitation.c.id)
        ).all()
    )


def open_items(conn: Connection, org: Any) -> list[dict[str, Any]]:
    expire(conn, org.id)
    return [view(conn, row) for row in _open(conn, org.id)]


def _invitee(conn: Connection, handle: str) -> str | None:
    """The approved, active human whose current handle this is, or None: nobody, an
    organisation, a pending or a deleted account."""
    found = conn.execute(
        select(t.human.c.id, t.human.c.account_status, t.human.c.deleted_at).where(
            t.human.c.handle == handle
        )
    ).first()
    if found is None or found.deleted_at is not None or found.account_status != "active":
        return None
    return str(found.id)


# --- creating and revoking -----------------------------------------------------------------


def _allowed(actor_role: str, role: str) -> None:
    """An owner invites to any role, an admin to `member` or `admin`, a member to none."""
    if actor_role == "owner":
        return
    if actor_role == "admin" and role in ("member", "admin"):
        return
    raise orgs.org_role()


def create(
    conn: Connection, org: Any, actor_id: str, actor_role: str, handle: str, role: str
) -> dict[str, Any]:
    """File the invitation; the same answer for a handle that names a human who can be
    invited and for one that does not (§6.26)."""
    if role not in orgs.ROLES:
        raise invalid({"role": "invalid"})
    _allowed(actor_role, role)
    if not _HANDLE.fullmatch(handle):
        raise invalid({"handle": "invalid"})
    expire(conn, org.id)
    member_handles = {m["handle"] for m in orgs.members(conn, org.id)}
    if handle in member_handles:
        raise invalid({"handle": "member"})
    if any(row.handle == handle for row in _open(conn, org.id)):
        raise invalid({"handle": "invited"})
    _check_rate(conn, org.id)
    now = clock.now()
    invitation_id = new_id("org_invitation")
    invitee = _invitee(conn, handle)
    request_id = None
    if invitee is not None:
        request_id = _file_request(conn, org, invitation_id, actor_id, invitee, role)
    conn.execute(
        insert(t.org_invitation).values(
            id=invitation_id,
            org_id=org.id,
            handle=handle,
            role=role,
            invited_by=actor_id,
            request_id=request_id,
            created_at=now,
            expires_at=now + LIFETIME,
            live=True,
        )
    )
    row = conn.execute(select(t.org_invitation).where(t.org_invitation.c.id == invitation_id)).one()
    return view(conn, row)


def _check_rate(conn: Connection, org_id: str) -> None:
    """At most `PER_DAY` invitations per organisation in 24 hours, counted from the rows,
    so a restart forgets nothing; `Retry-After` is when the oldest of them leaves."""
    since = clock.now() - timedelta(hours=24)
    times = list(
        conn.execute(
            select(t.org_invitation.c.created_at)
            .where(t.org_invitation.c.org_id == org_id, t.org_invitation.c.created_at > since)
            .order_by(t.org_invitation.c.created_at.desc())
            .limit(PER_DAY)
        ).scalars()
    )
    if len(times) >= PER_DAY:
        wait = times[-1] + timedelta(hours=24) - clock.now()
        raise rate_limited(max(1, int(wait.total_seconds()) + 1))


def _file_request(
    conn: Connection, org: Any, invitation_id: str, actor_id: str, human_id: str, role: str
) -> str:
    """The personal consent request to the invited human: no project, the organisation, the
    inviter as `asked_by_human`."""
    from maity_hub.notifications import records

    request_id = new_id("request")
    inviter = conn.execute(select(t.human.c.handle).where(t.human.c.id == actor_id)).scalar_one()
    conn.execute(
        insert(t.request).values(
            {
                "id": request_id,
                "project_id": None,
                "org_id": org.id,
                "class": "consent",
                "title": f"Join {org.display_name} ({org.handle}) as {role}"[: t.TITLE],
                "summary": (
                    f"{inviter} invites you to join the organisation {org.handle} as {role}. "
                    "You become a member only if you say go."
                ),
                "options": [],
                "priority": "normal",
                "to_kind": "human",
                "to_human": human_id,
                "personal": True,
                "proposal": {
                    "kind": KIND,
                    "invitation_id": invitation_id,
                    "org_id": org.id,
                    "to": human_id,
                    "role": role,
                },
                "asked_by": None,
                "asked_by_human": actor_id,
                "while_open": "wait",
                "status": "open",
                "created_at": clock.now(),
            }
        )
    )
    row = conn.execute(select(t.request).where(t.request.c.id == request_id)).one()
    records.personal_request(conn, row)
    return request_id


def revoke(conn: Connection, org: Any, actor_role: str, invitation_id: str) -> None:
    """Withdraw an open invitation and its request. An owner withdraws any, an admin one
    for the role `member` or `admin`."""
    invitation = conn.execute(
        select(t.org_invitation).where(
            t.org_invitation.c.id == invitation_id,
            t.org_invitation.c.org_id == org.id,
            t.org_invitation.c.live.is_(True),
        )
    ).first()
    if invitation is None:
        raise not_found()
    _allowed(actor_role, invitation.role)
    close(conn, invitation, "revoked")


# --- closing -------------------------------------------------------------------------------


def close(conn: Connection, invitation: Any, reason: str) -> None:
    """Close an open invitation for `reason`, and withdraw its request if one was filed."""
    done = conn.execute(
        update(t.org_invitation)
        .where(t.org_invitation.c.id == invitation.id, t.org_invitation.c.live.is_(True))
        .values(live=None, closed_at=clock.now(), closed_by=reason)
    ).rowcount
    if done != 1 or invitation.request_id is None:
        return
    from maity_hub.routes.requests import close_request

    close_request(conn, invitation.request_id, "withdrawn", None, reason=reason)


def withdraw_by_inviter(conn: Connection, org_id: str, human_id: str, role_now: str | None) -> None:
    """The inviter's role fell: an owner demoted to `admin` loses their open invitations for
    `owner`; demoted to `member`, removed or leaving, all of them (§6.26)."""
    for invitation in _open(conn, org_id):
        if invitation.invited_by != human_id:
            continue
        if role_now == "owner" or (role_now == "admin" and invitation.role != "owner"):
            continue
        close(conn, invitation, "inviter_role")


def withdraw_all(conn: Connection, org_id: str, reason: str) -> None:
    for invitation in _open(conn, org_id):
        close(conn, invitation, reason)


def withdraw_for_human(conn: Connection, human_id: str, reason: str) -> None:
    """The invited human's account is gone: every open invitation whose request went to
    them is withdrawn, in every organisation."""
    rows = conn.execute(
        select(t.org_invitation)
        .join(t.request, t.request.c.id == t.org_invitation.c.request_id)
        .where(t.org_invitation.c.live.is_(True), t.request.c.to_human == human_id)
    ).all()
    for invitation in rows:
        close(conn, invitation, reason)


def withdraw_by_inviter_everywhere(conn: Connection, human_id: str, reason: str) -> None:
    """The inviter's account is gone: every open invitation they sent, in every
    organisation, is withdrawn (§2.9, §6.26)."""
    rows = conn.execute(
        select(t.org_invitation).where(
            t.org_invitation.c.live.is_(True), t.org_invitation.c.invited_by == human_id
        )
    ).all()
    for invitation in rows:
        close(conn, invitation, reason)


def expire(conn: Connection, org_id: str | None = None) -> None:
    """Withdraw the invitations that are 14 days old, with their requests. The organisations
    concerned are locked first, in the order of their ids, as every other change of one is
    (§6.26): the minute worker holds no lock when it comes here."""
    due = t.org_invitation.c.live.is_(True) & (t.org_invitation.c.expires_at <= clock.now())
    ids = (
        select(t.org_invitation.c.org_id).where(due).distinct().order_by(t.org_invitation.c.org_id)
    )
    if org_id is not None:
        ids = ids.where(t.org_invitation.c.org_id == org_id)
    for locked_id in list(conn.execute(ids).scalars()):
        orgs.lock(conn, locked_id)  # None for an organisation deleted meanwhile: nothing to lock
    query = select(t.org_invitation).where(due)
    if org_id is not None:
        query = query.where(t.org_invitation.c.org_id == org_id)
    for invitation in conn.execute(query).all():
        close(conn, invitation, "expired")


# --- the answer ----------------------------------------------------------------------------


def _stale(request_id: str, message: str) -> proposals.Stale:
    error = ApiError(409, "invalid_transition", message, {"reason": "invitation_stale"})
    return proposals.Stale(error, request_id, "the invitation is stale")


def settle(conn: Connection, s: proposals.Settlement) -> None:
    """`go` makes the human a member with the invitation's role, if the invitation is still
    open and the organisation is not deleted; `no` and a withdrawal end it."""
    proposal = s.proposal
    invitation = conn.execute(
        select(t.org_invitation).where(t.org_invitation.c.id == proposal["invitation_id"])
    ).first()
    if invitation is None or invitation.live is not True:
        if s.outcome == "go":
            raise _stale(s.request.id, "the invitation is no longer open")
        return
    expired = invitation.expires_at <= clock.now()
    if s.outcome != "go":  # the invited human's no, or their withdrawal, which counts as one
        close(conn, invitation, "expired" if expired else "declined")
        return
    org = orgs.lock(conn, invitation.org_id)
    if org is None:
        raise _stale(s.request.id, "the organisation was deleted")
    if expired:  # the withdrawal that follows a stale `go` closes the row as `expired`
        raise _stale(s.request.id, "the invitation has expired")
    human_id = proposal["to"]
    closed = conn.execute(
        update(t.org_invitation)
        .where(t.org_invitation.c.id == invitation.id, t.org_invitation.c.live.is_(True))
        .values(live=None, closed_at=clock.now(), closed_by="accepted")
    ).rowcount
    if closed != 1:  # closed meanwhile by a path that holds no organisation lock
        raise _stale(s.request.id, "the invitation is no longer open")
    if orgs.role_of(conn, org.id, human_id) is None:
        conn.execute(
            insert(t.org_member).values(
                org_id=org.id, human_id=human_id, role=invitation.role, joined_at=clock.now()
            )
        )
        if invitation.role == "owner":  # the hub makes them an owner of the projects (§6.26)
            from maity_hub import org_projects

            org_projects.keep_in_all(conn, org.id, human_id)
    # Every other open invitation of this organisation whose request went to this human is
    # withdrawn now, so a later `go` finds nothing open (two names, two invitations).
    others = conn.execute(
        select(t.org_invitation)
        .join(t.request, t.request.c.id == t.org_invitation.c.request_id)
        .where(
            t.org_invitation.c.org_id == org.id,
            t.org_invitation.c.live.is_(True),
            t.request.c.to_human == human_id,
        )
    ).all()
    for other in others:
        close(conn, other, "superseded")


def _the_invitee(conn: Connection, request: Any, mine: Any) -> str | None:
    """Only the invited human answers."""
    proposal = proposals.of(request) or {}
    return None if getattr(mine.row, "human_id", None) == proposal.get("to") else "not_the_invitee"


proposals.register(
    KIND,
    settle,
    proposals.Answerer(refusal="the invited human answers an invitation", predicate=_the_invitee),
)


# --- the minute worker ---------------------------------------------------------------------


def sweep(engine: Engine) -> None:
    with engine.begin() as conn:
        expire(conn)


class Worker:
    """Withdraws the invitations that expired, every minute (§6.26)."""

    def __init__(self, engine: Engine, interval: float | None = None) -> None:
        self.engine = engine
        self.interval = INTERVAL if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-org-invitations", daemon=True)
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
                log.exception("the sweep of expired organisation invitations failed")
