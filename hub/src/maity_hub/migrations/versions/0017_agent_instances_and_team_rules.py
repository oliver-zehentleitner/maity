"""Agent instances and team rules (docs/api.md §6.17, §6.18).

Every agent credential becomes an agent instance with a short id, unique within its
membership and never reused (`credential.instance`). The membership carries its
team's rulebook; one that already holds several active credentials becomes a team of
that many (`max_instances`, at least 1). A card names the holding instance
(`claim_instance`, from the session that holds it today) and may name the instance it
is assigned to (`assigned_instance`). A member's join says which instance it adds.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-23
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
# A copy, not an import: a migration keeps meaning what it meant when it was written.
ALPHABET = "23456789abcdefghjkmnpqrstuvwxyz"


def _instance_ids() -> None:
    """One id per existing credential, oldest first; `max_instances` per membership."""
    bind = op.get_bind()
    credential = sa.table(
        "credential",
        sa.column("id", sa.String),
        sa.column("membership_id", sa.Integer),
        sa.column("instance", sa.String),
        sa.column("created_at", TIMESTAMP),
        sa.column("revoked_at", TIMESTAMP),
    )
    membership = sa.table(
        "membership", sa.column("id", sa.Integer), sa.column("max_instances", sa.Integer)
    )
    taken: dict[int, set[str]] = {}
    active: dict[int, int] = {}
    rows = bind.execute(
        sa.select(credential.c.id, credential.c.membership_id, credential.c.revoked_at).order_by(
            credential.c.created_at, credential.c.id
        )
    ).all()
    for row in rows:
        seen = taken.setdefault(row.membership_id, set())
        while True:
            candidate = "".join(secrets.choice(ALPHABET) for _ in range(4))
            if candidate not in seen:
                break
        seen.add(candidate)
        bind.execute(
            sa.update(credential).where(credential.c.id == row.id).values(instance=candidate)
        )
        if row.revoked_at is None:
            active[row.membership_id] = active.get(row.membership_id, 0) + 1
    for membership_id, count in active.items():
        if count > 1:
            bind.execute(
                sa.update(membership)
                .where(membership.c.id == membership_id)
                .values(max_instances=min(count, 16))
            )


def _claim_instances() -> None:
    """A card held through a session is held by that session's instance."""
    bind = op.get_bind()
    card = sa.table(
        "card",
        sa.column("id", sa.String),
        sa.column("claim_session_id", sa.String),
        sa.column("claim_instance", sa.String),
    )
    session = sa.table(
        "agent_session", sa.column("id", sa.String), sa.column("credential_id", sa.String)
    )
    credential = sa.table(
        "credential", sa.column("id", sa.String), sa.column("instance", sa.String)
    )
    rows = bind.execute(
        sa.select(card.c.id, credential.c.instance)
        .join(session, session.c.id == card.c.claim_session_id)
        .join(credential, credential.c.id == session.c.credential_id)
    ).all()
    for row in rows:
        bind.execute(sa.update(card).where(card.c.id == row.id).values(claim_instance=row.instance))


def upgrade() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.add_column(sa.Column("instance", sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column("replaces", sa.String(length=5), nullable=True))
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("max_instances", sa.Integer(), server_default="1", nullable=False)
        )
        batch_op.add_column(
            sa.Column("distribution", sa.String(length=16), server_default="free", nullable=False)
        )
        batch_op.add_column(sa.Column("lead_instance", sa.String(length=5), nullable=True))
        batch_op.add_column(
            sa.Column("wake", sa.String(length=16), server_default="all", nullable=False)
        )
        batch_op.add_column(
            sa.Column("review_within_team", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(sa.Column("team_updated_by", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("team_updated_at", TIMESTAMP, nullable=True))
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.add_column(sa.Column("assigned_instance", sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column("claim_instance", sa.String(length=5), nullable=True))
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("new_instance", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(sa.Column("replaces", sa.String(length=5), nullable=True))
        batch_op.add_column(sa.Column("instance", sa.String(length=5), nullable=True))
    _instance_ids()
    _claim_instances()
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.alter_column("instance", existing_type=sa.String(length=5), nullable=False)
        batch_op.create_unique_constraint("uq_credential_instance", ["membership_id", "instance"])


def downgrade() -> None:
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.drop_column("instance")
        batch_op.drop_column("replaces")
        batch_op.drop_column("new_instance")
    with op.batch_alter_table("card", schema=None) as batch_op:
        batch_op.drop_column("claim_instance")
        batch_op.drop_column("assigned_instance")
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("team_updated_at")
        batch_op.drop_column("team_updated_by")
        batch_op.drop_column("review_within_team")
        batch_op.drop_column("wake")
        batch_op.drop_column("lead_instance")
        batch_op.drop_column("distribution")
        batch_op.drop_column("max_instances")
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.drop_constraint("uq_credential_instance", type_="unique")
        batch_op.drop_column("replaces")
        batch_op.drop_column("instance")
