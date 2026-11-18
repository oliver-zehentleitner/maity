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

Rows are sealed when they are written with the setting on; when a plain row verifies a call
while the setting is on (`resealed`, in that call's own `last_used_at` update); and the rows
left over by `maity-hub seal-verifiers` (`seal_plain`). Never by a migration or a start of the
hub. The startup check counts the plain ones.

With `MAITY_SEALED_VERIFIERS_ONLY=1` (default off; it needs sealing on) a plain row verifies
nothing (`accepted`), answered as a sealed value the key does not open, and the hub does not
start while a live plain row is left (`check_at_startup`, `maity_hub.app.check_startup`).
"""

from __future__ import annotations

import base64
import binascii
import logging
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import Connection, Engine, bindparam, case, func, select, update

from maity_hub import secretbox
from maity_hub import tables as t

log = logging.getLogger(__name__)

SEALED = "s1:"
Table = Literal["credential", "runner_credential"]

# The instance key of the app that serves (`configure`, from `create_app`): a credential is
# written and read far from the settings, in the join, the enrolment and every call. The key
# reads sealed rows always; it seals new ones only while `_seal` is on (MAITY_SEAL_VERIFIERS).
# `_sealed_only` (MAITY_SEALED_VERIFIERS_ONLY) refuses a plain row when it authenticates.
_secret_key: list[bytes | None] = [None]
_seal: list[bool] = [False]
_sealed_only: list[bool] = [False]
BATCH = 500
_TABLES: tuple[tuple[Table, Any], ...] = (
    ("credential", t.credential),
    ("runner_credential", t.runner_credential),
)


def configure(secret_key: bytes | None, seal: bool = False, sealed_only: bool = False) -> None:
    _secret_key[0] = secret_key
    _seal[0] = seal and secret_key is not None
    _sealed_only[0] = sealed_only and _seal[0]


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
    current key does not open; None verifies nothing. The leak check reads with this, so a
    leaked plain credential is still revoked while MAITY_SEALED_VERIFIERS_ONLY is on."""
    if not value.startswith(SEALED):
        return value
    return _open(_secret_key[0], table, credential_id, value)


def accepted(table: Table, credential_id: str, value: str) -> str | None:
    """The verifier (hex) a stored value stands for when it authenticates a call: `usable`,
    and None for a plain row too while MAITY_SEALED_VERIFIERS_ONLY is on. The caller answers
    that None as it answers a sealed value the key does not open, so the refusal says nothing
    about sealing (hub/context/credentials.md)."""
    if _sealed_only[0] and not value.startswith(SEALED):
        return None
    return usable(table, credential_id, value)


def resealed(table: Table, credential_id: str, value: str) -> str | None:
    """Reseal on use: the sealed value for a plain row that has just verified a call while
    sealing is on, written in that call's `last_used_at` update (`reseal_value`); None when
    there is nothing to write (sealing off, or the row is sealed already)."""
    key = _secret_key[0]
    if key is None or not _seal[0] or value.startswith(SEALED):
        return None
    return _sealed(key, table, credential_id, value)


def reseal_value(table: Table, column: Any, credential_id: str, value: str) -> dict[str, Any]:
    """The `verifier` part of a call's `last_used_at` update: the sealed value while the row
    still holds the plain value read (a credential replaced meanwhile keeps its new value),
    else the row's own; nothing when there is nothing to reseal. No statement of its own."""
    sealed = resealed(table, credential_id, value)
    if sealed is None:
        return {}
    return {"verifier": case((column == value, sealed), else_=column)}


@dataclass(frozen=True)
class Counted:
    """One table's part of `maity-hub seal-verifiers`: rows this run sealed, rows sealed
    already before it, and plain rows left after it; revoked rows count too."""

    sealed: int
    already: int
    left: int


def count(engine: Engine) -> dict[Table, Counted]:
    """`maity-hub seal-verifiers --dry-run`: count and write nothing. Nothing is sealed, so
    every plain row is left."""
    counted: dict[Table, Counted] = {}
    with engine.connect() as conn:
        for name, table in _TABLES:
            already, plain = _split(conn, table)
            counted[name] = Counted(sealed=0, already=already, left=plain)
    return counted


def seal_and_count(engine: Engine, key: bytes) -> dict[Table, Counted]:
    """`maity-hub seal-verifiers`: `seal_plain` between a count before and one after."""
    with engine.connect() as conn:
        before = {name: _split(conn, table)[0] for name, table in _TABLES}
    sealed = seal_plain(engine, key)
    with engine.connect() as conn:
        return {
            name: Counted(sealed=sealed[name], already=before[name], left=_split(conn, table)[1])
            for name, table in _TABLES
        }


def _split(conn: Connection, table: Any) -> tuple[int, int]:
    """(sealed, plain) rows of a table, revoked ones included; one set-based read."""
    is_sealed = table.c.verifier.like(f"{SEALED}%")
    row = conn.execute(
        select(
            func.coalesce(func.sum(case((is_sealed, 1), else_=0)), 0),
            func.count(),
        ).select_from(table)
    ).one()
    sealed, total = int(row[0]), int(row[1])
    return sealed, total - sealed


def seal_plain(engine: Engine, key: bytes) -> dict[Table, int]:
    """`maity-hub seal-verifiers`: seal every plain verifier of both tables, revoked ones too,
    in batches of `BATCH`; a sealed row is left alone, so a second run seals nothing. A row is
    written only while it still holds the plain value read, so a credential replaced meanwhile
    keeps its new value. Returns the rows sealed per table."""
    counted: dict[Table, int] = {}
    for name, table in _TABLES:
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
    many are stored plain; each logged once, the plain ones with whether sealing is on. With
    MAITY_SEALED_VERIFIERS_ONLY the caller then refuses the start on plain ones
    (`maity_hub.app.check_startup`). Returns (unusable, plain)."""
    unusable = plain = 0
    with engine.connect() as conn:
        for table, columns in ((name, table.c) for name, table in _TABLES):
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
