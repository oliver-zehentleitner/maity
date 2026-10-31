"""Who is calling: a human with a cookie session, or an agent or a runner with a
credential.

`authenticate` resolves the caller from one request and applies the side
effects every authenticated call has (docs/api.md §2.4): presence on the
human, the membership and the session; for an agent, the renewal of its
leases (except on the events long-poll) and the move of its claims to the
live session; for a runner, its own last use and nothing on any membership
(§15.1).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import Connection, and_, select, update

from maity_hub import availability, clock
from maity_hub import tables as t
from maity_hub.auth import credentials, nonces
from maity_hub.config import DEFAULT_CLI_INSTALL
from maity_hub.errors import ApiError, unauthenticated
from maity_hub.events import Actor
from maity_hub.net import Origin

SESSION_COOKIE = "maity_session"
CSRF_COOKIE = "maity_csrf"
CSRF_HEADER = "x-csrf-token"
SESSION_IDLE = timedelta(days=14)
SESSION_ABSOLUTE = timedelta(days=30)
UNSAFE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}
CLOSED_STATUSES = ("done", "cancelled")


@dataclass(frozen=True)
class RequestFacts:
    """What authentication needs from a request, independent of the framework."""

    method: str
    raw_path: bytes
    raw_query: bytes
    headers: dict[str, str]  # lower-case names
    cookies: dict[str, str]
    body: bytes
    origin: Origin
    allow_plain_http: bool
    cli_install: str = DEFAULT_CLI_INSTALL


@dataclass(frozen=True)
class Bridged:
    """The bridge behind a `Maity-For` call (§2.3): the caller is then the served agent."""

    membership_id: int
    agent_id: str
    instance: str | None
    bridge_id: str

    def view(self) -> dict[str, str | None]:
        return {"member_id": self.agent_id, "instance": self.instance, "bridge_id": self.bridge_id}


@dataclass(frozen=True)
class Caller:
    kind: str  # human, agent, runner
    via: str  # cookie, bearer, signed
    human_id: str | None = None
    human_session: str | None = None  # id_hash of the dashboard session
    agent_id: str | None = None
    owner_id: str | None = None  # the human who owns the agent profile
    credential_id: str | None = None
    instance: str | None = None  # an agent credential's instance id (§6.17)
    session_id: str | None = None
    membership_id: int | None = None  # an agent's one membership
    project_id: str | None = None  # an agent's one project
    harness: str | None = None
    model: str | None = None
    runner_id: str | None = None
    bridge: Bridged | None = None  # a bridge calling as this agent (`Maity-For`, §2.3)

    @property
    def principal_id(self) -> str:
        """The member id; a runner is no member and has none (§15.1)."""
        principal = {"human": self.human_id, "agent": self.agent_id}.get(self.kind)
        if principal is None:
            raise RuntimeError("a caller without a principal")
        return principal

    @property
    def idempotency_caller(self) -> str:
        """Idempotency keys are unique per credential, or per human for cookies."""
        return self.credential_id or self.principal_id

    def runner_actor(self) -> Actor:
        """A runner as the actor of an event: no membership (§15.10)."""
        return Actor(
            membership_id=None,
            session_id=self.session_id,
            credential_id=self.credential_id,
            via=self.via,
            runner_id=self.runner_id,
        )

    def actor(self, membership_id: int) -> Actor:
        return Actor(
            membership_id=membership_id,
            session_id=self.session_id,
            credential_id=self.credential_id,
            via=self.via,
            harness=self.harness,
            model=self.model,
            bridge=self.bridge.view() if self.bridge else None,
        )


def session_id_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("ascii")).hexdigest()


def authenticate(conn: Connection, facts: RequestFacts, *, renew_leases: bool = True) -> Caller:
    authorization = facts.headers.get("authorization")
    if authorization:  # the header authenticates; a cookie alongside is ignored
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            return _bearer(conn, facts, value.strip(), renew_leases)
        if scheme == "Maity-HMAC":
            return _signed(conn, facts, value.strip(), renew_leases)
        raise unauthenticated("unsupported authorization scheme")
    if SESSION_COOKIE in facts.cookies:
        return _cookie(conn, facts, renew_leases)
    raise unauthenticated()


# --- humans ----------------------------------------------------------------------


def require_secure_transport(origin: Origin, allow_plain_http: bool) -> None:
    """A credential or a cookie crosses plain HTTP only on loopback or with the flag (§2.5)."""
    if not (origin.tls or origin.loopback or allow_plain_http):
        raise ApiError(403, "insecure_transport", "credentials and cookies travel over TLS only")


def _cookie(conn: Connection, facts: RequestFacts, renew: bool) -> Caller:
    require_secure_transport(facts.origin, facts.allow_plain_http)
    if facts.headers.get("sec-fetch-site") == "cross-site":
        raise ApiError(403, "csrf_mismatch", "cross-site request with a session cookie")
    now = clock.now()
    id_hash = session_id_hash(facts.cookies[SESSION_COOKIE])
    row = conn.execute(select(t.human_session).where(t.human_session.c.id_hash == id_hash)).first()
    if row is None or row.ended_at is not None or not session_alive(row, now):
        raise unauthenticated("the session has ended or expired")
    deleted = conn.execute(select(t.human.c.deleted_at).where(t.human.c.id == row.human_id))
    if deleted.scalar() is not None:  # a deleted account calls nothing (§2.9)
        raise unauthenticated("the session has ended or expired")
    if facts.method in UNSAFE_METHODS:
        token = facts.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(token.encode(), row.csrf_token.encode()):
            raise ApiError(403, "csrf_mismatch", "X-CSRF-Token does not match the session")
    conn.execute(
        update(t.human_session)
        .where(t.human_session.c.id_hash == id_hash)
        .values(last_seen_at=now, ip=facts.origin.address[:64])  # the latest call's (§2.6.5)
    )
    conn.execute(update(t.human).where(t.human.c.id == row.human_id).values(last_seen_at=now))
    conn.execute(
        update(t.membership)
        .where(t.membership.c.human_id == row.human_id, t.membership.c.removed_at.is_(None))
        .values(last_seen_at=now)
    )
    if renew:
        # A human holder works in the dashboard; its calls renew its leases too (§6.5). Only
        # the memberships that hold an open claim have a lease to renew: reading the rest
        # (the hold, the human, the project) and updating nothing would cost a human of
        # many projects several statements each on every request, to renew nothing.
        claimed = (
            select(t.card.c.id)
            .where(
                t.card.c.claim_holder == t.membership.c.id,
                t.card.c.status.notin_(CLOSED_STATUSES),
            )
            .exists()
        )
        memberships = conn.execute(
            select(t.membership.c.id, t.project.c.lease_seconds)
            .join(t.project, t.project.c.id == t.membership.c.project_id)
            .where(
                t.membership.c.human_id == row.human_id,
                t.membership.c.active.is_(True),
                claimed,
            )
        ).all()
        for membership_id, lease in memberships:
            conn.execute(
                update(t.card).where(
                    t.card.c.claim_holder == membership_id,
                    t.card.c.status.notin_(CLOSED_STATUSES),
                )
                # A limit's hold is never shortened by a renewal (§6.12).
                .values(lease_until=availability.renewed_lease(conn, membership_id, now, lease))
            )
    return Caller(kind="human", via="cookie", human_id=row.human_id, human_session=id_hash)


def has_live_session(conn: Connection, cookies: Mapping[str, str]) -> bool:
    """Whether a `maity_session` cookie names a session that is alive: the test of §16.7 for
    "a visitor without a session". It reads, it renews nothing, and it never raises."""
    value = cookies.get(SESSION_COOKIE)
    if not value or not value.isascii():
        return False
    row = conn.execute(
        select(t.human_session).where(t.human_session.c.id_hash == session_id_hash(value))
    ).first()
    if row is None or row.ended_at is not None or not session_alive(row, clock.now()):
        return False
    deleted = conn.execute(select(t.human.c.deleted_at).where(t.human.c.id == row.human_id))
    return deleted.scalar() is None


def session_alive(row: Any, now: datetime) -> bool:
    last_seen: datetime = row.last_seen_at
    expires: datetime = row.expires_at
    return now < expires and now < last_seen + SESSION_IDLE


def session_expires_at(row: Any) -> datetime:
    last_seen: datetime = row.last_seen_at
    expires: datetime = row.expires_at
    return min(expires, last_seen + SESSION_IDLE)


# --- agents ------------------------------------------------------------------------


def _bearer(conn: Connection, facts: RequestFacts, value: str, renew: bool) -> Caller:
    require_secure_transport(facts.origin, facts.allow_plain_http)
    presented = credentials.parse(value)
    if presented is None:
        raise unauthenticated()
    row = _credential(conn, presented.credential_id)
    if not credentials.secret_matches(presented.secret, row.verifier):
        raise unauthenticated()
    _refuse_revoked(row)  # only now: the caller proved possession (§1.3)
    if is_runner_credential(row.id):
        # Whatever any project's policy says, before any side effect (§15.1).
        raise ApiError(403, "signature_required", "a runner credential signs every call")
    return _agent(conn, row, "bearer", renew, facts)


def _signed(conn: Connection, facts: RequestFacts, credential_id: str, renew: bool) -> Caller:
    timestamp = facts.headers.get("maity-timestamp", "")
    nonce = facts.headers.get("maity-nonce", "")
    signature = facts.headers.get("maity-signature", "")
    if not (_timestamp_shape(timestamp) and _nonce_shape(nonce) and _hex64(signature)):
        raise ApiError(401, "signature_invalid", "the signature headers are malformed")
    now = clock.now()
    stamp = int(timestamp)
    # A request signed before the nonces were known could be replayed now, so it is refused as
    # skew (§2.2): before the database's nonce epoch where they are shared, before the process
    # started where the process keeps them.
    known_since = int(nonces.epoch(conn).timestamp()) if nonces.shared(conn) else PROCESS_STARTED
    if abs(stamp - now.timestamp()) > credentials.TIMESTAMP_WINDOW_SECONDS or stamp < known_since:
        raise ApiError(
            401,
            "timestamp_skew",
            "Maity-Timestamp is outside the window",
            {"server_time": clock.rfc3339(now)},
        )
    row = _credential(conn, credential_id)
    canonical = credentials.canonical_string(
        facts.method,
        facts.raw_path,
        facts.raw_query,
        timestamp,
        nonce,
        facts.body,
        facts.headers.get("maity-for"),
    )
    if not credentials.signature_matches(row.verifier, canonical, signature):
        raise ApiError(401, "signature_invalid", "the signature does not verify")
    _refuse_revoked(row)  # only now: the signature proved possession (§1.3)
    # Only a verified request spends its nonce, so a forger cannot burn them.
    spent_first = (
        nonces.first_use(conn, credential_id, nonce)
        if nonces.shared(conn)
        else NONCES.first_use(credential_id, nonce)
    )
    if not spent_first:
        raise ApiError(401, "nonce_reused", "this nonce was used within the window")
    if is_runner_credential(row.id):
        return _runner(conn, row)
    return _agent(conn, row, "signed", renew, facts)


NONCES = credentials.NonceWindow()
PROCESS_STARTED = int(time.time())


def _timestamp_shape(timestamp: str) -> bool:
    return 0 < len(timestamp) <= 12 and timestamp.isascii() and timestamp.isdigit()


def _hex64(signature: str) -> bool:
    return len(signature) == 64 and all(c in "0123456789abcdefABCDEF" for c in signature)


def _nonce_shape(nonce: str) -> bool:
    # At least 16 random bytes as base64url: 22 characters (docs/api.md §2.2).
    return 22 <= len(nonce) <= 128 and all(
        c.isascii() and (c.isalnum() or c in "-_") for c in nonce
    )


RUNNER_CREDENTIAL_PREFIX = "rcrd-"


def is_runner_credential(credential_id: str) -> bool:
    """Runner and agent credentials share the format and differ by the id's prefix."""
    return credential_id.startswith(RUNNER_CREDENTIAL_PREFIX)


def _credential(conn: Connection, credential_id: str) -> Any:
    if is_runner_credential(credential_id):
        return _runner_credential(conn, credential_id)
    row = conn.execute(
        select(
            t.credential.c.id,
            t.credential.c.verifier,
            t.credential.c.revoked_at,
            t.credential.c.revoked_reason,
            t.credential.c.revoke_due_at,
            t.credential.c.revoke_due_by,
            t.credential.c.membership_id,
            t.credential.c.instance,
            t.membership.c.project_id,
            t.membership.c.agent_id,
            t.membership.c.isolated_reason,
            t.membership.c.isolated_since,
            t.membership.c.isolated_by,
            t.agent_profile.c.owner_id,
            t.project.c.signing,
        )
        .join(t.membership, t.membership.c.id == t.credential.c.membership_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(t.credential.c.id == credential_id)
    ).first()
    if row is None:
        raise unauthenticated()
    return row


def _refuse_revoked(row: Any) -> None:
    from maity_hub import runner_revoke

    # A runner's stop: the placements it closed, told to the runner while the revoked
    # credential is its latest (§15.3); an agent credential has no such list.
    told = {}
    if getattr(row, "is_latest", False):
        told = {"stop": [p for applied in row.stopped or [] for p in applied["stopped"]]}
    if row.revoked_at is not None:
        raise ApiError(
            401,
            "credential_revoked",
            "this credential was revoked",
            {"reason": row.revoked_reason, **told},
        )
    if getattr(row, "runner_removed_at", None) is not None:
        # Removing a runner revokes its credential in the same transaction; this holds
        # even if a credential ever outlived its runner (§15.3).
        raise ApiError(
            401,
            "credential_revoked",
            "this runner was removed",
            {"reason": "runner_removed", **told},
        )
    if runner_revoke.due(row):  # its grace after a runner's stop has passed (§15.3)
        raise runner_revoke.RevocationDue(row.id, row.revoke_due_by)


# The two calls an isolated agent may still make, so that it learns why (§6.2).
ISOLATED_MAY = {("GET", b"/api/v1/me"), ("POST", b"/api/v1/me/resume")}


def _agent(conn: Connection, row: Any, via: str, renew: bool, facts: RequestFacts) -> Caller:
    cli_install = facts.cli_install
    if via == "bearer" and row.signing == "required":
        # After the proof of possession, before any side effect: no presence, no
        # lease, no last use, and no idempotent replay of an earlier answer (§2.2).
        raise ApiError(
            403,
            "signature_required",
            "this project requires signed requests: install the CLI; "
            "it uses the credential you already have",
            {"cli": cli_install, "then": "maity resume"},
        )
    if row.isolated_since is not None and (facts.method, facts.raw_path) not in ISOLATED_MAY:
        # Before any side effect, as for a required signature (§6.2, "Isolation").
        from maity_hub import isolation

        raise isolation.refusal(row)
    if row.isolated_since is not None:
        # The two calls it may make leave no trace: no presence, no lease, no session (§6.2).
        return Caller(
            kind="agent",
            via=via,
            agent_id=row.agent_id,
            owner_id=row.owner_id,
            credential_id=row.id,
            instance=row.instance,
            membership_id=row.membership_id,
            project_id=row.project_id,
        )
    now = clock.now()
    credential_id: str = row.id
    membership_id: int = row.membership_id
    project_id: str = row.project_id
    session = conn.execute(
        select(t.agent_session.c.id, t.agent_session.c.harness, t.agent_session.c.model).where(
            t.agent_session.c.credential_id == credential_id,
            t.agent_session.c.live.is_(True),
        )
    ).first()
    conn.execute(
        update(t.credential)
        .where(t.credential.c.id == credential_id)
        .values(last_used_at=now, last_used_via=via)
    )
    conn.execute(
        update(t.membership).where(t.membership.c.id == membership_id).values(last_seen_at=now)
    )
    if session is not None:
        conn.execute(
            update(t.agent_session)
            .where(t.agent_session.c.id == session.id)
            .values(last_seen_at=now)
        )
    instance: str = row.instance
    # The claim is the instance's (§6.5): a sibling's call renews nothing of it.
    held = and_(
        t.card.c.claim_holder == membership_id,
        t.card.c.claim_instance == instance,
        t.card.c.status.notin_(CLOSED_STATUSES),
    )
    if renew:
        lease = conn.execute(
            select(t.project.c.lease_seconds).where(t.project.c.id == project_id)
        ).scalar_one()
        renewed = availability.renewed_lease(conn, membership_id, now, lease)
        conn.execute(update(t.card).where(held).values(lease_until=renewed))
    if session is not None:
        # The claim belongs to the instance; it follows the instance's live session.
        conn.execute(
            update(t.card)
            .where(held, t.card.c.claim_session_id.is_distinct_from(session.id))
            .values(claim_session_id=session.id)
        )
    return Caller(
        kind="agent",
        via=via,
        agent_id=row.agent_id,
        owner_id=row.owner_id,
        credential_id=credential_id,
        instance=instance,
        session_id=session.id if session else None,
        membership_id=membership_id,
        project_id=project_id,
        harness=session.harness if session else None,
        model=session.model if session else None,
    )


# --- runners -----------------------------------------------------------------------


def _runner_credential(conn: Connection, credential_id: str) -> Any:
    row = conn.execute(
        select(
            t.runner_credential.c.id,
            t.runner_credential.c.verifier,
            t.runner_credential.c.revoked_at,
            t.runner_credential.c.revoked_reason,
            t.runner_credential.c.runner_id,
            t.runner_credential.c.stopped,
            t.runner_credential.c.created_at,
            t.runner.c.owner_id,
            t.runner.c.removed_at.label("runner_removed_at"),
        )
        .join(t.runner, t.runner.c.id == t.runner_credential.c.runner_id)
        .where(t.runner_credential.c.id == credential_id)
    ).first()
    if row is None:
        raise unauthenticated()
    newer = conn.execute(
        select(t.runner_credential.c.id).where(
            t.runner_credential.c.runner_id == row.runner_id,
            t.runner_credential.c.created_at > row.created_at,
        )
    ).first()
    return SimpleNamespace(**row._asdict(), is_latest=newer is None)


def _runner(conn: Connection, row: Any) -> Caller:
    now = clock.now()
    conn.execute(
        update(t.runner_credential)
        .where(t.runner_credential.c.id == row.id)
        .values(last_used_at=now, last_used_via="signed")
    )
    conn.execute(update(t.runner).where(t.runner.c.id == row.runner_id).values(last_seen_at=now))
    session_id = conn.execute(
        select(t.runner_session.c.id).where(
            t.runner_session.c.credential_id == row.id, t.runner_session.c.live.is_(True)
        )
    ).scalar()
    if session_id is not None:
        conn.execute(
            update(t.runner_session)
            .where(t.runner_session.c.id == session_id)
            .values(last_seen_at=now)
        )
    return Caller(
        kind="runner",
        via="signed",
        runner_id=row.runner_id,
        owner_id=row.owner_id,
        credential_id=row.id,
        session_id=session_id,
    )
