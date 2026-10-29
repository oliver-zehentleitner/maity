"""Project states before 2026-10-27 are mapped once to the new ones (docs/api.md §6.1).

`freeze` and `fixes-only` become `review`, `accepted` becomes `archived`; `build` and
`archived` stay. No `state_changed` is emitted for the mapping, and past events keep the
names they were written with. Downgrading maps back as far as the old states reach: `review`
becomes `freeze`, `plan` and `launch` become `build`.

Revision ID: 0094
Revises: 0091
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0094"
down_revision: str | None = "0091"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_project = sa.table("project", sa.column("state", sa.String(16)))


def _map(old: Sequence[str], new: str) -> None:
    op.execute(_project.update().where(_project.c.state.in_(old)).values(state=new))


def upgrade() -> None:
    _map(("freeze", "fixes-only"), "review")
    _map(("accepted",), "archived")


def downgrade() -> None:
    _map(("review",), "freeze")
    _map(("plan", "launch"), "build")
