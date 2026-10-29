"""The landing page in sections and the legal pages (docs/api.md §16.7, §16.7.1).

`instance_landing` held one Markdown body, a title and a call to action. It now holds
`default_language`, `pages` (per language `{title, description, sections}`) and `footer`; the
old body is carried over as the `en` page: a `hero` with the title and the call to action,
and a `text` section with the Markdown, enabled as before. A row that held nothing stays
disabled. The legal pages get their three tables: the setting, every version of a page, and
the version served now. Downgrading restores the old columns from the `en` page, as far as
it has the old shape; the legal tables go with their texts.

Revision ID: 0087
Revises: 0086
Create Date: 2026-10-29
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql, postgresql

revision: str = "0087"
down_revision: str | None = "0086"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TIMESTAMP = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql", "mariadb")
JSON_VALUE = sa.JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)
TABLE_OPTIONS: dict[str, Any] = {
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
}


def _carried(title: Any, markdown: Any, cta: Any) -> dict[str, Any]:
    """The `en` page the old body becomes."""
    sections: list[dict[str, Any]] = []
    if title or cta:
        hero: dict[str, Any] = {"type": "hero", "enabled": True}
        if title:
            hero["title"] = title
        if isinstance(cta, dict):
            hero["cta_primary"] = {"label": cta.get("label"), "href": cta.get("href")}
        sections.append(hero)
    if markdown:
        sections.append({"type": "text", "enabled": True, "markdown": markdown})
    return {"title": title or "Maity", "description": "", "sections": sections}


def upgrade() -> None:
    bind = op.get_bind()
    old = sa.table(
        "instance_landing",
        sa.column("id", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("title", sa.String),
        sa.column("markdown", sa.Text),
        sa.column("cta", sa.JSON(none_as_null=True)),
    )
    row = bind.execute(sa.select(old.c.enabled, old.c.title, old.c.markdown, old.c.cta)).first()
    with op.batch_alter_table("instance_landing", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("default_language", sa.String(length=8), server_default="en", nullable=False)
        )
        batch_op.add_column(sa.Column("pages", JSON_VALUE, nullable=True))
        batch_op.add_column(sa.Column("footer", JSON_VALUE, nullable=True))
    landing = sa.table(
        "instance_landing",
        sa.column("pages", sa.JSON(none_as_null=True)),
        sa.column("enabled", sa.Boolean),
    )
    if row is None:
        pages: dict[str, Any] = {}
        enabled = False
    else:
        page = _carried(row.title, row.markdown, row.cta)
        pages = {"en": page} if page["sections"] else {}
        enabled = bool(row.enabled) and bool(pages)
    bind.execute(sa.update(landing).values(pages=pages, enabled=enabled))
    with op.batch_alter_table("instance_landing", schema=None) as batch_op:
        batch_op.alter_column("pages", existing_type=JSON_VALUE, nullable=False)
        batch_op.alter_column("default_language", server_default=None, existing_type=sa.String(8))
        batch_op.drop_column("title")
        batch_op.drop_column("markdown")
        batch_op.drop_column("cta")

    op.create_table(
        "instance_legal",
        sa.Column("id", sa.String(length=16), nullable=False),
        sa.Column("default_language", sa.String(length=8), nullable=False),
        sa.Column("updated_at", TIMESTAMP, nullable=False),
        sa.Column("updated_by", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instance_legal")),
        **TABLE_OPTIONS,
    )
    op.create_table(
        "legal_version",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("page", sa.String(length=16), nullable=False),
        sa.Column("version", sa.String(length=20), nullable=False),
        sa.Column("languages", JSON_VALUE, nullable=False),
        sa.Column("created_at", TIMESTAMP, nullable=False),
        sa.Column("created_by", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_legal_version")),
        sa.UniqueConstraint("page", "version", name="uq_legal_version_page_version"),
        sqlite_autoincrement=True,
        **TABLE_OPTIONS,
    )
    op.create_table(
        "legal_page",
        sa.Column("page", sa.String(length=16), nullable=False),
        sa.Column("current", sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint("page", name=op.f("pk_legal_page")),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("legal_page")
    op.drop_table("legal_version")
    op.drop_table("instance_legal")
    bind = op.get_bind()
    landing = sa.table(
        "instance_landing",
        sa.column("pages", sa.JSON(none_as_null=True)),
        sa.column("enabled", sa.Boolean),
    )
    row = bind.execute(sa.select(landing.c.pages, landing.c.enabled)).first()
    with op.batch_alter_table("instance_landing", schema=None) as batch_op:
        batch_op.add_column(sa.Column("title", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("markdown", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("cta", JSON_VALUE, nullable=True))
    old = sa.table(
        "instance_landing",
        sa.column("title", sa.String),
        sa.column("markdown", sa.Text),
        sa.column("cta", sa.JSON(none_as_null=True)),
        sa.column("enabled", sa.Boolean),
    )
    page = ((row.pages or {}).get("en") if row is not None else None) or {}
    values: dict[str, Any] = {"title": page.get("title"), "markdown": None, "cta": None}
    for section in page.get("sections") or []:
        if section.get("type") == "hero" and isinstance(section.get("cta_primary"), dict):
            values["cta"] = section["cta_primary"]
        if section.get("type") == "text" and values["markdown"] is None:
            values["markdown"] = section.get("markdown")
    values["enabled"] = bool(row.enabled) if row is not None and values["markdown"] else False
    bind.execute(sa.update(old).values(**values))
    with op.batch_alter_table("instance_landing", schema=None) as batch_op:
        batch_op.drop_column("footer")
        batch_op.drop_column("pages")
        batch_op.drop_column("default_language")
