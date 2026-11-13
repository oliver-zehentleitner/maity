"""Agent credentials and request signing (docs/api.md §2.2).

A credential is `mty1.<credential_id>.<secret>`; the hub stores
`sha256(<secret>)` over the secret's text and nothing else. That verifier
checks a bearer presentation and is the HMAC key of a signed request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_from_bytes, unquote_to_bytes

PREFIX = "mty1"
# No boundary in front: a credential counts whatever stands right before it, a letter or the
# `n` of a JSON `\n` included (§2.2). A match is refused anyway; only a verified one is revoked.
PATTERN = re.compile(rb"mty1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
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
    """Every string in the credential format inside `data`, and inside the strings a JSON
    `data` decodes to, so that no escape (`\\n`, `\\u006d`) hides one (§2.2)."""
    found = _matches(data)
    for text in _json_strings(data):
        found += _matches(text.encode("utf-8", "replace"))
    return list(dict.fromkeys(found))


def _matches(data: bytes) -> list[Presented]:
    found = []
    for match in PATTERN.finditer(data):
        _, credential_id, secret = match.group(0).decode("ascii").split(".")
        found.append(Presented(credential_id, secret))
    return found


def _json_strings(data: bytes) -> list[str]:
    """The keys and string values of `data` read as JSON; none when it is no JSON."""
    if data.lstrip()[:1] not in (b"{", b"[", b'"'):
        return []
    try:
        stack: list[Any] = [json.loads(data)]
    except (ValueError, RecursionError):  # UnicodeDecodeError is a ValueError
        return []
    strings: list[str] = []
    while stack:
        value = stack.pop()
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            stack.extend(value.keys())
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    return strings


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
    method: str,
    raw_path: bytes,
    raw_query: bytes,
    timestamp: str,
    nonce: str,
    body: bytes,
    for_member: str | None = None,
    on_request: str | None = None,
) -> str:
    """The string a request signs (§2.2). `Maity-On-Request` adds its line, the bare request
    id, then `Maity-For` its own, `for:` and the value, before the body hash; without a header
    there is no line, so a request signs as it did before the header existed."""
    return "\n".join(
        [
            "MAITY-HMAC-V1",
            method.upper(),
            raw_path.decode("latin-1"),
            canonical_query(raw_query),
            timestamp,
            nonce,
            *([on_request] if on_request is not None else []),
            *([f"for:{for_member}"] if for_member is not None else []),
            hashlib.sha256(body).hexdigest(),
        ]
    )


def sign(verifier_hex: str, canonical: str) -> str:
    return hmac.new(bytes.fromhex(verifier_hex), canonical.encode("utf-8"), "sha256").hexdigest()


def signature_matches(verifier_hex: str, canonical: str, signature: str) -> bool:
    """Constant-time; `signature` must be ASCII hex, which the caller checked."""
    expected = sign(verifier_hex, canonical).encode("ascii")
    return hmac.compare_digest(expected, signature.lower().encode("ascii", "replace"))


# The expired nonces one call of `NonceWindow.first_use` drops at most.
FORGET_PER_CALL = 64


class NonceWindow:
    """Nonces seen per credential within the window, in the process: the window of SQLite
    and MariaDB, where the hub runs one replica (docs/api.md §8.3). PostgreSQL keeps them in
    the database, shared by every replica (`auth.nonces`).

    A nonce is kept until its window ends. The window is the same for every nonce, so the order
    in which nonces are spent is the order in which they expire: `_expiring` holds them in that
    order (the clock is read under the lock, so two threads append in the order of their
    deadlines), and each call drops expired ones from its front, at most `FORGET_PER_CALL`. A
    call never visits a live nonce, and when a whole burst expires together (the window of every
    nonce of it ends within a moment) its backlog is dropped over the next calls, each taking its
    bounded share: authentication runs on the event loop (`deps._resolve`, tsk-v874y63b4z8p PR
    2), where a pass over every nonce, live or expired, would hold every other request of the
    process. An expired nonce still in the dict is not a spent one: `first_use` compares its
    deadline, not its presence."""

    def __init__(self, seconds: int = NONCE_WINDOW_SECONDS) -> None:
        self._seconds = seconds
        self._seen: dict[tuple[str, str], tuple[float, object]] = {}
        self._expiring: deque[tuple[float, tuple[str, str]]] = deque()
        self._lock = threading.Lock()

    def first_use(self, credential_id: str, nonce: str, spender: object) -> bool:
        """Spend the nonce; False when another `spender` did within the window. A transaction
        that is run again does not take this window back, so its request, the same `spender`,
        still counts as the first."""
        with self._lock:
            now = time.monotonic()
            self._forget_expired(now)
            key = (credential_id, nonce)
            seen = self._seen.get(key)
            if seen is not None and seen[0] > now:
                return seen[1] is spender
            until = now + self._seconds
            self._seen[key] = (until, spender)
            self._expiring.append((until, key))
            return True

    def _forget_expired(self, now: float) -> None:
        """Drop at most `FORGET_PER_CALL` nonces whose window ended, the oldest first; a nonce
        spent again after its window keeps its newer entry (its older place in the queue no
        longer matches it). A call adds at most one nonce and drops up to that many, so a
        backlog shrinks with every call."""
        for _ in range(FORGET_PER_CALL):
            if not self._expiring or self._expiring[0][0] > now:
                return
            until, key = self._expiring.popleft()
            seen = self._seen.get(key)
            if seen is not None and seen[0] == until:
                del self._seen[key]
