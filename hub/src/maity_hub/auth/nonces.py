"""The nonces of signed requests, shared by every replica on PostgreSQL (docs/api.md §2.2,
hub/context/replicas.md 1c65bb74).

A nonce is spent by inserting it into `request_nonce`; no row inserted means it was spent
already, whichever replica saw it. Both tables are UNLOGGED there: a crash or a failover of the
database empties them together, and `nonce_epoch` says since when the nonces are known, so a
request signed before that moment is refused (as a request signed before the process started
is refused on the other databases, which keep the window in the process). The claim runs in the
caller's transaction, the short one that authenticates and commits before the route runs
(`deps._resolve`).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import Connection, delete, select
from sqlalchemy.dialects import postgresql

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth.credentials import NONCE_WINDOW_SECONDS

EPOCH_ID = 1
# Every this many claims a process deletes the spent nonces whose window is over; with several
# replicas each does, which only means the deletes are smaller.
SWEEP_EVERY = 1000
_claims = [0]


def shared(conn: Connection) -> bool:
    """Whether the nonces live in the database: on PostgreSQL, the one engine replicas run on."""
    return conn.dialect.name == "postgresql"


def epoch(conn: Connection) -> datetime:
    """Since when the nonces are known: set to now when the row is missing, after the tables
    were emptied by a crash or a failover, or on the first signed request ever."""
    found = conn.execute(select(t.nonce_epoch.c.since).where(t.nonce_epoch.c.id == EPOCH_ID))
    since = found.scalar()
    if since is not None:
        return since  # type: ignore[no-any-return]
    conn.execute(
        postgresql.insert(t.nonce_epoch)
        .values(id=EPOCH_ID, since=clock.now())
        .on_conflict_do_nothing()
    )
    return conn.execute(  # type: ignore[no-any-return]
        select(t.nonce_epoch.c.since).where(t.nonce_epoch.c.id == EPOCH_ID)
    ).scalar_one()


def first_use(conn: Connection, credential_id: str, nonce: str) -> bool:
    """Spend the nonce; False when any replica spent it within the window."""
    now = clock.now()
    # RETURNING, not `rowcount`: the driver reports -1 for an insert that skips its conflict.
    inserted = conn.execute(
        postgresql.insert(t.request_nonce)
        .values(
            credential_id=credential_id,
            nonce=nonce,
            expires_at=now + timedelta(seconds=NONCE_WINDOW_SECONDS),
        )
        .on_conflict_do_nothing()
        .returning(t.request_nonce.c.nonce)
    ).first()
    _claims[0] += 1
    if _claims[0] % SWEEP_EVERY == 0:
        conn.execute(delete(t.request_nonce).where(t.request_nonce.c.expires_at < now))
    return inserted is not None
