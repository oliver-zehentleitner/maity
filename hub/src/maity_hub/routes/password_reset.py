"""A forgotten password, reset by mail (docs/api.md §2.10): the anonymous request, and the
reset page's two calls.

The request always answers `202` before it looks the address up; the lookup and the mail run
in the background. `check` changes nothing. `complete` sets the password in one transaction,
ends every session of the human and signs nobody in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, Engine, select, update

from maity_hub import account_deletion, catalog, clock
from maity_hub import tables as t
from maity_hub.auth import email_links, passwords, second_factor, sessions, sign_in_settings
from maity_hub.auth import password_resets as resets
from maity_hub.config import Settings
from maity_hub.deps import engine_of, origin_of, settings_of
from maity_hub.errors import ApiError, invalid, rate_limited
from maity_hub.mail import address, outbox
from maity_hub.notifications import preferences, records
from maity_hub.routes import auth
from maity_hub.routes.auth import Strict
from maity_hub.routes.email_sign_in import _anonymous

router = APIRouter(prefix="/auth/password-reset")
LIMITS = resets.RequestLimits()
ENDED_BY = "password_reset"


class ResetRequest(Strict):
    address: str = Field(max_length=254)


class ResetCheck(Strict):
    token: str = Field(max_length=4096)


class ResetComplete(Strict):
    token: str = Field(max_length=4096)
    new: str = Field(min_length=1, max_length=1024)
    code: str | None = Field(default=None, max_length=128)
    recovery_code: str | None = Field(default=None, max_length=128)


def _enabled(conn: Connection, hub: Settings) -> None:
    """The instance's switch: off, the three calls are `method_disabled` (§2.10)."""
    if not sign_in_settings.password_reset_enabled(conn, hub):
        raise ApiError(
            403, "forbidden", "the password reset is switched off", {"reason": "method_disabled"}
        )


def _refused() -> ApiError:
    """Every dead token and every wrong code alike, never which reason (§2.10)."""
    return ApiError(403, "code_invalid", "this link or code does not work")


# --- asking --------------------------------------------------------------------------------


@router.post("")
def request_reset(
    body: ResetRequest, request: Request, background: BackgroundTasks
) -> JSONResponse:
    _anonymous(request)
    hub, engine = settings_of(request), engine_of(request)
    with engine.begin() as conn:
        _enabled(conn, hub)
    origin = origin_of(request)
    wait, allowed = LIMITS.take(body.address, origin.address)
    if wait:
        raise rate_limited(wait)
    if allowed:
        background.add_task(
            deliver,
            engine,
            hub,
            body.address,
            origin.address,
            request.headers.get("user-agent"),
            clock.now(),
        )
    # No cookie: a reset signs nobody in (§2.10).
    return JSONResponse({"expires_in": int(resets.LIFETIME.total_seconds())}, status_code=202)


def _eligible(conn: Connection, hub: Settings, human_id: str) -> tuple[Any, Any] | None:
    """The human and their mail settings while a reset mail may go to them: active, not
    suspended, with a password, a verified address, their own switch on, and the instance
    offering the reset (§2.10)."""
    human = conn.execute(select(t.human).where(t.human.c.id == human_id)).first()
    row = conn.execute(
        select(t.notification_settings)
        .where(t.notification_settings.c.human_id == human_id)
        .with_for_update()
    ).first()
    if (
        human is None
        or not _active(human)
        or not second_factor.has_password(human)
        or row is None
        or row.address_status != "verified"
        or row.address is None
        or not preferences.preferences(conn, human_id)["email"]["password_reset"]
        or not sign_in_settings.view(conn, hub)["password_reset_available"]
    ):
        return None
    return human, row


def _active(human: Any) -> bool:
    return bool(human.account_status == "active" and human.suspended_at is None)


def deliver(
    engine: Engine,
    hub: Settings,
    given: str,
    source: str,
    user_agent: str | None,
    requested_at: datetime,
) -> None:
    """Runs after the response is sent; no lookup of an address on the response path."""
    if not address.valid(given.strip()):
        return
    with engine.begin() as conn:
        human_id = conn.execute(
            select(t.notification_settings.c.human_id).where(
                t.notification_settings.c.address_normalized == address.normalized(given)
            )
        ).scalar()
        if human_id is None:
            return
        email_links.lock_human(conn, human_id)
        found = _eligible(conn, hub, human_id)
        # The address may have changed after the lookup without a lock.
        if found is None or found[1].address_normalized != address.normalized(given):
            return
        human, row = found
        key = hub.mail.signing_key
        assert key is not None  # `password_reset_available` holds only with it
        issued = resets.issue(conn, human_id=human_id, source=source, requested_at=requested_at)
        if issued is None:
            return
        token = resets.token(key, human_id, issued, human.password_generation, row.epoch)
        language = preferences.text_language(conn, human_id)
        browser, system = sessions.describe(user_agent)
        words = catalog.section("password_reset", language)
        mail_only = (
            second_factor.via(conn, hub, human_id) == "email"
            and second_factor.policy(conn, hub) == "email"
        )
        body = words["mail"].format(
            name=" ".join(human.display_name.split()),
            link=f"{hub.public_url.rstrip('/')}/sign-in/reset#{token}",
            requested_at=clock.rfc3339(requested_at),
            browser=browser or "?",
            system=system or "?",
            address=source,
            mailbox=words["mail_mailbox"] if mail_only else "",
        )
        outbox.enqueue(
            conn,
            kind="password_reset",
            to=row.address,
            human_id=human_id,
            subject=words["subject"],
            body=body,
        )


# --- the reset page ------------------------------------------------------------------------


def _live(conn: Connection, hub: Settings, token: str, *, lock: bool) -> tuple[Any, Any] | None:
    """The token's row and its human while the token holds: signed, unexpired, unused, of the
    current password and address, of an account still active (§2.10). None otherwise."""
    payload = resets.read(hub.mail.signing_key, token)
    if payload is None:
        return None
    if lock:
        email_links.lock_human(conn, payload["h"])  # issue, guesses and use, one at a time
    row = resets.live(conn, payload)
    human = conn.execute(select(t.human).where(t.human.c.id == payload["h"])).first()
    epoch = conn.execute(
        select(t.notification_settings.c.epoch).where(
            t.notification_settings.c.human_id == payload["h"]
        )
    ).scalar()
    if (
        row is None
        or human is None
        or not _active(human)
        or human.password_generation != payload["g"]
        or epoch != payload["e"]
    ):
        return None
    return row, human


def _factor(conn: Connection, hub: Settings, human_id: str) -> str | None:
    """What the reset asks for or says: a human's stored TOTP enrolment counts under any
    policy, `off` included; the mail is the factor only under `email` (§2.10)."""
    if second_factor.enrolled(second_factor.factor_of(conn, human_id)):
        return "totp"
    if second_factor.policy(conn, hub) == "email":
        return "email"
    return None


def _page_limit(request: Request) -> None:
    wait = auth.LOGIN_BY_ADDRESS.hit(origin_of(request).address)  # shared with the login
    if wait:
        raise rate_limited(wait)


@router.post("/check")
def check(body: ResetCheck, request: Request) -> JSONResponse:
    _anonymous(request)
    _page_limit(request)
    hub = settings_of(request)
    with engine_of(request).begin() as conn:
        _enabled(conn, hub)
        found = _live(conn, hub, body.token, lock=False)
        if found is None:
            raise _refused()
        _, human = found
        return JSONResponse(
            {
                "display_name": human.display_name,
                "handle": human.handle,
                "factor": _factor(conn, hub, human.id),
            }
        )


@router.post("/complete")
def complete(body: ResetComplete, request: Request) -> JSONResponse:
    _anonymous(request)
    _page_limit(request)
    if len(body.new) < passwords.MIN_LENGTH:
        raise invalid({"new": "too_short"}, "a password has at least 12 characters")
    hub = settings_of(request)
    browser, system = sessions.describe(request.headers.get("user-agent"))
    with engine_of(request).begin() as conn:
        _enabled(conn, hub)
        # A refusal still commits: the count of a wrong code and an alarm stay.
        done = _complete(conn, hub, body, origin_of(request).address, browser, system)
    if not done:
        raise _refused()
    return JSONResponse({})


def _complete(
    conn: Connection,
    hub: Settings,
    body: ResetComplete,
    ip: str,
    browser: str | None,
    system: str | None,
) -> bool:
    """The reset in the caller's transaction; False is a refusal. One winner per token twice
    over: the human's lock, and `use` that takes only an unused row."""
    # The token first: a dead one answers without comparing or counting a code, so
    # whoever kept an old link cannot void the human's new ones (§2.10).
    found = _live(conn, hub, body.token, lock=True)
    if found is None:
        return False
    row, human = found
    if _factor(conn, hub, human.id) == "totp" and not _code_right(
        conn, hub, human.id, body, ip, browser, system
    ):
        return False
    if not resets.use(conn, row):
        return False
    _reset(conn, human.id, body.new, ip, browser, system)
    return True


def _code_right(
    conn: Connection,
    hub: Settings,
    human_id: str,
    body: ResetComplete,
    ip: str,
    browser: str | None,
    system: str | None,
) -> bool:
    """The TOTP or recovery code of an enrolled human, consumed as at the sign-in step (one
    winner, §2.8.2) and counted as every second-factor code (§2.8.6). Without a usable instance
    key this fails closed with the sign-in step's answer. A wrong one also counts over 24 hours
    across links; the fifth and every further one voids every open link and alarms."""
    if body.code is None and body.recovery_code is None:
        return False  # no guess: refused, neither compared nor counted
    used = second_factor.check(
        conn, hub, human_id, code=body.code, recovery_code=body.recovery_code
    )
    if used is not None:
        return True
    if resets.wrong_code(conn, human_id) >= resets.WRONG_ALARM:
        resets.void_human(conn, human_id)
        second_factor.failed(conn, human_id, "password_reset", ip, browser, system)
    return False


def _reset(
    conn: Connection,
    human_id: str,
    new: str,
    ip: str,
    browser: str | None,
    system: str | None,
) -> None:
    """The new password and all it ends (§2.10): every session, however made, and with them
    their device codes and the mail factor's links; every sign-in link and reset link; an
    unconfirmed new address; a pending account deletion. Agent credentials stay."""
    conn.execute(
        update(t.human)
        .where(t.human.c.id == human_id)
        .values(password_hash=passwords.hash_password(new))
    )
    resets.password_changed(conn, human_id)  # the generation moves, the open links die
    sessions.end_where(conn, t.human_session.c.human_id == human_id, ENDED_BY)
    email_links.void_human(conn, human_id)
    preferences.void_pending_address(conn, human_id)
    account_deletion.withdraw(conn, human_id, ENDED_BY)
    records.write(conn, human_id, "password_reset", {"ip": ip, "browser": browser, "os": system})
