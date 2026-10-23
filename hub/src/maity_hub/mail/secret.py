"""Secrets the hub stores, encrypted with the instance key `MAITY_SECRET_KEY` (docs/api.md
§16.2): AES-256-GCM, a random 96-bit nonce per encryption stored with the ciphertext, and
the field name as associated data, so a ciphertext copied to another field does not
decrypt. Today that is the SMTP password the instance admin sets."""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32
NONCE_BYTES = 12


def seal(key: bytes, field: str, plaintext: str) -> dict[str, str]:
    """The stored form: `{"nonce", "ciphertext"}`, both base64."""
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(key).encrypt(nonce, plaintext.encode(), field.encode())
    return {
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(sealed).decode(),
    }


def open_sealed(key: bytes | None, field: str, stored: object) -> str | None:
    """The plaintext, or None when there is no key or the key cannot decrypt it (the
    key was changed or lost): such a secret counts as not set (§16.2)."""
    if key is None or not isinstance(stored, dict):
        return None
    try:
        nonce = base64.b64decode(stored["nonce"], validate=True)
        sealed = base64.b64decode(stored["ciphertext"], validate=True)
        return AESGCM(key).decrypt(nonce, sealed, field.encode()).decode()
    except (KeyError, TypeError, ValueError, InvalidTag):
        return None
