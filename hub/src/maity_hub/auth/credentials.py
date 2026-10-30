"""Agent credentials and request signing (docs/api.md §2.2).

A credential is `mty1.<credential_id>.<secret>`; the hub stores
`sha256(<secret>)` over the secret's text and nothing else. That verifier
checks a bearer presentation and is the HMAC key of a signed request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time
from dataclasses import dataclass
from urllib.parse import quote_from_bytes, unquote_to_bytes

PREFIX = "mty1"
PATTERN = re.compile(rb"\bmty1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
EMPTY_BODY_SHA256 = hashlib.sha256(b"").hexdigest()

TIMESTAMP_WINDOW_SECONDS = 300
NONCE_WINDOW_SECONDS = 600


@dataclass(frozen=True)
class Presented:
    credential_id: str
    secret: str


def issue(credential_id: str) -> tuple[str, str]:
    """A new credential value and its verifier (hex)."""
    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    return f"{PREFIX}.{credential_id}.{secret}", verifier_of(secret)


def verifier_of(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def parse(value: str) -> Presented | None:
    match = PATTERN.fullmatch(value.encode("utf-8", "replace"))
    if match is None:
        return None
    _, credential_id, secret = value.split(".")
    return Presented(credential_id, secret)


def find_all(data: bytes) -> list[Presented]:
    """Every string in the credential format inside `data`."""
    found = []
    for match in PATTERN.finditer(data):
        _, credential_id, secret = match.group(0).decode("ascii").split(".")
        found.append(Presented(credential_id, secret))
    return found


def secret_matches(secret: str, verifier_hex: str) -> bool:
    return hmac.compare_digest(verifier_of(secret), verifier_hex)


def _rfc3986(raw: bytes) -> str:
    """Percent-decode to bytes and re-encode: on bytes, so that distinct raw
    queries never meet in one canonical form (`%FF` stays `%FF`, a raw `+`
    is `%2B`, raw UTF-8 is encoded once)."""
    return quote_from_bytes(unquote_to_bytes(raw), safe="-_.~")


def canonical_query(raw_query: bytes) -> str:
    """Pairs sorted bytewise by key, repeated keys in request order, RFC 3986 encoded."""
    pairs = []
    for part in raw_query.split(b"&"):
        if not part:
            continue
        key, _, value = part.partition(b"=")
        pairs.append((_rfc3986(key), _rfc3986(value)))
    pairs.sort(key=lambda pair: pair[0].encode("ascii"))  # stable: repeats keep their order
    return "&".join(f"{key}={value}" for key, value in pairs)


def canonical_string(
    method: str, raw_path: bytes, raw_query: bytes, timestamp: str, nonce: str, body: bytes
) -> str:
    return "\n".join(
        [
            "MAITY-HMAC-V1",
            method.upper(),
            raw_path.decode("latin-1"),
            canonical_query(raw_query),
            timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        ]
    )


def sign(verifier_hex: str, canonical: str) -> str:
    return hmac.new(bytes.fromhex(verifier_hex), canonical.encode("utf-8"), "sha256").hexdigest()


def signature_matches(verifier_hex: str, canonical: str, signature: str) -> bool:
    """Constant-time; `signature` must be ASCII hex, which the caller checked."""
    expected = sign(verifier_hex, canonical).encode("ascii")
    return hmac.compare_digest(expected, signature.lower().encode("ascii", "replace"))


class NonceWindow:
    """Nonces seen per credential within the window, in the process: the window of SQLite
    and MariaDB, where the hub runs one replica (docs/api.md §8.3). PostgreSQL keeps them in
    the database, shared by every replica (`auth.nonces`)."""

    def __init__(self, seconds: int = NONCE_WINDOW_SECONDS) -> None:
        self._seconds = seconds
        self._seen: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def first_use(self, credential_id: str, nonce: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._seen) > 10_000:
                self._seen = {k: t for k, t in self._seen.items() if t > now}
            key = (credential_id, nonce)
            expires = self._seen.get(key)
            if expires is not None and expires > now:
                return False
            self._seen[key] = now + self._seconds
            return True
