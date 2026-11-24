"""The daily cap of wrong second-factor codes and who revoked a join link (docs/api.md §2.8.6,
§3.1).

`second_factor_day` counts each human's wrong second-factor codes per UTC day; `unlocks` counts
the times the mailed link lifted the cap that day, `alerted` whether the alert with that link
was written since. It starts empty. `join_link.revoked_by` is who revoked a join; null on every
existing row, whose revoker was not recorded.

Revision ID: 20261113200000_sf_day_revoked_by
Revises: 20261113130000_experiment_notice
Create Date: 2026-11-13
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20261113200000_sf_day_revoked_by"
down_revision: str | None = "20261113130000_experiment_notice"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "second_factor_day",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("wrong_codes", sa.Integer(), nullable=False),
        sa.Column("unlocks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("alerted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_second_factor_day_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", "day", name=op.f("pk_second_factor_day")),
        **MYSQL,
    )
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.add_column(sa.Column("revoked_by", sa.String(length=40), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.drop_column("revoked_by")
    # The table goes whole, its primary key with it: no index is dropped alone while a foreign
    # key needs it (MariaDB error 1553).
    op.drop_table("second_factor_day")
