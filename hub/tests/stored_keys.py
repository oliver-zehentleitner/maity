"""The keys a limit keyed by a mail address keeps (hub/context/auth.md 7d3f0a52): in
`rate_count.subject` where the counts are shared across replicas, else in the process's
limiter. Each holds the address's `known_sources.address_key`, never the address nor a plain
SHA-256 of it."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable

from sqlalchemy import Engine, select

from maity_hub import shared_counts
from maity_hub import tables as t
from maity_hub.auth import known_sources
from maity_hub.ratelimit import Limiter


def stored(engine: Engine, limiter: Limiter) -> list[str]:
    """The keys `limiter` holds now, as they are stored."""
    if not limiter.local and shared_counts.active():
        with engine.connect() as conn:
            rows = conn.execute(
                select(t.rate_count.c.subject).where(t.rate_count.c.bucket == limiter.name)
            )
            return [str(subject) for subject in rows.scalars()]
    return list(limiter._hits)


def assert_keyed(engine: Engine, limiters: Iterable[Limiter], normalized: str) -> None:
    """Every limiter holds a key, and each of its keys holds the keyed fingerprint of
    `normalized`, and neither the address nor its plain SHA-256."""
    with engine.connect() as conn:
        keyed = known_sources.address_key(conn, normalized)
    plain = hashlib.sha256(normalized.encode()).hexdigest()
    for limiter in limiters:
        keys = stored(engine, limiter)
        assert keys, f"{limiter.name} holds no key"
        for key in keys:
            assert keyed in key, (limiter.name, key)
            assert normalized not in key and "@" not in key, (limiter.name, key)
            assert plain not in key, (limiter.name, key)
