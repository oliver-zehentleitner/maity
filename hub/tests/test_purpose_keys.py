"""One derivation for every keyed value the hub stores (`secretbox.purpose_key`): HKDF of
`MAITY_SECRET_KEY` per purpose, else a random fallback key made at first use."""

from __future__ import annotations

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
    secretbox.prepare_fallback(migrated, None, positions.KEY_NAME, wipe_when_keyed=False)
    with migrated.connect() as conn:
        stored = store.sealed(conn, positions.KEY_NAME)
        assert stored is not None and len(stored) == 32
        assert secretbox.purpose_key(conn, None, positions.PURPOSE, positions.KEY_NAME) == stored
        keyed = secretbox.purpose_key(conn, KEY, positions.PURPOSE, positions.KEY_NAME)
        assert keyed == secretbox.derive(KEY, positions.PURPOSE) != stored


def test_a_second_first_use_keeps_the_key(migrated: Engine) -> None:
    secretbox.prepare_fallback(migrated, None, positions.KEY_NAME, wipe_when_keyed=False)
    with migrated.connect() as conn:
        first = secretbox.stored_fallback(conn, positions.KEY_NAME)
    secretbox.prepare_fallback(migrated, None, positions.KEY_NAME, wipe_when_keyed=False)
    with migrated.connect() as conn:
        assert first is not None and secretbox.stored_fallback(conn, positions.KEY_NAME) == first


@pytest.mark.parametrize("wipe", [True, False])
def test_an_instance_key_makes_nothing_and_wipes_only_on_request(
    migrated: Engine, wipe: bool
) -> None:
    secretbox.prepare_fallback(migrated, KEY, positions.KEY_NAME, wipe_when_keyed=wipe)
    with migrated.connect() as conn:
        assert store.sealed(conn, positions.KEY_NAME) is None
    secretbox.prepare_fallback(migrated, None, positions.KEY_NAME, wipe_when_keyed=wipe)
    secretbox.prepare_fallback(migrated, KEY, positions.KEY_NAME, wipe_when_keyed=wipe)
    with migrated.connect() as conn:
        assert (store.sealed(conn, positions.KEY_NAME) is None) is wipe


def test_a_stored_value_of_the_wrong_length_is_no_key(migrated: Engine) -> None:
    with migrated.begin() as conn:
        store.add_sealed(conn, positions.KEY_NAME, b"short")
    with migrated.connect() as conn:
        assert secretbox.stored_fallback(conn, positions.KEY_NAME) is None
