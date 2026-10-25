"""Two-factor sign-in for humans (docs/api.md §2.8).

`second_factor` holds one row per human who ever enrolled: the sealed TOTP secret, the
last step used, an unconfirmed enrolment, and the generation reset links name.
`recovery_code` holds the HMACs of the ten recovery codes, `second_factor_reset` an
instance admin's reset waiting for the human's confirmation by mail. `human_session`
gains its state (`full`, `second_factor`, `enrolment`), whether its sign-in is
complete, when it last gave the password and the second factor, how its sign-in's
second step was given, and the login's `next`; `ended_by` grows for the two new
reasons (`second_factor_disabled`, `second_factor_reset`).

Revision ID: 0051
Revises: 0045
Create Date: 2026-10-25
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0051"
down_revision: str | None = "0045"
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
    with op.batch_alter_table("human_session") as batch:
        batch.alter_column(
            "ended_by",
            existing_type=sa.String(length=16),
            type_=sa.String(length=32),
            existing_nullable=True,
        )
        batch.add_column(
            sa.Column("state", sa.String(length=16), nullable=False, server_default="full")
        )
        batch.add_column(
            sa.Column("sign_in_complete", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch.add_column(sa.Column("password_at", TIMESTAMP, nullable=True))
        batch.add_column(sa.Column("second_factor_at", TIMESTAMP, nullable=True))
        batch.add_column(sa.Column("second_factor", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("next", sa.String(length=512), nullable=True))
    op.create_table(
        "second_factor",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("secret", sa.LargeBinary(), nullable=True),
        sa.Column("enrolled_at", TIMESTAMP, nullable=True),
        sa.Column("last_step", sa.BigInteger(), nullable=True),
        sa.Column("last_used_at", TIMESTAMP, nullable=True),
        sa.Column("pending_secret", sa.LargeBinary(), nullable=True),
        sa.Column("pending_session", sa.String(length=64), nullable=True),
        sa.Column("pending_expires_at", TIMESTAMP, nullable=True),
        sa.Column("generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reset_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_second_factor_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", name=op.f("pk_second_factor")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "recovery_code",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_recovery_code_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", "code_hash", name=op.f("pk_recovery_code")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "second_factor_reset",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("used_at", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_second_factor_reset_human_id_human")
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["human.id"],
            name=op.f("fk_second_factor_reset_requested_by_human"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_second_factor_reset")),
        **TABLE_OPTIONS,
    )
    op.create_index(op.f("ix_second_factor_reset_human_id"), "second_factor_reset", ["human_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_second_factor_reset_human_id"), table_name="second_factor_reset")
    op.drop_table("second_factor_reset")
    op.drop_table("recovery_code")
    op.drop_table("second_factor")
    # The two new reasons do not fit the old width: they go before it shrinks.
    op.execute(
        "UPDATE human_session SET ended_by = NULL "
        "WHERE ended_by IN ('second_factor_disabled', 'second_factor_reset', "
        "'second_factor_failed')"
    )
    with op.batch_alter_table("human_session") as batch:
        for name in ("next", "second_factor", "second_factor_at", "password_at"):
            batch.drop_column(name)
        batch.drop_column("sign_in_complete")
        batch.drop_column("state")
        batch.alter_column(
            "ended_by",
            existing_type=sa.String(length=32),
            type_=sa.String(length=16),
            existing_nullable=True,
        )
