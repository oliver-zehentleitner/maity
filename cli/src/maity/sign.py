"""Request signing, docs/api.md §2.2.

    Authorization: Maity-HMAC <credential_id>
    Maity-Timestamp: <unix seconds>
    Maity-Nonce: <16 random bytes, base64url>
    Maity-Signature: hex(HMAC-SHA256(sha256(<secret>), canonical))

The key is the raw 32 bytes of sha256 over the secret's text, the value the hub stores as the
verifier; the secret itself never leaves this process.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass

from maity.state import Secret

SCHEME = "MAITY-HMAC-V1"
CREDENTIAL_RE = re.compile(r"^mty1\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)$")
# The pattern the hub refuses in any body or query, and revokes a real credential for.
CREDENTIAL_IN_TEXT_RE = re.compile(r"\bmty1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")


class CredentialFormatError(Exception):
    """The value is not a credential in the `mty1.<id>.<secret>` format."""


@dataclass(frozen=True, repr=False)
class SigningKey:
    credential_id: str
    _key: bytes

    def __repr__(self) -> str:
        return f"SigningKey({self.credential_id}, <redacted>)"


def is_credential(value: str) -> bool:
    return CREDENTIAL_RE.match(value) is not None


def contains_credential(text: str) -> bool:
    return CREDENTIAL_IN_TEXT_RE.search(text) is not None


def signing_key(credential: Secret) -> SigningKey:
    match = CREDENTIAL_RE.match(credential.reveal())
    if match is None:
        raise CredentialFormatError("the stored credential is not in the mty1.<id>.<secret> format")
    credential_id, secret = match.groups()
    return SigningKey(credential_id, hashlib.sha256(secret.encode("utf-8")).digest())


def _enc(text: str) -> str:
    return urllib.parse.quote(text, safe="-_.~")


def canonical_query(pairs: Sequence[tuple[str, str]]) -> str:
    """Pairs sorted bytewise by key, repeated keys kept in request order, RFC 3986 encoded."""
    ordered = sorted(pairs, key=lambda kv: kv[0].encode("utf-8"))  # sorted() is stable
    return "&".join(f"{_enc(k)}={_enc(v)}" for k, v in ordered)


def canonical_string(
    method: str, path: str, query: str, timestamp: str, nonce: str, body: bytes
) -> str:
    return "\n".join(
        [
            SCHEME,
            method.upper(),
            path,
            query,
            timestamp,
            nonce,
            hashlib.sha256(body).hexdigest(),
        ]
    )


def new_nonce() -> str:
    return secrets.token_urlsafe(16)


def sign_headers(
    key: SigningKey, method: str, path: str, query: str, body: bytes, timestamp: int
) -> dict[str, str]:
    nonce = new_nonce()
    stamp = str(timestamp)
    canonical = canonical_string(method, path, query, stamp, nonce, body)
    signature = hmac.new(key._key, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "Authorization": f"Maity-HMAC {key.credential_id}",
        "Maity-Timestamp": stamp,
        "Maity-Nonce": nonce,
        "Maity-Signature": signature,
    }
