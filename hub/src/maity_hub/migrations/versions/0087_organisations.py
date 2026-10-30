"""Organisations, the second kind of namespace owner (docs/api.md §6.26).

`org` is the organisation, `org_member` a human's role in it and `org_invitation` an offer to
become a member, answered by the invited human's own word. `handle_register` is the one
namespace of current handles: its primary key is what makes a human's and an organisation's
handle unique together under any race, so no code path has to remember to check. Every
existing human's handle is entered here; later accounts and organisations enter theirs when
they are made, and a row is never deleted, so a deleted account's handle stays taken.

Re-chained at merge time: `down_revision` is the head of the chain this branch started
from and follows whatever head `main` has when it lands.

Revision ID: 0087
Revises: 0093
Create Date: 2026-10-29
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0087"
down_revision: str | None = "0093"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def upgrade() -> None:
    op.create_table(
        "handle_register",
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("owner_id", sa.String(length=40), nullable=False),
        sa.CheckConstraint("kind IN ('human', 'org')", name=op.f("ck_handle_register_kind_known")),
        sa.PrimaryKeyConstraint("handle", name=op.f("pk_handle_register")),
        sa.UniqueConstraint("owner_id", name="uq_handle_register_owner"),
        **TABLE_OPTIONS,
    )
    op.execute(
        "INSERT INTO handle_register (handle, kind, owner_id) SELECT handle, 'human', id FROM human"
    )

    op.create_table(
        "org",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column(
            "members_create_projects", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column("public_page", sa.String(length=8), server_default="off", nullable=False),
        sa.Column("deleted_at", TIMESTAMP, nullable=True),
        sa.CheckConstraint("public_page IN ('off', 'on')", name=op.f("ck_org_public_page_known")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org")),
        sa.UniqueConstraint("handle", name=op.f("uq_org_handle")),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "org_member",
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("human_id", sa.String(length=40), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("joined_at", TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')", name=op.f("ck_org_member_role_known")
        ),
        sa.ForeignKeyConstraint(
            ["human_id"], ["human.id"], name=op.f("fk_org_member_human_id_human")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"], name=op.f("fk_org_member_org_id_org")),
        sa.PrimaryKeyConstraint("org_id", "human_id", name="pk_org_member"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_org_member_human", "org_member", ["human_id"])

    op.create_table(
        "org_invitation",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("org_id", sa.String(length=40), nullable=False),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=8), nullable=False),
        sa.Column("invited_by", sa.String(length=40), nullable=False),
        sa.Column("request_id", sa.String(length=40), nullable=True),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("expires_at", TIMESTAMP, nullable=False),
        sa.Column("closed_at", TIMESTAMP, nullable=True),
        sa.Column("closed_by", sa.String(length=16), nullable=True),
        sa.Column("live", sa.Boolean(), nullable=True),
        sa.CheckConstraint("live IS NOT FALSE", name=op.f("ck_org_invitation_live_true_or_null")),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')", name=op.f("ck_org_invitation_role_known")
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["human.id"], name=op.f("fk_org_invitation_invited_by_human")
        ),
        sa.ForeignKeyConstraint(["org_id"], ["org.id"], name=op.f("fk_org_invitation_org_id_org")),
        sa.ForeignKeyConstraint(
            ["request_id"], ["request.id"], name=op.f("fk_org_invitation_request_id_request")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_org_invitation")),
        sa.UniqueConstraint("org_id", "handle", "live", name="uq_org_invitation_open"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_org_invitation_org", "org_invitation", ["org_id"])


def downgrade() -> None:
    op.drop_table("org_invitation")
    op.drop_table("org_member")
    op.drop_table("org")
    op.drop_table("handle_register")
