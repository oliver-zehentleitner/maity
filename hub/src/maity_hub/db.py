"""Database access: one engine, SQLAlchemy Core tables, Alembic migrations."""

from __future__ import annotations

from importlib.resources import files
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, MetaData, create_engine, event

# Explicit constraint names, so that migrations can address constraints by
# name on every engine (MySQL and SQLite generate their own otherwise).
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_N_name)s",
        "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def make_engine(url: str) -> Engine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def alembic_config(engine: Engine) -> Config:
    config = Config()
    config.set_main_option("script_location", str(files("maity_hub") / "migrations"))
    config.attributes["engine"] = engine
    return config


def migrate(engine: Engine, revision: str = "head") -> None:
    command.upgrade(alembic_config(engine), revision)


def downgrade(engine: Engine, revision: str = "base") -> None:
    command.downgrade(alembic_config(engine), revision)


def head_revision(engine: Engine) -> str | None:
    return ScriptDirectory.from_config(alembic_config(engine)).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()
