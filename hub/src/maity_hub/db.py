"""Database access: one engine, SQLAlchemy Core tables, Alembic migrations."""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
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


CONNECT_TIMEOUT_SECONDS = 5


def make_engine(url: str) -> Engine:
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # Fail fast on an unreachable server instead of waiting for TCP's own timeout.
        kwargs["connect_args"] = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def alembic_config(engine: Engine, script_location: Path | None = None) -> Config:
    config = Config()
    location = script_location or Path(str(files("maity_hub") / "migrations"))
    config.set_main_option("script_location", str(location))
    config.set_main_option("file_template", "%%(rev)s_%%(slug)s")
    config.attributes["engine"] = engine
    return config


def migrate(engine: Engine, revision: str = "head") -> None:
    command.upgrade(alembic_config(engine), revision)


def downgrade(engine: Engine, revision: str = "base") -> None:
    command.downgrade(alembic_config(engine), revision)


def head_revision(engine: Engine) -> str | None:
    return ScriptDirectory.from_config(alembic_config(engine)).get_current_head()


def current_revision(engine: Engine) -> str | None:
    """The database's revision; connecting at all proves it is reachable."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def create_revision(engine: Engine, message: str, script_location: Path | None = None) -> Path:
    """Autogenerate the next numbered revision against a database at head.

    Development only: `make revision m="..."` runs it on a scratch SQLite file.
    """
    config = alembic_config(engine, script_location)
    script = ScriptDirectory.from_config(config)
    numbers = [int(rev.revision) for rev in script.walk_revisions() if rev.revision.isdigit()]
    rev_id = f"{max(numbers, default=0) + 1:04d}"
    command.upgrade(config, "head")
    created = command.revision(config, message=message, autogenerate=True, rev_id=rev_id)
    if created is None or isinstance(created, list):
        raise RuntimeError("alembic did not create exactly one revision")
    return Path(created.path)
