"""The forge webhook of a project (docs/api.md §17.4).

`forge_webhook` holds one row per project with a webhook: its secret sealed with
`MAITY_SECRET_KEY` (AES-256-GCM, `maity_hub.secretbox`), when it was created and
rotated, and the time and result of the last verified delivery.

`event.subject_id` widens from 40 to 255 characters: an automatic deploy's subject is
`<environment>@<sha>` (§17.1), up to 64 + 1 + 64 characters, more than an id.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-23
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0021"
down_revision: str | None = "0020"
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
        "forge_webhook",
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("secret_sealed", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("rotated_at", TIMESTAMP, nullable=True),
        sa.Column("last_delivery_at", TIMESTAMP, nullable=True),
        sa.Column("last_result", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_forge_webhook_project_id_project")
        ),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_forge_webhook")),
        **TABLE_OPTIONS,
    )
    with op.batch_alter_table("event", schema=None) as batch_op:
        batch_op.alter_column(
            "subject_id",
            existing_type=sa.String(length=40),
            type_=sa.String(length=255),
            existing_nullable=True,
        )


def downgrade() -> None:
    # A deploy subject longer than an id does not fit back: those items lose it.
    op.execute(sa.text("UPDATE event SET subject_id = NULL WHERE subject_type = 'deploy'"))
    with op.batch_alter_table("event", schema=None) as batch_op:
        batch_op.alter_column(
            "subject_id",
            existing_type=sa.String(length=255),
            type_=sa.String(length=40),
            existing_nullable=True,
        )
    op.drop_table("forge_webhook")
