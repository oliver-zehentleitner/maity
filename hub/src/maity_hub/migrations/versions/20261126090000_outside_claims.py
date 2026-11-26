"""An outsider's claim: the three policy fields, the card field and the claim request table
(docs/api.md §6.1 `looking_for_coders`, `outside_claims`, `outside_claims_max`; §6.4
`open_to_outsiders`, `claim_requests`; §6.5, "An outsider's claim").

- `project.looking_for_coders`, `project.outside_claims` and `project.outside_claims_max`:
  nullable, and null reads as the default (`per_card`, `human`, no cap), as for
  `own_approvals`. No backfill: a project that predates them reads the defaults, and the
  next write of its policy, which starts from that reading, stores them.
- `card.open_to_outsiders`: not null, server default false, so every existing card reads
  `false`.
- `claim_request`: empty. `pending` is True while a request waits and NULL once it is
  settled, under a unique key with `task_id`: one waiting request per card on PostgreSQL,
  MariaDB and SQLite alike, which have no partial index in common
  (hub/context/persistence.md 6f948103). Its timestamps are the hub's `UtcDateTime`, as on
  every request row (microseconds on MariaDB).

The downgrade drops the table and the four columns, and with them any value set and any
request filed.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261126090000_outside_claims
Revises: 20261124170513_org_link_check
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261126090000_outside_claims"
down_revision: str | None = "20261124170513_org_link_check"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# maity_hub.types.UtcDateTime stores naive UTC; microseconds on MySQL/MariaDB.
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
ID = 40
INSTANCE = 5


def upgrade() -> None:
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("looking_for_coders", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("outside_claims", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("outside_claims_max", sa.Integer(), nullable=True))
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("open_to_outsiders", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.create_table(
        "claim_request",
        sa.Column("id", sa.String(ID), nullable=False),
        sa.Column("project_id", sa.String(ID), nullable=False),
        sa.Column("task_id", sa.String(ID), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("instance", sa.String(INSTANCE), nullable=False),
        sa.Column("owner_id", sa.String(ID), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("pending", sa.Boolean(), nullable=True),
        sa.Column("reason", sa.String(32), nullable=True),
        sa.Column("requested_at", TIMESTAMP, nullable=False),
        sa.Column("lapses_at", TIMESTAMP, nullable=False),
        sa.Column("lapsed_at", TIMESTAMP, nullable=True),
        sa.Column("lapse_request_id", sa.String(ID), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", TIMESTAMP, nullable=True),
        sa.CheckConstraint("pending IS NOT FALSE", name="pending_true_or_null"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["card.id"]),
        sa.ForeignKeyConstraint(["member_id"], ["membership.id"]),
        sa.ForeignKeyConstraint(["owner_id"], ["human.id"]),
        sa.ForeignKeyConstraint(["decided_by"], ["membership.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "pending", name="uq_claim_request_one_pending"),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
        mariadb_charset="utf8mb4",
        mariadb_collate="utf8mb4_bin",
    )
    op.create_index("ix_claim_request_project_status", "claim_request", ["project_id", "status"])
    op.create_index("ix_claim_request_member_status", "claim_request", ["member_id", "status"])
    op.create_index("ix_claim_request_owner_status", "claim_request", ["owner_id", "status"])
    op.create_index("ix_claim_request_status_lapses", "claim_request", ["status", "lapses_at"])


def downgrade() -> None:
    # The table with its indexes: on MariaDB an index a foreign key uses cannot go first.
    op.drop_table("claim_request")
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.drop_column("open_to_outsiders")
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_column("outside_claims_max")
        batch_op.drop_column("outside_claims")
        batch_op.drop_column("looking_for_coders")
