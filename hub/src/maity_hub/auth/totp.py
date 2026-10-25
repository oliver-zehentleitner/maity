"""Time-based one-time codes, RFC 6238 over RFC 4226 (docs/api.md §2.8.1): HMAC-SHA-1,
six digits, a 30-second step, the current step and one either side accepted. Which
step a human used last is the caller's to keep, so a code is accepted once."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote, urlencode

DIGITS = 6
PERIOD = 30
SKEW = 1  # steps either side of the current one
SECRET_BYTES = 20


def new_secret() -> bytes:
    return secrets.token_bytes(SECRET_BYTES)


def base32(secret: bytes) -> str:
    """The secret as an authenticator app takes it: base32 without padding."""
    return base64.b32encode(secret).decode().rstrip("=")


def uri(secret: bytes, handle: str, issuer: str) -> str:
    label = quote(f"{issuer}:{handle}", safe=":@")
    query = urlencode(
        {"secret": base32(secret), "issuer": issuer, "digits": DIGITS, "period": PERIOD}
    )
    return f"otpauth://totp/{label}?{query}"


def code_at(secret: bytes, step: int) -> str:
    digest = hmac.new(secret, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def step_of(timestamp: float) -> int:
    return int(timestamp // PERIOD)


def normalised(code: str) -> str | None:
    """Spaces are ignored; anything but six digits is no code."""
    text = "".join(code.split())
    return text if len(text) == DIGITS and text.isascii() and text.isdigit() else None


def matching_step(secret: bytes, code: str, timestamp: float, after: int | None) -> int | None:
    """The step `code` belongs to within the window, newer than `after` (the last step
    used), or None. Compared in constant time per candidate."""
    text = normalised(code)
    if text is None:
        return None
    now = step_of(timestamp)
    for step in range(now - SKEW, now + SKEW + 1):
        if after is not None and step <= after:
            continue
        if hmac.compare_digest(code_at(secret, step), text):
            return step
    return None
