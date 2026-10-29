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
from sqlalchemy import Engine, insert, select
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
        return
    with engine.begin() as conn:
        if store.sealed(conn, LOCK_PEPPER) is not None:
            return
    try:
        with engine.begin() as conn:
            store.add_sealed(conn, LOCK_PEPPER, os.urandom(32))
    except IntegrityError:
        pass  # another request or replica made it first; its pepper stands


def lock_key(conn: Any, secret_key: bytes | None, value: str) -> str:
    """What a per-address lock row is stored under: an HMAC of the normalized address,
    never the address itself, so a lock outlives no account's address (§2.9). The key
    comes from `MAITY_SECRET_KEY` (HKDF) when it is set, else from the stored pepper;
    every caller must pass the same `secret_key`, or one address would get two rows."""
    if secret_key is not None:
        info = LOCK_PURPOSE.encode()
        key: bytes | None = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info).derive(
            secret_key
        )
    else:
        key = store.sealed(conn, LOCK_PEPPER)
    if not key:
        raise RuntimeError("the address lock pepper is not prepared")
    return hmac.new(key, normalized(value).encode(), hashlib.sha256).hexdigest()


def lock(conn: Any, secret_key: bytes | None, value: str) -> None:
    """The per-address lock that verifying, changing and registering an address take
    (§18.4, §2.7.1): the address's row in `address_lock`, made if absent, then locked
    until commit."""
    key = lock_key(conn, secret_key, value)
    try:
        with conn.begin_nested():
            conn.execute(insert(t.address_lock).values(digest=key))
    except IntegrityError:
        pass  # it exists; lock it below
    conn.execute(
        select(t.address_lock.c.digest).where(t.address_lock.c.digest == key).with_for_update()
    )
