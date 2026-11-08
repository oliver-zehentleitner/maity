"""`contact`: a human's contacts (docs/api.md §6.29).

A row per (human, contact), one way: the contact may contact the human. Nothing to copy: nobody
had contacts before.

Revision ID: 20261108200000_contacts
Revises: 20261107160000_avatar_size
Create Date: 2026-11-08
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261108200000_contacts"
down_revision: str | None = "20261107160000_avatar_size"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "contact",
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("contact_id", sa.String(length=40), nullable=False),
        sa.Column("since", TIMESTAMP, nullable=False),
        sa.CheckConstraint("human_id <> contact_id", name=op.f("ck_contact_not_self")),
        sa.ForeignKeyConstraint(["human_id"], ["human.id"], name=op.f("fk_contact_human_id_human")),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["human.id"], name=op.f("fk_contact_contact_id_human")
        ),
        sa.PrimaryKeyConstraint("human_id", "contact_id", name=op.f("pk_contact")),
        **MYSQL,
    )
    op.create_index("ix_contact_human", "contact", ["human_id", "since"])
    op.create_index("ix_contact_contact", "contact", ["contact_id", "since"])


def downgrade() -> None:
    # The indexes go with the table: MariaDB refuses to drop one alone while a foreign key
    # needs it (error 1553).
    op.drop_table("contact")
