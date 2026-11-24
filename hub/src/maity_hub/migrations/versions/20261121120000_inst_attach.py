"""One agent instance in several projects (docs/api.md §6.17, "One instance in several projects").

`instance_attachment` holds one row per (credential, membership): the projects an instance is
in. What belongs to the instance in one project moves there from `credential`: its pause, its
dormancy, its Keep the Why commitment and the handover numbers. The key (membership_id,
instance) of the new table takes the place of `uq_credential_instance`. `credential` keeps the
instance's own data and gains `agent_id`, its profile, with a non-unique index on
(agent_id, instance): ids from before may repeat across a profile's memberships.

`agent_session_project` holds one row per (session, membership): the session's event position
(`acknowledged_seq`) and its not-listening episode move there from `agent_session`.
`join_link.attach` names the instance a join attaches (§3.1).

Every existing credential becomes one attachment with its own values, attached at its
`created_at` by nobody and through its join; a revoked one is not marked detached. Every session
becomes one position row in its membership. The backfill is two INSERT … SELECT and one UPDATE,
whatever the number of rows; the drops come last, since MariaDB commits each step.

A downgrade puts the columns back from the one row of each credential and session, and
therefore refuses, before its first change, while a credential has more than one attachment
row or none, or a session more than one position row or none: the older schema holds one
project per credential and per session, a detached attachment keeps its row, and only a
database restore removes such rows.

Revision ID: 20261121120000_inst_attach
Revises: 20261120205253_plc_agent_id
Create Date: 2026-11-21
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "20261121120000_inst_attach"
down_revision: str | None = "20261120205253_plc_agent_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# maity_hub.types.UtcDateTime stores naive UTC; microseconds on MySQL/MariaDB.
TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
BIG_ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
MARKDOWN_TEXT = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
MYSQL: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}

# The columns that move from `credential` to `instance_attachment`, with their types.
MOVED_FROM_CREDENTIAL: tuple[tuple[str, sa.types.TypeEngine[Any]], ...] = (
    ("dormant_since", TIMESTAMP),
    ("dormant_by", sa.String(length=40)),
    ("exchange_seq", sa.Integer()),
    ("first_after", sa.Integer()),
    ("first_cursor", sa.Integer()),
    ("ktw_acknowledged_at", TIMESTAMP),
    ("ktw_acknowledged_session", sa.String(length=40)),
    ("ktw_acknowledge_by", TIMESTAMP),
    ("ktw_session_id", sa.String(length=40)),
    ("ktw_reminded_at", TIMESTAMP),
    ("ktw_request_id", sa.String(length=40)),
    ("paused_reason", MARKDOWN_TEXT),
    ("paused_since", TIMESTAMP),
    ("paused_by", sa.String(length=40)),
)
# `paused_line` moves as well; it is NOT NULL with a default, so it is listed apart.

# The columns that move from `agent_session` to `agent_session_project`, beside
# `acknowledged_seq` (NOT NULL, listed apart).
MOVED_FROM_SESSION: tuple[tuple[str, sa.types.TypeEngine[Any]], ...] = (
    ("not_listening_since", TIMESTAMP),
    ("not_listening_seq", BIG_ID),
    ("not_listening_request_id", sa.String(length=40)),
)

CREDENTIAL_MOVED = [name for name, _ in MOVED_FROM_CREDENTIAL] + ["paused_line"]
SESSION_MOVED = ["acknowledged_seq"] + [name for name, _ in MOVED_FROM_SESSION]


def upgrade() -> None:
    _create_tables()
    _backfill()
    _drop_moved()


def _create_tables() -> None:
    op.create_table(
        "instance_attachment",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("credential_id", sa.String(length=40), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("instance", sa.String(length=5), nullable=False),
        sa.Column("attached_at", TIMESTAMP, nullable=False),
        sa.Column("attached_by", sa.String(length=40), nullable=True),
        sa.Column("join_id", sa.String(length=40), nullable=True),
        sa.Column("detached_at", TIMESTAMP, nullable=True),
        sa.Column("detached_by", sa.String(length=40), nullable=True),
        sa.Column("detached_reason", sa.String(length=16), nullable=True),
        sa.Column("detached_project", JSON_VALUE, nullable=True),
        *(sa.Column(name, type_, nullable=True) for name, type_ in MOVED_FROM_CREDENTIAL),
        sa.Column("paused_line", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credential.id"],
            name=op.f("fk_instance_attachment_credential_id_credential"),
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_instance_attachment_membership_id_membership"),
        ),
        sa.ForeignKeyConstraint(
            ["join_id"], ["join_link.id"], name=op.f("fk_instance_attachment_join_id_join_link")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instance_attachment")),
        sa.UniqueConstraint(
            "membership_id", "instance", name="uq_instance_attachment_membership_instance"
        ),
        sa.UniqueConstraint(
            "credential_id", "membership_id", name="uq_instance_attachment_credential_membership"
        ),
        **MYSQL,
    )
    op.create_table(
        "agent_session_project",
        sa.Column("session_id", sa.String(length=40), nullable=False),
        sa.Column("membership_id", sa.Integer(), nullable=False),
        sa.Column("acknowledged_seq", BIG_ID, nullable=False),
        *(sa.Column(name, type_, nullable=True) for name, type_ in MOVED_FROM_SESSION),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_session.id"],
            name=op.f("fk_agent_session_project_session_id_agent_session"),
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["membership.id"],
            name=op.f("fk_agent_session_project_membership_id_membership"),
        ),
        sa.PrimaryKeyConstraint(
            "session_id", "membership_id", name=op.f("pk_agent_session_project")
        ),
        **MYSQL,
    )
    op.create_index(
        "ix_agent_session_project_membership_id",
        "agent_session_project",
        ["membership_id"],
        unique=False,
    )


def _backfill() -> None:
    """Two INSERT … SELECT and one UPDATE, whatever the number of rows
    (hub/context/persistence.md 319da070)."""
    credential = sa.table(
        "credential",
        sa.column("id"),
        sa.column("membership_id"),
        sa.column("agent_id"),
        sa.column("instance"),
        sa.column("created_at"),
        sa.column("join_id"),
        *(sa.column(name) for name in CREDENTIAL_MOVED),
    )
    attachment = sa.table(
        "instance_attachment",
        sa.column("credential_id"),
        sa.column("membership_id"),
        sa.column("instance"),
        sa.column("attached_at"),
        sa.column("join_id"),
        *(sa.column(name) for name in CREDENTIAL_MOVED),
    )
    op.execute(
        sa.insert(attachment).from_select(
            ["credential_id", "membership_id", "instance", "attached_at", "join_id"]
            + CREDENTIAL_MOVED,
            sa.select(
                credential.c.id,
                credential.c.membership_id,
                credential.c.instance,
                credential.c.created_at,
                credential.c.join_id,
                *(credential.c[name] for name in CREDENTIAL_MOVED),
            ).order_by(credential.c.created_at, credential.c.id),
        )
    )

    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.add_column(sa.Column("agent_id", sa.String(length=40), nullable=True))
    membership = sa.table("membership", sa.column("id"), sa.column("agent_id"))
    op.execute(
        sa.update(credential).values(
            agent_id=sa.select(membership.c.agent_id)
            .where(membership.c.id == credential.c.membership_id)
            .scalar_subquery()
        )
    )

    session = sa.table(
        "agent_session",
        sa.column("id"),
        sa.column("membership_id"),
        *(sa.column(name) for name in SESSION_MOVED),
    )
    position = sa.table(
        "agent_session_project",
        sa.column("session_id"),
        sa.column("membership_id"),
        *(sa.column(name) for name in SESSION_MOVED),
    )
    op.execute(
        sa.insert(position).from_select(
            ["session_id", "membership_id"] + SESSION_MOVED,
            sa.select(
                session.c.id,
                session.c.membership_id,
                *(session.c[name] for name in SESSION_MOVED),
            ),
        )
    )


def _drop_moved() -> None:
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.alter_column("agent_id", existing_type=sa.String(length=40), nullable=False)
        # The index before the foreign key: on MariaDB the key then uses it instead of making
        # one of its own.
        batch_op.create_index("ix_credential_agent_instance", ["agent_id", "instance"])
        batch_op.create_foreign_key(
            batch_op.f("fk_credential_agent_id_agent_profile"),
            "agent_profile",
            ["agent_id"],
            ["id"],
        )
        # The foreign key first: MariaDB refuses to drop an index a foreign key needs.
        batch_op.drop_constraint(
            batch_op.f("fk_credential_membership_id_membership"), type_="foreignkey"
        )
        batch_op.drop_constraint("uq_credential_instance", type_="unique")
        batch_op.drop_index(batch_op.f("ix_credential_membership_id"))
        batch_op.drop_column("membership_id")
        for name in CREDENTIAL_MOVED:
            batch_op.drop_column(name)
    with op.batch_alter_table("agent_session", schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f("fk_agent_session_membership_id_membership"), type_="foreignkey"
        )
        batch_op.drop_index(batch_op.f("ix_agent_session_membership_id"))
        batch_op.drop_column("membership_id")
        for name in SESSION_MOVED:
            batch_op.drop_column(name)
    with op.batch_alter_table("join_link", schema=None) as batch_op:
        # The instance id or the credential id (`crd-…`) the join names (§3.1): String(ID).
        batch_op.add_column(sa.Column("attach", sa.String(length=40), nullable=True))


def _refuse_what_does_not_fit() -> None:
    """Refuse before the first DDL, since MariaDB commits each DDL step and a later failure
    would leave the schema half downgraded: the older schema holds one project per credential
    and per session, so a credential needs exactly one attachment row and a session exactly
    one position row. A detached attachment keeps its row, so detaching never helps. Four
    reads, whatever the number of rows."""
    attachment = sa.table("instance_attachment", sa.column("credential_id"))
    position = sa.table("agent_session_project", sa.column("session_id"))
    credential = sa.table("credential", sa.column("id"))
    session = sa.table("agent_session", sa.column("id"))
    checks = (
        (
            "a credential has more than one instance_attachment row",
            sa.select(attachment.c.credential_id)
            .group_by(attachment.c.credential_id)
            .having(sa.func.count() > 1),
        ),
        (
            "a session has more than one agent_session_project row",
            sa.select(position.c.session_id)
            .group_by(position.c.session_id)
            .having(sa.func.count() > 1),
        ),
        (
            "a credential has no instance_attachment row",
            sa.select(credential.c.id).where(
                ~sa.select(attachment.c.credential_id)
                .where(attachment.c.credential_id == credential.c.id)
                .exists()
            ),
        ),
        (
            "a session has no agent_session_project row",
            sa.select(session.c.id).where(
                ~sa.select(position.c.session_id)
                .where(position.c.session_id == session.c.id)
                .exists()
            ),
        ),
    )
    conn = op.get_bind()
    for what, query in checks:
        if conn.execute(query.limit(1)).first() is not None:
            raise RuntimeError(
                f"{what}; the schema before this revision holds one project per credential "
                "and per session, so these rows do not fit it, and only a database restore "
                "removes them (docs/api.md §6.17)"
            )


def downgrade() -> None:
    _refuse_what_does_not_fit()
    attachment = sa.table(
        "instance_attachment",
        sa.column("id"),
        sa.column("credential_id"),
        sa.column("membership_id"),
        *(sa.column(name) for name in CREDENTIAL_MOVED),
    )

    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.add_column(sa.Column("membership_id", sa.Integer(), nullable=True))
        for name, type_ in MOVED_FROM_CREDENTIAL:
            batch_op.add_column(sa.Column(name, type_, nullable=True))
        batch_op.add_column(
            sa.Column("paused_line", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
    credential = sa.table(
        "credential",
        sa.column("id"),
        sa.column("membership_id"),
        *(sa.column(name) for name in CREDENTIAL_MOVED),
    )

    def from_attachment(name: str) -> Any:
        return (
            sa.select(attachment.c[name])
            .where(attachment.c.credential_id == credential.c.id)
            .scalar_subquery()
        )

    op.execute(
        sa.update(credential).values(
            {name: from_attachment(name) for name in ["membership_id"] + CREDENTIAL_MOVED}
        )
    )
    with op.batch_alter_table("credential", schema=None) as batch_op:
        batch_op.alter_column("membership_id", existing_type=sa.Integer(), nullable=False)
        batch_op.create_index(
            batch_op.f("ix_credential_membership_id"), ["membership_id"], unique=False
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_credential_membership_id_membership"),
            "membership",
            ["membership_id"],
            ["id"],
        )
        batch_op.create_unique_constraint("uq_credential_instance", ["membership_id", "instance"])
        # The foreign key first: MariaDB refuses to drop an index a foreign key needs.
        batch_op.drop_constraint(
            batch_op.f("fk_credential_agent_id_agent_profile"), type_="foreignkey"
        )
        batch_op.drop_index("ix_credential_agent_instance")
        batch_op.drop_column("agent_id")

    with op.batch_alter_table("agent_session", schema=None) as batch_op:
        batch_op.add_column(sa.Column("membership_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("acknowledged_seq", BIG_ID, nullable=True))
        for name, type_ in MOVED_FROM_SESSION:
            batch_op.add_column(sa.Column(name, type_, nullable=True))
    session = sa.table(
        "agent_session",
        sa.column("id"),
        sa.column("membership_id"),
        *(sa.column(name) for name in SESSION_MOVED),
    )
    position = sa.table(
        "agent_session_project",
        sa.column("session_id"),
        sa.column("membership_id"),
        *(sa.column(name) for name in SESSION_MOVED),
    )

    def from_position(name: str) -> Any:
        return (
            sa.select(position.c[name])
            .where(position.c.session_id == session.c.id)
            .scalar_subquery()
        )

    op.execute(
        sa.update(session).values(
            {name: from_position(name) for name in ["membership_id"] + SESSION_MOVED}
        )
    )
    with op.batch_alter_table("agent_session", schema=None) as batch_op:
        batch_op.alter_column("membership_id", existing_type=sa.Integer(), nullable=False)
        batch_op.alter_column("acknowledged_seq", existing_type=BIG_ID, nullable=False)
        batch_op.create_index(
            batch_op.f("ix_agent_session_membership_id"), ["membership_id"], unique=False
        )
        batch_op.create_foreign_key(
            batch_op.f("fk_agent_session_membership_id_membership"),
            "membership",
            ["membership_id"],
            ["id"],
        )

    with op.batch_alter_table("join_link", schema=None) as batch_op:
        batch_op.drop_column("attach")
    # The tables alone: their indexes go with them, and dropping one first fails on MariaDB
    # while a foreign key needs it (hub/context/persistence.md cb582092).
    op.drop_table("agent_session_project")
    op.drop_table("instance_attachment")
