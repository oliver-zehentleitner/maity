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


# How many human ids one statement names, well below every backend's bound on parameters.
CHUNK = 500


def _mail_language(settings: object) -> str:
    """What agents write in, when the portal has it, else English: the rest of
    `languages.of_interface` once the interface language has not decided (§6.2)."""
    if isinstance(settings, str):
        settings = json.loads(settings)
    mail = settings.get("email") if isinstance(settings, dict) else None
    written = mail.get("language") if isinstance(mail, dict) else None
    return str(written) if written in INTERFACE else "en"


def _backfill() -> None:
    """Set-based, so the work grows with the rows that change, not with humans × joins: one
    statement per table sets the instruction with the owner's interface language, and only
    the owners without one are read again, for their mail language, a chunk at a time."""
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
    chosen = sa.case(
        (human.c.interface_language.in_(INTERFACE), human.c.interface_language),
        else_=sa.null(),
    )
    owner = (
        sa.select(profile.c.owner_id).where(profile.c.id == membership.c.agent_id).scalar_subquery()
    )
    owner_chosen = (
        sa.select(chosen)
        .select_from(profile.join(human, human.c.id == profile.c.owner_id))
        .where(profile.c.id == membership.c.agent_id)
        .scalar_subquery()
    )
    creator_chosen = sa.select(chosen).where(human.c.id == join.c.created_by).scalar_subquery()
    conn = op.get_bind()
    conn.execute(
        sa.update(membership)
        .where(membership.c.agent_id.is_not(None), membership.c.role.in_(ROLES))
        .values(subagents=sa.true(), subagents_by=owner, subagents_language=owner_chosen)
    )
    still_open = (
        join.c.role.in_(ROLES),
        join.c.used_at.is_(None),
        join.c.revoked_at.is_(None),
        join.c.burned_at.is_(None),
    )
    conn.execute(
        sa.update(join)
        .where(*still_open)
        .values(subagents=sa.true(), subagents_language=creator_chosen)
    )
    # The owners left without a language: their mail language, else English.
    member_left = membership.c.subagents.is_(True) & membership.c.subagents_language.is_(None)
    join_left = join.c.subagents.is_(True) & join.c.subagents_language.is_(None)
    left = sorted(
        {
            *conn.execute(
                sa.select(membership.c.subagents_by)
                .where(member_left, membership.c.subagents_by.is_not(None))
                .distinct()
            ).scalars(),
            *conn.execute(sa.select(join.c.created_by).where(join_left).distinct()).scalars(),
        }
    )
    by_language: dict[str, list[str]] = {}
    for start in range(0, len(left), CHUNK):
        ids = left[start : start + CHUNK]
        stored = dict(
            conn.execute(
                sa.select(settings.c.human_id, settings.c.preferences).where(
                    settings.c.human_id.in_(ids)
                )
            ).all()
        )
        for human_id in ids:
            by_language.setdefault(_mail_language(stored.get(human_id)), []).append(human_id)
    for language, ids in by_language.items():
        for start in range(0, len(ids), CHUNK):
            chunk = ids[start : start + CHUNK]
            conn.execute(
                sa.update(membership)
                .where(member_left, membership.c.subagents_by.in_(chunk))
                .values(subagents_language=language)
            )
            conn.execute(
                sa.update(join)
                .where(join_left, join.c.created_by.in_(chunk))
                .values(subagents_language=language)
            )


def downgrade() -> None:
    with op.batch_alter_table("membership", schema=None) as batch_op:
        batch_op.drop_column("subagents_by")
        batch_op.drop_column("subagents_language")
        batch_op.drop_column("subagents")
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.drop_column("subagents_language")
        batch_op.drop_column("subagents")
