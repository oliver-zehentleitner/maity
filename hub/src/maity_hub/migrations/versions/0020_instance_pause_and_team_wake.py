"""An agent instance's own pause, and the team wake an event recorded (docs/api.md
§5.3, §8.2).

An instance is a credential, so its pause lives on the credential row, in the same
three columns as the membership's. An event records which instances it wakes for each
team whose `wake` rule narrowed it (`wakes`, null when none did), and `round_robin`
remembers its last choice on the membership. A card keeps every instance that reported
it (`reported_instances`), for `review_within_team`. The project row says whether any
of its teams narrows at all (`team_wake`), so that a project without such a team costs
no extra query per event.

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


def upgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.add_column(sa.Column("paused_reason", MARKDOWN_TEXT, nullable=True))
        batch_op.add_column(sa.Column("paused_since", TIMESTAMP, nullable=True))
        batch_op.add_column(sa.Column("paused_by", sa.String(length=40), nullable=True))
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(sa.Column("round_robin_last", sa.String(length=5), nullable=True))
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reported_instances", JSON_VALUE, nullable=True))
    with op.batch_alter_table("event", schema=None) as batch_op:
        batch_op.add_column(sa.Column("wakes", JSON_VALUE, nullable=True))
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("team_wake", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
    # A team rule set since 0014 already narrows its project's wake.
    project = sa.table("project", sa.column("id", sa.String), sa.column("team_wake", sa.Boolean))
    membership = sa.table(
        "membership",
        sa.column("project_id", sa.String),
        sa.column("wake", sa.String),
        sa.column("removed_at", TIMESTAMP),
    )
    narrowed = sa.select(membership.c.project_id).where(
        membership.c.wake != "all", membership.c.removed_at.is_(None)
    )
    op.get_bind().execute(
        sa.update(project).where(project.c.id.in_(narrowed)).values(team_wake=sa.true())
    )


def downgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("team_wake")
    with op.batch_alter_table("event", schema=None) as batch_op:
        batch_op.drop_column("wakes")
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.drop_column("reported_instances")
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("round_robin_last")
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.drop_column("paused_by")
        batch_op.drop_column("paused_since")
        batch_op.drop_column("paused_reason")
