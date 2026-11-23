"""`event.review_signer` and `event.review_pr` (docs/api.md §2.3 "Own approvals", §8.4).

On a `review_result` the hub records, when it stores the event, whether its author stood as a
signer at that moment (`review_signer`), and the pull request number its subject `#<n>` names
(`review_pr`); both stay null on every other event. Own approvals read the record instead of
reconstructing a standing the rows no longer show, and find the results that name a card only
by its pull request through `ix_event_review_pr`.

Existing events get nothing: a `review_result` stored before this has no record, and counts
as no own approval (the lead's ruling of 2026-11-23); a new result from its author counts.
Adding two nullable columns and an index rewrites nothing.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 20261123170000_review_signer
Revises: 20261123140000_own_approvals
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261123170000_review_signer"
down_revision: str | None = "20261123140000_own_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A nullable column without a default: no backend copies the table for it (SQLite's
    # ADD COLUMN included), as for `actor_agent_id` before.
    op.add_column("event", sa.Column("review_signer", sa.Boolean(), nullable=True))
    op.add_column("event", sa.Column("review_pr", sa.Integer(), nullable=True))
    # `review_pr` first, so the index serves only a lookup by pull request number: led by
    # `project_id`, PostgreSQL's planner took it for reads filtered on the project alone.
    op.create_index("ix_event_review_pr", "event", ["review_pr", "project_id"])


def downgrade() -> None:
    op.drop_index("ix_event_review_pr", table_name="event")
    with op.batch_alter_table("event") as batch:
        batch.drop_column("review_pr")
        batch.drop_column("review_signer")
