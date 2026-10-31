"""`conversation_pin`: a human's pinned conversations (docs/api.md §9.3 "Pinned").

One row per human, project and chat id, at most 20 per human; a direct conversation's id is its
agent's member id, so the project is part of the key. Nothing to copy: no chat was pinned
before.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261031161000_conversation_pins
Revises: 20261031125530_long_polls
Create Date: 2026-10-31
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261031161000_conversation_pins"
down_revision: str | None = "20261031125530_long_polls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "conversation_pin",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("pinned_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_conversation_pin_human_id_human")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_conversation_pin_project_id_project")
        ),
        sa.PrimaryKeyConstraint(
            "human_id", "project_id", "conversation_id", name=op.f("pk_conversation_pin")
        ),
        **MYSQL,
    )
    op.create_index("ix_conversation_pin_project", "conversation_pin", ["project_id"])


def downgrade() -> None:
    # The index goes with the table: MariaDB refuses to drop it alone while the project's
    # foreign key needs it (error 1553).
    op.drop_table("conversation_pin")
