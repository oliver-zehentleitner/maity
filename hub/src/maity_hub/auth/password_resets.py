"""Links to reset a forgotten password (docs/api.md §2.10): their single-use rows, the
password generation every link carries, the wrong codes counted per human over 24 hours, and
the anonymous request's limits.

A link is a signed token (§18.6) `{h, p: password_reset, n, x, g, e}`: the human, the nonce,
the expiry, the password generation and the address epoch it was made under. The hub keeps
`sha256(nonce)` for single use; a forged token is refused before any lookup.

The single-use rows, the human row lock and the request limits are implemented once, for
this table and `email_sign_in` alike, in auth/single_use.py; `issue`, `use`, `void_human`,
`void_open` and `RequestLimits` here are thin wrappers over it. This module holds what only
the reset has: the signed token, the reading of a row by its token (`live`), the password
generation and the wrong codes at resets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, delete, func, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import single_use
from maity_hub.auth.single_use import digest
from maity_hub.notifications import tokens

LIFETIME = timedelta(minutes=30)
KIND = single_use.Kind(t.password_reset, LIFETIME)
PURPOSE = "password_reset"
# The wrong codes at resets of one human in the 24 hours before each one, across every link:
# the fifth and every further one voids the open links and alarms (§2.10).
WRONG_WINDOW = timedelta(hours=24)
WRONG_ALARM = 5


@dataclass(frozen=True)
class Issued:
    nonce: str
    expires_at: datetime


def issue(conn: Connection, *, human_id: str, source: str, requested_at: datetime) -> Issued | None:
    """A new link for `human_id`, asked from `source`. It voids the earlier unused link asked
    from the same source, and only that one, so nobody elsewhere can void the link the human
    is about to use. None when a newer request from that source has already issued one, or
    this request has outlived a link's life before its turn came (`single_use.issue`)."""
    issued = single_use.issue(
        conn, KIND, human_id=human_id, source=source, requested_at=requested_at
    )
    if issued is None:
        return None
    nonce, expires = issued
    return Issued(nonce, expires)


def token(key: bytes, human_id: str, issued: Issued, generation: int, epoch: int) -> str:
    return tokens.make(
        key,
        {
            "h": human_id,
            "p": PURPOSE,
            "n": issued.nonce,
            "x": int(issued.expires_at.timestamp()),
            "g": generation,
            "e": epoch,
        },
    )


def read(key: bytes | None, value: str) -> dict[str, Any] | None:
    """The token's payload when its signature, purpose, shape and expiry hold; never why not."""
    payload = tokens.read(key, value)
    if (
        payload is None
        or payload.get("p") != PURPOSE
        or not isinstance(payload.get("h"), str)
        or not isinstance(payload.get("n"), str)
        or not all(isinstance(payload.get(k), int) for k in ("x", "g", "e"))
        or payload["x"] <= clock.now().timestamp()
    ):
        return None
    return payload


def live(conn: Connection, payload: dict[str, Any]) -> Any:
    """The token's row while unused and unexpired; it consumes nothing (a mail scanner only
    reads)."""
    return conn.execute(
        select(t.password_reset).where(
            t.password_reset.c.nonce_hash == digest(payload["n"]),
            t.password_reset.c.human_id == payload["h"],
            t.password_reset.c.used_at.is_(None),
            t.password_reset.c.expires_at > clock.now(),
        )
    ).first()


def use(conn: Connection, row: Any) -> bool:
    return single_use.use(conn, KIND, row)


def wrong_code(conn: Connection, human_id: str) -> int:
    """Count one wrong code at a reset of `human_id`; the number in the 24 hours before it,
    this one included. Older rows count for nothing and go."""
    now = clock.now()
    since = now - WRONG_WINDOW
    conn.execute(
        delete(t.password_reset_wrong).where(
            t.password_reset_wrong.c.human_id == human_id, t.password_reset_wrong.c.at <= since
        )
    )
    conn.execute(insert(t.password_reset_wrong).values(human_id=human_id, at=now))
    return int(
        conn.execute(
            select(func.count())
            .select_from(t.password_reset_wrong)
            .where(
                t.password_reset_wrong.c.human_id == human_id,
                t.password_reset_wrong.c.at > since,
            )
        ).scalar_one()
    )


PREFIX = "auth.password_resets"  # the limiters' names: keys of the shared counts, never renamed


class RequestLimits(single_use.RequestLimits):
    """`POST /auth/password-reset`, as `POST /auth/email-link` (§2.6.4), in buckets named under
    `auth.password_resets`: only the source limit answers `429`; over the pair limits the
    answer stays `202` and nothing is sent, and so over the recipient's limit
    (auth/single_use.py)."""

    def __init__(self) -> None:
        super().__init__(PREFIX)


def password_changed(conn: Connection, human_id: str) -> None:
    """A new password, by `POST /auth/password` or a reset: the generation moves, so every
    link made under the old one dies with it, and the open ones are voided now too. That
    includes the link that lifts the daily second-factor cap (§2.8.6): the day's alert counts
    as not written, so the next wrong code mails one under the new generation. The human's
    row is updated before the day's, the order a wrong code's count takes too
    (`second_factor._count_day`)."""
    conn.execute(
        update(t.human)
        .where(t.human.c.id == human_id)
        .values(password_generation=t.human.c.password_generation + 1)
    )
    conn.execute(
        update(t.second_factor_day)
        .where(t.second_factor_day.c.human_id == human_id)
        .values(alerted=False)
    )
    void_human(conn, human_id)


def void_human(conn: Connection, human_id: str) -> None:
    """Every open link of one human: a password change, the human's own switch turned off, a
    change or removal of the address, or the fifth wrong code at resets in a day."""
    single_use.void_human(conn, KIND, human_id)


def void_open(conn: Connection) -> None:
    """Every open link of the instance, when its switch turns the reset off."""
    single_use.void_open(conn, KIND)
