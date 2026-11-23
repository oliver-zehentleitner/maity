"""The one implementation of single-use mail links: the rows of `email_sign_in` (a mailed
sign-in link and its code, auth/email_links.py) and of `password_reset` (a link to reset a
forgotten password, auth/password_resets.py), and the anonymous request's limits of both.

This module holds what the two kinds share, with the table as a parameter (`Kind`): the human
row lock, issuing a row (`start`, `add`, `issue`), using it once (`use`), voiding the open rows
of one human or of the instance (`void_human`, `void_open`), and `RequestLimits` with the
recipient's limits (`recipient_over`). Each kind's own parts stay in its module: the sign-in
code, its MAC and the per-day count of wrong codes in auth/email_links.py; the signed reset
token, the password generation and the wrong codes at resets in auth/password_resets.py. Both
modules keep their former names as thin wrappers over this one, and this module imports
neither of them.

A human row lock serialises issuance, guesses and use on all three engines; a conditional
update remains the final single-use check.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Table, insert, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.codes import digest as digest
from maity_hub.ratelimit import Limiter, Mark


@dataclass(frozen=True)
class Kind:
    """One kind of single-use link: its table, the life of a row, and the columns a spent
    row clears together with setting `used_at` (`email_sign_in` clears its `code_mac`, so
    that a used or voided link's code dies with it)."""

    table: Table
    lifetime: timedelta
    cleared: tuple[str, ...] = ()

    def spent(self, at: datetime) -> dict[str, Any]:
        """The values that mark a row used or voided at `at`."""
        return {"used_at": at, **{column: None for column in self.cleared}}


def lock_human(conn: Connection, human_id: str) -> None:
    conn.execute(select(t.human.c.id).where(t.human.c.id == human_id).with_for_update()).one()


def start(
    conn: Connection,
    kind: Kind,
    *,
    human_id: str,
    source: str,
    requested_at: datetime | None = None,
) -> datetime | None:
    """The first half of issuing a row for `human_id`, asked from `source`: under the human
    row lock, it voids the earlier unused row asked from the same source, and only that one,
    so nobody elsewhere can void the link the human is about to use. The request's moment
    (now when `requested_at` is None), or None, and nothing changed, when a newer request
    from that source has already issued one or this request has outlived a row's life before
    its turn came. `add` completes it in the same transaction."""
    lock_human(conn, human_id)
    table = kind.table
    now = clock.now()
    requested_at = requested_at or now
    newer = conn.execute(
        select(table.c.nonce_hash)
        .where(
            table.c.human_id == human_id,
            table.c.source == source,
            table.c.created_at > requested_at,
        )
        .limit(1)
    ).first()
    if newer is not None or requested_at + kind.lifetime <= now:
        return None
    conn.execute(
        update(table)
        .where(
            table.c.human_id == human_id,
            table.c.source == source,
            table.c.used_at.is_(None),
        )
        .values(**kind.spent(now))
    )
    return requested_at


def add(
    conn: Connection,
    kind: Kind,
    *,
    nonce_hash: str,
    human_id: str,
    source: str,
    requested_at: datetime,
    **columns: Any,
) -> datetime:
    """The second half of issuing: the new row, with the kind's own `columns`; its expiry."""
    expires = requested_at + kind.lifetime
    conn.execute(
        insert(kind.table).values(
            nonce_hash=nonce_hash,
            human_id=human_id,
            source=source,
            created_at=requested_at,
            expires_at=expires,
            **columns,
        )
    )
    return expires


def issue(
    conn: Connection,
    kind: Kind,
    *,
    human_id: str,
    source: str,
    requested_at: datetime | None = None,
    **columns: Any,
) -> tuple[str, datetime] | None:
    """`start` and `add` with a fresh nonce: the nonce and the expiry, or None (see `start`).
    A kind that computes more of its row in between (the sign-in code) calls them itself."""
    at = start(conn, kind, human_id=human_id, source=source, requested_at=requested_at)
    if at is None:
        return None
    nonce = secrets.token_urlsafe(32)
    expires = add(
        conn,
        kind,
        nonce_hash=digest(nonce),
        human_id=human_id,
        source=source,
        requested_at=at,
        **columns,
    )
    return nonce, expires


def use(conn: Connection, kind: Kind, row: Any) -> bool:
    """Spend `row` once: True for the one caller that did, while it was unused and unexpired."""
    table = kind.table
    result = conn.execute(
        update(table)
        .where(
            table.c.nonce_hash == row.nonce_hash,
            table.c.used_at.is_(None),
            table.c.expires_at > clock.now(),
        )
        .values(**kind.spent(clock.now()))
    )
    return result.rowcount == 1


def void_human(conn: Connection, kind: Kind, human_id: str) -> None:
    """Every open row of one human."""
    table = kind.table
    conn.execute(
        update(table)
        .where(table.c.human_id == human_id, table.c.used_at.is_(None))
        .values(**kind.spent(clock.now()))
    )


def void_open(conn: Connection, kind: Kind) -> None:
    """Every open row of the instance."""
    table = kind.table
    conn.execute(update(table).where(table.c.used_at.is_(None)).values(**kind.spent(clock.now())))


# Mails one address is sent in answer to anonymous requests (§2.6.4), each path in buckets of
# its own. Places per hour and per day, counted in source networks: a network's first mail to
# the address in a window takes a place, its further mails take none and are held by its pair
# limits alone. One network can so never spend the address's places, nor can up to four, but
# for the moment two or three first requests of one network run at once (`recipient_over`):
# beyond it, only five distinct networks in an hour (twenty in a day) leave a further network
# without one. The path's instance-wide hourly budget is a separate cap (mail/settings.py),
# which for resets and registration fewer networks reach: three at their 10 an hour spend the
# default 30; sign-in's 60 takes six.
RECIPIENT_PER_HOUR = 5
RECIPIENT_PER_DAY = 20
# And the mails themselves, from all networks together, queued in any hour and any day: the
# windows slide, so a place passes from one network to the next within them, and the places
# alone do not bound the mails. Counted at the request, not at delivery (§2.6.4). Four networks
# at their pair limits (10 a day each) ask for at most 40 in any hour or day, so these never
# stop fewer than five.
RECIPIENT_MAILS_PER_HOUR = 50
RECIPIENT_MAILS_PER_DAY = 200

Recipient = tuple[Limiter, Limiter, Limiter, Limiter, Limiter, Limiter]


def recipient_over(limiters: Recipient, address_key: str, asker: str) -> bool:
    """Count one mail to the address for `asker`, the source network (`Origin.limit_key`) or,
    for a verification mail, the asking account; True when it may not go out, and then
    nothing is recorded. `address_key` is the address's `known_sources.address_key`, never
    the address or a plain hash of it.

    `limiters`: the address's places per hour and per day, the marks of the askers holding
    one (limit 1, the same windows), and its mails per hour and per day; each is an attribute
    of its own where it is held, so that the tests find and reset it. The places are taken
    first, then the mails; a mark is set only once all of them were had, at its place's own
    moment (`Limiter.place(at=)`), so that mark and place leave the window together, and it
    is never given back: a mark seen by a concurrent request is a place really held, and once
    its requests are done a network without a mark holds no place. Concurrent first requests
    of one network each take a place (two or three, its quarter limit), so for that moment it
    holds as many; each that finds the mark set after gives its place back. An account's
    verification requests run one at a time (under its settings row), so never at once."""
    hour, day, hour_askers, day_askers, mails_hour, mails_day = limiters
    address = address_key
    pair = f"{address_key} {asker}"
    taken: list[tuple[Limiter, Mark, Limiter | None]] = []

    def give_back() -> bool:
        for limiter, mark, _ in taken:
            limiter.release(address, mark)
        return True

    for budget, askers in ((hour, hour_askers), (day, day_askers)):
        if askers.blocked(pair):
            continue  # the asker holds a place in this window
        wait, mark = budget.place(address)
        if wait:
            return give_back()
        taken.append((budget, mark, askers))
    for mails in (mails_hour, mails_day):
        wait, mark = mails.place(address)
        if wait:
            return give_back()
        taken.append((mails, mark, None))
    for limiter, mark, marks in taken:
        if marks is not None and marks.place(pair, at=mark)[0]:
            limiter.release(address, mark)  # a concurrent request marked it with its own place
    return False


class RequestLimits:
    """The anonymous request's limits of one path, in buckets of its own named under
    `prefix` (`auth.email_links`, `auth.password_resets`): the names key the shared counts
    (`rate_count`), so they must never change. Only the source limit is observable; the pair
    limits and the recipient's silently suppress delivery. The address is counted by its
    `known_sources.address_key`, and existing and unknown addresses take the same path.
    `source` is the caller's `Origin.limit_key`."""

    def __init__(self, prefix: str) -> None:
        self.by_source = Limiter(10, 3600, name=f"{prefix}.by_source")
        self.pair_quarter = Limiter(3, 900, name=f"{prefix}.pair_quarter")
        self.pair_day = Limiter(10, 86400, name=f"{prefix}.pair_day")
        self.recipient_hour = Limiter(RECIPIENT_PER_HOUR, 3600, name=f"{prefix}.recipient_hour")
        self.recipient_day = Limiter(RECIPIENT_PER_DAY, 86400, name=f"{prefix}.recipient_day")
        self.recipient_hour_networks = Limiter(1, 3600, name=f"{prefix}.recipient_hour_networks")
        self.recipient_day_networks = Limiter(1, 86400, name=f"{prefix}.recipient_day_networks")
        self.recipient_mails_hour = Limiter(
            RECIPIENT_MAILS_PER_HOUR,
            3600,
            name=f"{prefix}.recipient_mails_hour",
            exact=True,
        )
        self.recipient_mails_day = Limiter(
            RECIPIENT_MAILS_PER_DAY,
            86400,
            name=f"{prefix}.recipient_mails_day",
            exact=True,
        )

    def take(self, address_key: str, source: str) -> tuple[int, bool]:
        """`address_key`: the asked address's `known_sources.address_key`."""
        wait = self.by_source.hit(source)
        if wait:
            return wait, False
        pair = f"{address_key} {source}"
        quarter = self.pair_quarter.hit(pair)
        day = self.pair_day.hit(pair)
        if quarter or day:
            return 0, False
        # Counted in networks, only for a mail the pair limits let through (`recipient_over`).
        return 0, not recipient_over(self.recipient(), address_key, source)

    def recipient(self) -> Recipient:
        return (
            self.recipient_hour,
            self.recipient_day,
            self.recipient_hour_networks,
            self.recipient_day_networks,
            self.recipient_mails_hour,
            self.recipient_mails_day,
        )
