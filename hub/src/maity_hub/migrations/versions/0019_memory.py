"""Memory: the soul of an agent profile and its versions, team and community entries
(docs/api.md §19).

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0019"
down_revision: str | None = "0018"
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
        "soul",
        sa.Column("agent_id", sa.String(length=40), nullable=False),
        sa.Column("markdown", MARKDOWN_TEXT, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("by_kind", sa.String(length=16), nullable=False),
        sa.Column("by_id", sa.String(length=40), nullable=False),
        sa.Column("confirmed_by", sa.String(length=40), nullable=True),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"], ["agent_profile.id"], name=op.f("fk_soul_agent_id_agent_profile")
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["human.id"], name=op.f("fk_soul_confirmed_by_human")
        ),
        sa.PrimaryKeyConstraint("agent_id", name=op.f("pk_soul")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "soul_version",
        sa.Column("agent_id", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("markdown", MARKDOWN_TEXT, nullable=False),
        sa.Column("by_kind", sa.String(length=16), nullable=False),
        sa.Column("by_id", sa.String(length=40), nullable=False),
        sa.Column("confirmed_by", sa.String(length=40), nullable=True),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_profile.id"],
            name=op.f("fk_soul_version_agent_id_agent_profile"),
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["human.id"], name=op.f("fk_soul_version_confirmed_by_human")
        ),
        sa.PrimaryKeyConstraint("agent_id", "version", name=op.f("pk_soul_version")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "memory_entry",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("store", sa.String(length=16), nullable=False),
        sa.Column("team_membership", sa.Integer(), nullable=True),
        sa.Column("text", MARKDOWN_TEXT, nullable=True),
        sa.Column("tags", JSON_VALUE, nullable=False),
        sa.Column("by_kind", sa.String(length=16), nullable=False),
        sa.Column("by_membership", sa.Integer(), nullable=True),
        sa.Column("by_session_id", sa.String(length=40), nullable=True),
        sa.Column("by_instance", sa.String(length=40), nullable=True),
        sa.Column("confirmed_by", sa.String(length=40), nullable=True),
        sa.Column("request_id", sa.String(length=40), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("deleted_at", TIMESTAMP, nullable=True),
        sa.Column("deleted_by_kind", sa.String(length=16), nullable=True),
        sa.Column("deleted_by_membership", sa.Integer(), nullable=True),
        sa.Column("deleted_reason", MARKDOWN_TEXT, nullable=True),
        sa.CheckConstraint(
            "(store = 'team' AND team_membership IS NOT NULL)"
            " OR (store = 'community' AND team_membership IS NULL)",
            name=op.f("ck_memory_entry_store_shape"),
        ),
        sa.CheckConstraint(
            "(deleted_at IS NULL AND text IS NOT NULL)"
            " OR (deleted_at IS NOT NULL AND text IS NULL)",
            name=op.f("ck_memory_entry_tombstone_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_memory_entry_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["team_membership"],
            ["membership.id"],
            name=op.f("fk_memory_entry_team_membership_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["by_membership"],
            ["membership.id"],
            name=op.f("fk_memory_entry_by_membership_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["human.id"], name=op.f("fk_memory_entry_confirmed_by_human")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"], ["request.id"], name=op.f("fk_memory_entry_request_id_request")
        ),
        sa.ForeignKeyConstraint(
            ["deleted_by_membership"],
            ["membership.id"],
            name=op.f("fk_memory_entry_deleted_by_membership_membership"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_entry")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_memory_entry_project_store",
        "memory_entry",
        ["project_id", "store", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_memory_entry_team", "memory_entry", ["team_membership", "created_at"], unique=False
    )


def downgrade() -> None:
    # The tables take their indexes along; MariaDB refuses to drop an index a foreign key
    # needs first.
    op.drop_table("memory_entry")
    op.drop_table("soul_version")
    op.drop_table("soul")
