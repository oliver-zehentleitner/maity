"""Card links, the edit history and notes (docs/api.md §6.13, §6.15, §6.16).

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "card_link",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("card_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("forge", sa.String(length=32), nullable=True),
        sa.Column("repository", sa.String(length=255), nullable=True),
        sa.Column("number", BIG_ID, nullable=True),
        sa.Column("observed", JSON_VALUE, nullable=True),
        sa.Column("added_by", sa.Integer(), nullable=False),
        sa.Column("added_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(["card_id"], ["card.id"], name=op.f("fk_card_link_card_id_card")),
        sa.ForeignKeyConstraint(
            ["added_by"], ["membership.id"], name=op.f("fk_card_link_added_by_membership")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_link")),
        **TABLE_OPTIONS,
    )
    op.create_index(op.f("ix_card_link_card_id"), "card_link", ["card_id"], unique=False)
    op.create_table(
        "card_history",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("card_id", sa.String(length=40), nullable=False),
        sa.Column("at", TIMESTAMP, nullable=False),
        sa.Column("actor_membership", sa.Integer(), nullable=True),
        sa.Column("actor_session_id", sa.String(length=40), nullable=True),
        sa.Column("field", sa.String(length=32), nullable=False),
        sa.Column("link_id", sa.String(length=40), nullable=True),
        sa.Column("link_change", sa.String(length=8), nullable=True),
        sa.Column("before", JSON_VALUE, nullable=True),
        sa.Column("after", JSON_VALUE, nullable=True),
        sa.Column("diff", MARKDOWN_TEXT, nullable=True),
        sa.Column("event_seq", BIG_ID, nullable=True),
        sa.Column("redacted", sa.Boolean(), nullable=False),
        sa.Column("redaction", JSON_VALUE, nullable=True),
        sa.ForeignKeyConstraint(
            ["card_id"], ["card.id"], name=op.f("fk_card_history_card_id_card")
        ),
        sa.ForeignKeyConstraint(
            ["actor_membership"],
            ["membership.id"],
            name=op.f("fk_card_history_actor_membership_membership"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_history")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_card_history_card_at", "card_history", ["card_id", "at", "id"], unique=False
    )
    op.create_index("ix_card_history_link", "card_history", ["link_id"], unique=False)
    op.create_table(
        "card_note",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("card_id", sa.String(length=40), nullable=False),
        sa.Column("author", sa.Integer(), nullable=False),
        sa.Column("author_kind", sa.String(length=16), nullable=False),
        sa.Column("body", MARKDOWN_TEXT, nullable=True),
        sa.Column("mentions", JSON_VALUE, nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("resolution", JSON_VALUE, nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("event_seq", BIG_ID, nullable=True),
        sa.Column("redacted", sa.Boolean(), nullable=False),
        sa.Column("redaction", JSON_VALUE, nullable=True),
        sa.ForeignKeyConstraint(["card_id"], ["card.id"], name=op.f("fk_card_note_card_id_card")),
        sa.ForeignKeyConstraint(
            ["author"], ["membership.id"], name=op.f("fk_card_note_author_membership")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_card_note")),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_card_note_card_created", "card_note", ["card_id", "created_at", "id"], unique=False
    )
    op.create_index(
        "ix_card_note_author_created", "card_note", ["author", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_card_note_author_created", table_name="card_note")
    op.drop_index("ix_card_note_card_created", table_name="card_note")
    op.drop_table("card_note")
    op.drop_index("ix_card_history_link", table_name="card_history")
    op.drop_index("ix_card_history_card_at", table_name="card_history")
    op.drop_table("card_history")
    op.drop_index(op.f("ix_card_link_card_id"), table_name="card_link")
    op.drop_table("card_link")
