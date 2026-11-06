"""A join carries the owner's instruction to work in subagents (§3.1, §5.2, §6.2).

`join_link.subagents` and `.subagents_language` are what the join set; the exchange copies them
to the membership with `subagents_by`, the join's creator. A membership and an open join that
predate the field take the role default of a join that omits it (docs/api.md §6.2,
req-7s40gwjt3h11): on for `coder` and `reviewer`, set by the agent profile's owner (for a join,
its creator) in the language the hub speaks to that human (`languages.of_interface`).

Revision ID: 20261106210000_join_subagents
Revises: 20261105120000_known_source
Create Date: 2026-11-06
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261106210000_join_subagents"
down_revision: str | None = "20261105120000_known_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("subagents", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("subagents_language", sa.String(length=16), nullable=True))
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("subagents", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("subagents_language", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("subagents_by", sa.String(length=40), nullable=True))

    _backfill()


ROLES = ("coder", "reviewer")
# The interface languages when this migration was written (maity_hub.languages.INTERFACE);
# a migration keeps its own copy, so a later language does not change what it did.
INTERFACE = ("en", "de", "fr", "es", "pt", "it", "nl", "ja", "ko", "zh-Hans")


def _language(chosen: object, settings: object) -> str:
    """`languages.of_interface`: the interface language chosen, else what agents write in when
    the portal has it, else English (§6.2)."""
    if isinstance(settings, str):
        settings = json.loads(settings)
    mail = settings.get("email") if isinstance(settings, dict) else None
    written = mail.get("language") if isinstance(mail, dict) else None
    for tag in (chosen, written):
        if tag in INTERFACE:
            return str(tag)
    return "en"


def _backfill() -> None:
    human = sa.table(
        "human", sa.column("id", sa.String), sa.column("interface_language", sa.String)
    )
    settings = sa.table(
        "notification_settings",
        sa.column("human_id", sa.String),
        sa.column("preferences", sa.JSON),
    )
    profile = sa.table(
        "agent_profile", sa.column("id", sa.String), sa.column("owner_id", sa.String)
    )
    membership = sa.table(
        "membership",
        sa.column("agent_id", sa.String),
        sa.column("role", sa.String),
        sa.column("subagents", sa.Boolean),
        sa.column("subagents_language", sa.String),
        sa.column("subagents_by", sa.String),
    )
    join = sa.table(
        "join_link",
        sa.column("role", sa.String),
        sa.column("created_by", sa.String),
        sa.column("used_at", sa.DateTime),
        sa.column("revoked_at", sa.DateTime),
        sa.column("burned_at", sa.DateTime),
        sa.column("subagents", sa.Boolean),
        sa.column("subagents_language", sa.String),
    )
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(human.c.id, human.c.interface_language, settings.c.preferences).select_from(
            human.outerjoin(settings, settings.c.human_id == human.c.id)
        )
    ).all()
    for human_id, chosen, stored in rows:
        language = _language(chosen, stored)
        owned = sa.select(profile.c.id).where(profile.c.owner_id == human_id)
        conn.execute(
            sa.update(membership)
            .where(membership.c.agent_id.in_(owned), membership.c.role.in_(ROLES))
            .values(subagents=sa.true(), subagents_by=human_id, subagents_language=language)
        )
        conn.execute(
            sa.update(join)
            .where(
                join.c.created_by == human_id,
                join.c.role.in_(ROLES),
                join.c.used_at.is_(None),
                join.c.revoked_at.is_(None),
                join.c.burned_at.is_(None),
            )
            .values(subagents=sa.true(), subagents_language=language)
        )


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("subagents_by")
        batch_op.drop_column("subagents_language")
        batch_op.drop_column("subagents")
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.drop_column("subagents_language")
        batch_op.drop_column("subagents")
