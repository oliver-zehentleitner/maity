"""A human's verdict on a chat message (docs/api.md §9.7, "Agree and disagree").

One row per message and human: `agree` or `disagree`, an optional sentence with `disagree`, and
`set_seq`, the `chat_verdict` event that set it. A new verdict replaces the row, taking it back
deletes it. The row outlives a redaction of its event, which is why it is not derived from the
events (hub/context/events.md). A new table: nothing to carry over.

The chain follows whatever head `main` has when it lands.

Revision ID: 20261114200000_chat_verdict
Revises: 20261114130000_repo_url_2048
Create Date: 2026-11-14
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

from maity_hub.types import UtcDateTime

revision: str = "20261114200000_chat_verdict"
down_revision: str | None = "20261114130000_repo_url_2048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "chat_verdict",
        sa.Column("message_seq", BIG_ID, nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("value", sa.String(length=8), nullable=False),
        sa.Column("sentence", sa.String(length=500), nullable=True),
        sa.Column("set_seq", BIG_ID, nullable=False),
        sa.Column("at", UtcDateTime(), nullable=False),
        sa.CheckConstraint("value IN ('agree', 'disagree')", name=op.f("ck_chat_verdict_value")),
        sa.ForeignKeyConstraint(
            ["message_seq"], ["event.seq"], name=op.f("fk_chat_verdict_message_seq_event")
        ),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_chat_verdict_human_id_human")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_chat_verdict_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["set_seq"], ["event.seq"], name=op.f("fk_chat_verdict_set_seq_event")
        ),
        sa.PrimaryKeyConstraint("message_seq", "human_id", name=op.f("pk_chat_verdict")),
        **MYSQL,
    )


def downgrade() -> None:
    # The table alone: no index of another table goes, so no foreign key loses its index.
    op.drop_table("chat_verdict")
