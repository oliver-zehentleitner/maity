"""The one address syntax of docs/api.md §18.4: exactly one RFC 5321 `addr-spec`.

`local-part@domain`, ASCII only, at most 254 characters with a local part of at most
64, a domain of host-name labels with at least one dot (no IP literal). No display
name, no angle brackets, no comma, semicolon, whitespace or control character, and no
second `@` outside a quoted local part. The checked address is handed to SMTP as the
single recipient; nothing ever parses a list out of it.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import Engine, delete, insert, select
from sqlalchemy.exc import IntegrityError

from maity_hub import instance_settings as store
from maity_hub import tables as t

MAX_ADDRESS = 254
MAX_LOCAL = 64

# RFC 5321 atext: letters, digits and these.
_ATOM = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+"
# A quoted local part, without what §18.4 refuses anywhere: whitespace, comma,
# semicolon and angle brackets. A backslash quotes the next printable character.
_QCHAR = r"[!#-+\--:=?-\[\]-~]"
_QUOTED = rf'"(?:{_QCHAR}|\\[!-+\--:=?-~])*"'
_LOCAL = re.compile(rf"(?:{_ATOM}(?:\.{_ATOM})*|{_QUOTED})")
LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


def valid(value: object) -> bool:
    """Whether `value` is one address in the syntax of §18.4."""
    if not isinstance(value, str) or not value.isascii() or len(value) > MAX_ADDRESS:
        return False
    local, at, domain = value.rpartition("@")
    if not at or not local or len(local) > MAX_LOCAL:
        return False
    if _LOCAL.fullmatch(local) is None:
        return False
    labels = domain.split(".")
    return len(labels) >= 2 and all(LABEL.fullmatch(label) for label in labels)


def normalized(value: str) -> str:
    """The form one account per address compares: trimmed and lower-cased (§2.6.3,
    §18.4)."""
    return value.strip().lower()


# The key per-address lock rows are stored under when no instance key is set: a random
# pepper the hub makes at first use, in a transaction of its own (`prepare`), as the
# notification positions' key is made; not sealed, there is no key to seal it with.
LOCK_PEPPER = "address.lock_pepper"
LOCK_PURPOSE = "address.lock"

store.register_secret(LOCK_PEPPER)


def prepare(engine: Engine, secret_key: bytes | None) -> None:
    """Make the stored pepper at first use, before the caller's transaction that locks:
    insert if absent, and on a concurrent first use keep the winner's."""
    if secret_key is not None:
        with engine.begin() as conn:  # no longer used once an instance key is set
            if store.sealed(conn, LOCK_PEPPER) is not None:
                store.put_sealed(conn, LOCK_PEPPER, None, None)
        return
    with engine.begin() as conn:
        if store.sealed(conn, LOCK_PEPPER) is not None:
            return
    try:
        with engine.begin() as conn:
            store.add_sealed(conn, LOCK_PEPPER, os.urandom(32))
    except IntegrityError:
        pass  # another request or replica made it first; its pepper stands


def _hmac_key(conn: Any, secret_key: bytes | None) -> bytes | None:
    if secret_key is not None:
        info = LOCK_PURPOSE.encode()
        derived: bytes = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(
            secret_key
        )
        return derived
    stored = store.sealed(conn, LOCK_PEPPER)
    return stored if stored is not None and len(stored) == 32 else None


def lock_key(conn: Any, secret_key: bytes | None, value: str) -> str:
    """What a per-address lock row is stored under: an HMAC of the normalized address,
    never the address itself, so a lock outlives no account's address (§2.9). The key
    comes from `MAITY_SECRET_KEY` (HKDF) when it is set, else from the stored pepper;
    every caller must pass the same `secret_key`, or one address would get two rows."""
    key = _hmac_key(conn, secret_key)
    if key is None:
        raise RuntimeError("the address lock pepper is not prepared")
    return hmac.new(key, normalized(value).encode(), hashlib.sha256).hexdigest()


def forget_locks(conn: Any, secret_key: bytes | None, values: set[str]) -> None:
    """Remove the lock rows of these addresses where nothing else needs them, for an
    account deletion (§2.9): without an instance key the pepper sits in the same
    database, so a row would still let a full dump confirm a guessed address. A row is
    made again at its next use, so no serialisation is lost; one for an address with a
    pending registration stays. Without a key there can be no row to remove."""
    key = _hmac_key(conn, secret_key)
    if key is None or not values:
        return
    digests = {hmac.new(key, normalized(v).encode(), hashlib.sha256).hexdigest(): v for v in values}
    conn.execute(delete(t.address_lock).where(t.address_lock.c.digest.in_(digests)))
    waiting = set(
        conn.execute(
            select(t.pending_registration.c.address_normalized).where(
                t.pending_registration.c.address_normalized.in_({normalized(v) for v in values})
            )
        ).scalars()
    )
    free = [d for d, v in digests.items() if normalized(v) not in waiting]
    conn.execute(delete(t.registration_lock).where(t.registration_lock.c.digest.in_(free)))


def lock(conn: Any, secret_key: bytes | None, value: str) -> None:
    """The per-address lock that verifying, changing and registering an address take
    (§18.4, §2.7.1): the address's row in `address_lock`, made if absent, then locked
    until commit."""
    take_lock(conn, t.address_lock, lock_key(conn, secret_key, value))


def take_lock(conn: Any, table: Any, key: str) -> None:
    """A lock row keyed by `key`, made if absent, then locked until commit. A deletion may
    remove the row between the insert that found it and the lock (`forget_locks`); the
    lock then finds nothing under READ COMMITTED, so the pair runs once more, and a second
    empty read fails loudly rather than going on unlocked."""
    for _attempt in range(2):
        try:
            with conn.begin_nested():
                conn.execute(insert(table).values(digest=key))
        except IntegrityError:
            pass  # it exists; lock it below
        found = conn.execute(
            select(table.c.digest).where(table.c.digest == key).with_for_update()
        ).first()
        if found is not None:
            return
    raise RuntimeError(f"the lock row in {table.name} vanished twice")
