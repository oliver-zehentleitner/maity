"""The per-address locks (docs/api.md §18.4, §2.7.1) hold an HMAC of the address, never the
address: a lock row outlives no account's address (§2.9)."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import Engine, delete, select

from maity_hub import registration_accounts
from maity_hub import tables as t
from maity_hub.mail import address as addresses
from tests import factory
from tests.conftest import ClientFactory
from tests.test_registration_accounts import admin as admin  # noqa: F401  (the fixture)
from tests.test_registration_accounts import complete, requested, settings_for

DIGEST = re.compile(r"[0-9a-f]{64}")


def _keys(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        return [
            *conn.execute(select(t.address_lock.c.digest)).scalars(),
            *conn.execute(select(t.registration_lock.c.digest)).scalars(),
        ]


def test_a_registration_and_a_claim_leave_no_address_in_a_lock(
    make_client: ClientFactory, migrated: Engine, admin: object
) -> None:
    settings = settings_for()
    pending = requested(make_client, migrated, settings, "Ada@Example.com")
    assert complete(migrated, settings, pending.id).kind == "created"
    holder = factory.human(migrated, "holder")
    with migrated.begin() as conn:
        assert registration_accounts.claim_address(
            conn, "grace@example.org", holder, secret_key=None
        )
    keys = _keys(migrated)
    assert keys and all(DIGEST.fullmatch(k) for k in keys)
    assert not any("@" in k or "example" in k for k in keys)


def test_the_key_is_one_per_address_and_the_instance_key_comes_first(migrated: Engine) -> None:
    with migrated.connect() as conn:
        stored = addresses.lock_key(conn, None, "ada@example.com")
        assert stored == addresses.lock_key(conn, None, "  Ada@Example.COM ")
        assert stored != addresses.lock_key(conn, None, "grace@example.com")
        keyed = addresses.lock_key(conn, b"k" * 32, "ada@example.com")
        assert keyed != stored and DIGEST.fullmatch(keyed)


def test_without_the_pepper_and_an_instance_key_no_lock_is_taken(migrated: Engine) -> None:
    """No bare hash as a fallback: a missing pepper is an error, not a weaker key."""
    with migrated.begin() as conn:
        conn.execute(
            delete(t.instance_secret).where(t.instance_secret.c.name == addresses.LOCK_PEPPER)
        )
        with pytest.raises(RuntimeError):
            addresses.lock(conn, None, "ada@example.com")
        addresses.lock(conn, b"k" * 32, "ada@example.com")  # the instance key needs none
    addresses.prepare(migrated, None)  # made again at the next first use
    with migrated.begin() as conn:
        addresses.lock(conn, None, "ada@example.com")
