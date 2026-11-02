"""`project.setup` is never null, and a jour fixe round has no `mode` (docs/api.md §6.1, §20.5).

Nobody checked production for a project without `setup`, so a `NULL` row gets what the code
did with one: no option chosen, no card created. Every round runs in its group chat, nothing
branched on `mode`, so the column goes without keeping any row apart; the maintainer allowed
that for this test data. The downgrade restores the column with `chat` for every round and
cannot tell which `setup` was filled here.

Revision ID: 20261101060000_setup_round_mode
Revises: 20261101050000_org_alias
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261101060000_setup_round_mode"
down_revision = "20261101050000_org_alias"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
NOTHING_CHOSEN: dict[str, object] = {
    "keep_the_why_init": False,
    "keep_the_why_badge": False,
    "keep_the_why_ci": False,
    "keep_the_why_dashboard": False,
    "dashboard_path": None,
    "maity_badge": False,
    "cards": [],
}


def upgrade() -> None:
    project = sa.table("project", sa.column("id", sa.String()), sa.column("setup", JSON_VALUE))
    conn = op.get_bind()
    rows = conn.execute(sa.select(project.c.id, project.c.setup)).all()
    for row in rows:
        if row.setup is None:  # a SQL `NULL` and a stored JSON `null` read the same
            conn.execute(
                project.update().where(project.c.id == row.id).values(setup=NOTHING_CHOSEN)
            )
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.alter_column("setup", existing_type=JSON_VALUE, nullable=False)
    with op.batch_alter_table("jour_fixe_round", schema=None) as batch_op:
        batch_op.drop_column("mode")


def downgrade() -> None:
    with op.batch_alter_table("jour_fixe_round", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("mode", sa.String(length=16), nullable=False, server_default="chat")
        )
    with op.batch_alter_table("jour_fixe_round", schema=None) as batch_op:
        batch_op.alter_column("mode", existing_type=sa.String(length=16), server_default=None)
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.alter_column("setup", existing_type=JSON_VALUE, nullable=True)
