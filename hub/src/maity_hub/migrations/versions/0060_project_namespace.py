"""Projects in their owner's namespace (docs/api.md §6.25).

Every project gets a namespace owner: the human with an active `owner` membership that is
the oldest (ties by id). The creator's own membership is the first one of every project, so
while the creator is still an active owner, that is the creator. A project with no such human
stops the migration and is named to the operator. Slugs stay as they are and become unique
per owner; every existing project keeps its slug as `legacy_slug`, frozen, for the addresses
outside the API. Stored slugs are rewritten to full names: a human's limit
`show_reason_in`. A request's `action.path` does not exist yet; the migration that adds it
writes the new form.

A slug that is a word following a project in a route, or a human handle that is a dashboard
route word, stops the migration too: the operator renames it first.

Revision ID: 0060
Revises: 0062
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0060"
down_revision: str | None = "0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")

# The words that follow `/projects/{owner}/{slug}/` in a route at this revision (§6.25), and
# the dashboard's top-level route words (§6.25 "Dashboard routes and handles").
ROUTE_WORDS = frozenset(
    {
        "attachments", "banner", "conversations", "credentials", "events", "forge",
        "invitations", "joins", "jour-fixe", "keep-the-why", "logo", "members", "memory",
        "messages", "placements", "probe", "requests", "rules", "runners", "swarm", "takeovers",
        "tasks", "ticker", "transfer",
    }
)  # fmt: skip
DASHBOARD_WORDS = frozenset(
    {
        "account", "admin", "agents", "all", "chats", "components", "invite", "join", "login",
        "new", "notifications", "observe", "p", "register", "requests", "runners", "s",
        "settings", "sign-in",
    }
)  # fmt: skip

project = sa.table(
    "project",
    sa.column("id", sa.String),
    sa.column("slug", sa.String),
    sa.column("owner_id", sa.String),
    sa.column("legacy_slug", sa.String),
    sa.column("created_at", TIMESTAMP),
)
membership = sa.table(
    "membership",
    sa.column("project_id", sa.String),
    sa.column("human_id", sa.String),
    sa.column("role", sa.String),
    sa.column("active", sa.Boolean),
    sa.column("joined_at", TIMESTAMP),
)
human = sa.table(
    "human",
    sa.column("id", sa.String),
    sa.column("handle", sa.String),
    sa.column("limit_show_reason_in", sa.JSON),
)


class NamespaceMigrationStopped(RuntimeError):
    """What the operator has to fix before the namespace migration can run."""


def _check(bind: sa.Connection) -> None:
    problems = []
    for row in bind.execute(sa.select(project.c.slug)).all():
        if row.slug in ROUTE_WORDS:
            problems.append(f"project slug {row.slug!r} is a route word: rename the project")
    for row in bind.execute(sa.select(human.c.handle)).all():
        if row.handle in DASHBOARD_WORDS:
            problems.append(f"human handle {row.handle!r} is a dashboard route: rename it")
    if problems:
        raise NamespaceMigrationStopped("; ".join(problems))


def _owners(bind: sa.Connection) -> dict[str, str]:
    """project id → its namespace owner's human id; stops on a project without one."""
    owners: dict[str, str] = {}
    missing = []
    for row in bind.execute(sa.select(project.c.id, project.c.slug)).all():
        owner = bind.execute(
            sa.select(membership.c.human_id)
            .where(
                membership.c.project_id == row.id,
                membership.c.human_id.is_not(None),
                membership.c.role == "owner",
                membership.c.active.is_(True),
            )
            .order_by(membership.c.joined_at, membership.c.human_id)
            .limit(1)
        ).scalar()
        if owner is None:
            missing.append(row.slug)
        else:
            owners[row.id] = owner
    if missing:
        raise NamespaceMigrationStopped(
            "no human with an active owner membership in: " + ", ".join(sorted(missing))
        )
    return owners


def upgrade() -> None:
    bind = op.get_bind()
    _check(bind)
    owners = _owners(bind)
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("legacy_slug", sa.String(length=64), nullable=True))
    for project_id, owner_id in owners.items():
        bind.execute(
            sa.update(project)
            .where(project.c.id == project_id)
            .values(owner_id=owner_id, legacy_slug=project.c.slug)
        )
    full = {
        row.slug: f"{row.handle}/{row.slug}"
        for row in bind.execute(
            sa.select(project.c.slug, human.c.handle).join(human, human.c.id == project.c.owner_id)
        ).all()
    }
    for row in bind.execute(
        sa.select(human.c.id, human.c.limit_show_reason_in).where(
            human.c.limit_show_reason_in.is_not(None)
        )
    ).all():
        slugs = row.limit_show_reason_in
        if isinstance(slugs, list):
            names = [full[s] for s in slugs if isinstance(s, str) and s in full]
            bind.execute(
                sa.update(human).where(human.c.id == row.id).values(limit_show_reason_in=names)
            )
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.alter_column("owner_id", existing_type=sa.String(length=40), nullable=False)
        batch_op.create_foreign_key(
            op.f("fk_project_owner_id_human"), "human", ["owner_id"], ["id"]
        )
        batch_op.drop_constraint(op.f("uq_project_slug"), type_="unique")
        batch_op.create_unique_constraint("uq_project_owner_slug", ["owner_id", "slug"])
    op.create_table(
        "project_alias",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.String(length=40), nullable=False),
        sa.Column("owner_id", sa.String(length=40), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name=op.f("fk_project_alias_project_id_project")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["human.id"], name=op.f("fk_project_alias_owner_id_human")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_alias")),
        sa.UniqueConstraint("owner_id", "slug", name="uq_project_alias_owner_slug"),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_table("project_alias")
    for row in bind.execute(
        sa.select(human.c.id, human.c.limit_show_reason_in).where(
            human.c.limit_show_reason_in.is_not(None)
        )
    ).all():
        names = row.limit_show_reason_in
        if isinstance(names, list):
            slugs = [n.split("/", 1)[-1] for n in names if isinstance(n, str)]
            bind.execute(
                sa.update(human).where(human.c.id == row.id).values(limit_show_reason_in=slugs)
            )
    # Slugs two owners share get the project id appended, all but the oldest, so that
    # the old instance-wide key holds again (as 0032's downgrade does for handles).
    seen: set[str] = set()
    for row in bind.execute(
        sa.select(project.c.id, project.c.slug).order_by(project.c.created_at, project.c.id)
    ).all():
        if row.slug in seen:
            bind.execute(
                sa.update(project)
                .where(project.c.id == row.id)
                .values(slug=f"{row.slug[:23]}-{row.id}")
            )
        seen.add(row.slug)
    with op.batch_alter_table("project", schema=None) as batch_op:
        batch_op.drop_constraint("uq_project_owner_slug", type_="unique")
        batch_op.create_unique_constraint(op.f("uq_project_slug"), ["slug"])
        batch_op.drop_constraint(op.f("fk_project_owner_id_human"), type_="foreignkey")
        batch_op.drop_column("legacy_slug")
        batch_op.drop_column("owner_id")
