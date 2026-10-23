"""A human's preferences (docs/api.md §19.4): one versioned text per human, the switch per
membership, the agent membership that is given its owner's text, and personal requests
addressed to a human in person (`to_kind = 'human'`).

Revision ID: 0037
Revises: 0021
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0037"
down_revision: str | None = "0021"
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
TO_SHAPE_BEFORE = (
    "(to_kind = 'member' AND to_member IS NOT NULL AND to_role IS NULL AND to_human IS NULL)"
    " OR (to_kind = 'role' AND to_role IS NOT NULL AND to_member IS NULL AND to_human IS NULL)"
    " OR (to_kind = 'owner' AND to_member IS NULL AND to_role IS NULL AND to_human IS NULL)"
    " OR (to_kind = 'profile_owner' AND to_profile IS NOT NULL AND to_human IS NOT NULL"
    " AND to_member IS NULL AND to_role IS NULL)"
)
TO_SHAPE = TO_SHAPE_BEFORE + (
    " OR (to_kind = 'human' AND to_human IS NOT NULL AND to_profile IS NULL"
    " AND to_member IS NULL AND to_role IS NULL)"
)
PERSONAL_SHAPE_BEFORE = (
    "(personal AND to_kind = 'profile_owner') OR (NOT personal AND to_kind <> 'profile_owner')"
)
PERSONAL_SHAPE = (
    "(personal AND to_kind IN ('profile_owner', 'human'))"
    " OR (NOT personal AND to_kind NOT IN ('profile_owner', 'human'))"
)


def _version_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("markdown", MARKDOWN_TEXT, nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("by_kind", sa.String(length=16), nullable=False),
        sa.Column("by_id", sa.String(length=40), nullable=False),
        sa.Column("proposed_by", JSON_VALUE, nullable=True),
        sa.Column("confirmed_by", sa.String(length=40), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "preferences",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        *_version_columns(),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_preferences_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", name=op.f("pk_preferences")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "preferences_version",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        *_version_columns(),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_preferences_version_human_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", "version", name=op.f("pk_preferences_version")),
        **TABLE_OPTIONS,
    )
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("preferences_include", sa.Boolean(), server_default=sa.true(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("owner_preferences", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_request_personal_shape"), type_="check")
        batch_op.drop_constraint(batch_op.f("ck_request_to_shape"), type_="check")
        batch_op.create_check_constraint(batch_op.f("ck_request_to_shape"), TO_SHAPE)
        batch_op.create_check_constraint(batch_op.f("ck_request_personal_shape"), PERSONAL_SHAPE)


def downgrade() -> None:
    op.execute("DELETE FROM request WHERE to_kind = 'human'")  # no earlier schema holds them
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f("ck_request_personal_shape"), type_="check")
        batch_op.drop_constraint(batch_op.f("ck_request_to_shape"), type_="check")
        batch_op.create_check_constraint(batch_op.f("ck_request_to_shape"), TO_SHAPE_BEFORE)
        batch_op.create_check_constraint(
            batch_op.f("ck_request_personal_shape"), PERSONAL_SHAPE_BEFORE
        )
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("owner_preferences")
        batch_op.drop_column("preferences_include")
    op.drop_table("preferences_version")
    op.drop_table("preferences")
