"""Secrets stored at rest (docs/api.md §16.2, §17.4): AES-256-GCM with the instance key.

`MAITY_SECRET_KEY` is 32 bytes, base64, from the environment and nowhere else; it is
checked when the hub starts. Every value gets a random 96-bit nonce, stored in front of
its ciphertext, and the name of the field it belongs to as associated data, so a value
copied into another field does not decrypt. A value the current key cannot open (the
key changed, the row was altered) raises `SealedError`: it never reads as empty.
"""

from __future__ import annotations

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

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
