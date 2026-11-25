"""`forge_link.forge_user_id` and `forge_link.owner_ok_at` (docs/api.md §11.4, "An installation
on a forge organisation is re-checked").

A link to an installation on a forge organisation keeps the forge user who linked it
(`forge_user_id`), so the owner check reads that user by id and never by a stored login, and
the time of its last owner check that succeeded (`owner_ok_at`), apart from `checked_at`, the
last check whatever came of it: a refused mint or a check without an answer never makes the
link fresh. Both are NULL on a link to an installation on a user account, which this changes
nothing for.

No backfill: before this revision the hub refused every installation on a forge organisation
(`organisation_installation`), so no `forge_link` row with `account_type` `Organization`
exists. For the same reason the downgrade deletes the rows with `account_type`
`Organization` before it drops the columns (the lead's ruling Q3, seq 214797): without
`forge_user_id` and `owner_ok_at` such a link could not be checked, and the code before this
revision would serve it as a link on a user account, with no owner check at all. Only rows
this revision's code wrote are deleted; each one's human links it again after an upgrade.

Adding two nullable columns without a default rewrites no table.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261124170513_org_link_check
Revises: 20261123170000_review_signer
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20261124170513_org_link_check"
down_revision: str | None = "20261123170000_review_signer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# maity_hub.types.UtcDateTime stores naive UTC; microseconds on MySQL/MariaDB.
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.add_column("forge_link", sa.Column("forge_user_id", BIG_ID, nullable=True))
    op.add_column("forge_link", sa.Column("owner_ok_at", TIMESTAMP, nullable=True))


def downgrade() -> None:
    forge_link = sa.table("forge_link", sa.column("account_type", sa.String()))
    op.execute(sa.delete(forge_link).where(forge_link.c.account_type == "Organization"))
    with op.batch_alter_table("forge_link") as batch:
        batch.drop_column("owner_ok_at")
        batch.drop_column("forge_user_id")
