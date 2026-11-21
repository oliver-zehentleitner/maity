"""Who is calling: a human with a cookie session, or an agent or a runner with a
credential.

`authenticate` resolves the caller from one request and applies the side
effects every authenticated call has (docs/api.md §2.4): presence on the
human, the membership and the session; for an agent, the renewal of its
leases (except on the events long-poll) and the move of its claims to the
live session; for a runner, its own last use and nothing on any membership
(§15.1). Before any of them, a read of the API counts against the credential's read limit
(§1.7, `read_limits`).
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import ColumnElement, Connection, and_, or_, select, update

from maity_hub import availability, clock, ids, read_limits, timing
from maity_hub import tables as t
from maity_hub.admin import instance_admin_id_query
from maity_hub.auth import credentials, nonces, verifiers
from maity_hub.auth.permitted import Calls
from maity_hub.cards import open_claims
from maity_hub.config import DEFAULT_CLI_INSTALL
from maity_hub.errors import ApiError, unauthenticated
from maity_hub.events import Actor
from maity_hub.net import Origin
from maity_hub.seen import SEEN_EVERY, latest_call

SESSION_COOKIE = "maity_session"
CSRF_COOKIE = "maity_csrf"
CSRF_HEADER = "x-csrf-token"
SESSION_IDLE = timedelta(days=14)
SESSION_ABSOLUTE = timedelta(days=30)
UNSAFE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}


@dataclass(frozen=True)
class RequestFacts:
    """What authentication needs from a request, independent of the framework."""

    method: str
    raw_path: bytes  # as sent: what a signature covers and the isolation gate compares
    path: str  # as the router matches it, decoded (`scope["path"]`): what the read limit counts
    raw_query: bytes
    headers: dict[str, str]  # lower-case names
    cookies: dict[str, str]
    body: bytes
    origin: Origin
    allow_plain_http: bool
    cli_install: str = DEFAULT_CLI_INSTALL
    request: object = field(default_factory=object)  # one per request, whatever runs again
    # The credentials this request's read was counted for (§1.7 "Reads per credential"): one
    # per request like `request`, so a run again of its transaction is not counted again.
    reads_paid: set[str] = field(default_factory=set, compare=False)
    # The (credential, nonce) pairs this request spent in the database (§2.2, PostgreSQL),
    # kept across its transaction's runs like `reads_paid`, so that `keep_nonces_spent` can
    # spend them again once a refusal has rolled the transaction back. The process's window
    # (SQLite, MariaDB) is outside the transaction and records nothing here.
    nonces_spent: set[tuple[str, str]] = field(default_factory=set, compare=False)
    # MAITY_MAX_READS_PER_MINUTE as the environment set it (None: the admin's or the default),
    # and the route's pattern for the read limit's log line (§1.7 "Reads per credential").
    max_reads_env: int | str | None = None
    route: str = "-"


@dataclass(frozen=True)
class Bridged:
    """The bridge behind a `Maity-For` call (§2.3): the caller is then the served agent."""

    membership_id: int
    agent_id: str
    instance: str | None
    bridge_id: str

    def view(self) -> dict[str, str | None]:
        return {"member_id": self.agent_id, "instance": self.instance, "bridge_id": self.bridge_id}


@dataclass(eq=False)
class OnRequest:
    """A signed `Maity-On-Request` and the call it came with, as §2.3 compares them.
    `spent_seq` names the event of this call's spend: a route may read its membership more than
    once. It proves nothing alone, since a retried transaction has rolled that spend back; only
    the request's row, showing the same seq, does."""

    request_id: str
    method: str
    path: str  # below /api/v1
    query: str | None
    body_sha256: str | None
    spent_seq: int | None = None


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
    on_request: OnRequest | None = None  # a proxy's go for this call, signed (§2.3)
    # A cookie call's session row and account status as authentication read them, after
    # its presence writes locked both rows, so that the second-factor gate and the pending
    # check do not read them again on every call (tsk-6srccd2r1h62).
    session_row: Any = field(default=None, compare=False, repr=False)
    account_status: str | None = field(default=None, compare=False)

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


def _count_read(conn: Connection, facts: RequestFacts, key: str) -> None:
    """The read limit per credential (§1.7 "Reads per credential"): a `GET` or `HEAD` of the
    API counts against `key`, the credential's id or the session's hash; past the limit it is
    `rate_limited`. Called once the credential is known and before any side effect (§2.4), so
    a refused read writes nothing; a write is not counted. Whether it is a read of the API is
    decided on the path the router matches, so every spelling of a route counts as the route."""
    if read_limits.counts(facts.method, facts.path):
        read_limits.take(
            conn,
            key,
            env_value=facts.max_reads_env,
            paid=facts.reads_paid,
            method=facts.method.upper(),
            route=facts.route,
        )


def session_id_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("ascii")).hexdigest()


def authenticate(
    conn: Connection, facts: RequestFacts, *, renew_leases: bool = True, seen: bool = True
) -> Caller:
    """The caller of the request. `seen=False` (a dashboard tab's presence, §18.4) checks a
    cookie session as any call does but writes no `last_seen_at`: that call shows nobody as
    online and keeps no session alive (§2.4)."""
    authorization = facts.headers.get("authorization")
    if authorization:  # the header authenticates; a cookie alongside is ignored
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            return _bearer(conn, facts, value.strip(), renew_leases)
        if scheme == "Maity-HMAC":
            return _signed(conn, facts, value.strip(), renew_leases)
        raise unauthenticated("unsupported authorization scheme")
    if SESSION_COOKIE in facts.cookies:
        return _cookie(conn, facts, renew_leases, seen)
    raise unauthenticated()


def precheck(conn: Connection, facts: RequestFacts) -> None:
    """Refuse, from the headers alone, a caller whom no body could authenticate, so that a
    large body is not read for it (§8.7). It runs the first checks of `authenticate`, in
    the same order and with the same refusals; the rest (the signature, which covers the
    body, a revoked credential, the CSRF token among them) wait for the full check after
    the body. It renews nothing and spends no nonce."""
    authorization = facts.headers.get("authorization")
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer":
            _possessed(conn, facts, value.strip())
            return
        if scheme == "Maity-HMAC":
            _signed_headers(conn, facts)
            _credential(conn, value.strip())
            return
        raise unauthenticated("unsupported authorization scheme")
    if SESSION_COOKIE not in facts.cookies:
        raise unauthenticated()
    _cookie_headers(facts)
    if not has_live_session(conn, facts.cookies):
        raise unauthenticated("the session has ended or expired")


# --- humans ----------------------------------------------------------------------


def require_secure_transport(origin: Origin, allow_plain_http: bool) -> None:
    """A credential or a cookie crosses plain HTTP only on loopback or with the flag (§2.5)."""
    if not (origin.tls or origin.loopback or allow_plain_http):
        raise ApiError(403, "insecure_transport", "credentials and cookies travel over TLS only")


def _cookie_headers(facts: RequestFacts) -> None:
    require_secure_transport(facts.origin, facts.allow_plain_http)
    if facts.headers.get("sec-fetch-site") == "cross-site":
        raise ApiError(403, "csrf_mismatch", "cross-site request with a session cookie")


def _cookie(conn: Connection, facts: RequestFacts, renew: bool, seen: bool = True) -> Caller:
    _cookie_headers(facts)
    now = clock.now()
    presented = facts.cookies[SESSION_COOKIE]
    if not presented.isascii():  # names no session; `session_id_hash` encodes ASCII only
        raise unauthenticated("the session has ended or expired")
    id_hash = session_id_hash(presented)
    # The session is checked before anything is written (§2.4): an ended or expired session,
    # or one of a deleted account, sends no presence write at all, and neither does a read
    # past the limit per credential (§1.7), counted once the session is known to be live.
    row = _live_session(conn, id_hash, now)
    if facts.method in UNSAFE_METHODS:
        token = facts.headers.get(CSRF_HEADER, "")
        if not hmac.compare_digest(token.encode(), row.csrf_token.encode()):
            raise ApiError(403, "csrf_mismatch", "X-CSRF-Token does not match the session")
    _count_read(conn, facts, id_hash)
    # Presence at most once every `SEEN_EVERY` (§2.4), sent only when the read says it is due;
    # its update checks the session again, so a session ended meanwhile matches nothing. A
    # dashboard tab's presence (`seen=False`, §18.4) writes none of it.
    if seen and row.last_seen_at <= now - SEEN_EVERY:
        touched = conn.execute(
            update(t.human_session)
            .where(
                t.human_session.c.id_hash == id_hash,
                live_session_clause(now),
                t.human_session.c.last_seen_at <= now - SEEN_EVERY,
            )
            .values(last_seen_at=now, ip=facts.origin.address[:64])  # the latest call's (§2.6.5)
        ).rowcount
        if touched == 1:
            # The session's row is locked now, then its human's, in the order they always
            # were. The session is read again under those locks, so the gate and the pending
            # check decide on it as it stands, under READ COMMITTED too (#1540 review); once a
            # minute per session, on the call that writes its presence.
            conn.execute(
                update(t.human).where(t.human.c.id == row.human_id).values(last_seen_at=now)
            )
            conn.execute(
                update(t.membership)
                .where(t.membership.c.human_id == row.human_id, t.membership.c.removed_at.is_(None))
                .values(last_seen_at=now)
            )
        # Read again whether the update matched or not. No row means one of two things since
        # the first read: another call of this session already wrote its presence (the
        # session is alive, and this read says so), or the session ended or its account was
        # deleted (this read refuses). Going on with the first read would renew leases and
        # authenticate a session that has ended.
        row = _live_session(conn, id_hash, now)
    if renew:
        # A human holder works in the dashboard; its calls renew its leases too (§6.5). Only
        # the memberships that hold an open claim have a lease to renew: reading the rest
        # (the hold, the human, the project) and updating nothing would cost a human of
        # many projects several statements each on every request, to renew nothing.
        claimed = select(t.card.c.id).where(open_claims(t.membership.c.id)).exists()
        memberships = conn.execute(
            select(t.membership.c.id, t.project.c.lease_seconds)
            .join(t.project, t.project.c.id == t.membership.c.project_id)
            .where(
                t.membership.c.human_id == row.human_id,
                t.membership.c.active.is_(True),
                t.membership.c.trust != "guest",  # a guest holds no cards (§2.3)
                claimed,
            )
        ).all()
        for membership_id, lease in memberships:
            conn.execute(
                update(t.card).where(open_claims(membership_id))
                # A limit's hold is never shortened by a renewal (§6.12).
                .values(lease_until=availability.renewed_lease(conn, membership_id, now, lease))
            )
    timing.admit(row.human_is_instance_admin)
    return Caller(
        kind="human",
        via="cookie",
        human_id=row.human_id,
        human_session=id_hash,
        session_row=row,
        account_status=row.human_account_status,
    )


def _live_session(conn: Connection, id_hash: str, now: datetime) -> Any:
    """The session `id_hash` names with its human, read in one statement (tsk-6srccd2r1h62);
    `unauthenticated` unless it is live and its account not deleted (§2.9)."""
    # Whether this is the instance admin, for `Server-Timing` (`timing.admit`): in this same
    # read rather than one more on every cookie call, as a join that finds the human only
    # when it is the earliest account.
    admin = t.human.alias("instance_admin")
    row = conn.execute(
        select(
            t.human_session,
            t.human.c.deleted_at.label("human_deleted_at"),
            t.human.c.account_status.label("human_account_status"),
            admin.c.id.is_not(None).label("human_is_instance_admin"),
        )
        .join(t.human, t.human.c.id == t.human_session.c.human_id)
        .outerjoin(admin, and_(admin.c.id == t.human.c.id, admin.c.id == instance_admin_id_query()))
        .where(t.human_session.c.id_hash == id_hash)
    ).first()
    if row is None or row.ended_at is not None or not session_alive(row, now):
        raise unauthenticated("the session has ended or expired")
    if row.human_deleted_at is not None:  # a deleted account calls nothing (§2.9)
        raise unauthenticated("the session has ended or expired")
    return row


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
    # The idle time runs from the latest call the stored time may stand for (`seen`), so a
    # session in use never expires early.
    return now < expires and now < latest_call(last_seen) + SESSION_IDLE


def live_session_clause(now: datetime) -> ColumnElement[bool]:
    """`human_session` rows that are not ended and `session_alive` at `now`, in SQL: every
    statement that selects live sessions takes this, so the readings move together."""
    session = t.human_session.c
    return and_(
        session.ended_at.is_(None),
        session.expires_at > now,
        session.last_seen_at > now - SESSION_IDLE - SEEN_EVERY,  # latest_call() + SESSION_IDLE
    )


def session_expires_at(row: Any) -> datetime:
    last_seen: datetime = row.last_seen_at
    expires: datetime = row.expires_at
    return min(expires, latest_call(last_seen) + SESSION_IDLE)


# --- agents ------------------------------------------------------------------------


def _possessed(conn: Connection, facts: RequestFacts, value: str) -> Any:
    """The credential a bearer value names, once its secret matches."""
    require_secure_transport(facts.origin, facts.allow_plain_http)
    presented = credentials.parse(value)
    if presented is None:
        raise unauthenticated()
    row = _credential(conn, presented.credential_id)
    verifier = _verifier(row)
    if verifier is None or not credentials.secret_matches(presented.secret, verifier):
        raise unauthenticated()
    return row


def _bearer(conn: Connection, facts: RequestFacts, value: str, renew: bool) -> Caller:
    row = _possessed(conn, facts, value)
    _refuse_revoked(row)  # only now: the caller proved possession (§1.3)
    if is_runner_credential(row.id):
        # Whatever any project's policy says, before any side effect (§15.1).
        raise ApiError(403, "signature_required", "a runner credential signs every call")
    return _agent(conn, row, "bearer", renew, facts)


def _signed_headers(conn: Connection, facts: RequestFacts) -> tuple[str, str, str]:
    """A signed call's checks that need no body: the headers' shape and the time window."""
    timestamp = facts.headers.get("maity-timestamp", "")
    nonce = facts.headers.get("maity-nonce", "")
    signature = facts.headers.get("maity-signature", "")
    if not (_timestamp_shape(timestamp) and _nonce_shape(nonce) and _hex64(signature)):
        raise ApiError(401, "signature_invalid", "the signature headers are malformed")
    on_request = facts.headers.get("maity-on-request")
    if on_request is not None and not ids.has_shape("request", on_request):
        # Before the canonical string is built: its line is the bare value, and only a request
        # id's shape keeps it apart from the `for:` line of `Maity-For` (§2.2).
        raise ApiError(401, "signature_invalid", "Maity-On-Request is not a request id")
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
    return timestamp, nonce, signature


def _signed(conn: Connection, facts: RequestFacts, credential_id: str, renew: bool) -> Caller:
    timestamp, nonce, signature = _signed_headers(conn, facts)
    row = _credential(conn, credential_id)
    canonical = credentials.canonical_string(
        facts.method,
        facts.raw_path,
        facts.raw_query,
        timestamp,
        nonce,
        facts.body,
        facts.headers.get("maity-for"),
        facts.headers.get("maity-on-request"),
    )
    verifier = _verifier(row)
    if verifier is None or not credentials.signature_matches(verifier, canonical, signature):
        raise ApiError(401, "signature_invalid", "the signature does not verify")
    _refuse_revoked(row)  # only now: the signature proved possession (§1.3)
    # Only a verified request spends its nonce, so a forger cannot burn them.
    if nonces.shared(conn):
        if not nonces.first_use(conn, credential_id, nonce):
            raise ApiError(401, "nonce_reused", "this nonce was used within the window")
        # Only the database's claim is undone by a refusal's rollback; the process's window
        # keeps its own, so a refusal there opens no transaction to claim it again.
        facts.nonces_spent.add((credential_id, nonce))
    elif not NONCES.first_use(credential_id, nonce, facts.request):
        raise ApiError(401, "nonce_reused", "this nonce was used within the window")
    if is_runner_credential(row.id):
        return _runner(conn, row, facts)
    caller = _agent(conn, row, "signed", renew, facts)
    return replace(caller, on_request=_on_request(facts))


NONCES = credentials.NonceWindow()
PROCESS_STARTED = int(time.time())


def keep_nonces_spent(conn: Connection, facts: RequestFacts) -> None:
    """Spend again, in `conn`'s own transaction, the nonces this request spent before a
    refusal rolled its authentication back (§2.2): a refused request keeps its nonce spent,
    so the same request sent again is `nonce_reused` once the refusal's condition ends, as
    it already is where the process keeps the nonces (hub/context/auth.md fbc8c3e0). Only
    the database's claims are recorded, so this runs only where they live. An insert that
    finds the nonce spent meanwhile leaves it spent."""
    for credential_id, nonce in sorted(facts.nonces_spent):
        nonces.first_use(conn, credential_id, nonce)


def _timestamp_shape(timestamp: str) -> bool:
    return 0 < len(timestamp) <= 12 and timestamp.isascii() and timestamp.isdigit()


def _on_request(facts: RequestFacts) -> OnRequest | None:
    request_id = facts.headers.get("maity-on-request")
    if request_id is None:
        return None
    return OnRequest(
        request_id=request_id,
        method=facts.method.upper(),
        path=facts.raw_path.decode("latin-1").removeprefix("/api/v1"),
        query=facts.raw_query.decode("latin-1") or None,
        body_sha256=hashlib.sha256(facts.body).hexdigest() if facts.body else None,
    )


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


def _verifier(row: Any) -> str | None:
    """The row's verifier, unsealed; None when the instance key does not open it, or when it is
    plain while MAITY_SEALED_VERIFIERS_ONLY is on: both answer alike (§2.2)."""
    table: verifiers.Table = "runner_credential" if is_runner_credential(row.id) else "credential"
    return verifiers.accepted(table, row.id, row.verifier)


def _credential(conn: Connection, credential_id: str) -> Any:
    """The credential row a presented id names, on both paths and in the precheck. An id the
    hub could not have issued names no credential and is refused as an unknown one, before
    any query (§1 `unauthenticated`): a signed call's id arrives as the header sent it."""
    runner = is_runner_credential(credential_id)
    if not ids.has_shape("runner_credential" if runner else "credential", credential_id):
        raise unauthenticated()
    if runner:
        return _runner_credential(conn, credential_id)
    attachment = t.instance_attachment
    # TODO(hub PR B): resolve the attachment of the route's project. Until then a credential
    # attached to several projects authenticates in its oldest attachment that is not
    # detached, by attached_at and then id, so the choice never depends on the order the
    # database returns rows in.
    first = attachment.alias("first_attachment")
    oldest = (
        select(first.c.id)
        .where(first.c.credential_id == t.credential.c.id, first.c.detached_at.is_(None))
        .order_by(first.c.attached_at, first.c.id)
        .limit(1)
        .correlate(t.credential)
        .scalar_subquery()
    )
    row = conn.execute(
        select(
            t.credential.c.id,
            t.credential.c.verifier,
            t.credential.c.revoked_at,
            t.credential.c.revoked_reason,
            t.credential.c.revoke_due_at,
            t.credential.c.revoke_due_by,
            attachment.c.membership_id,
            t.credential.c.instance,
            t.membership.c.project_id,
            t.membership.c.agent_id,
            t.membership.c.isolated_reason,
            t.membership.c.isolated_since,
            t.membership.c.isolated_by,
            t.agent_profile.c.owner_id,
            t.project.c.signing,
        )
        .select_from(t.credential)
        .join(
            attachment,
            and_(attachment.c.credential_id == t.credential.c.id, attachment.c.id == oldest),
        )
        .join(t.membership, t.membership.c.id == attachment.c.membership_id)
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


# The two calls an isolated agent may still make, so that it learns why (§6.2), and
# `GET /bootstrap`, whose parts are refused one by one as their single routes are (§5.4,
# `refuse_isolated`). Read on the raw request path, so `/api/v1/m%65` is not `/me`.
ISOLATED_MAY = Calls(
    ("GET", "/me"),
    ("POST", "/me/resume"),
    ("GET", "/bootstrap"),
)


def refuse_isolated(conn: Connection, caller: Caller, method: str, path: str) -> None:
    """The refusal an isolated agent's call on `path` gets (§6.2), for a caller authenticated
    on another path: each part of `GET /bootstrap` (§5.4). Read as of now, in the part's
    own transaction."""
    if caller.kind != "agent" or caller.membership_id is None:
        return
    if ISOLATED_MAY.admits_api(method, path):
        return
    row = conn.execute(
        select(
            t.membership.c.isolated_reason,
            t.membership.c.isolated_since,
            t.membership.c.isolated_by,
        ).where(t.membership.c.id == caller.membership_id)
    ).first()
    if row is not None and row.isolated_since is not None:
        from maity_hub import isolation

        raise isolation.refusal(row)


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
    if row.isolated_since is not None and not ISOLATED_MAY.admits_api(
        facts.method, facts.raw_path.decode("latin-1")  # byte for byte
    ):
        # Before any side effect, as for a required signature (§6.2, "Isolation").
        from maity_hub import isolation

        raise isolation.refusal(row)
    # After the refusals that need no count, before the last use, presence and the leases: a
    # read past the limit renews nothing (§1.7). A bridge's call with `Maity-For` counts here,
    # against the bridge's own credential (§2.3).
    _count_read(conn, facts, row.id)
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
    # Reseal on use (§2.2): a plain row that verified is sealed in this same update.
    conn.execute(
        update(t.credential)
        .where(t.credential.c.id == credential_id)
        .values(
            last_used_at=now,
            last_used_via=via,
            **verifiers.reseal_value(
                "credential", t.credential.c.verifier, credential_id, row.verifier
            ),
        )
    )
    # Presence at most once every `SEEN_EVERY` (§2.4): within it these match nothing and write
    # nothing.
    conn.execute(
        update(t.membership)
        .where(
            t.membership.c.id == membership_id,
            or_(
                t.membership.c.last_seen_at.is_(None),
                t.membership.c.last_seen_at <= now - SEEN_EVERY,
            ),
        )
        .values(last_seen_at=now)
    )
    if session is not None:
        conn.execute(
            update(t.agent_session)
            .where(
                t.agent_session.c.id == session.id,
                t.agent_session.c.last_seen_at <= now - SEEN_EVERY,
            )
            .values(last_seen_at=now)
        )
    instance: str = row.instance
    # The claim is the instance's (§6.5): a sibling's call renews nothing of it.
    held = open_claims(membership_id, instance=instance)
    if renew:
        lease = conn.execute(
            select(t.project.c.lease_seconds).where(t.project.c.id == project_id)
        ).scalar_one()
        renewed = availability.renewed_lease(conn, membership_id, now, lease)
        # Only a membership that may still hold cards renews them: a guest's claim runs out
        # (§2.3, §6.5). In the same statement, so a call costs no more than before.
        may_hold = (
            select(t.membership.c.id)
            .where(t.membership.c.id == membership_id, t.membership.c.trust != "guest")
            .exists()
        )
        conn.execute(update(t.card).where(held, may_hold).values(lease_until=renewed))
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


def _runner(conn: Connection, row: Any, facts: RequestFacts) -> Caller:
    _count_read(conn, facts, row.id)  # before its last use and presence, as for an agent (§1.7)
    now = clock.now()
    conn.execute(  # reseal on use, as `_agent` does (§2.2)
        update(t.runner_credential)
        .where(t.runner_credential.c.id == row.id)
        .values(
            last_used_at=now,
            last_used_via="signed",
            **verifiers.reseal_value(
                "runner_credential", t.runner_credential.c.verifier, row.id, row.verifier
            ),
        )
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
