"""Mail as the second factor (docs/api.md §2.8.8).

`notification_settings.address_ever_verified` is set at the first verification of an address
and never cleared; an account that existed before it counts as having had one when its address
is `verified` or `disabled` (a disabled address was verified once, §18.7), so no such account
falls under "never had one". `human_session.mail_token_mac` and `mail_code_mac` are the HMACs
of the token and the code mailed to a second-factor session, `mail_sent` the mails it was sent
and `mail_sent_at` when the newest went (a step-up's code lives 15 minutes in a session that lives
for days).

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261031191500_mail_factor
Revises: 20261031125530_long_polls
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261031191500_mail_factor"
down_revision = "20261031190604_jour_fixe_series"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")


def upgrade() -> None:
    with op.batch_alter_table("notification_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "address_ever_verified", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
    notification_settings = sa.table(
        "notification_settings",
        sa.column("address_status", sa.String()),
        sa.column("address_ever_verified", sa.Boolean()),
    )
    op.execute(
        notification_settings.update()
        .where(notification_settings.c.address_status.in_(("verified", "disabled")))
        .values(address_ever_verified=True)
    )
    with op.batch_alter_table("human_session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("mail_token_mac", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("mail_code_mac", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("mail_sent", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("mail_sent_at", TIMESTAMP, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("human_session", schema=None) as batch_op:
        batch_op.drop_column("mail_sent_at")
        batch_op.drop_column("mail_sent")
        batch_op.drop_column("mail_code_mac")
        batch_op.drop_column("mail_token_mac")
    with op.batch_alter_table("notification_settings", schema=None) as batch_op:
        batch_op.drop_column("address_ever_verified")
