"""A note's `version`: 1 when posted, one more with every edit and with its redaction, named
as `base_version` by an edit or a redaction (docs/api.md §6.16). A note posted before has
the version 1, edited or not: the hub kept no count of its edits, and the version is only
compared, never counted back. Events written before carry the note without `version` until
an edit or a redaction rewrites them in place.

Revision ID: 20261102230000_card_note_version
Revises: 20261102110000_profiles_public
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102230000_card_note_version"
down_revision: str | None = "20261102110000_profiles_public"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("card_note") as batch:
        batch.add_column(sa.Column("version", sa.Integer(), server_default="1", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("card_note") as batch:
        batch.drop_column("version")
