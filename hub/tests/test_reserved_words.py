"""Names the schema uses that MySQL or MariaDB reserve, and SQLAlchemy does not quote by itself.

SQLAlchemy quotes an identifier only when it is in its dialect's reserved list
(`sqlalchemy.dialects.mysql.reserved_words`), and that list lags the servers: `vector`,
reserved since MariaDB 11.7, is not in it, and migration 0034 failed on MariaDB 11.8. These
tests need no server: they fail on every engine when a name from `NEWER_RESERVED` is used
without `quote=True`, so the next such word is found in CI before an operator's install is.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import re
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest
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


# A name is quoted when it is `quoted_name("…", True)` (or `quote=True` inside it), and for a column
# or a table being created also by a `quote=True` keyword on the call. Names that are not string
# literals (a variable, a helper's argument) cannot be judged here and are left out.
QUOTE_KEYWORD = {"Column", "Table", "create_table"}


def _literal(node: ast.expr | None) -> tuple[str, bool] | None:
    """The name a node spells and whether quoted_name quotes it; None when it is no literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, False
    if isinstance(node, ast.Call) and _callee(node) == "quoted_name" and node.args:
        inner = _literal(node.args[0])
        if inner is None:
            return None
        flag = node.args[1] if len(node.args) > 1 else _keyword(node, "quote")
        return inner[0], isinstance(flag, ast.Constant) and flag.value is True
    return None


def _callee(call: ast.Call) -> str | None:
    func = call.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    return next((k.value for k in call.keywords if k.arg == name), None)


def _arg(call: ast.Call, index: int, name: str) -> ast.expr | None:
    return call.args[index] if len(call.args) > index else _keyword(call, name)


def _on_op(call: ast.Call) -> bool:
    """`op.alter_column(table, column)`; a batch's `batch_op.alter_column(column)` has no table."""
    func = call.func
    return isinstance(func, ast.Attribute) and getattr(func.value, "id", None) == "op"


def _names(call: ast.Call) -> list[tuple[str, ast.expr | None]]:
    """(what, node) for every identifier the call names: tables and columns."""
    callee, table = _callee(call), (0 if _on_op(call) else None)
    shift = 1 if table is not None else 0
    found: list[tuple[str, ast.expr | None]] = []
    if callee in ("Column", "column"):
        node = _keyword(call, "name")
        if node is None and call.args and _literal(call.args[0]) is not None:
            node = call.args[0]
        found.append(("column", node))
    elif callee in ("Table", "table", "create_table", "drop_table"):
        found.append(("table", _arg(call, 0, "table_name" if callee != "Table" else "name")))
    elif callee == "rename_table":
        found += [("table", _arg(call, 0, "old_table_name"))]
        found += [("table", _arg(call, 1, "new_table_name"))]
    elif callee in ("alter_column", "drop_column"):
        if table is not None:
            found.append(("table", _arg(call, 0, "table_name")))
        found.append(("column", _arg(call, shift, "column_name")))
        if callee == "alter_column":
            found.append(("column", _keyword(call, "new_column_name")))
    elif callee == "add_column" and table is not None:
        found.append(("table", _arg(call, 0, "table_name")))
    elif callee in ("create_index", "create_unique_constraint"):
        if table is not None:
            found.append(("table", _arg(call, 1, "table_name")))
        columns = _arg(call, 1 + shift, "columns")
        if isinstance(columns, (ast.List, ast.Tuple)):
            found += [("column", c) for c in columns.elts]
    return found


def unquoted_names(source: str) -> list[str]:
    """`<line>: <table|column> <name>` for every reserved name in source left unquoted."""
    missing = []
    for call in (n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)):
        keyword = _keyword(call, "quote")
        flagged = (
            _callee(call) in QUOTE_KEYWORD
            and isinstance(keyword, ast.Constant)
            and keyword.value is True
        )
        for what, node in _names(call):
            spelled = _literal(node)
            if spelled is None or spelled[0].lower() not in UNQUOTED:
                continue
            created = node is _arg(call, 0, "name") or node is _keyword(call, "name")
            if spelled[1] or (flagged and created):
                continue
            missing.append(f"{call.lineno}: {what} {spelled[0]}")
    return missing


def test_every_reserved_name_in_the_migrations_is_quoted() -> None:
    missing = [
        f"{path.name}:{finding}"
        for path in sorted(VERSIONS.glob("*.py"))
        for finding in unquoted_names(path.read_text(encoding="utf-8"))
    ]
    assert missing == [], f"reserved on MySQL/MariaDB, needs quote=True: {missing}"


QUOTED_FORMS = {
    "a Column over several lines, quote=True on a later one": """
sa.Column(
    "vector",
    JSON_VALUE,
    nullable=False,
    quote=True,
)""",
    "a Column named by quoted_name": 'sa.Column(sa.sql.quoted_name("vector", True), JSON_VALUE)',
    "quoted_name with the keyword": 'sa.Column(quoted_name("vector", quote=True), JSON_VALUE)',
    "a Column named by keyword, quoted": 'sa.Column(name="vector", type_=JSON_VALUE, quote=True)',
    "a table created with quote=True": """
op.create_table(
    "vector",
    sa.Column("id", sa.String(40)),
    quote=True,
)""",
    "a rename to a quoted name": (
        'op.alter_column("t", "v", new_column_name=quoted_name("vector", True))'
    ),
    "a table rename to a quoted name": 'op.rename_table("t", quoted_name("vector", True))',
    "add_column's table is a table, its column the Column's": (
        'op.add_column("notification_position", sa.Column("vector", JSON_VALUE, quote=True))'
    ),
    "an ordinary name": 'sa.Column("body", sa.Text())',
}

UNQUOTED_FORMS = {
    "a Column over several lines": ('sa.Column(\n    "vector",\n    JSON_VALUE,\n)', "column"),
    "a Column named by keyword": ('sa.Column(name="vector", type_=JSON_VALUE)', "column"),
    "quote=True only in a comment": ('sa.Column("vector", JSON_VALUE),  # quote=True', "column"),
    "quoted_name without quote": ('sa.Column(quoted_name("vector", None), JSON_VALUE)', "column"),
    "a rename to the word": ('op.alter_column("t", "v", new_column_name="vector")', "column"),
    "an alter of the column": ('op.alter_column("t", "vector", nullable=True)', "column"),
    "an alter in a batch": ('batch_op.alter_column("vector", nullable=True)', "column"),
    "a drop of the column": ('op.drop_column("t", "vector")', "column"),
    "a table created under the word": ('op.create_table("vector", sa.Column("id", X))', "table"),
    "a table renamed to the word": ('op.rename_table("t", "vector")', "table"),
    "a column added to a table of the word": (
        'op.add_column("vector", sa.Column("x", X))',
        "table",
    ),
    "an index over the column": ('op.create_index("ix", "t", ["vector"])', "column"),
    "a column added on one line": (
        'op.add_column("notification_read", sa.Column("vector", sa.JSON(), nullable=True))',
        "column",
    ),
    "a column added in a batch": ('batch_op.add_column(sa.Column("vector", X))', "column"),
    "a single-quoted name": ("sa.Column('vector', JSON_VALUE)", "column"),
    "a lightweight table of the word": ('sa.table("vector", sa.column("id"))', "table"),
    "a lightweight column of the word": ('sa.table("t", sa.column("vector", X))', "column"),
    "an index in a batch": ('batch_op.create_index("ix", ["vector"])', "column"),
    "a quote=True on the call that renames": (
        'op.alter_column("t", "v", new_column_name="vector", quote=True)',
        "column",
    ),
}


@pytest.mark.parametrize("source", QUOTED_FORMS.values(), ids=QUOTED_FORMS.keys())
def test_a_quoted_form_passes(source: str) -> None:
    assert unquoted_names(source) == []


@pytest.mark.parametrize("source, what", UNQUOTED_FORMS.values(), ids=UNQUOTED_FORMS.keys())
def test_an_unquoted_form_is_found(source: str, what: str) -> None:
    assert [f.split(": ", 1)[1] for f in unquoted_names(source)] == [f"{what} vector"]


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
