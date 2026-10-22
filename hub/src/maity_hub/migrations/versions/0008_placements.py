"""Placements, their consent requests, and the project's spawn policy (docs/api.md §6.1,
§15.5–15.7).

`placement.active` is a True-or-NULL marker: at most one active placement per
membership, per (project, new handle) and per (project, runner, clone).
`request.placement_id` links a consent request to the placement it settles.
`project.spawn_requests` and `project.max_placements` get their defaults for the
projects that exist when this runs.

Self-contained like 0002: the types are spelled out here.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-22
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0008"
down_revision: str | None = "0007"
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
        "placement",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=True),
        sa.Column("new_handle", sa.String(length=64), nullable=True),
        sa.Column("new_profile", JSON_VALUE, nullable=True),
        sa.Column("runner_id", sa.String(length=40), nullable=False),
        sa.Column("target", sa.String(length=200), nullable=True),
        sa.Column("harness", sa.String(length=32), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("clone", sa.String(length=64), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=True),
        sa.Column("desired", sa.String(length=16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("rejoin", sa.Boolean(), nullable=False),
        sa.Column("stop_grace_seconds", sa.Integer(), nullable=False),
        sa.Column("approval_status", sa.String(length=16), nullable=False),
        sa.Column("pending_change", JSON_VALUE, nullable=True),
        sa.Column("reason", MARKDOWN_TEXT, nullable=True),
        sa.Column("credential_id", sa.String(length=40), nullable=True),
        sa.Column("reported", JSON_VALUE, nullable=True),
        sa.Column("reported_seq", sa.Integer(), nullable=False),
        sa.Column("session_hint", sa.String(length=200), nullable=True),
        sa.Column("closing", sa.String(length=32), nullable=True),
        sa.Column("closed_at", TIMESTAMP, nullable=True),
        sa.Column("closed_reason", sa.String(length=32), nullable=True),
        sa.Column("created_by", sa.String(length=40), nullable=False),
        sa.Column("proposed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("updated_by", sa.String(length=40), nullable=True),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.CheckConstraint("active IS NOT FALSE", name=op.f("ck_placement_active_true_or_null")),
        sa.CheckConstraint(
            "membership_id IS NOT NULL OR new_handle IS NOT NULL",
            name=op.f("ck_placement_names_an_agent"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["human.id"], name=op.f("fk_placement_created_by_human")
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["credential.id"], name=op.f("fk_placement_credential_id_credential")
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_placement_membership_id_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_placement_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by"], ["membership.id"], name=op.f("fk_placement_proposed_by_membership")
        ),
        sa.ForeignKeyConstraint(
            ["runner_id"], ["runner.id"], name=op.f("fk_placement_runner_id_runner")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_placement")),
        sa.UniqueConstraint(
            "membership_id", "active", name=op.f("uq_placement_membership_id_active")
        ),
        sa.UniqueConstraint(
            "project_id",
            "new_handle",
            "active",
            name=op.f("uq_placement_project_id_new_handle_active"),
        ),
        sa.UniqueConstraint(
            "project_id",
            "runner_id",
            "clone",
            "active",
            name=op.f("uq_placement_project_id_runner_id_clone_active"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(op.f("ix_placement_runner_id"), "placement", ["runner_id"], unique=False)
    op.create_index(
        "ix_event_subject",
        "event",
        ["project_id", "subject_type", "subject_id", "seq"],
        unique=False,
    )
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.add_column(sa.Column("placement_id", sa.String(length=40), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f("fk_request_placement_id_placement"), "placement", ["placement_id"], ["id"]
        )
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "spawn_requests", sa.String(length=16), server_default="consent", nullable=False
            )
        )
        batch_op.add_column(
            sa.Column("max_placements", sa.Integer(), server_default="8", nullable=False)
        )


def downgrade() -> None:
    op.drop_index("ix_event_subject", table_name="event")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("max_placements")
        batch_op.drop_column("spawn_requests")
    with op.batch_alter_table("request", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_request_placement_id_placement"), type_="foreignkey"
        )
        batch_op.drop_column("placement_id")
    op.drop_table("placement")
