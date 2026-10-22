"""Token and code of a single-use link: a join (docs/api.md §3) or a runner
pairing (§15.2). The hub stores only their hashes."""

from __future__ import annotations

import hashlib
import re
import secrets

from maity_hub.ids import CROCKFORD


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def new_token() -> str:
    """128 random bits, URL-safe."""
    return secrets.token_urlsafe(16)


def new_code() -> str:
    """60 random bits as Crockford base32 in groups of four: `Q7MD-3XPL-8ZWE`."""
    raw = "".join(secrets.choice(CROCKFORD) for _ in range(12)).upper()
    return "-".join(raw[i : i + 4] for i in range(0, 12, 4))


def normalise_code(code: str) -> str:
    """Crockford's reading: case-blind, `-` and spaces ignored, I and L are 1, O is 0."""
    cleaned = re.sub(r"[\s-]", "", code.upper())
    return cleaned.translate(str.maketrans("ILO", "110"))


def code_matches(code: str, code_hash: str) -> bool:
    return secrets.compare_digest(digest(normalise_code(code)), code_hash)
