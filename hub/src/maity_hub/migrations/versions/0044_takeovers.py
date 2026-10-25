"""Takeovers (docs/api.md §6.19).

A takeover records who takes a held card from whom, the window the holder has to
answer, and how it ended. The project policy gains `takeover_window_minutes`, and a
request may name the takeover it was filed for (the escalation's decision).

Revision ID: 0044
Revises: 0022
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0044"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "takeover",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("task_id", sa.String(length=40), nullable=False),
        sa.Column("from_member", sa.Integer(), nullable=False),
        sa.Column("from_instance", sa.String(length=5), nullable=True),
        sa.Column("to_member", sa.Integer(), nullable=False),
        sa.Column("to_instance", sa.String(length=5), nullable=True),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("requested_instance", sa.String(length=5), nullable=True),
        sa.Column("reason", MARKDOWN_TEXT, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False),
        sa.Column("window_ends_at", TIMESTAMP, nullable=False),
        sa.Column("escalate_at", TIMESTAMP, nullable=True),
        sa.Column("objection", JSON_VALUE, nullable=True),
        sa.Column("override", JSON_VALUE, nullable=True),
        sa.Column("outcome", JSON_VALUE, nullable=True),
        sa.Column("request_id", sa.String(length=40), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("closed_at", TIMESTAMP, nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_takeover_project_id_project")
        ),
        sa.ForeignKeyConstraint(["task_id"], ["card.id"], name=op.f("fk_takeover_task_id_card")),
        sa.ForeignKeyConstraint(
            ["from_member"], ["membership.id"], name=op.f("fk_takeover_from_member_membership")
        ),
        sa.ForeignKeyConstraint(
            ["to_member"], ["membership.id"], name=op.f("fk_takeover_to_member_membership")
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["membership.id"], name=op.f("fk_takeover_requested_by_membership")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_takeover")),
        **TABLE_OPTIONS,
    )
    op.create_index(op.f("ix_takeover_task_id"), "takeover", ["task_id"], unique=False)
    op.create_index(
        "ix_takeover_project_status", "takeover", ["project_id", "status"], unique=False
    )
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("takeover_id", sa.String(length=40), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_request_takeover_id_takeover"), "takeover", ["takeover_id"], ["id"]
        )
        batch_op.create_index(batch_op.f("ix_request_takeover_id"), ["takeover_id"], unique=False)
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("takeover_window_minutes", sa.Integer(), server_default="60", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("takeover_window_minutes")
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("fk_request_takeover_id_takeover"), type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_request_takeover_id"))
        batch_op.drop_column("takeover_id")
    # The table takes its indexes with it; MariaDB refuses to drop one alone that
    # backs a foreign key.
    op.drop_table("takeover")
