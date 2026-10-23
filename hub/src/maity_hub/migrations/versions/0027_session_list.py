"""The session list: what each human session shows of itself (docs/api.md §2.6.5).

`human_session` gains a public id (`hss-…`, never the cookie's value), the method that
made it, the browser and operating system its sign-in named, the address of its latest
call, the session that approved a device code, and why it ended. Every existing
session was made by password and gets a fresh public id.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-23
"""

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A copy, not an import: a migration keeps meaning what it meant when it was written.
CROCKFORD = "0123456789abcdefghjkmnpqrstvwxyz"


def upgrade() -> None:
    with op.batch_alter_table("human_session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("public_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("method", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("browser", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("os", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("ip", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("approved_by", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("ended_by", sa.String(length=16), nullable=True))
    bind = op.get_bind()
    session = sa.table(
        "human_session",
        sa.column("id_hash", sa.String),
        sa.column("public_id", sa.String),
        sa.column("method", sa.String),
        sa.column("ip", sa.String),
        sa.column("source", sa.String),
        sa.column("ended_at", sa.DateTime),
        sa.column("ended_by", sa.String),
    )
    for row in bind.execute(sa.select(session.c.id_hash, session.c.source, session.c.ended_at)):
        public_id = "hss-" + "".join(secrets.choice(CROCKFORD) for _ in range(12))
        bind.execute(
            sa.update(session)
            .where(session.c.id_hash == row.id_hash)
            .values(
                public_id=public_id,
                method="password",
                ip=row.source,
                # Before the list, only a logout or a password change ended a session.
                ended_by="logout" if row.ended_at is not None else None,
            )
        )
    with op.batch_alter_table("human_session", schema=None) as batch_op:
        batch_op.alter_column("public_id", existing_type=sa.String(length=40), nullable=False)
        batch_op.alter_column("method", existing_type=sa.String(length=16), nullable=False)
        batch_op.create_unique_constraint("uq_human_session_public_id", ["public_id"])


def downgrade() -> None:
    with op.batch_alter_table("human_session", schema=None) as batch_op:
        batch_op.drop_constraint("uq_human_session_public_id", type_="unique")
        batch_op.drop_column("ended_by")
        batch_op.drop_column("approved_by")
        batch_op.drop_column("ip")
        batch_op.drop_column("os")
        batch_op.drop_column("browser")
        batch_op.drop_column("method")
        batch_op.drop_column("public_id")
