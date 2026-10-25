"""The jour fixe (docs/api.md §20): the schedule and moderator order on the project, the
rounds, their answers and answer tags, and the presence minutes of agents.

Revision ID: 0038
Revises: 0025
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0038"
down_revision: str | None = "0025"
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
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("jour_fixe", JSON_VALUE, nullable=True))
        batch_op.add_column(sa.Column("jour_fixe_moderators", JSON_VALUE, nullable=True))
        batch_op.add_column(sa.Column("jour_fixe_anchor", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("jour_fixe_last_slot", TIMESTAMP, nullable=True))
    op.create_table(
        "jour_fixe_round",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("reason", MARKDOWN_TEXT, nullable=True),
        sa.Column("skip_reason", sa.String(length=32), nullable=True),
        sa.Column("missed_slots", sa.Integer(), nullable=True),
        sa.Column("scheduled_for", TIMESTAMP, nullable=False),
        sa.Column("opened_at", TIMESTAMP, nullable=True),
        sa.Column("answers_close_at", TIMESTAMP, nullable=True),
        sa.Column("steps", JSON_VALUE, nullable=False),
        sa.Column("exchange_closed_at", TIMESTAMP, nullable=True),
        sa.Column("report_due_at", TIMESTAMP, nullable=True),
        sa.Column("reported_at", TIMESTAMP, nullable=True),
        sa.Column("config", JSON_VALUE, nullable=True),
        sa.Column("moderator", JSON_VALUE, nullable=True),
        sa.Column("invited", JSON_VALUE, nullable=False),
        sa.Column("absent", JSON_VALUE, nullable=False),
        sa.Column("answers_received", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=True),
        sa.Column("statement", JSON_VALUE, nullable=True),
        sa.Column("posts", JSON_VALUE, nullable=False),
        sa.Column("report", JSON_VALUE, nullable=True),
        sa.Column("tag_key", sa.String(length=64), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_jour_fixe_round_project_id_project")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jour_fixe_round")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_jour_fixe_round_project", "jour_fixe_round", ["project_id", "scheduled_for"]
    )
    op.create_table(
        "jour_fixe_answer",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("round_id", sa.String(length=40), nullable=False),
        sa.Column("anonymous", sa.Boolean(), nullable=False),
        sa.Column("author", sa.Integer(), nullable=True),
        sa.Column("went_well", MARKDOWN_TEXT, nullable=True),
        sa.Column("went_badly", MARKDOWN_TEXT, nullable=True),
        sa.Column("would_help", MARKDOWN_TEXT, nullable=True),
        sa.Column("tag", sa.String(length=64), nullable=True),
        sa.Column("withdrawn", sa.Boolean(), nullable=False),
        sa.Column("redaction", JSON_VALUE, nullable=True),
        sa.Column("shuffle", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["jour_fixe_round.id"],
            name=op.f("fk_jour_fixe_answer_round_id_jour_fixe_round"),
        ),
        sa.ForeignKeyConstraint(
            ["author"], ["membership.id"], name=op.f("fk_jour_fixe_answer_author_membership")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jour_fixe_answer")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        op.f("ix_jour_fixe_answer_round_id"), "jour_fixe_answer", ["round_id"], unique=False
    )
    op.create_table(
        "jour_fixe_tag",
        sa.Column("round_id", sa.String(length=40), nullable=False),
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["round_id"],
            ["jour_fixe_round.id"],
            name=op.f("fk_jour_fixe_tag_round_id_jour_fixe_round"),
        ),
        sa.PrimaryKeyConstraint("round_id", "tag", name=op.f("pk_jour_fixe_tag")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "presence_minute",
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("minute", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_presence_minute_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint("membership_id", "minute", name=op.f("pk_presence_minute")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("presence_minute")
    op.drop_table("jour_fixe_tag")
    # The tables alone: each index goes with its table. Dropping an index first fails on
    # MariaDB where a foreign key still uses it (round_id, project_id lead them).
    op.drop_table("jour_fixe_answer")
    op.drop_table("jour_fixe_round")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("jour_fixe_last_slot")
        batch_op.drop_column("jour_fixe_anchor")
        batch_op.drop_column("jour_fixe_moderators")
        batch_op.drop_column("jour_fixe")
