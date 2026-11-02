"""The source the project's last forge choice found, for the replicas whose probe did not run
(hub/context/replicas.md 83da2bfa): `none` when it found none, NULL before any. Only PostgreSQL
writes it, the other databases run one replica.

Revision ID: 20261102100000_project_probe_via
Revises: 20261102090000_forge_budget
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261102100000_project_probe_via"
down_revision: str | None = "20261102090000_forge_budget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.add_column(sa.Column("probe_via", sa.String(length=16)))


def downgrade() -> None:
    with op.batch_alter_table("project") as batch:
        batch.drop_column("probe_via")
