"""Secrets stored at rest (docs/api.md §16.2, §17.4): AES-256-GCM with the instance key.

`MAITY_SECRET_KEY` is 32 bytes, base64, from the environment and nowhere else; it is
checked when the hub starts. Every value gets a random 96-bit nonce, stored in front of
its ciphertext, and the name of the field it belongs to as associated data, so a value
copied into another field does not decrypt. A value the current key cannot open (the
key changed, the row was altered) raises `SealedError`: it never reads as empty.

A key for one purpose (an HMAC key, a sealing key) is derived from the instance key with
HKDF, the purpose as `info`, or where no instance key is set it is a random 32-byte
fallback key the hub stores in `instance_secret` at first use (`prepare_fallback`), not
sealed: there is no key to seal it with. `purpose_key` picks one of the two, so every
keyed value the hub stores comes from one derivation.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import IntegrityError

from maity_hub import instance_settings as store

KEY_BYTES = 32
NONCE_BYTES = 12


class SealedError(Exception):
    """A stored secret the current key does not open. Carries no secret material."""


def parse_key(value: str) -> bytes | None:
    """`MAITY_SECRET_KEY`: unset is None; anything but 32 base64 bytes is `ValueError`,
    whose message names the variable and never its value."""
    text = value.strip()
    if not text:
        return None
    try:
        key = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("MAITY_SECRET_KEY is not base64") from None
    if len(key) != KEY_BYTES:
        raise ValueError(f"MAITY_SECRET_KEY must be {KEY_BYTES} bytes, base64")
    return key


def seal(key: bytes, field: str, plaintext: bytes) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, field.encode())


def open_sealed(key: bytes, field: str, sealed: bytes) -> bytes:
    if len(sealed) <= NONCE_BYTES:
        raise SealedError(f"the stored {field} is not a sealed value")
    try:
        return AESGCM(key).decrypt(sealed[:NONCE_BYTES], sealed[NONCE_BYTES:], field.encode())
    except InvalidTag:
        raise SealedError(f"the stored {field} does not open with this MAITY_SECRET_KEY") from None


def derive(base: bytes, purpose: str) -> bytes:
    """The 32-byte key for `purpose` from `base`: HKDF-SHA256, no salt, the purpose as
    `info`. A purpose string is part of every key made under it: changing one invalidates
    what was stored or issued under it."""
    derived: bytes = HKDF(
        algorithm=hashes.SHA256(), length=KEY_BYTES, salt=None, info=purpose.encode()
    ).derive(base)
    return derived


def stored_fallback(conn: Connection, name: str) -> bytes | None:
    """The fallback key stored under `name` (a name registered with
    `instance_settings.register_secret`), or None while it is not made yet."""
    stored = store.sealed(conn, name)
    return stored if stored is not None and len(stored) == KEY_BYTES else None


def purpose_key(
    conn: Connection, secret_key: bytes | None, purpose: str, fallback_name: str
) -> bytes | None:
    """The key for `purpose`: derived from the instance key when it is set, else the
    stored fallback key `fallback_name` as it is, None while that is not made yet. Every
    caller of one purpose must pass the same `secret_key`."""
    if secret_key is not None:
        return derive(secret_key, purpose)
    return stored_fallback(conn, fallback_name)


def prepare_fallback(
    engine: Engine, secret_key: bytes | None, name: str, *, wipe_when_keyed: bool
) -> None:
    """Make the fallback key `name` at first use, in a transaction of its own, before
    the caller's transaction that reads it: insert if absent, and on a concurrent first
    use keep the winner's. With an instance key nothing is made; `wipe_when_keyed`
    removes a fallback key made earlier, which nothing reads while the instance key is
    set."""
    if secret_key is not None:
        if wipe_when_keyed:
            with engine.begin() as conn:
                if store.sealed(conn, name) is not None:
                    store.put_sealed(conn, name, None, None)
        return
    with engine.begin() as conn:
        if store.sealed(conn, name) is not None:
            return
    try:
        with engine.begin() as conn:
            store.add_sealed(conn, name, os.urandom(KEY_BYTES))
    except IntegrityError:
        pass  # another request or replica made it first; its key stands
