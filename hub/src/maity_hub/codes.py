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


ALPHABET = CROCKFORD.upper()  # as a code is shown and stored: 0-9 and A-Z without I, L, O, U


def random_code(length: int) -> str:
    """`length` random characters of Crockford base32, upper case, no groups."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def new_code() -> str:
    """60 random bits as Crockford base32 in groups of four: `Q7MD-3XPL-8ZWE`."""
    raw = random_code(12)
    return "-".join(raw[i : i + 4] for i in range(0, 12, 4))


def _read(code: str) -> str:
    cleaned = re.sub(r"[\s-]", "", code.upper())
    return cleaned.translate(str.maketrans("ILO", "110"))


def normalise_code(code: str) -> str:
    """Crockford's reading: case-blind, `-` and spaces ignored, I and L are 1, O is 0."""
    return _read(code)


def normalise(code: str, length: int) -> str | None:
    """Crockford's reading as `normalise_code`, checked: the upper-case code without
    hyphens when it is `length` characters of the alphabet, else None. A stored hash is
    taken over exactly this form (device codes, docs/api.md §2.6.2)."""
    text = _read(code)
    return text if len(text) == length and all(c in ALPHABET for c in text) else None


def code_matches(code: str, code_hash: str) -> bool:
    return secrets.compare_digest(digest(normalise_code(code)), code_hash)
