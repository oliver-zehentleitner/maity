"""Cards written in the one shape the code reads (docs/api.md §6.8, §6.18).

Two shapes of older cards were read through a branch of their own: a card that has been
reported carries `reported_instances`, the instances that reported it, but a card reported
before 0022 has only `report`; and a contract card carries `path` and `section` in its
`contract`, but one made before §6.8 named a place has neither. This fills both, so that the
code reads each card the same way and the branches are gone: the instance of the report becomes
the one entry of the list, and a contract without a place gets the default place (`docs/api.md`,
no section), as a new one gets it from the input.

The chain is not fixed by this file: it follows whatever head `main` has when it lands.

Revision ID: 0101
Revises: 0099
Create Date: 2026-10-30
"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0101"
down_revision: str | None = "0099"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
DEFAULT_PATH = "docs/api.md"


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def upgrade() -> None:
    conn = op.get_bind()
    card = sa.table(
        "card",
        sa.column("id", sa.String),
        sa.column("kind", sa.String),
        sa.column("report", JSON_VALUE),
        sa.column("reported_instances", JSON_VALUE),
        sa.column("contract", JSON_VALUE),
    )
    rows = conn.execute(
        sa.select(card.c.id, card.c.kind, card.c.report, card.c.reported_instances, card.c.contract)
    ).all()
    for row in rows:
        values: dict[str, Any] = {}
        report, reporters = _json(row.report), _json(row.reported_instances)
        if isinstance(report, dict) and not reporters:
            values["reported_instances"] = [
                {
                    "member_id": report.get("reported_by"),
                    "instance": report.get("reported_instance"),
                }
            ]
        contract = _json(row.contract)
        if row.kind == "contract" and isinstance(contract, dict):
            written = {"path": DEFAULT_PATH, "section": None, **contract}
            if written != contract:
                values["contract"] = written
        if values:
            conn.execute(sa.update(card).where(card.c.id == row.id).values(**values))


def downgrade() -> None:
    """The cards stay as written: the old shapes were read, never required."""
