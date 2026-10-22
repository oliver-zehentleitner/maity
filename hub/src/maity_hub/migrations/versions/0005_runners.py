"""Runners: the runner, its enrollments and its credentials (docs/api.md §15.1–15.3).

A runner is a caller of its own, owned by a human, and not a membership.
`runner.active` and `runner_credential.live` are True-or-NULL markers: a
name is unique among one owner's runners until the runner is removed, and a
runner has at most one unrevoked credential.

Self-contained like 0002: the types are spelled out here.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-22
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0005"
down_revision: str | None = "0004"
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
        "runner",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("owner_id", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.Column("removed_at", TIMESTAMP, nullable=True),
        sa.Column("last_seen_at", TIMESTAMP, nullable=True),
        sa.Column("version", sa.Text(), nullable=True),
        sa.Column("capabilities", JSON_VALUE, nullable=True),
        sa.Column("capabilities_at", TIMESTAMP, nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.CheckConstraint("active IS NOT FALSE", name=op.f("ck_runner_active_true_or_null")),
        sa.ForeignKeyConstraint(["owner_id"], ["human.id"], name=op.f("fk_runner_owner_id_human")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner")),
        sa.UniqueConstraint(
            "owner_id", "name", "active", name=op.f("uq_runner_owner_id_name_active")
        ),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "runner_enrollment",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("runner_id", sa.String(length=40), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=True),
        sa.Column("attach", JSON_VALUE, nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("created_by", sa.String(length=40), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("used_at", TIMESTAMP, nullable=True),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("burned_at", TIMESTAMP, nullable=True),
        sa.Column("revoked_at", TIMESTAMP, nullable=True),
        sa.CheckConstraint(
            "runner_id IS NOT NULL OR name IS NOT NULL",
            name=op.f("ck_runner_enrollment_names_a_runner"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["human.id"], name=op.f("fk_runner_enrollment_created_by_human")
        ),
        sa.ForeignKeyConstraint(
            ["runner_id"], ["runner.id"], name=op.f("fk_runner_enrollment_runner_id_runner")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner_enrollment")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_runner_enrollment_token_hash")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        op.f("ix_runner_enrollment_created_by"), "runner_enrollment", ["created_by"], unique=False
    )
    op.create_table(
        "runner_credential",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("runner_id", sa.String(length=40), nullable=False),
        sa.Column("verifier", sa.String(length=64), nullable=False),
        sa.Column("enrollment_id", sa.String(length=40), nullable=False),
        sa.Column("client", sa.Text(), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("last_used_at", TIMESTAMP, nullable=True),
        sa.Column("last_used_via", sa.String(length=16), nullable=True),
        sa.Column("revoked_at", TIMESTAMP, nullable=True),
        sa.Column("revoked_by", sa.String(length=40), nullable=True),
        sa.Column("revoked_reason", MARKDOWN_TEXT, nullable=True),
        sa.Column("live", sa.Boolean(), nullable=True),
        sa.CheckConstraint(
            "live IS NOT FALSE", name=op.f("ck_runner_credential_live_true_or_null")
        ),
        sa.ForeignKeyConstraint(
            ["enrollment_id"],
            ["runner_enrollment.id"],
            name=op.f("fk_runner_credential_enrollment_id_runner_enrollment"),
        ),
        sa.ForeignKeyConstraint(
            ["runner_id"], ["runner.id"], name=op.f("fk_runner_credential_runner_id_runner")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner_credential")),
        sa.UniqueConstraint("runner_id", "live", name=op.f("uq_runner_credential_runner_id_live")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("runner_credential")
    op.drop_table("runner_enrollment")
    op.drop_table("runner")
