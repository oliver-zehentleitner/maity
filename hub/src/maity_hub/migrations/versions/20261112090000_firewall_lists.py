"""`chat_access` and `chat_access_agent`: a human's allow and deny entries for their agents
(docs/api.md §9.6, "The lists").

Nothing to copy: nobody had entries before.

Revision ID: 20261112090000_firewall_lists
Revises: 20261111150000_present_until
Create Date: 2026-11-12
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261112090000_firewall_lists"
down_revision: str | None = "20261111150000_present_until"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}
ONE_SUBJECT = (
    "(CASE WHEN owner_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN subject_human_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN subject_agent_id IS NULL THEN 0 ELSE 1 END)"
    " + (CASE WHEN project_id IS NULL THEN 0 ELSE 1 END) = 1"
)


def upgrade() -> None:
    op.create_table(
        "chat_access",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("agents_all", sa.Boolean(), nullable=False),
        sa.Column("owner_id", sa.String(length=40), nullable=True),
        sa.Column("subject_human_id", sa.String(length=40), nullable=True),
        sa.Column("subject_agent_id", sa.String(length=40), nullable=True),
        sa.Column("project_id", sa.String(length=40), nullable=True),
        sa.Column("their_agents", sa.String(length=8), nullable=True),
        sa.Column("their_human", sa.Boolean(), nullable=True),
        sa.Column("duration", sa.String(length=8), nullable=True),
        sa.Column("until", TIMESTAMP, nullable=True),
        sa.Column("allowed", sa.String(length=1000), nullable=True),
        sa.Column("denied", sa.String(length=1000), nullable=True),
        sa.Column("by", sa.String(length=40), nullable=False),
        sa.Column("since", TIMESTAMP, nullable=False),
        sa.CheckConstraint("kind IN ('allow', 'deny')", name=op.f("ck_chat_access_kind")),
        sa.CheckConstraint(ONE_SUBJECT, name=op.f("ck_chat_access_one_subject")),
        sa.CheckConstraint(
            "kind = 'deny' OR (subject_human_id IS NULL AND subject_agent_id IS NULL)",
            name=op.f("ck_chat_access_allow_subject"),
        ),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_chat_access_human_id_human")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["human.id"], name=op.f("fk_chat_access_owner_id_human")
        ),
        sa.ForeignKeyConstraint(
            ["subject_human_id"],
            ["human.id"],
            name=op.f("fk_chat_access_subject_human_id_human"),
        ),
        sa.ForeignKeyConstraint(
            ["subject_agent_id"],
            ["agent_profile.id"],
            name=op.f("fk_chat_access_subject_agent_id_agent_profile"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_chat_access_project_id_project")
        ),
        sa.ForeignKeyConstraint(["by"], ["human.id"], name=op.f("fk_chat_access_by_human")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_access")),
        **MYSQL,
    )
    op.create_index("ix_chat_access_human", "chat_access", ["human_id", "kind", "since"])
    op.create_index("ix_chat_access_owner", "chat_access", ["owner_id"])
    op.create_index("ix_chat_access_subject_human", "chat_access", ["subject_human_id"])
    op.create_index("ix_chat_access_subject_agent", "chat_access", ["subject_agent_id"])
    op.create_index("ix_chat_access_project", "chat_access", ["project_id"])
    op.create_table(
        "chat_access_agent",
        sa.Column("entry_id", sa.String(length=40), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("agent_id", sa.String(length=40), nullable=False),
        sa.CheckConstraint("side IN ('own', 'theirs')", name=op.f("ck_chat_access_agent_side")),
        sa.ForeignKeyConstraint(
            ["entry_id"],
            ["chat_access.id"],
            name=op.f("fk_chat_access_agent_entry_id_chat_access"),
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agent_profile.id"],
            name=op.f("fk_chat_access_agent_agent_id_agent_profile"),
        ),
        sa.PrimaryKeyConstraint("entry_id", "side", "agent_id", name=op.f("pk_chat_access_agent")),
        **MYSQL,
    )
    op.create_index("ix_chat_access_agent_agent", "chat_access_agent", ["agent_id"])


def downgrade() -> None:
    # The indexes go with the tables: MariaDB refuses to drop one alone while a foreign key
    # needs it (error 1553). The agents first: they point at the entries.
    op.drop_table("chat_access_agent")
    op.drop_table("chat_access")
