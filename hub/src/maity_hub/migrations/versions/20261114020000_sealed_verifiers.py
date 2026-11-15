"""Credential verifiers sealed at rest (docs/api.md §2.2, §16.2).

`credential.verifier` and `runner_credential.verifier` widen from 64 to 128 characters, room
for a sealed verifier: `s1:` and the base64 of the 32 bytes sealed by `maity_hub.secretbox`,
the table, the column and the id as associated data (`maity_hub.auth.verifiers`). The upgrade
only widens; it seals nothing, with or without the instance key. Sealing is opt-in
(`MAITY_SEAL_VERIFIERS`, default off, switched on later): with it on the hub seals what it
writes, and `maity-hub seal-verifiers` seals the rows written before
(hub/context/credentials.md).

Edited in place, revision ID and down_revision kept (card tsk-47b7fwkvft30, lead lotse,
2026-11-15). The form released in 0.1.0a6 also sealed every row when the key was given. That is
safe to change: the deploy that was to ship 0.1.0a6 never did, so our instances go from 0.1.0a5
to 0.1.0a7 and run this revision only in the form that widens. A database that already ran the
0.1.0a6 form has this revision recorded and does not run it again; its sealed rows keep
working, because the hub reads sealed rows whether sealing is on or off.

The downgrade opens every sealed row with the key and writes the hex back, in batches of
`BATCH` (one `UPDATE … WHERE id = :id` executed for many rows at a time), then narrows the
columns again. It refuses while a sealed row exists and no key, or not the key it was sealed
with, is given: an older hub could not read such a row.

Revision ID: 20261114020000_sealed_verifiers
Revises: 20261113200000_sf_day_revoked_by
Create Date: 2026-11-14
"""

import base64
import binascii
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

from maity_hub import secretbox

revision: str = "20261114020000_sealed_verifiers"
down_revision: str | None = "20261113200000_sf_day_revoked_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("credential", "runner_credential")
SEALED = "s1:"
BATCH = 500


def _key() -> bytes | None:
    key: bytes | None = context.config.attributes.get("secret_key")
    return key


def _field(table: str, credential_id: str) -> str:
    return f"{table}.verifier:{credential_id}"


def _rows(table: str, sealed: bool) -> list[tuple[str, str]]:
    rows = sa.table(table, sa.column("id", sa.String), sa.column("verifier", sa.String))
    like = rows.c.verifier.like(f"{SEALED}%")
    query = sa.select(rows.c.id, rows.c.verifier).where(like if sealed else sa.not_(like))
    return [(row.id, row.verifier) for row in op.get_bind().execute(query)]


def _write(table: str, values: list[dict[str, str]]) -> None:
    rows = sa.table(table, sa.column("id", sa.String), sa.column("verifier", sa.String))
    statement = (
        sa.update(rows)
        .where(rows.c.id == sa.bindparam("row_id"))
        .values(verifier=sa.bindparam("value"))
    )
    for start in range(0, len(values), BATCH):
        op.get_bind().execute(statement, values[start : start + BATCH])


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "verifier",
                existing_type=sa.String(64),
                type_=sa.String(128),
                existing_nullable=False,
            )


def downgrade() -> None:
    key = _key()
    opened: dict[str, list[dict[str, str]]] = {}
    for table in TABLES:
        values = []
        for row_id, value in _rows(table, sealed=True):
            if key is None:
                raise RuntimeError(
                    f"{table} holds sealed verifiers: downgrade with MAITY_SECRET_KEY set"
                )
            try:
                sealed = base64.b64decode(value[len(SEALED) :], validate=True)
                plain = secretbox.open_sealed(key, _field(table, row_id), sealed)
            except (binascii.Error, ValueError, secretbox.SealedError):
                raise RuntimeError(
                    f"{table} {row_id}: the verifier does not open with this MAITY_SECRET_KEY"
                ) from None
            values.append({"row_id": row_id, "value": plain.hex()})
        opened[table] = values
    for table in TABLES:  # nothing written before every row opened
        _write(table, opened[table])
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "verifier",
                existing_type=sa.String(128),
                type_=sa.String(64),
                existing_nullable=False,
            )
