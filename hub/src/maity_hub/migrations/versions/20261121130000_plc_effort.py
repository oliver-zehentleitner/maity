"""A placement names its reasoning effort (docs/api.md §15.5).

`placement.effort` is one of the efforts the runner advertises for the placement's harness, or
null for the harness's own default. Null for every existing row, which is what they ran on.

Revision ID: 20261121130000_plc_effort
Revises: 20261121120000_inst_attach
Create Date: 2026-11-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261121130000_plc_effort"
down_revision: str | None = "20261121120000_inst_attach"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.add_column(sa.Column("effort", sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("placement", schema=None) as batch_op:
        batch_op.drop_column("effort")
