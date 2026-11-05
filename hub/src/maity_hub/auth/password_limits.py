"""Wrong passwords (docs/api.md §2.1). The login counts them per account; once five are in the
window, the password signs in for the rest of it only from a known source of the account, and
every other source is told to take the link or to wait. The password change, the
re-authentication and the address change count in buckets of their own, so a session's wrong
attempts pause nobody's sign-in.

Every bucket takes the attempt before the password is compared and gives it back when it is
right (`ratelimit.Attempt`): logins running at the same time never get past the limit together.
"""

from __future__ import annotations

from types import TracebackType

from sqlalchemy import Connection

from maity_hub.auth import known_sources, sign_in_settings
from maity_hub.config import Settings
from maity_hub.errors import ApiError
from maity_hub.ratelimit import Limiter, Mark

WRONG = 5
WINDOW = 15 * 60

LOGIN = Limiter(WRONG, WINDOW, name="auth.password_limits.LOGIN")  # per account
LOGIN_FROM = Limiter(WRONG, WINDOW, name="auth.password_limits.LOGIN_FROM")  # per account+source
CHANGE = Limiter(WRONG, WINDOW, name="auth.password_limits.CHANGE")
REAUTHENTICATE = Limiter(WRONG, WINDOW, name="auth.password_limits.REAUTHENTICATE")
ADDRESS_CHANGE = Limiter(WRONG, WINDOW, name="auth.password_limits.ADDRESS_CHANGE")
ALL = (LOGIN, LOGIN_FROM, CHANGE, REAUTHENTICATE, ADDRESS_CHANGE)


def account_key(conn: Connection, human_id: str | None, normalized_address: str) -> str:
    """The login's bucket: the account's id, or for an address of no account its keyed
    fingerprint (`known_sources.fingerprint`), so that the count's rows never hold an address
    nor a plain hash a guess could be checked against. Without a key, one bucket for them all."""
    if human_id is not None:
        return human_id
    return "address:" + (known_sources.fingerprint(conn, normalized_address) or "unkeyed")


def paused(conn: Connection, hub: Settings, wait: int) -> ApiError:
    """The answer to a password from a source that is not known while the account's limit is
    spent: the link where the instance offers it (§2.6.1), else when to try again."""
    if sign_in_settings.view(conn, hub)["email_link_available"]:
        details = {"reason": "email_link"}
        return ApiError(401, "unauthenticated", "sign in with a link by mail", details)
    return ApiError(
        401,
        "unauthenticated",
        "the password is paused here for a while",
        {"reason": "password_paused", "retry_after": wait},
    )


class LoginAttempt:
    """One password at the login, counted for the account and for the account from this
    source before it is compared. Refused with `paused` when the account's limit is spent and
    the source is not known, or has spent its own. Leaving gives the attempt back unless
    `wrong` kept it."""

    def __init__(
        self, conn: Connection, hub: Settings, account: str, human_id: str | None, source: str
    ) -> None:
        self._pair = f"{account} {source}"
        self._account = account
        wait, mark = LOGIN.place(account)
        pair_wait, pair_mark = LOGIN_FROM.place(self._pair)
        if wait and (
            pair_wait or human_id is None or not known_sources.known(conn, human_id, source)
        ):
            LOGIN_FROM.release(self._pair, pair_mark)
            raise paused(conn, hub, max(wait, pair_wait))
        self._marks: tuple[Mark, Mark] = (mark, pair_mark)
        self._kept = False

    def wrong(self) -> None:
        self._kept = True

    def __enter__(self) -> LoginAttempt:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        if not self._kept:
            LOGIN.release(self._account, self._marks[0])
            LOGIN_FROM.release(self._pair, self._marks[1])
