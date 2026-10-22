"""Who answers a placement's consent request (docs/api.md §6.1, §15.6).

`project.spawn_consent_by` is `human` (only humans holding `requests:answer`) or `role`
(every holder, agents included); projects made before this ran get `human`, the
maintainer's default.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "spawn_consent_by", sa.String(length=16), server_default="human", nullable=False
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("spawn_consent_by")
