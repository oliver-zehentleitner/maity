"""The sources a human's sign-ins completed from (docs/api.md §2.1): past the limit of wrong
passwords, only such a source keeps the password.

The hub keeps a keyed fingerprint of each source address, never the address: an HMAC-SHA-256
under a key derived (HKDF, purpose `sign_in.known_source`) from `MAITY_SECRET_KEY`, or where no
instance key is set from the per-address lock's pepper, which the hub makes at first use
(`addresses.prepare`; the login runs it before its transaction, as every route that locks an
address does). One pepper serves both, each under its own derived key. Without an instance key
the pepper sits in the same database, so a full copy of it lets an address be found by trying
them all; with one, it does not. Until the pepper exists no source is remembered or known. A
fingerprint goes 30 days after its last sign-in and with the account (§2.9).
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import Connection, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock
from maity_hub import instance_settings as store
from maity_hub import tables as t
from maity_hub.mail import address as addresses

KEPT_FOR = timedelta(days=30)
PURPOSE = "sign_in.known_source"

# The instance key of the app that serves (`configure`, from `create_app`): a session is made
# far from the settings, in every way of signing in.
_secret_key: list[bytes | None] = [None]


def configure(secret_key: bytes | None) -> None:
    _secret_key[0] = secret_key


def _key(conn: Connection) -> bytes | None:
    base = _secret_key[0]
    if base is None:
        stored = store.sealed(conn, addresses.LOCK_PEPPER)
        if stored is None or len(stored) != 32:
            return None
        base = stored
    derived: bytes = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=PURPOSE.encode()
    ).derive(base)
    return derived


def fingerprint(conn: Connection, source: str) -> str | None:
    """None without a key (no pepper made yet): then no source is known."""
    key = _key(conn)
    if key is None:
        return None
    return hmac.new(key, source.encode(), hashlib.sha256).hexdigest()


def remember(conn: Connection, human_id: str, source: str | None) -> None:
    """A sign-in of `human_id` completed from `source`. Every fingerprint past its 30 days
    goes now, for every human at once."""
    now = clock.now()
    conn.execute(delete(t.known_source).where(t.known_source.c.last_at < now - KEPT_FOR))
    found = fingerprint(conn, source) if source else None
    if found is None:
        return
    row = (t.known_source.c.human_id == human_id) & (t.known_source.c.fingerprint == found)
    if conn.execute(update(t.known_source).where(row).values(last_at=now)).rowcount:
        return
    try:
        with conn.begin_nested():
            conn.execute(
                insert(t.known_source).values(human_id=human_id, fingerprint=found, last_at=now)
            )
    except IntegrityError:  # a sign-in of the same human from the same source committed first
        conn.execute(update(t.known_source).where(row).values(last_at=now))


def known(conn: Connection, human_id: str, source: str) -> bool:
    found = fingerprint(conn, source)
    if found is None:
        return False
    return (
        conn.execute(
            select(t.known_source.c.human_id).where(
                t.known_source.c.human_id == human_id,
                t.known_source.c.fingerprint == found,
                t.known_source.c.last_at >= clock.now() - KEPT_FOR,
            )
        ).first()
        is not None
    )
