"""A person's interface language, and the two languages a registration chose (docs/api.md §6.2,
§2.7.1).

Revision ID: 20261102000000_interface_lang
Revises: 20261101140000_request_action
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102000000_interface_lang"
down_revision = "20261101140000_request_action"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("human", sa.Column("interface_language", sa.String(length=35), nullable=True))
    with op.batch_alter_table("pending_registration") as batch:
        batch.add_column(sa.Column("interface_language", sa.String(length=35), nullable=True))
        batch.add_column(sa.Column("chosen_language", sa.String(length=35), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("pending_registration") as batch:
        batch.drop_column("chosen_language")
        batch.drop_column("interface_language")
    op.drop_column("human", "interface_language")
