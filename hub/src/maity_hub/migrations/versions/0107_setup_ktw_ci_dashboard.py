"""The Keep the Why setup options for CI and the dashboard (docs/api.md §6.21).

A project's `setup` gains `keep_the_why_ci`, `keep_the_why_dashboard` and `dashboard_path`.
A project created before they were offered had nothing chosen for them, so its `setup` is
written with `false`, `false` and `null` here; the code reads one shape and keeps no
fallback for the old one. A project without `setup` keeps `null`.

Revision ID: 0107
Revises: 0101
Create Date: 2026-10-30
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0107"
down_revision: str | None = "0101"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
ADDED = {"keep_the_why_ci": False, "keep_the_why_dashboard": False, "dashboard_path": None}


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _project() -> sa.TableClause:
    return sa.table("project", sa.column("id", sa.String), sa.column("setup", JSON_VALUE))


def upgrade() -> None:
    conn = op.get_bind()
    project = _project()
    for row in conn.execute(sa.select(project.c.id, project.c.setup)).all():
        setup = _json(row.setup)
        if isinstance(setup, dict):
            written = {**setup, **{k: v for k, v in ADDED.items() if k not in setup}}
            if written != setup:
                conn.execute(sa.update(project).where(project.c.id == row.id).values(setup=written))


def downgrade() -> None:
    conn = op.get_bind()
    project = _project()
    for row in conn.execute(sa.select(project.c.id, project.c.setup)).all():
        setup = _json(row.setup)
        if isinstance(setup, dict) and any(k in setup for k in ADDED):
            kept = {k: v for k, v in setup.items() if k not in ADDED}
            conn.execute(sa.update(project).where(project.c.id == row.id).values(setup=kept))
