"""Settings stored for notification kinds that no longer exist are deleted (docs/api.md §18.4).

The maintainer's decision of 2026-10-26 removed `card`, `agent`, `keep_the_why`, `ticker`,
`jour_fixe`, `system` and `registration`; until now the hub skipped what was stored for them
on every read. This keeps only the four kinds that exist (`inbox`, `chat`, `mention`,
`security`) in `browser.kinds`, `browser.content` and `email.kinds`, so that the code no
longer has to know the old ones. Not reversible: the old values governed nothing.

Revision ID: 0084
Revises: 0080
Create Date: 2026-10-29
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0084"
down_revision: str | None = "0080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = ("inbox", "chat", "mention", "security")


def _kept(stored: Any) -> Any:
    if not isinstance(stored, dict):
        return stored
    out: dict[str, Any] = {}
    for side, given in stored.items():
        if not isinstance(given, dict):
            out[side] = given
            continue
        kept = dict(given)
        for key in ("kinds", "content"):
            if isinstance(kept.get(key), dict):
                kept[key] = {k: v for k, v in kept[key].items() if k in KINDS}
        out[side] = kept
    return out


def upgrade() -> None:
    settings = sa.table(
        "notification_settings",
        sa.column("human_id", sa.String),
        sa.column("preferences", sa.JSON(none_as_null=True)),
    )
    bind = op.get_bind()
    for human_id, stored in bind.execute(sa.select(settings.c.human_id, settings.c.preferences)):
        kept = _kept(stored)
        if kept != stored:
            bind.execute(
                sa.update(settings).where(settings.c.human_id == human_id).values(preferences=kept)
            )


def downgrade() -> None:
    pass  # the deleted values governed nothing
