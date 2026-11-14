"""A credential's verifier as it is stored (docs/api.md §2.2, §16.2).

The verifier (`credentials.verifier_of`) is the HMAC key of a signed request, so the hub
stores it sealed with the instance key `MAITY_SECRET_KEY` (`maity_hub.secretbox`): `s1:`
and the base64 of the sealed 32 bytes, with the table, the column and the credential's id
as associated data, so a value copied into another row does not open. Without an instance
key it is stored as 64 hex characters, as before; both forms are read. A sealed value the
current key does not open (the key unset, changed or lost) verifies nothing: the credential
answers as an unknown one, and its agent or runner joins again (hub/context/credentials.md).

Rows are sealed when they are written and by the migration `20261114020000_sealed_verifiers`,
never by a start of the hub: a key added later leaves the older rows plain until their
credential is replaced, and the startup check counts them.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any, Literal

from sqlalchemy import Engine, select

from maity_hub import secretbox
from maity_hub import tables as t

log = logging.getLogger(__name__)

SEALED = "s1:"
Table = Literal["credential", "runner_credential"]

# The instance key of the app that serves (`configure`, from `create_app`): a credential is
# written and read far from the settings, in the join, the enrolment and every call.
_secret_key: list[bytes | None] = [None]


def configure(secret_key: bytes | None) -> None:
    _secret_key[0] = secret_key


def field(table: Table, credential_id: str) -> str:
    return f"{table}.verifier:{credential_id}"


def stored(table: Table, credential_id: str, verifier_hex: str) -> str:
    """What the row holds for a new verifier: sealed with the instance key, plain without."""
    key = _secret_key[0]
    if key is None:
        return verifier_hex
    sealed = secretbox.seal(key, field(table, credential_id), bytes.fromhex(verifier_hex))
    return SEALED + base64.b64encode(sealed).decode("ascii")


def usable(table: Table, credential_id: str, value: str) -> str | None:
    """The verifier (hex) a stored value stands for, or None when it is a sealed value the
    current key does not open; None verifies nothing."""
    if not value.startswith(SEALED):
        return value
    return _open(_secret_key[0], table, credential_id, value)


def check_at_startup(engine: Engine, key: bytes | None) -> tuple[int, int]:
    """At startup, read only: how many live verifiers the instance key does not open, and how
    many are stored plain; each logged once. Returns (unusable, plain)."""
    unusable = plain = 0
    with engine.connect() as conn:
        tables: tuple[tuple[Table, Any], ...] = (
            ("credential", t.credential.c),
            ("runner_credential", t.runner_credential.c),
        )
        for table, columns in tables:
            rows = conn.execute(
                select(columns.id, columns.verifier).where(columns.revoked_at.is_(None))
            )
            for row in rows:
                if not row.verifier.startswith(SEALED):
                    plain += 1
                elif _open(key, table, row.id, row.verifier) is None:
                    unusable += 1
    if unusable:
        log.error(
            "%d live credential(s) cannot be verified: MAITY_SECRET_KEY is %s; their agents "
            "and runners are refused until they join again",
            unusable,
            "unset" if key is None else "not the key they were sealed with",
        )
    if plain:
        log.warning(
            "%d live credential verifier(s) are stored unsealed (%s); they stay so until "
            "their agents and runners join again",
            plain,
            "MAITY_SECRET_KEY is unset" if key is None else "written before the key was set",
        )
    return unusable, plain


def _open(key: bytes | None, table: Table, credential_id: str, value: str) -> str | None:
    if key is None:
        return None
    try:
        sealed = base64.b64decode(value[len(SEALED) :], validate=True)
        return secretbox.open_sealed(key, field(table, credential_id), sealed).hex()
    except (binascii.Error, ValueError, secretbox.SealedError):
        return None
