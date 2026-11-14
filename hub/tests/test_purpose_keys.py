"""One derivation for every keyed value the hub stores (`secretbox.purpose_key`): HKDF of
`MAITY_SECRET_KEY` per purpose, else a random fallback key made at first use."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import Engine

from maity_hub import instance_settings as store
from maity_hub import secretbox
from maity_hub.auth import known_sources
from maity_hub.mail import address as addresses
from maity_hub.notifications import positions

KEY = b"k" * 32

# What HKDF-SHA256 (no salt, the purpose as info) gave for KEY before the derivation had one
# home. A change here invalidates every lock row, position and known source already stored.
PINNED = {
    addresses.LOCK_PURPOSE: "c26859703866155ca6552787960becae7a36e8788f0cf58c5d93b90d1a8e7d38",
    positions.PURPOSE: "b1375ec552e6cb421eb0bb478863b6a731cac2796a7d32ab108c92c8cbf18dbe",
    known_sources.PURPOSE: "93a4948805ccabc2c78b5a235bbfa55c7bb069e156a266ca6579466361c23397",
}


@pytest.mark.parametrize("purpose", sorted(PINNED))
def test_the_derived_keys_stay_byte_identical(purpose: str) -> None:
    assert secretbox.derive(KEY, purpose).hex() == PINNED[purpose]


def test_the_instance_key_comes_first_else_the_fallback(migrated: Engine) -> None:
    with migrated.connect() as conn:
        assert secretbox.purpose_key(conn, None, positions.PURPOSE, positions.KEY_NAME) is None
    secretbox.prepare_fallback(migrated, None, positions.KEY_NAME)
    with migrated.connect() as conn:
        stored = store.sealed(conn, positions.KEY_NAME)
        assert stored is not None and len(stored) == 32
        assert secretbox.purpose_key(conn, None, positions.PURPOSE, positions.KEY_NAME) == stored
        keyed = secretbox.purpose_key(conn, KEY, positions.PURPOSE, positions.KEY_NAME)
        assert keyed == secretbox.derive(KEY, positions.PURPOSE) != stored


def test_a_second_first_use_keeps_the_key(migrated: Engine) -> None:
    secretbox.prepare_fallback(migrated, None, positions.KEY_NAME)
    with migrated.connect() as conn:
        first = secretbox.stored_fallback(conn, positions.KEY_NAME)
    secretbox.prepare_fallback(migrated, None, positions.KEY_NAME)
    with migrated.connect() as conn:
        assert first is not None and secretbox.stored_fallback(conn, positions.KEY_NAME) == first


def test_an_instance_key_makes_nothing(migrated: Engine) -> None:
    secretbox.prepare_fallback(migrated, KEY, positions.KEY_NAME)
    with migrated.connect() as conn:
        assert store.sealed(conn, positions.KEY_NAME) is None


@pytest.mark.parametrize(
    ("prepare", "name"),
    [(positions.prepare, positions.KEY_NAME), (addresses.prepare, addresses.LOCK_PEPPER)],
)
def test_the_fallback_key_is_gone_once_an_instance_key_is_set(
    migrated: Engine, prepare: Callable[[Engine, bytes | None], None], name: str
) -> None:
    """Nothing stored needs a fallback key once `MAITY_SECRET_KEY` is set: the position key
    and the address pepper are both removed at the next first use."""
    prepare(migrated, None)
    with migrated.connect() as conn:
        assert store.sealed(conn, name) is not None
    prepare(migrated, KEY)
    with migrated.connect() as conn:
        assert store.sealed(conn, name) is None
        if name == positions.KEY_NAME:  # positions keep working, under the derived key
            token = positions.issue(conn, KEY, "hum_wipe", positions.Position(account=3))
            found = positions.read(conn, KEY, "hum_wipe", token)
            assert found is not None and found.account == 3


def test_a_stored_value_of_the_wrong_length_is_no_key(migrated: Engine) -> None:
    with migrated.begin() as conn:
        store.add_sealed(conn, positions.KEY_NAME, b"short")
    with migrated.connect() as conn:
        assert secretbox.stored_fallback(conn, positions.KEY_NAME) is None
