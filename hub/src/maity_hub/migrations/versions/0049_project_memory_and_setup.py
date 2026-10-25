"""The project's memory provider in place of the Keep the Why flag, and the setup chosen
at creation (docs/api.md §6.1, §6.21).

`memory_provider` replaces `keep_the_why`: a project that had it on reads
`keep-the-why`, every other `none`. `setup` is null for every existing project: nothing
was chosen, so nothing is created when its repository is set.

Revision ID: 0049
Revises: 0042 (rechain at merge; the number reserved by the coordinator)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0049"
down_revision: str | None = "0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(
            sa.Column("memory_provider", sa.String(32), nullable=False, server_default="none")
        )
        batch.add_column(sa.Column("setup", JSON_VALUE, nullable=True))
    project = sa.table(
        "project", sa.column("keep_the_why", sa.Boolean), sa.column("memory_provider", sa.String)
    )
    op.execute(
        project.update()
        .where(project.c.keep_the_why.is_(True))
        .values(memory_provider="keep-the-why")
    )
    with op.batch_alter_table("project") as batch:
        batch.drop_column("keep_the_why")


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(
            sa.Column("keep_the_why", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    project = sa.table(
        "project", sa.column("keep_the_why", sa.Boolean), sa.column("memory_provider", sa.String)
    )
    op.execute(
        project.update()
        .where(project.c.memory_provider == "keep-the-why")
        .values(keep_the_why=True)
    )
    with op.batch_alter_table("project") as batch:
        batch.drop_column("setup")
        batch.drop_column("memory_provider")
