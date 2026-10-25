"""Registration, part 2 (docs/api.md §2.7.1 step 6, §2.7.4, §2.7.5, §16.4): completing a
pending registration into an account, and the accounts that wait for approval.

Completion runs as one transaction under the address's lock, the lock registration and
the address verification of §18.4 share. The admission is checked again there: the mode,
the lists, a block and an admitting invitation are read as they are at that moment, not
as they were when the mail went out. Whatever refuses after the password was checked
leaves nothing behind but the voided pending registration, or the pending registration
as it was where the contract keeps it (a wrong password, a taken handle, changed terms,
the hourly cap).
"""

from __future__ import annotations

import logging
import re
import secrets
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Engine, delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock, invitations, registration
from maity_hub import tables as t
from maity_hub.admin import instance_admin_id
from maity_hub.auth import passwords, sessions
from maity_hub.auth.caller import SESSION_ABSOLUTE, session_id_hash
from maity_hub.ids import new_id
from maity_hub.models import HANDLE_PATTERN

WRONG_PASSWORDS_BEFORE_VOID = 5  # §2.7.3
PENDING_ACCOUNT_FOR = timedelta(days=30)  # undecided, then deleted (§2.7.5)
BLOCK_FOR = timedelta(days=30)  # after a rejection or an expiry (§16.4)
DISPLAY_NAME_MAX = 64
REASON_MAX = 1024
PENDING_PAGE = "/#/pending"
# A `registration_lock` key no address can be (it has no `@`): the instance-wide budget.
BUDGET_LOCK = "*new-accounts-per-hour*"
_HANDLE = re.compile(HANDLE_PATTERN)
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Completion:
    """What a completion came to; the link page turns it into its answer.

    `kind` is `created`, `closed` (no longer admitted: the page says registration is
    closed), `gone` (the link no longer works, never why), `wrong_password`, `invalid`
    (`fields` names them), `terms_changed` (show the current terms again) or `later`
    (the hourly cap: try again later, the pending registration kept)."""

    kind: str
    fields: dict[str, str] = field(default_factory=dict)
    human_id: str | None = None
    account_status: str | None = None
    next: str | None = None
    session_id: str | None = None
    csrf: str | None = None


def claim_address(conn: Connection, normalized: str, human_id: str) -> bool:
    """Write the address as the account's verified address (§18.4), unique across the
    accounts; False when another account holds it. Fails closed: until the verified
    address is stored, no completion can claim one, so none creates an account."""
    # TODO(#280): insert the verified address under the unique normalized-address
    # constraint of §18.4 and answer False when it refuses.
    del conn, normalized, human_id
    return False


def admitted(
    conn: Connection, resolved: registration.Resolved, given: str, *, lock: bool = False
) -> bool:
    """§2.7.1: the mode and the lists, or an open address-bound invitation that admits;
    with `lock` (completion) the invitations stay as read until the account exists."""
    if resolved.allows(given):
        return True
    return resolved.mail_ready and invitations.admits_address(
        conn, registration.normalized(given), lock=lock
    )


def _blocked(conn: Connection, normalized: str, now: Any) -> bool:
    return (
        conn.execute(
            select(t.registration_block.c.until).where(
                t.registration_block.c.address_normalized == normalized,
                t.registration_block.c.until > now,
            )
        ).first()
        is not None
    )


def check_names(conn: Connection, handle: str, display_name: str) -> dict[str, str]:
    """§2.7.4: the handle's syntax and uniqueness among humans, the display name."""
    errors: dict[str, str] = {}
    if not _HANDLE.fullmatch(handle):
        errors["handle"] = "invalid"
    elif conn.execute(select(t.human.c.id).where(t.human.c.handle == handle)).first():
        errors["handle"] = "taken"
    if not 1 <= len(display_name) <= DISPLAY_NAME_MAX or any(
        ord(c) < 32 or ord(c) == 127 for c in display_name
    ):
        errors["display_name"] = "invalid"
    return errors


def _void(conn: Connection, pending_id: str, now: Any) -> None:
    conn.execute(
        update(t.pending_registration)
        .where(t.pending_registration.c.id == pending_id)
        .values(voided_at=now)
    )


def complete(
    conn: Connection,
    resolve: Callable[[Connection], registration.Resolved],
    pending_id: str,
    *,
    password: str,
    handle: str,
    display_name: str,
    terms_seen: str | None,
    terms_accepted: bool,
    source: str,
    user_agent: str | None = None,
) -> Completion:
    """§2.7.1 step 6, in its order. The caller has checked the link's signature and
    nonce (§18.6) and holds the transaction; this commits nothing itself. `resolve`
    reads the registration settings, called under the address's lock, so the admission
    decided on is the one in force when the account is made."""
    now = clock.now()
    found = conn.execute(
        select(t.pending_registration.c.address_normalized).where(
            t.pending_registration.c.id == pending_id
        )
    ).first()
    if found is None:
        return Completion("gone")
    from maity_hub.routes.registration import lock_address

    lock_address(conn, found.address_normalized)  # first: the claim's lock (§2.7.1)
    pending = conn.execute(
        select(t.pending_registration).where(t.pending_registration.c.id == pending_id)
    ).first()
    if pending is None or pending.voided_at is not None or pending.expires_at <= now:
        return Completion("gone")
    normalized = pending.address_normalized
    resolved = resolve(conn)
    # Before the operator's account exists, a registered account would be the earliest
    # human and so the instance admin (§16): until then the instance registers nobody.
    if (
        instance_admin_id(conn) is None
        or not admitted(conn, resolved, pending.address, lock=True)
        or _blocked(conn, normalized, now)
    ):
        _void(conn, pending.id, now)
        return Completion("closed")
    if not passwords.verify_password(password, pending.password_hash):
        wrong = pending.wrong_passwords + 1
        values: dict[str, Any] = {"wrong_passwords": wrong}
        if wrong >= WRONG_PASSWORDS_BEFORE_VOID:
            values["voided_at"] = now
        conn.execute(
            update(t.pending_registration)
            .where(t.pending_registration.c.id == pending.id)
            .values(**values)
        )
        return Completion("wrong_password")
    errors = check_names(conn, handle, display_name)
    terms = resolved.value("terms")
    if terms is not None and not terms_accepted:
        errors["terms"] = "required"
    if errors:
        return Completion("invalid", fields=errors)
    if terms is not None and terms_seen != terms["version"]:
        return Completion("terms_changed")  # nothing created, no acceptance (§2.7.2)
    # The instance's hourly budget: one lock every completion takes, after its address's
    # and held until the account exists, so two addresses never both take the last place.
    lock_address(conn, BUDGET_LOCK)
    if _registered_last_hour(conn, now) >= resolved.value("max_new_accounts_per_hour"):
        return Completion("later")
    human_id = new_id("human")
    status = "pending" if resolved.value("approval") == "operator" else "active"
    made = conn.begin_nested()  # the account and its address claim, or neither
    try:
        conn.execute(
            insert(t.human).values(
                id=human_id,
                handle=handle,
                display_name=display_name,
                password_hash=pending.password_hash,
                created_at=now,
                last_login_at=now,
                last_seen_at=now,
                account_status=status,
                registered_at=now,
                terms_version=terms["version"] if terms is not None else None,
                terms_accepted_at=now if terms is not None else None,
            )
        )
    except IntegrityError:  # the handle taken meanwhile, after the check above
        made.rollback()
        return Completion("invalid", fields={"handle": "taken"})
    if not claim_address(conn, normalized, human_id):
        made.rollback()
        _void(conn, pending.id, now)  # a loser: as an expired link, never why (§2.7.1)
        return Completion("gone")
    made.commit()
    if status == "pending":
        conn.execute(
            insert(t.account_registration).values(
                human_id=human_id,
                address=pending.address,
                address_normalized=normalized,
                source_ip=pending.source_ip,
                created_at=now,
                expires_at=now + PENDING_ACCOUNT_FOR,
                status="pending",
            )
        )
        # TODO(#280): the `registration_pending` account record for every instance
        # admin (§16.4, §18.1), through the notification store.
    conn.execute(  # this one used, every other of the address unusable (§2.7.1)
        update(t.pending_registration)
        .where(
            t.pending_registration.c.address_normalized == normalized,
            t.pending_registration.c.voided_at.is_(None),
        )
        .values(voided_at=now)
    )
    session_id, csrf = start_session(conn, human_id, source, user_agent)
    return Completion(
        "created",
        human_id=human_id,
        account_status=status,
        next=PENDING_PAGE if status == "pending" else registration.safe_next(pending.next),
        session_id=session_id,
        csrf=csrf,
    )


def _registered_last_hour(conn: Connection, now: Any) -> int:
    return int(
        conn.execute(
            select(func.count())
            .select_from(t.human)
            .where(t.human.c.registered_at > now - timedelta(hours=1))
        ).scalar_one()
    )


def start_session(
    conn: Connection, human_id: str, source: str, user_agent: str | None = None
) -> tuple[str, str]:
    """A fresh dashboard session (§2.1), `method: "register"` in the session list
    (§2.6.5): the session id and its CSRF token. The link page sets the cookies."""
    now = clock.now()
    browser, system = sessions.describe(user_agent)
    session_id, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)
    conn.execute(
        insert(t.human_session).values(
            id_hash=session_id_hash(session_id),
            human_id=human_id,
            csrf_token=csrf,
            created_at=now,
            last_seen_at=now,
            expires_at=now + SESSION_ABSOLUTE,
            source=source[:64],
            public_id=new_id("human_session"),
            method="register",
            browser=browser,
            os=system,
            ip=source[:64],
        )
    )
    return session_id, csrf


# --- the accounts that wait (§16.4) -----------------------------------------------------


def item(conn: Connection, row: Any) -> dict[str, Any]:
    """A pending account as the instance admin decides on it."""
    human = conn.execute(select(t.human).where(t.human.c.id == row.human_id)).first()
    found = {
        "id": row.human_id,
        "handle": human.handle if human is not None else None,
        "display_name": human.display_name if human is not None else None,
        "address": row.address,
        "created_at": clock.rfc3339(row.created_at),
        "expires_at": clock.rfc3339(row.expires_at),
        "source_ip": row.source_ip,
        "terms": (
            {
                "version": human.terms_version,
                "accepted_at": clock.rfc3339(human.terms_accepted_at),
            }
            if human is not None and human.terms_version is not None
            else None
        ),
    }
    return found


def locked(conn: Connection, human_id: str) -> Any:
    """The row, taken for this transaction: two admins deciding at once go in turn."""
    return conn.execute(
        select(t.account_registration)
        .where(t.account_registration.c.human_id == human_id)
        .with_for_update()
    ).first()


def approve(conn: Connection, row: Any, by: str) -> None:
    now = clock.now()
    conn.execute(
        update(t.human).where(t.human.c.id == row.human_id).values(account_status="active")
    )
    conn.execute(
        update(t.account_registration)
        .where(t.account_registration.c.human_id == row.human_id)
        .values(status="active", decided_at=now, decided_by=by)
    )
    # TODO(#280): the mail "Your Maity account is approved" with the login page's link
    # (security budget, §16.2) and the `registration_approved` account record (§18.1).


def remove(conn: Connection, row: Any, status: str, by: str | None, reason: str | None) -> None:
    """Delete the pending account with its sessions and block its address for 30 days:
    a rejection (`by`, `reason`) or an expiry (§2.7.5). The row keeps the decision and
    the reason, no longer the address or where the request came from."""
    now = clock.now()
    conn.execute(delete(t.human_session).where(t.human_session.c.human_id == row.human_id))
    conn.execute(delete(t.human).where(t.human.c.id == row.human_id))
    block(conn, row.address_normalized, now + BLOCK_FOR)
    conn.execute(
        update(t.account_registration)
        .where(t.account_registration.c.human_id == row.human_id)
        .values(
            status=status,
            decided_at=now,
            decided_by=by,
            reason=reason,
            address=None,
            address_normalized=None,
            source_ip=None,
        )
    )
    # TODO(#280): mail the person — `reason` on a rejection, "was not approved in time"
    # on an expiry (security budget, §16.2) — and the `registration_rejected` record.


def block(conn: Connection, normalized: str, until: Any) -> None:
    """Block an address from registering until `until`, extending an earlier block."""
    found = conn.execute(
        select(t.registration_block.c.until)
        .where(t.registration_block.c.address_normalized == normalized)
        .with_for_update()
    ).first()
    if found is None:
        conn.execute(
            insert(t.registration_block).values(
                address_normalized=normalized, until=until, created_at=clock.now()
            )
        )
    elif found.until < until:
        conn.execute(
            update(t.registration_block)
            .where(t.registration_block.c.address_normalized == normalized)
            .values(until=until)
        )


def expire(conn: Connection) -> int:
    """Delete every pending account nobody decided on within 30 days (§2.7.5)."""
    now = clock.now()
    due = conn.execute(
        select(t.account_registration.c.human_id).where(
            t.account_registration.c.status == "pending",
            t.account_registration.c.expires_at <= now,
        )
    ).scalars()
    count = 0
    for human_id in list(due):
        row = locked(conn, human_id)
        if row is not None and row.status == "pending" and row.expires_at <= now:
            remove(conn, row, "expired", None, None)
            count += 1
    return count


INTERVAL = 3600.0  # seconds between expiry sweeps


class Worker:
    """Runs `expire` in the background: an undecided account goes after 30 days whether
    or not an instance admin looks (§2.7.5)."""

    def __init__(self, engine: Engine, interval: float | None = None) -> None:
        self.engine = engine
        self.interval = INTERVAL if interval is None else interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-registrations", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                with self.engine.begin() as conn:
                    expire(conn)
            except Exception:
                log.exception("the registration expiry sweep failed")
