"""The instance admin's limits for one project or one human account (docs/api.md §16.5.1).

One row per value set, on a project (`project_id`) or on an account (`human_id`), never both:
`value` is a whole number or `"unlimited"`; no row means the instance's value or the default
ceiling (§6.31). A new table: nothing to carry over, and without a row every limit stays as
it was.

Revision ID: 20261117230000_limit_override
Revises: 20261117130000_plc_per_instance
Create Date: 2026-11-17
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from maity_hub.types import JSON_VALUE, UtcDateTime

revision: str = "20261117230000_limit_override"
down_revision: str | None = "20261117100000_roles_version"  # LOCAL: back to plc_per_instance before the PR
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
        "limit_override",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=True),
        sa.Column("human_id", sa.String(length=40), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("value", JSON_VALUE, nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.Column("updated_by", sa.String(length=40), nullable=True),
        sa.CheckConstraint(
            "(project_id IS NULL) <> (human_id IS NULL)", name=op.f("ck_limit_override_one")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_limit_override_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_limit_override_human_id_human")
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"], ["human.id"], name=op.f("fk_limit_override_updated_by_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_limit_override")),
        sa.UniqueConstraint("project_id", "name", name="uq_limit_override_project"),
        sa.UniqueConstraint("human_id", "name", name="uq_limit_override_human"),
        **MYSQL,
    )


def downgrade() -> None:
    # The table alone: no index of another table goes, so no foreign key loses its index.
    op.drop_table("limit_override")
