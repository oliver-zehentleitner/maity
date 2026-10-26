"""An index on the event table for the notifications' change check (docs/api.md §18.2).

The held long-poll's stamp reads, per project, the highest `seq` among the kinds that can
make a notification item. `(project_id, kind, seq)` answers that from the index alone;
`(project_id, seq)` alone makes it fetch every event row of the project.

Revision ID: 0054
Revises: 0040
Create Date: 2026-10-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0054"
down_revision: str | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_event_project_kind_seq", "event", ["project_id", "kind", "seq"])


def downgrade() -> None:
    op.drop_index("ix_event_project_kind_seq", table_name="event")
