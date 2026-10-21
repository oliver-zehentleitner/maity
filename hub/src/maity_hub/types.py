"""Column types that behave the same on PostgreSQL, SQLite and MySQL/MariaDB."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Dialect, Integer, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.types import TypeDecorator, TypeEngine

# Microseconds on MySQL/MariaDB, whose DATETIME drops fractions by default.
TIMESTAMP_IMPL: TypeEngine[datetime] = DateTime().with_variant(
    mysql.DATETIME(fsp=6), "mysql", "mariadb"
)

# Markdown bodies are capped at 16 KiB characters (docs/api.md §1.7); MySQL's
# TEXT holds 64 KiB bytes, too little for 16 Ki four-byte characters.
MARKDOWN_TEXT: TypeEngine[str] = Text().with_variant(mysql.MEDIUMTEXT(), "mysql", "mariadb")

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
