"""Two-factor sign-in for humans (docs/api.md §2.8): the enrolment and its proof, the
second step of a sign-in, step-up before sensitive calls, recovery codes, and the
instance policy's effect on a session.

A session's stored `state` is `full`, `second_factor` (the first factor is done, the
code is not) or `enrolment` (the policy wants a factor first). Whether a full session
must enrol is worked out on every call, not stored: a session the human already held
when the policy was turned on, or when they became an owner, is held at enrolment from
its next call without a write (§2.8.5).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import admin, clock, secretbox
from maity_hub import tables as t
from maity_hub.auth import passwords, sessions, totp
from maity_hub.auth.caller import Caller, session_expires_at
from maity_hub.auth.sign_in_settings import second_factor_policy
from maity_hub.config import Settings
from maity_hub.errors import ApiError, invalid, rate_limited, unauthenticated
from maity_hub.notifications import records
from maity_hub.ratelimit import Limiter

SECOND_STEP = timedelta(minutes=5)  # a second-factor session's life
FRESH = timedelta(minutes=10)  # the password's proof and the step-up's window
TRUSTED_AGE = timedelta(hours=24)  # the proof for an account without a password
ENROLMENT = timedelta(minutes=10)  # an unconfirmed enrolment
RECOVERY_CODES = 10
WRONG_PER_SESSION = 5

# 10 wrong codes per human in 15 minutes, every kind of check alike (§2.8.6).
WRONG_BY_HUMAN = Limiter(10, 15 * 60)
ENROLMENTS_BY_HUMAN = Limiter(5, 60 * 60)
_wrong_in_session: dict[str, int] = {}

SECRET_FIELD = "second_factor.secret"
_CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"
_CROCKFORD_READ = str.maketrans({"i": "1", "l": "1", "o": "0"})

# What a second-factor and an enrolment session may call (§2.8.2, §2.8.5), below
# `/api/v1`.
SECOND_STEP_CALLS = {
    ("GET", "/auth/session"),
    ("POST", "/auth/second-factor/verify"),
    ("POST", "/auth/logout"),
}
ENROLMENT_CALLS = {
    ("GET", "/auth/session"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/reauthenticate"),
    ("GET", "/auth/second-factor"),
    ("POST", "/auth/second-factor/totp"),
    ("POST", "/auth/second-factor/totp/confirm"),
}


# --- reading -------------------------------------------------------------------------


def policy(conn: Connection, hub: Settings) -> str:
    return second_factor_policy(conn, hub)


def factor_of(conn: Connection, human_id: str, *, lock: bool = False) -> Any:
    query = select(t.second_factor).where(t.second_factor.c.human_id == human_id)
    return conn.execute(query.with_for_update() if lock else query).first()


def enrolled(factor: Any) -> bool:
    return factor is not None and factor.secret is not None


def owns_a_project(conn: Connection, human_id: str) -> bool:
    found = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.human_id == human_id,
            t.membership.c.role == "owner",
            t.membership.c.removed_at.is_(None),
        )
    ).first()
    return found is not None


def must_enrol(conn: Connection, hub: Settings, human_id: str) -> bool:
    """`required_admins` for an instance admin or a project owner, or after a reset,
    and no factor yet; never while the policy is `off` (§2.8.3, §2.8.5)."""
    current = policy(conn, hub)
    if current == "off":
        return False
    factor = factor_of(conn, human_id)
    if enrolled(factor):
        return False
    if factor is not None and factor.reset_required:
        return True
    return current == "required_admins" and (
        admin.is_instance_admin(conn, human_id) or owns_a_project(conn, human_id)
    )


def asks(conn: Connection, hub: Settings, human_id: str) -> bool:
    """Whether a sign-in of this human has a second step."""
    return policy(conn, hub) != "off" and enrolled(factor_of(conn, human_id))


# --- the session's state and the gate ------------------------------------------------


def state(conn: Connection, hub: Settings, row: Any) -> str:
    """The effective state of a live session: `full`, `second_factor`, `enrolment`, or
    `ended` / `expired` when the session has to end at this call."""
    off = policy(conn, hub) == "off"
    if row.state == "second_factor":
        if off:
            return "ended"  # §2.8.5: open second steps end when the policy turns off
        if clock.now() - row.created_at >= SECOND_STEP:
            return "expired"
        return "second_factor"
    if row.state == "enrolment" or must_enrol(conn, hub, row.human_id):
        if off and not row.sign_in_complete:
            return "ended"
        if not must_enrol(conn, hub, row.human_id):
            # The reason went away (the policy changed, the human enrolled elsewhere):
            # the sign-in completes as it is.
            if not row.sign_in_complete:
                sessions.complete_in_place(conn, row)
            return "full"
        return "enrolment"
    return "full"


def gate(conn: Connection, hub: Settings, caller: Caller, method: str, path: str) -> None:
    """Refuse every call a second-factor or enrolment session may not make, before any
    side effect of the route (§2.8.2, §2.8.5)."""
    if caller.kind != "human" or caller.human_session is None:
        return
    row = _session(conn, caller.human_session)
    current = state(conn, hub, row)
    if current == "full":
        return
    if current in ("ended", "expired"):
        by = "expired" if current == "expired" else "second_factor_disabled"
        sessions.end(conn, [row], by)
        raise unauthenticated("the sign-in has to start again")
    call = (method, path.removeprefix("/api/v1"))
    if current == "second_factor" and call not in SECOND_STEP_CALLS:
        raise refused("second_factor_required", "this session owes the second factor")
    if current == "enrolment" and call not in ENROLMENT_CALLS:
        raise refused(
            "second_factor_enrolment_required", "this session has to set up the second factor first"
        )


def _session(conn: Connection, id_hash: str) -> Any:
    return conn.execute(select(t.human_session).where(t.human_session.c.id_hash == id_hash)).one()


def session_view(conn: Connection, hub: Settings, row: Any) -> dict[str, Any] | None:
    """What `GET /auth/session` answers for a session that owes a step, else None."""
    current = state(conn, hub, row)
    if current not in ("second_factor", "enrolment"):
        return None
    if current == "second_factor":
        expires = row.created_at + SECOND_STEP
    else:
        expires = session_expires_at(row)
    return {
        "second_factor": "required" if current == "second_factor" else "enrolment_required",
        "session_id": row.public_id,
        "csrf_token": row.csrf_token,
        "expires_at": clock.rfc3339(expires),
    }


# --- after the first factor ----------------------------------------------------------


def begin(
    conn: Connection,
    hub: Settings,
    human_id: str,
    *,
    method: str,
    address: str,
    user_agent: str | None,
    approved_by: str | None = None,
    next_route: str | None = None,
) -> tuple[str, str, str, str]:
    """The session a completed first factor gets: (cookie value, CSRF token, public id,
    state). An enrolled human's goes to the second step; one the policy wants enrolled
    to enrolment; everyone else's is a full sign-in at once (§2.8.2, §2.8.5)."""
    if asks(conn, hub, human_id):
        chosen = "second_factor"
    elif must_enrol(conn, hub, human_id):
        chosen = "enrolment"
    else:
        chosen = "full"
    session_id, csrf, public_id = sessions.create(
        conn,
        human_id,
        method=method,
        address=address,
        user_agent=user_agent,
        approved_by=approved_by,
        state=chosen,
        next_route=next_route if chosen != "full" else None,
    )
    return session_id, csrf, public_id, chosen


# --- codes -----------------------------------------------------------------------------


def _key(hub: Settings) -> bytes:
    if hub.secret_key is None:
        raise ApiError(409, "secret_key_missing", "the instance has no MAITY_SECRET_KEY")
    return hub.secret_key


def _open(hub: Settings, sealed: bytes) -> bytes:
    try:
        return secretbox.open_sealed(_key(hub), SECRET_FIELD, sealed)
    except secretbox.SealedError:
        raise ApiError(
            409, "secret_key_missing", "MAITY_SECRET_KEY no longer opens the stored secrets"
        ) from None


def _recovery_hash(key: bytes, human_id: str, code: str) -> str:
    message = f"recovery_code\x00{human_id}\x00{code}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def normalised_recovery(code: str) -> str | None:
    """Case, spaces and the hyphen ignored, `i`/`l` read as `1`, `o` as `0`."""
    text = "".join(code.split()).replace("-", "").lower().translate(_CROCKFORD_READ)
    if len(text) != 10 or any(c not in _CROCKFORD for c in text):
        return None
    return text


def _new_recovery_codes(conn: Connection, key: bytes, human_id: str) -> list[str]:
    conn.execute(delete(t.recovery_code).where(t.recovery_code.c.human_id == human_id))
    codes = ["".join(secrets.choice(_CROCKFORD) for _ in range(10)) for _ in range(RECOVERY_CODES)]
    conn.execute(
        insert(t.recovery_code),
        [{"human_id": human_id, "code_hash": _recovery_hash(key, human_id, c)} for c in codes],
    )
    return [f"{c[:5]}-{c[5:]}" for c in codes]


def recovery_codes_left(conn: Connection, human_id: str) -> int:
    return len(
        conn.execute(
            select(t.recovery_code.c.code_hash).where(
                t.recovery_code.c.human_id == human_id, t.recovery_code.c.used_at.is_(None)
            )
        ).all()
    )


def _consume_totp(conn: Connection, hub: Settings, factor: Any, code: str) -> bool:
    """The code's step is consumed only if newer than the last one used, by a
    conditional update: of two concurrent checks with one code, one wins (§2.8.2)."""
    secret = _open(hub, factor.secret)
    step = totp.matching_step(secret, code, clock.now().timestamp(), factor.last_step)
    if step is None:
        return False
    last = t.second_factor.c.last_step
    done = conn.execute(
        update(t.second_factor)
        .where(
            t.second_factor.c.human_id == factor.human_id,
            last.is_(None) | (last < step),
        )
        .values(last_step=step, last_used_at=clock.now())
    )
    return done.rowcount == 1


def _consume_recovery(conn: Connection, hub: Settings, human_id: str, code: str) -> bool:
    text = normalised_recovery(code)
    if text is None:
        return False
    done = conn.execute(
        update(t.recovery_code)
        .where(
            t.recovery_code.c.human_id == human_id,
            t.recovery_code.c.code_hash == _recovery_hash(_key(hub), human_id, text),
            t.recovery_code.c.used_at.is_(None),
        )
        .values(used_at=clock.now())
    )
    if done.rowcount != 1:
        return False
    _move_generation(conn, human_id)
    return True


def check(
    conn: Connection,
    hub: Settings,
    human_id: str,
    *,
    code: str | None,
    recovery_code: str | None,
) -> str | None:
    """Check one code of an enrolled human: `totp` or `recovery_code` when right, None
    when wrong (counted against the human's limit). `rate_limited` once the limit is
    spent, before anything is checked (§2.8.6)."""
    wait = WRONG_BY_HUMAN.blocked(human_id)
    if wait:
        raise rate_limited(wait)
    factor = factor_of(conn, human_id)
    if not enrolled(factor):
        return None
    if code is not None and _consume_totp(conn, hub, factor, code):
        return "totp"
    if recovery_code is not None and _consume_recovery(conn, hub, human_id, recovery_code):
        changed(
            conn,
            human_id,
            "recovery_code_used",
            _handle(conn, human_id),
            recovery_codes_left=recovery_codes_left(conn, human_id),
        )
        return "recovery_code"
    WRONG_BY_HUMAN.hit(human_id)
    return None


def refused(reason: str, message: str) -> ApiError:
    return ApiError(403, "forbidden", message, {"reason": reason})


def code_invalid() -> ApiError:
    return ApiError(403, "code_invalid", "the code is wrong or was used")


# --- the second step of a sign-in ----------------------------------------------------


def verify(
    conn: Connection,
    hub: Settings,
    caller: Caller,
    *,
    code: str | None,
    recovery_code: str | None,
) -> tuple[str, str] | datetime | None:
    """`POST /auth/second-factor/verify`. From a second-factor session: the new cookie
    value and CSRF token of the completed sign-in. From a full session: a step-up, the
    time it is good until (§2.8.4). None for a wrong code, whose consequences — the
    count, the ended session, the alert — the caller commits before it refuses."""
    if caller.human_session is None:
        raise unauthenticated("this endpoint needs a dashboard session")
    if policy(conn, hub) == "off":
        raise refused("method_disabled", "the second factor is switched off")
    row = _session(conn, caller.human_session)
    human_id = row.human_id
    second_step = row.state == "second_factor"
    used = check(conn, hub, human_id, code=code, recovery_code=recovery_code)
    if used is None:
        if second_step:
            wrong = _wrong_in_session.get(row.id_hash, 0) + 1
            _wrong_in_session[row.id_hash] = wrong
            if wrong >= WRONG_PER_SESSION:
                _wrong_in_session.pop(row.id_hash, None)
                failed(conn, human_id, row.method, row.ip, row.browser, row.os)
                sessions.end(conn, [row], "revoked")
        elif WRONG_BY_HUMAN.blocked(human_id):
            # The tenth wrong step-up code in the window is told too (§2.8.2).
            failed(conn, human_id, "step_up", row.ip, row.browser, row.os)
        return None  # the caller commits what a wrong code caused, then refuses
    if second_step:
        _wrong_in_session.pop(row.id_hash, None)
        try:
            return sessions.complete_sign_in(conn, row, used)
        except LookupError:
            raise code_invalid() from None
    now = clock.now()
    conn.execute(
        update(t.human_session)
        .where(t.human_session.c.id_hash == row.id_hash)
        .values(second_factor_at=now)
    )
    return now + FRESH


# --- step-up ---------------------------------------------------------------------------


def require_step_up(conn: Connection, hub: Settings, caller: Caller) -> None:
    """A sensitive call of an enrolled human needs the factor within the last 10
    minutes on the calling session (§2.8.4); otherwise it changes nothing."""
    if caller.kind != "human" or caller.human_session is None:
        return
    if not asks(conn, hub, caller.principal_id):
        return
    row = _session(conn, caller.human_session)
    if row.second_factor_at is None or clock.now() - row.second_factor_at >= FRESH:
        raise refused("step_up_required", "this call needs your second factor first")


# --- enrolment ---------------------------------------------------------------------------


def require_proof(conn: Connection, caller: Caller) -> Any:
    """§2.8.1: the password within the last 10 minutes on the calling session, or, for an
    account without one, a session in good standing at least 24 hours old. Returns the
    session row."""
    if caller.human_session is None:
        raise unauthenticated("this endpoint needs a dashboard session")
    row = _session(conn, caller.human_session)
    human = conn.execute(select(t.human).where(t.human.c.id == row.human_id)).one()
    now = clock.now()
    if has_password(human):
        if row.password_at is None or now - row.password_at >= FRESH:
            raise refused("reauthentication_required", "give your password again first")
        return row
    confirmed = sessions.confirmed_sessions(conn, row.human_id)
    if not sessions.good_standing(row, confirmed):
        raise refused("not_in_good_standing", "only a session in good standing may do this")
    if now - row.created_at < TRUSTED_AGE:
        raise refused("session_too_new", "this session is too new for this")
    return row


def has_password(human: Any) -> bool:
    return bool(human.password_hash) and human.password_hash != passwords.DUMMY_HASH


def reauthenticate(conn: Connection, caller: Caller, password: str) -> datetime:
    """`POST /auth/reauthenticate`: the password given again on this session."""
    if caller.human_session is None:
        raise unauthenticated("this endpoint needs a dashboard session")
    human = conn.execute(select(t.human).where(t.human.c.id == caller.principal_id)).one()
    if not has_password(human) or not passwords.verify_password(password, human.password_hash):
        raise invalid({"password": "mismatch"}, "the password is wrong")
    now = clock.now()
    conn.execute(
        update(t.human_session)
        .where(t.human_session.c.id_hash == caller.human_session)
        .values(password_at=now)
    )
    return now + FRESH


def start(conn: Connection, hub: Settings, caller: Caller, issuer: str) -> dict[str, Any]:
    """`POST /auth/second-factor/totp`: a new secret, shown this once."""
    key = _key(hub)
    if policy(conn, hub) == "off":
        raise refused("method_disabled", "the second factor is switched off")
    row = require_proof(conn, caller)
    human_id = row.human_id
    if enrolled(factor_of(conn, human_id)):
        require_step_up(conn, hub, caller)  # enrolling again (§2.8.1)
    wait = ENROLMENTS_BY_HUMAN.hit(human_id)
    if wait:
        raise rate_limited(wait)
    secret = totp.new_secret()
    values = {
        "pending_secret": secretbox.seal(key, SECRET_FIELD, secret),
        "pending_session": row.id_hash,
        "pending_expires_at": clock.now() + ENROLMENT,
    }
    _ensure_row(conn, human_id)
    conn.execute(
        update(t.second_factor).where(t.second_factor.c.human_id == human_id).values(**values)
    )
    handle = conn.execute(select(t.human.c.handle).where(t.human.c.id == human_id)).scalar_one()
    return {
        "secret": totp.base32(secret),
        "otpauth_uri": totp.uri(secret, handle, issuer),
        "expires_in": int(ENROLMENT.total_seconds()),
    }


def confirm(conn: Connection, hub: Settings, caller: Caller, code: str) -> dict[str, Any]:
    """`POST /auth/second-factor/totp/confirm`: a current code turns the started
    enrolment on; the old factor, if any, stays valid until now (§2.8.1)."""
    key = _key(hub)
    if caller.human_session is None:
        raise unauthenticated("this endpoint needs a dashboard session")
    human_id = caller.principal_id
    wait = WRONG_BY_HUMAN.blocked(human_id)
    if wait:
        raise rate_limited(wait)
    factor = factor_of(conn, human_id, lock=True)
    now = clock.now()
    if (
        factor is None
        or factor.pending_secret is None
        or factor.pending_session != caller.human_session
        or factor.pending_expires_at is None
        or factor.pending_expires_at <= now
    ):
        raise code_invalid()
    secret = _open(hub, factor.pending_secret)
    step = totp.matching_step(secret, code, now.timestamp(), None)
    if step is None:
        WRONG_BY_HUMAN.hit(human_id)
        raise code_invalid()
    conn.execute(
        update(t.second_factor)
        .where(t.second_factor.c.human_id == human_id)
        .values(
            secret=factor.pending_secret,
            enrolled_at=now,
            last_step=step,
            last_used_at=now,
            pending_secret=None,
            pending_session=None,
            pending_expires_at=None,
            reset_required=False,
            generation=factor.generation + 1,
        )
    )
    codes = _new_recovery_codes(conn, key, human_id)
    row = _session(conn, caller.human_session)
    completion = None
    if not row.sign_in_complete:
        # An enrolment session's sign-in completes as the verify's does (§2.8.5).
        completion = sessions.complete_sign_in(conn, row, "totp")
    else:
        conn.execute(
            update(t.human_session)
            .where(t.human_session.c.id_hash == row.id_hash)
            .values(second_factor_at=now, state="full")
        )
    changed(conn, human_id, "enrolled", _handle(conn, human_id))
    return {"recovery_codes": codes, "completion": completion}


def regenerate(conn: Connection, hub: Settings, caller: Caller) -> list[str]:
    key = _key(hub)
    require_proof(conn, caller)
    require_step_up(conn, hub, caller)
    human_id = caller.principal_id
    if not enrolled(factor_of(conn, human_id, lock=True)):
        raise ApiError(409, "conflict", "no second factor is enrolled")
    codes = _new_recovery_codes(conn, key, human_id)
    _move_generation(conn, human_id)
    changed(conn, human_id, "recovery_codes", _handle(conn, human_id))
    return codes


def disable(conn: Connection, hub: Settings, caller: Caller) -> None:
    """`DELETE /auth/second-factor`: off, and every other session ends (§2.8.1)."""
    if policy(conn, hub) == "off":
        raise refused("method_disabled", "the second factor is switched off")
    require_proof(conn, caller)
    require_step_up(conn, hub, caller)
    human_id = caller.principal_id
    if not enrolled(factor_of(conn, human_id, lock=True)):
        raise ApiError(409, "conflict", "no second factor is enrolled")
    if policy(conn, hub) == "required_admins" and (
        admin.is_instance_admin(conn, human_id) or owns_a_project(conn, human_id)
    ):
        raise refused("second_factor_required", "the instance requires your second factor")
    remove(conn, human_id)
    sessions.end_where(
        conn,
        (t.human_session.c.human_id == human_id)
        & (t.human_session.c.id_hash != caller.human_session),
        "second_factor_disabled",
    )
    changed(conn, human_id, "disabled", _handle(conn, human_id))


def remove(conn: Connection, human_id: str, *, reset: bool = False) -> None:
    """The factor and its recovery codes go; the generation moves."""
    conn.execute(delete(t.recovery_code).where(t.recovery_code.c.human_id == human_id))
    _ensure_row(conn, human_id)
    conn.execute(
        update(t.second_factor)
        .where(t.second_factor.c.human_id == human_id)
        .values(
            secret=None,
            enrolled_at=None,
            last_step=None,
            pending_secret=None,
            pending_session=None,
            pending_expires_at=None,
            reset_required=reset,
            generation=t.second_factor.c.generation + 1,
        )
    )


def view(conn: Connection, hub: Settings, human_id: str) -> dict[str, Any]:
    factor = factor_of(conn, human_id)
    on = enrolled(factor)
    return {
        "enrolled": on,
        "enrolled_at": clock.rfc3339(factor.enrolled_at) if on else None,
        "recovery_codes_left": recovery_codes_left(conn, human_id) if on else 0,
        "last_used_at": (
            clock.rfc3339(factor.last_used_at) if on and factor.last_used_at else None
        ),
        "required": must_enrol(conn, hub, human_id)
        or (
            on
            and policy(conn, hub) == "required_admins"
            and (admin.is_instance_admin(conn, human_id) or owns_a_project(conn, human_id))
        ),
    }


def _ensure_row(conn: Connection, human_id: str) -> None:
    if factor_of(conn, human_id) is None:
        conn.execute(insert(t.second_factor).values(human_id=human_id))


def _move_generation(conn: Connection, human_id: str) -> None:
    conn.execute(
        update(t.second_factor)
        .where(t.second_factor.c.human_id == human_id)
        .values(generation=t.second_factor.c.generation + 1)
    )


def _handle(conn: Connection, human_id: str) -> str:
    return str(conn.execute(select(t.human.c.handle).where(t.human.c.id == human_id)).scalar_one())


# --- telling the human -------------------------------------------------------------------


def changed(conn: Connection, human_id: str, change: str, by: str, **extra: Any) -> None:
    """`second_factor_changed`, a security notification with a security mail (§2.8.1)."""
    records.write(conn, human_id, "second_factor_changed", {"change": change, "by": by, **extra})


def failed(
    conn: Connection,
    human_id: str,
    method: str,
    ip: str | None,
    browser: str | None,
    os: str | None,
) -> None:
    records.write(
        conn,
        human_id,
        "second_factor_failed",
        {"method": method, "ip": ip, "browser": browser, "os": os},
    )


def told_instance_off(conn: Connection, by: str) -> None:
    """Every enrolled human learns the instance turned the factor off (§2.8.5)."""
    who = conn.execute(select(t.human.c.handle).where(t.human.c.id == by)).scalar() or by
    for human_id in conn.execute(
        select(t.second_factor.c.human_id).where(t.second_factor.c.secret.is_not(None))
    ).scalars():
        changed(conn, human_id, "instance_off", who)
