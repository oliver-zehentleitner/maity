"""Human passwords: scrypt from the standard library (docs/api.md §2.1)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading

N, R, P = 2**15, 8, 1
MIN_LENGTH = 12  # characters, no composition rules (docs/api.md §2.1)
SALT_BYTES = 32
KEY_BYTES = 32
# 128 * r * n bytes of work memory, plus headroom; the default cap is too small.
MAXMEM = 64 * 1024 * 1024


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# Each derivation holds 32 MiB; at most this many run at once, so a burst of
# logins queues instead of exhausting memory.
CONCURRENT = 4
_SLOTS = threading.BoundedSemaphore(CONCURRENT)


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    with _SLOTS:
        return hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=MAXMEM, dklen=KEY_BYTES
        )


def hash_password(password: str) -> str:
    """`scrypt$<n>$<r>$<p>$<salt>$<key>`: the parameters travel with the hash."""
    salt = secrets.token_bytes(SALT_BYTES)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P))}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, key = stored.split("$")
        if scheme != "scrypt":
            return False
        derived = _derive(password, _unb64(salt), int(n), int(r), int(p))
    except ValueError:
        return False
    return hmac.compare_digest(derived, _unb64(key))


# Verified against when the handle does not exist, so that a wrong handle
# costs the same time as a wrong password.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
