"""Column types that behave the same on PostgreSQL, SQLite and MySQL/MariaDB."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, Dialect, Integer, Text
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.types import TypeDecorator, TypeEngine

# Microseconds on MySQL/MariaDB, whose DATETIME drops fractions by default.
TIMESTAMP_IMPL: TypeEngine[datetime] = DateTime().with_variant(
    mysql.DATETIME(fsp=6), "mysql", "mariadb"
)

# Markdown bodies are capped at 16 KiB characters (docs/api.md §1.7); MySQL's
# TEXT holds 64 KiB bytes, too little for 16 Ki four-byte characters.
MARKDOWN_TEXT: TypeEngine[str] = Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")

# JSON values. An absent value is SQL NULL, never the JSON literal `null`, so
# that `IS NULL` finds it; JSONB on PostgreSQL. MariaDB's JSON is a validated
# LONGTEXT, MySQL's a native type; SQLite stores text.
JSON_VALUE: TypeEngine[Any] = JSON(none_as_null=True).with_variant(
    postgresql.JSONB(none_as_null=True), "postgresql"
)


# Table options for the MySQL family: utf8mb4 whatever the server's default,
# and a binary collation, so that uniqueness and comparison are exact (case-
# and accent-sensitive) as they are on PostgreSQL and SQLite.
MYSQL_TABLE: dict[str, Any] = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_bin",
    # SQLAlchemy's MariaDB dialect reads its own prefix, not mysql_.
    "mariadb_charset": "utf8mb4",
    "mariadb_collate": "utf8mb4_bin",
}

# SQLite autoincrements only an INTEGER PRIMARY KEY.
BIG_ID: TypeEngine[int] = BigInteger().with_variant(Integer(), "sqlite")


class UtcDateTime(TypeDecorator[datetime]):
    """An aware UTC datetime in Python, a naive UTC timestamp in the database.

    Naive values are refused on the way in, so that no local time is ever
    stored by accident; values come back with `tzinfo=UTC`.
    """

    impl = TIMESTAMP_IMPL
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime: the hub stores UTC only")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(stamp, datetime):
            raise TypeError(f"expected a timestamp from the database, got {type(stamp).__name__}")
        return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)
