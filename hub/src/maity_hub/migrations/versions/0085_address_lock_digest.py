"""The per-address locks hold the address's HMAC, never the address (docs/api.md §2.9).

`address_lock` and `registration_lock` kept a row per normalized address for good, so an
address outlived the account deletion that §2.9 says deletes it, and every address that
ever started a registration stayed in clear. The rows are only locks: nothing reads their
value, so both tables are made again keyed by `digest`, the HMAC the hub computes
(`addresses.lock_key`), and the old rows go. Without an instance key the HMAC's key is a
random pepper the hub makes at first use (`addresses.prepare`); the downgrade removes it.

Revision ID: 0085
Revises: 0084
Create Date: 2026-10-29
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0085"
down_revision: str | None = "0084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}
PEPPER = "address.lock_pepper"
_secret = sa.table("instance_secret", sa.column("name", sa.String))


def _lock_table(name: str, column: str, length: int) -> None:
    op.create_table(
        name,
        sa.Column(column, sa.String(length=length), nullable=False),
        sa.PrimaryKeyConstraint(column, name=op.f(f"pk_{name}")),
        **OPTIONS,
    )


def upgrade() -> None:
    # Only locks: no transaction holds one while the migration runs, and a row is made
    # again on the next use.
    op.drop_table("address_lock")
    op.drop_table("registration_lock")
    _lock_table("address_lock", "digest", 64)
    _lock_table("registration_lock", "digest", 64)


def downgrade() -> None:
    op.execute(_secret.delete().where(_secret.c.name == PEPPER))
    op.drop_table("registration_lock")
    op.drop_table("address_lock")
    _lock_table("registration_lock", "address_normalized", 254)
    _lock_table("address_lock", "address", 254)
