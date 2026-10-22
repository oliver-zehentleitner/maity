"""Runner attachments and sessions, and runners as event actors (docs/api.md §15.4,
§15.8, §15.10).

`runner_attachment.active` and `runner_session.live` are True-or-NULL markers:
one active attachment per (project, runner), one live session per runner
credential. `event.actor_runner_id` names the runner that caused an event;
it has no foreign key, like the event's session and credential columns.

Self-contained like 0002: the types are spelled out here.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-22
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0006"
down_revision: str | None = "0005"
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
    op.create_table(
        "runner_session",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("credential_id", sa.String(length=40), nullable=False),
        sa.Column("client", sa.Text(), nullable=True),
        sa.Column("started_at", TIMESTAMP, nullable=False),
        sa.Column("last_seen_at", TIMESTAMP, nullable=False),
        sa.Column("ended_at", TIMESTAMP, nullable=True),
        sa.Column("live", sa.Boolean(), nullable=True),
        sa.CheckConstraint("live IS NOT FALSE", name=op.f("ck_runner_session_live_true_or_null")),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["runner_credential.id"],
            name=op.f("fk_runner_session_credential_id_runner_credential"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner_session")),
        sa.UniqueConstraint(
            "credential_id", "live", name=op.f("uq_runner_session_credential_id_live")
        ),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "runner_attachment",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("runner_id", sa.String(length=40), nullable=False),
        sa.Column("attached_by", sa.String(length=40), nullable=False),
        sa.Column("attached_at", TIMESTAMP, nullable=False),
        sa.Column("detached_at", TIMESTAMP, nullable=True),
        sa.Column("detached_by", sa.String(length=40), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.CheckConstraint(
            "active IS NOT FALSE", name=op.f("ck_runner_attachment_active_true_or_null")
        ),
        sa.ForeignKeyConstraint(
            ["attached_by"], ["human.id"], name=op.f("fk_runner_attachment_attached_by_human")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_runner_attachment_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["runner_id"], ["runner.id"], name=op.f("fk_runner_attachment_runner_id_runner")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runner_attachment")),
        sa.UniqueConstraint(
            "project_id",
            "runner_id",
            "active",
            name=op.f("uq_runner_attachment_project_id_runner_id_active"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        op.f("ix_runner_attachment_runner_id"), "runner_attachment", ["runner_id"], unique=False
    )
    # A plain ADD COLUMN on every engine: a batch rebuild of the event table on SQLite
    # would have to carry its AUTOINCREMENT across.
    op.add_column("event", sa.Column("actor_runner_id", sa.String(length=40), nullable=True))


def downgrade() -> None:
    op.drop_column("event", "actor_runner_id")
    op.drop_table("runner_attachment")
    op.drop_table("runner_session")
