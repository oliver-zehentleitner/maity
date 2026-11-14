"""Links to reset a forgotten password (docs/api.md §2.10): their single-use rows, the
password generation every link carries, the wrong codes counted per human over 24 hours, and
the anonymous request's limits.

A link is a signed token (§18.6) `{h, p: password_reset, n, x, g, e}`: the human, the nonce,
the expiry, the password generation and the address epoch it was made under. The hub keeps
`sha256(nonce)` for single use; a forged token is refused before any lookup.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, delete, func, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth.email_links import digest, lock_human
from maity_hub.notifications import tokens
from maity_hub.ratelimit import Limiter

LIFETIME = timedelta(minutes=30)
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
    this request has outlived a link's life before its turn came."""
    lock_human(conn, human_id)
    now = clock.now()
    newer = conn.execute(
        select(t.password_reset.c.nonce_hash)
        .where(
            t.password_reset.c.human_id == human_id,
            t.password_reset.c.source == source,
            t.password_reset.c.created_at > requested_at,
        )
        .limit(1)
    ).first()
    if newer is not None or requested_at + LIFETIME <= now:
        return None
    conn.execute(
        update(t.password_reset)
        .where(
            t.password_reset.c.human_id == human_id,
            t.password_reset.c.source == source,
            t.password_reset.c.used_at.is_(None),
        )
        .values(used_at=now)
    )
    nonce = secrets.token_urlsafe(32)
    expires = requested_at + LIFETIME
    conn.execute(
        insert(t.password_reset).values(
            nonce_hash=digest(nonce),
            human_id=human_id,
            source=source,
            created_at=requested_at,
            expires_at=expires,
        )
    )
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
    done = conn.execute(
        update(t.password_reset)
        .where(
            t.password_reset.c.nonce_hash == row.nonce_hash,
            t.password_reset.c.used_at.is_(None),
            t.password_reset.c.expires_at > clock.now(),
        )
        .values(used_at=clock.now())
    )
    return done.rowcount == 1


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


class RequestLimits:
    """`POST /auth/password-reset`, as `POST /auth/email-link` (§2.6.4), in buckets of its own:
    only the source limit answers `429`; over the pair limits the answer stays `202` and nothing
    is sent. Existing and unknown addresses take the same path."""

    def __init__(self) -> None:
        self.by_source = Limiter(10, 3600, name="auth.password_resets.by_source")
        self.pair_quarter = Limiter(3, 900, name="auth.password_resets.pair_quarter")
        self.pair_day = Limiter(10, 86400, name="auth.password_resets.pair_day")

    def take(self, address: str, source: str) -> tuple[int, bool]:
        wait = self.by_source.hit(source)
        if wait:
            return wait, False
        key = digest(f"{source}\0{address.strip().casefold()}")
        quarter = self.pair_quarter.hit(key)
        day = self.pair_day.hit(key)
        return 0, not (quarter or day)


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
    conn.execute(
        update(t.password_reset)
        .where(t.password_reset.c.human_id == human_id, t.password_reset.c.used_at.is_(None))
        .values(used_at=clock.now())
    )


def void_open(conn: Connection) -> None:
    """Every open link of the instance, when its switch turns the reset off."""
    conn.execute(
        update(t.password_reset)
        .where(t.password_reset.c.used_at.is_(None))
        .values(used_at=clock.now())
    )
