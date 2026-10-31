"""A human's meat-proxy choice per conversation (docs/api.md §9.3, "Meat proxy per chat").

One row per human, project and conversation (the id of a direct conversation is its agent's, the
same in every project the agent is in, so it is no participant row): `true` or `false`; no row
follows the profile. Deleted with the account and in the person's own export.

The chain follows whatever head `main` has when it lands.

Revision ID: 20261031170000_chat_meat_proxy
Revises: 20261031150000_join_takes_over
Create Date: 2026-10-31
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20261031170000_chat_meat_proxy"
down_revision: str | None = "20261031150000_join_takes_over"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "conversation_meat_proxy",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("meat_proxy", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_conversation_meat_proxy_human_id_human")
        ),
        sa.PrimaryKeyConstraint(
            "human_id", "conversation_id", name=op.f("pk_conversation_meat_proxy")
        ),
        **MYSQL,
    )


def downgrade() -> None:
    op.drop_table("conversation_meat_proxy")
