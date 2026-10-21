"""Who is calling: a human with a cookie session, or an agent with a credential.

`authenticate` resolves the caller from one request and applies the side
effects every authenticated call has (docs/api.md §2.4): presence on the
human, the membership and the session; for an agent, the renewal of its
leases (except on the events long-poll) and the move of its claims to the
live session.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, and_, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import credentials
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


@dataclass(frozen=True)
class Caller:
    kind: str  # human, agent
    via: str  # cookie, bearer, signed
    human_id: str | None = None
    human_session: str | None = None  # id_hash of the dashboard session
    agent_id: str | None = None
    owner_id: str | None = None  # the human who owns the agent profile
    credential_id: str | None = None
    session_id: str | None = None
    membership_id: int | None = None  # an agent's one membership
    project_id: str | None = None  # an agent's one project
    harness: str | None = None
    model: str | None = None

    @property
    def principal_id(self) -> str:
        principal = self.human_id if self.kind == "human" else self.agent_id
        if principal is None:
            raise RuntimeError("a caller without a principal")
        return principal

    @property
    def idempotency_caller(self) -> str:
        """Idempotency keys are unique per credential, or per human for cookies."""
        return self.credential_id or self.principal_id

    def actor(self, membership_id: int) -> Actor:
        return Actor(
            membership_id=membership_id,
            session_id=self.session_id,
            credential_id=self.credential_id,
            via=self.via,
            harness=self.harness,
            model=self.model,
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
        return _cookie(conn, facts)
    raise unauthenticated()


# --- humans ----------------------------------------------------------------------


def _cookie(conn: Connection, facts: RequestFacts) -> Caller:
    if facts.headers.get("sec-fetch-site") == "cross-site":
        raise ApiError(403, "csrf_mismatch", "cross-site request with a session cookie")
    now = clock.now()
    id_hash = session_id_hash(facts.cookies[SESSION_COOKIE])
    row = conn.execute(select(t.human_session).where(t.human_session.c.id_hash == id_hash)).first()
    if row is None or row.ended_at is not None or not session_alive(row, now):
        raise unauthenticated("the session has ended or expired")
    if facts.method in UNSAFE_METHODS:
        token = facts.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(token.encode(), row.csrf_token.encode()):
            raise ApiError(403, "csrf_mismatch", "X-CSRF-Token does not match the session")
    conn.execute(
        update(t.human_session).where(t.human_session.c.id_hash == id_hash).values(last_seen_at=now)
    )
    conn.execute(update(t.human).where(t.human.c.id == row.human_id).values(last_seen_at=now))
    conn.execute(
        update(t.membership)
        .where(t.membership.c.human_id == row.human_id, t.membership.c.removed_at.is_(None))
        .values(last_seen_at=now)
    )
    return Caller(kind="human", via="cookie", human_id=row.human_id, human_session=id_hash)


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
    if not (facts.origin.tls or facts.origin.loopback or facts.allow_plain_http):
        raise ApiError(403, "insecure_transport", "a bearer credential is accepted over TLS only")
    presented = credentials.parse(value)
    if presented is None:
        raise unauthenticated()
    row = _credential(conn, presented.credential_id)
    if not credentials.secret_matches(presented.secret, row.verifier):
        raise unauthenticated()
    return _agent(conn, row, "bearer", renew)


def _signed(conn: Connection, facts: RequestFacts, credential_id: str, renew: bool) -> Caller:
    timestamp = facts.headers.get("maity-timestamp", "")
    nonce = facts.headers.get("maity-nonce", "")
    signature = facts.headers.get("maity-signature", "")
    if not (timestamp.isdigit() and _nonce_shape(nonce) and signature):
        raise ApiError(401, "signature_invalid", "the signature headers are incomplete")
    now = clock.now()
    if abs(int(timestamp) - now.timestamp()) > credentials.TIMESTAMP_WINDOW_SECONDS:
        raise ApiError(
            401,
            "timestamp_skew",
            "Maity-Timestamp is outside the window",
            {"server_time": clock.rfc3339(now)},
        )
    row = _credential(conn, credential_id)
    canonical = credentials.canonical_string(
        facts.method, facts.raw_path, facts.raw_query, timestamp, nonce, facts.body
    )
    if not credentials.signature_matches(row.verifier, canonical, signature):
        raise ApiError(401, "signature_invalid", "the signature does not verify")
    # Only a verified request spends its nonce, so a forger cannot burn them.
    if not NONCES.first_use(credential_id, nonce):
        raise ApiError(401, "nonce_reused", "this nonce was used within the window")
    return _agent(conn, row, "signed", renew)


NONCES = credentials.NonceWindow()


def _nonce_shape(nonce: str) -> bool:
    return 16 <= len(nonce) <= 128 and all(c.isalnum() or c in "-_" for c in nonce)


def _credential(conn: Connection, credential_id: str) -> Any:
    row = conn.execute(
        select(
            t.credential.c.id,
            t.credential.c.verifier,
            t.credential.c.revoked_at,
            t.credential.c.revoked_reason,
            t.credential.c.membership_id,
            t.membership.c.project_id,
            t.membership.c.agent_id,
            t.agent_profile.c.owner_id,
        )
        .join(t.membership, t.membership.c.id == t.credential.c.membership_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.credential.c.id == credential_id)
    ).first()
    if row is None:
        raise unauthenticated()
    if row.revoked_at is not None:
        raise ApiError(
            401,
            "credential_revoked",
            "this credential was revoked",
            {"reason": row.revoked_reason},
        )
    return row


def _agent(conn: Connection, row: Any, via: str, renew: bool) -> Caller:
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
        update(t.credential).where(t.credential.c.id == credential_id).values(last_used_at=now)
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
    held = and_(t.card.c.claim_holder == membership_id, t.card.c.status.notin_(CLOSED_STATUSES))
    if renew:
        lease = conn.execute(
            select(t.project.c.lease_seconds).where(t.project.c.id == project_id)
        ).scalar_one()
        conn.execute(update(t.card).where(held).values(lease_until=now + timedelta(seconds=lease)))
    if session is not None:
        # The claim belongs to the membership; it follows the live session.
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
        session_id=session.id if session else None,
        membership_id=membership_id,
        project_id=project_id,
        harness=session.harness if session else None,
        model=session.model if session else None,
    )
