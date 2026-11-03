"""Profiles are public by default, and a page can be kept out of search (docs/api.md §16.9).

`human.public_profile` defaults to true, and every existing account is switched on: the
maintainer's decision of 2026-11-02 (tsk-my5gvj4warte), with two accounts at the time. An
instance that upgrades later switches its existing accounts the same way, which is why the
changelog asks its operator to tell their users before the upgrade.
`public_page.indexed` is false for a page search engines must not list (a person whose
profile is off keeps a page with handle and name, `noindex` and out of the sitemap).

The downgrade restores the old default only: the accounts the upgrade switched on stay on.

Revision ID: 20261102110000_profiles_public
Revises: 20261102120000_maintenance
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102110000_profiles_public"
down_revision: str | None = "20261102120000_maintenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.alter_column(
            "public_profile",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.true(),
        )
    op.execute(sa.text("UPDATE human SET public_profile = :on").bindparams(on=True))
    with op.batch_alter_table("public_page", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("indexed", sa.Boolean(), server_default=sa.true(), nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("public_page", schema=None) as batch_op:
        batch_op.drop_column("indexed")
    with op.batch_alter_table("human", schema=None) as batch_op:
        batch_op.alter_column(
            "public_profile",
            existing_type=sa.Boolean(),
            existing_nullable=False,
            server_default=sa.false(),
        )
