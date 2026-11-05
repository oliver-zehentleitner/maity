"""The sources a human's sign-ins completed from (docs/api.md §2.1): past the limit of wrong
passwords, only such a source keeps the password.

The hub keeps a keyed fingerprint of each source address, never the address: an HMAC-SHA-256
under a key derived from `MAITY_SECRET_KEY`, or under the pepper the migration stored where no
instance key is set. Without an instance key the pepper sits in the same database, so a full
copy of it lets an address be found by trying them all; with one, it does not. A fingerprint
goes 30 days after its last sign-in and with the account (§2.9).
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

KEPT_FOR = timedelta(days=30)
PURPOSE = "sign_in.known_source"
PEPPER = "sign_in.known_source_pepper"  # made by the migration of `known_source`

store.register_secret(PEPPER)

# The instance key of the app that serves (`configure`, from `create_app`): a session is made
# far from the settings, in every way of signing in.
_secret_key: list[bytes | None] = [None]


def configure(secret_key: bytes | None) -> None:
    _secret_key[0] = secret_key


def _key(conn: Connection) -> bytes | None:
    secret_key = _secret_key[0]
    if secret_key is not None:
        derived: bytes = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=None, info=PURPOSE.encode()
        ).derive(secret_key)
        return derived
    stored = store.sealed(conn, PEPPER)
    return stored if stored is not None and len(stored) == 32 else None


def fingerprint(conn: Connection, source: str) -> str | None:
    """None without a key (the pepper removed by hand): then no source is known."""
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
