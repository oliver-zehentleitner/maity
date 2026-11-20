"""Names the schema uses that MySQL or MariaDB reserve, and SQLAlchemy does not quote by itself.

SQLAlchemy quotes an identifier only when it is in its dialect's reserved list
(`sqlalchemy.dialects.mysql.reserved_words`), and that list lags the servers: `vector`,
reserved since MariaDB 11.7, is not in it, and migration 0034 failed on MariaDB 11.8. These
tests need no server: they fail on every engine when a name from `NEWER_RESERVED` is used
without `quote=True`, so the next such word is found in CI before an operator's install is.
"""

from __future__ import annotations

import importlib.util
import io
import re
from importlib.resources import files
from pathlib import Path
from types import ModuleType

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.mysql import reserved_words
from sqlalchemy.dialects.mysql.mariadb import MariaDBDialect
from sqlalchemy.schema import CreateTable
from sqlalchemy.sql.elements import quoted_name

from maity_hub import tables as t
from maity_hub.db import metadata

# Words the servers reserve that SQLAlchemy's lists may lack, from the vendors' lists:
# the MariaDB KB "Reserved Words" (a version in brackets: reserved from that release on) and the
# MySQL 8.4 and 9.7 reference manuals, "Keywords and Reserved Words", the (R) words new since
# 8.0. A word SQLAlchemy already knows is quoted by it; listing it here does no harm.
NEWER_RESERVED = frozenset(
    {
        "vector",  # MariaDB 11.7+
        "sql_after_gtids",  # MariaDB 11.3+
        "sql_before_gtids",  # MariaDB 11.3+
        "conversion",  # MariaDB 12.3+
        "current_path",  # MariaDB 12.3+
        "to_date",  # MariaDB 12.3+
        "qualify",  # MySQL 8.4
        "tablesample",  # MySQL 8.4
        "external",  # MySQL 9.x
        "library",  # MySQL 9.x
    }
)
KNOWN = reserved_words.RESERVED_WORDS_MARIADB | reserved_words.RESERVED_WORDS_MYSQL
UNQUOTED = NEWER_RESERVED - KNOWN

VERSIONS = Path(str(files("maity_hub") / "migrations" / "versions"))
# `sa.Column("name", …)`, `sa.column("name", …)` and `op.create_table("name", …)` up to the end of
# the line: the migrations write one column per line.
NAMED = re.compile(r"""\b(?:Column|column|create_table|add_column)\(\s*"(\w+)"(.*)$""", re.M)


def test_sqlalchemy_still_lacks_vector() -> None:
    """The reason the column carries quote=True. When a SQLAlchemy update learns the word, this
    fails: the flag is then redundant (harmless), and the entry in hub/context/persistence.md
    is due for review."""
    assert "vector" in UNQUOTED


def _unquoted(name: str) -> bool:
    return name.lower() in UNQUOTED and not (isinstance(name, quoted_name) and name.quote)


def test_every_reserved_name_in_the_tables_is_quoted() -> None:
    missing = []
    for table in metadata.tables.values():
        if _unquoted(table.name):
            missing.append(table.name)
        missing += [f"{table.name}.{c.name}" for c in table.c if _unquoted(c.name)]
    assert missing == [], f"reserved on MySQL/MariaDB, needs quote=True: {missing}"


def test_every_reserved_name_in_the_migrations_is_quoted() -> None:
    missing = [
        f"{path.name}: {m.group(1)}"
        for path in sorted(VERSIONS.glob("*.py"))
        for m in NAMED.finditer(path.read_text(encoding="utf-8"))
        if m.group(1).lower() in UNQUOTED and "quote=True" not in m.group(2)
    ]
    assert missing == [], f"reserved on MySQL/MariaDB, needs quote=True: {missing}"


def _migration(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, VERSIONS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0034_creates_the_vector_column_quoted_on_mariadb() -> None:
    """0034's DDL as MariaDB gets it, written offline: what a fresh install runs."""
    out = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="mariadb", opts={"as_sql": True, "output_buffer": out}
    )
    with Operations.context(context):
        _migration("0034_notifications").upgrade()
    ddl = out.getvalue()
    assert "CREATE TABLE notification_position" in ddl
    assert "`vector` JSON NOT NULL" in ddl


def test_the_queries_on_positions_quote_vector_on_mariadb() -> None:
    dialect = MariaDBDialect()
    position = t.notification_position
    statements = [
        CreateTable(position),
        insert(position).values(
            id="npos-x", human_id="h", vector={}, created_at=None, last_used_at=None
        ),
        select(position),
        update(position).values(vector={}),
    ]
    for statement in statements:
        sql = str(statement.compile(dialect=dialect))
        assert "`vector`" in sql, sql
        assert not re.search(r"(?<![`.])\bvector\b(?!`)", sql), sql
