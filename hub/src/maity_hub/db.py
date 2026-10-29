"""Database access: one engine, SQLAlchemy Core tables, Alembic migrations."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, MetaData, create_engine, event
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.pool import NullPool

from maity_hub.errors import connection_cause

log = logging.getLogger(__name__)

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
# A name that did not resolve is tried once more after this pause (and as much again, at
# random): the cluster's DNS answers in bursts and a second try mostly gets through.
RESOLVE_PAUSE_SECONDS = 0.25
# A pooled connection older than this is replaced when it is next taken (30 minutes): it bounds the
# age of a connection, whatever sits between the hub and the server. A dead one is found by
# `pool_pre_ping`, which tests every connection as it is taken.
POOL_RECYCLE_SECONDS = 1800
# What a PostgreSQL connection says it is in `pg_stat_activity.application_name`: the serving
# hub, its readiness probe, and every other command (`migrate`, `owner create`, ...).
APPLICATION_SERVING = "maity-hub"
APPLICATION_HEALTH = "maity-hub-health"
APPLICATION_COMMAND = "maity-hub-cli"
# What the readiness probe may spend on the database: the connect timeout above and this long
# for its one statement (PostgreSQL's `statement_timeout`, the driver's `read_timeout` on
# MariaDB). It runs on a connection of its own, so a slow database answers 503 within about
# this long and does not hold the probe's request thread for the pool's wait.
HEALTH_STATEMENT_SECONDS = 5


def connect_once_more_on_dns[T](connect: Callable[..., T], args: Any, kwargs: Any) -> T:
    """`connect(*args, **kwargs)`; if the host name does not resolve, once more after a short
    pause. Any other failure, and a second failure, go on to the caller as they are."""
    try:
        return connect(*args, **kwargs)
    except Exception as error:
        if connection_cause(error) != "dns":
            raise
    log.warning("database host did not resolve; trying once more")
    time.sleep(RESOLVE_PAUSE_SECONDS * (1 + random.random()))
    return connect(*args, **kwargs)


def postgres_options(*, statement: float = 0, idle_in_transaction: float = 0) -> str:
    """The `options` startup parameter that sets the two session timeouts of a PostgreSQL
    connection, in milliseconds; empty when both are 0 (off)."""
    wanted = {
        "statement_timeout": statement,
        "idle_in_transaction_session_timeout": idle_in_transaction,
    }
    return " ".join(
        f"-c {name}={round(seconds * 1000)}" for name, seconds in wanted.items() if seconds > 0
    )


def make_engine(
    url: str,
    pool_size: int = 16,
    max_overflow: int = 16,
    pool_recycle: int = POOL_RECYCLE_SECONDS,
    statement_timeout: float = 0,
    idle_in_transaction_timeout: float = 0,
    application_name: str = APPLICATION_COMMAND,
) -> Engine:
    # hide_parameters: a failing statement's error never carries the values.
    kwargs: dict[str, Any] = {"pool_pre_ping": True, "hide_parameters": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        # READ COMMITTED on every server engine, PostgreSQL's default: after a
        # writer waited for the project lock, its reads see what the writer
        # before it committed. InnoDB's default REPEATABLE READ would keep the
        # snapshot of the first read (hub/context/persistence.md).
        kwargs["isolation_level"] = "READ COMMITTED"
        # Fail fast on an unreachable server instead of waiting for TCP's own timeout.
        kwargs["connect_args"] = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
        # Per connection, not per role: the hub sets them for its own sessions only, and
        # `maity-hub migrate` and the CLI commands, which take no timeouts, run unbounded.
        options = postgres_options(
            statement=statement_timeout, idle_in_transaction=idle_in_transaction_timeout
        )
        if url.startswith("postgresql"):
            kwargs["connect_args"]["application_name"] = application_name
            if options:
                kwargs["connect_args"]["options"] = options
        kwargs["pool_size"], kwargs["max_overflow"] = pool_size, max_overflow
        # Connections are kept and reused, the most recently used first, so that the few that
        # a quiet hub needs stay warm and the rest age out; a new connection is a name lookup
        # and a handshake (hub/context/persistence.md).
        kwargs["pool_use_lifo"] = True
        kwargs["pool_recycle"] = pool_recycle if pool_recycle > 0 else -1
    engine = create_engine(url, **kwargs)
    if not url.startswith("sqlite"):

        @event.listens_for(engine, "do_connect")
        def _connect(dialect: Any, _record: Any, cargs: Any, cparams: Any) -> Any:
            return connect_once_more_on_dns(dialect.loaded_dbapi.connect, cargs, cparams)

    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_pragmas)
        event.listen(engine, "begin", _sqlite_begin_immediate)
    return engine


def make_health_engine(engine: Engine) -> Engine | None:
    """An engine for the readiness probe alone: the same database, no pool (a connection per
    check, closed after it) and a short statement timeout. None for SQLite, where there is
    no pool wait to escape and a second engine could be a second, empty database."""
    if engine.dialect.name == "sqlite":
        return None
    kwargs: dict[str, Any] = {
        "poolclass": NullPool,
        "hide_parameters": True,
        "connect_args": {"connect_timeout": CONNECT_TIMEOUT_SECONDS},
    }
    if engine.dialect.name == "postgresql":
        kwargs["connect_args"]["options"] = postgres_options(statement=HEALTH_STATEMENT_SECONDS)
        kwargs["connect_args"]["application_name"] = APPLICATION_HEALTH
    elif engine.dialect.name in ("mysql", "mariadb"):
        # No server-side statement timeout to set per session here: the driver stops waiting.
        kwargs["connect_args"]["read_timeout"] = HEALTH_STATEMENT_SECONDS
    health = create_engine(engine.url, **kwargs)

    @event.listens_for(health, "do_connect")
    def _connect(dialect: Any, _record: Any, cargs: Any, cparams: Any) -> Any:
        return connect_once_more_on_dns(dialect.loaded_dbapi.connect, cargs, cparams)

    return health


def _sqlite_begin_immediate(conn: Any) -> None:
    """Every SQLite transaction takes the write lock at its start.

    pysqlite would send BEGIN only at the first write, so the reads before it
    ran unlocked, and `events.lock_project` serialised nothing; a transaction
    that read first could not even upgrade to a write once another had
    committed. SQLite has one writer anyway; this makes the hub wait for it
    where the other engines wait for the project row.
    """
    conn.exec_driver_sql("BEGIN IMMEDIATE")


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    # The driver's own transaction handling off: SQLAlchemy's begin event
    # issues BEGIN IMMEDIATE instead (_sqlite_begin_immediate).
    dbapi_connection.isolation_level = None
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    # Readers do not block the writer and the writer waits instead of failing
    # (hub/context/persistence.md); WAL needs a file, not :memory:.
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA journal_mode")
    if cursor.fetchone()[0] != "memory":
        cursor.execute("PRAGMA journal_mode=WAL")
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


# Deadlock and serialisation failures: the database rolled the transaction back
# and expects it to be run again. InnoDB reports them under ordinary
# concurrency (two calls of one agent touching its credential and cards).
TRANSIENT = {"40001", "40P01", "1213", "1205"}
RETRIES = 4


def is_transient(error: BaseException) -> bool:
    from maity_hub.errors import driver_code

    return isinstance(error, OperationalError | DBAPIError) and driver_code(error) in TRANSIENT


def retrying[T](work: Callable[[], T]) -> T:
    """Run `work` (one whole transaction) again after a transient conflict."""
    for attempt in range(RETRIES):
        try:
            return work()
        except DBAPIError as error:
            if not is_transient(error) or attempt == RETRIES - 1:
                raise
            time.sleep(0.01 * (2**attempt) * (1 + random.random()))
    raise RuntimeError("unreachable")
