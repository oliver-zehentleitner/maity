"""The tokens in mail links (docs/api.md §18.6): the base64url of `{human id, purpose,
kind or address, epoch, …}` and an HMAC-SHA-256 over it with `MAITY_MAIL_SIGNING_KEY`.
The hub stores no unsubscribe token; a verify token carries its expiry and a nonce that
only the newest link of a human holds."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from typing import Any

MAX_LENGTH = 1024


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make(key: bytes, payload: dict[str, Any]) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(key, body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def read(key: bytes | None, token: str) -> dict[str, Any] | None:
    """The payload of a token this hub signed, or None; never which part was wrong."""
    if key is None or not token or len(token) > MAX_LENGTH or token.count(".") != 1:
        return None
    body, mac = token.split(".")
    expected = hmac.new(key, body.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(expected, _unb64(mac)):
            return None
        payload = json.loads(_unb64(body))
    except (binascii.Error, ValueError):
        return None
    return payload if isinstance(payload, dict) else None
