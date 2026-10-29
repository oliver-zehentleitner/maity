"""Deleting your own account (docs/api.md §2.9).

`human.deleted_at`: set when the account was deleted; the row stays, so every stored id
keeps resolving and the handle stays taken for good. `account_deletion` holds a
deletion request waiting for its confirmation by mail: `id` is the sha256 of the mailed
link's nonce, `live` is true while it may still be confirmed and NULL once it was
withdrawn (by `DELETE /me/deletion`, a newer request, a password change or a change of
the verified address), used or replaced, so a human has at most one pending request on
every engine. The instance statistics count deleted accounts from `human.deleted_at`
(§16.6 stores nothing of its own), so no counter table is needed. `account_lock` holds
one row per human and nothing else: a human caller's transaction takes it with a shared
lock before its first locking statement and the deletion takes it exclusively first
(`write_guard`), so the two share one lock order and no other lock of the human row
takes part; existing humans get their row here, later ones when first needed.

Re-chained at merge time: `down_revision` is the head of the chain this branch started
from and follows whatever head `main` has when it lands.

Revision ID: 0076
Revises: 0073
Create Date: 2026-10-28
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0076"
down_revision: str | None = "0073"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    with op.batch_alter_table("human") as batch_op:
        batch_op.add_column(sa.Column("deleted_at", TIMESTAMP, nullable=True))
    op.create_table(
        "account_deletion",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("requested_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("withdrawn_at", TIMESTAMP, nullable=True),
        sa.Column("withdrawn_by", sa.String(length=32), nullable=True),
        sa.Column("used_at", TIMESTAMP, nullable=True),
        sa.Column("live", sa.Boolean(), nullable=True),
        sa.CheckConstraint("live IS NOT FALSE", name=op.f("ck_account_deletion_live_true_or_null")),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_account_deletion_human_id_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_deletion")),
        sa.UniqueConstraint("human_id", "live", name=op.f("uq_account_deletion_human_id_live")),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "account_lock",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_account_lock_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", name=op.f("pk_account_lock")),
        **TABLE_OPTIONS,
    )
    op.execute("INSERT INTO account_lock (human_id) SELECT id FROM human")


def downgrade() -> None:
    op.drop_table("account_lock")
    op.drop_table("account_deletion")
    with op.batch_alter_table("human") as batch_op:
        batch_op.drop_column("deleted_at")
