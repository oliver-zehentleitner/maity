"""\"I am a meat proxy\" has two parts the person picks (docs/api.md §5.2).

`human.meat_proxy_lead` and `human.meat_proxy_hands` replace `human.meat_proxy`: the switch is
derived, on while a part is. A human who had the switch on gets both parts on, which is what
switching it on means; the old column goes.

Revision ID: 0103
Revises: 0100
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0103"
down_revision: str | None = "0100"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

human = sa.table(
    "human",
    sa.column("meat_proxy", sa.Boolean()),
    sa.column("meat_proxy_lead", sa.Boolean()),
    sa.column("meat_proxy_hands", sa.Boolean()),
)


def upgrade() -> None:
    with op.batch_alter_table("human") as batch_op:
        batch_op.add_column(
            sa.Column("meat_proxy_lead", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("meat_proxy_hands", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
    op.execute(
        human.update().values(
            meat_proxy_lead=human.c.meat_proxy, meat_proxy_hands=human.c.meat_proxy
        )
    )
    with op.batch_alter_table("human") as batch_op:
        batch_op.drop_column("meat_proxy")


def downgrade() -> None:
    with op.batch_alter_table("human") as batch_op:
        batch_op.add_column(
            sa.Column("meat_proxy", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
    op.execute(
        human.update().values(meat_proxy=sa.or_(human.c.meat_proxy_lead, human.c.meat_proxy_hands))
    )
    with op.batch_alter_table("human") as batch_op:
        batch_op.drop_column("meat_proxy_hands")
        batch_op.drop_column("meat_proxy_lead")
