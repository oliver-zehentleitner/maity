"""A credential's verifier as it is stored (docs/api.md §2.2, §16.2).

The verifier (`credentials.verifier_of`) is the HMAC key of a signed request. Sealing it is
opt-in: with `MAITY_SEAL_VERIFIERS=1` and the instance key `MAITY_SECRET_KEY` the hub stores
it sealed (`maity_hub.secretbox`): `s1:` and the base64 of the sealed 32 bytes, with the
table, the column and the credential's id as associated data, so a value copied into another
row does not open. With the setting off (the default) it is stored as 64 hex characters, as
before. Both forms are read either way, so switching the setting off again locks no one out.
A sealed value the current key does not open (the key unset, changed or lost) verifies
nothing: the credential answers as an unknown one, and its agent or runner joins again
(hub/context/credentials.md).

Rows are sealed when they are written with the setting on, and the rows written before by
`maity-hub seal-verifiers` (`seal_plain`); never by a migration or a start of the hub. The
startup check counts the plain ones.
"""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any, Literal

from sqlalchemy import Engine, bindparam, select, update

from maity_hub import secretbox
from maity_hub import tables as t

log = logging.getLogger(__name__)

SEALED = "s1:"
Table = Literal["credential", "runner_credential"]

# The instance key of the app that serves (`configure`, from `create_app`): a credential is
# written and read far from the settings, in the join, the enrolment and every call. The key
# reads sealed rows always; it seals new ones only while `_seal` is on (MAITY_SEAL_VERIFIERS).
_secret_key: list[bytes | None] = [None]
_seal: list[bool] = [False]
BATCH = 500


def configure(secret_key: bytes | None, seal: bool = False) -> None:
    _secret_key[0] = secret_key
    _seal[0] = seal and secret_key is not None


def field(table: Table, credential_id: str) -> str:
    return f"{table}.verifier:{credential_id}"


def stored(table: Table, credential_id: str, verifier_hex: str) -> str:
    """What the row holds for a new verifier: sealed while sealing is on, plain otherwise."""
    key = _secret_key[0]
    if key is None or not _seal[0]:
        return verifier_hex
    return _sealed(key, table, credential_id, verifier_hex)


def _sealed(key: bytes, table: Table, credential_id: str, verifier_hex: str) -> str:
    sealed = secretbox.seal(key, field(table, credential_id), bytes.fromhex(verifier_hex))
    return SEALED + base64.b64encode(sealed).decode("ascii")


def usable(table: Table, credential_id: str, value: str) -> str | None:
    """The verifier (hex) a stored value stands for, or None when it is a sealed value the
    current key does not open; None verifies nothing."""
    if not value.startswith(SEALED):
        return value
    return _open(_secret_key[0], table, credential_id, value)


def seal_plain(engine: Engine, key: bytes) -> dict[Table, int]:
    """`maity-hub seal-verifiers`: seal every plain verifier of both tables, revoked ones too,
    in batches of `BATCH`; a sealed row is left alone, so a second run seals nothing. A row is
    written only while it still holds the plain value read, so a credential replaced meanwhile
    keeps its new value. Returns the rows sealed per table."""
    tables: tuple[tuple[Table, Any], ...] = (
        ("credential", t.credential),
        ("runner_credential", t.runner_credential),
    )
    counted: dict[Table, int] = {}
    for name, table in tables:
        with engine.connect() as conn:
            rows = conn.execute(
                select(table.c.id, table.c.verifier).where(table.c.verifier.not_like(f"{SEALED}%"))
            ).all()
        statement = (
            update(table)
            .where(table.c.id == bindparam("row_id"), table.c.verifier == bindparam("plain"))
            .values(verifier=bindparam("value"))
        )
        sealed = 0
        for start in range(0, len(rows), BATCH):
            values = [
                {
                    "row_id": row.id,
                    "plain": row.verifier,
                    "value": _sealed(key, name, row.id, row.verifier),
                }
                for row in rows[start : start + BATCH]
            ]
            with engine.begin() as conn:
                result = conn.execute(statement, values)
            # Not every driver counts an executemany; then every row written is counted.
            sealed += result.rowcount if result.rowcount >= 0 else len(values)
        counted[name] = sealed
    return counted


def check_at_startup(engine: Engine, key: bytes | None, seal: bool = False) -> tuple[int, int]:
    """At startup, read only: how many live verifiers the instance key does not open, and how
    many are stored plain; each logged once, the plain ones with whether sealing is on.
    Returns (unusable, plain)."""
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
    if plain and seal and key is not None:
        log.warning(
            "%d live credential verifier(s) are stored unsealed; sealing is on "
            "(MAITY_SEAL_VERIFIERS), `maity-hub seal-verifiers` seals them",
            plain,
        )
    elif plain:
        log.info(
            "%d live credential verifier(s) are stored unsealed; sealing is off "
            "(MAITY_SEAL_VERIFIERS)",
            plain,
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
