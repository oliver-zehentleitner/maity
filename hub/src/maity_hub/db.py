"""Database access: the engines, SQLAlchemy Core tables, Alembic migrations.

A serving hub has a sync engine (the routes in the thread pool, the background workers,
migrations) and, beside it on the same database, an async engine (`make_async_engine`) whose
connections drive the same sync `Connection` code through `AsyncConnection.run_sync`
(tsk-v874y63b4z8p, hub/context/persistence.md)."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import (
    URL,
    Connection,
    Engine,
    MetaData,
    create_engine,
    event,
    func,
    make_url,
    select,
)
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.util import await_only

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
APPLICATION_LISTENER = "maity-hub-listener"
# TCP keepalives of the listener's connection: a connection a NAT or the pod network drops
# silently is noticed after about a minute (30 s idle, then 3 probes 10 s apart), so the
# listener connects again instead of waiting for notices that never come.
LISTENER_KEEPALIVES = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 3,
}
# What the readiness probe may spend on the database: the connect timeout above and this long
# for its one statement (PostgreSQL's `statement_timeout`, the driver's `read_timeout` on
# MariaDB). It runs on a connection of its own, so a slow database answers 503 within about
# this long and does not hold the probe's request thread for the pool's wait.
HEALTH_STATEMENT_SECONDS = 5


def connect_once_more_on_dns[T](
    connect: Callable[..., T],
    args: Any,
    kwargs: Any,
    pause: Callable[[float], None] | None = None,
) -> T:
    """`connect(*args, **kwargs)`; if the host name does not resolve, once more after a short
    pause. Any other failure, and a second failure, go on to the caller as they are. `pause`
    sleeps, `time.sleep` when not given: the async engine's connect runs on the event loop, so
    it awaits there (`_pause_on_the_loop`) instead of stopping the loop."""
    try:
        return connect(*args, **kwargs)
    except Exception as error:
        if connection_cause(error) != "dns":
            raise
    log.warning("database host did not resolve; trying once more")
    (pause or time.sleep)(RESOLVE_PAUSE_SECONDS * (1 + random.random()))
    return connect(*args, **kwargs)


def _pause_on_the_loop(seconds: float) -> None:
    """`asyncio.sleep` from inside the async engine's connect: that code runs in SQLAlchemy's
    greenlet on the event loop, where `time.sleep` would stop every other request."""
    await_only(asyncio.sleep(seconds))


def postgres_options(*, statement: float = 0, idle_in_transaction: float = 0) -> str:
    """The `options` startup parameter of a PostgreSQL connection: the session time zone UTC,
    whatever the server's default (hub/context/persistence.md), and the two session timeouts
    in milliseconds, each left out when 0 (off)."""
    wanted = {
        "statement_timeout": statement,
        "idle_in_transaction_session_timeout": idle_in_transaction,
    }
    return " ".join(
        [
            "-c TimeZone=UTC",
            *(f"-c {name}={round(s * 1000)}" for name, s in wanted.items() if s > 0),
        ]
    )


def with_url_options(url: str | URL, options: str) -> str:
    """The hub's `options` after any the DATABASE_URL carries (`?options=-c search_path=…`):
    the driver takes the hub's value instead of the URL's, so the URL's would be lost, and
    with both the later `-c` wins, so the hub's time zone and timeouts still hold."""
    given = make_url(url).query.get("options")
    parts = [given] if isinstance(given, str) else list(given or ())
    return " ".join([*parts, options])


def _engine_options(
    url: str,
    pool_size: int,
    max_overflow: int,
    pool_recycle: int,
    statement_timeout: float,
    idle_in_transaction_timeout: float,
    application_name: str,
) -> dict[str, Any]:
    """The options of a serving engine, sync or async: one place, so the two engines of a hub
    cannot drift apart in isolation, timeouts, pool or names."""
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
            kwargs["connect_args"]["options"] = with_url_options(url, options)
        kwargs["pool_size"], kwargs["max_overflow"] = pool_size, max_overflow
        # Connections are kept and reused, the most recently used first, so that the few that
        # a quiet hub needs stay warm and the rest age out; a new connection is a name lookup
        # and a handshake (hub/context/persistence.md).
        kwargs["pool_use_lifo"] = True
        kwargs["pool_recycle"] = pool_recycle if pool_recycle > 0 else -1
    return kwargs


def _hook(engine: Engine, pause: Callable[[float], None] | None) -> None:
    """The connect and transaction events of a serving engine (for the async engine, its
    `sync_engine`): the DNS retry off SQLite, the pragmas and `BEGIN IMMEDIATE` on it."""
    if engine.dialect.name != "sqlite":

        @event.listens_for(engine, "do_connect")
        def _connect(dialect: Any, _record: Any, cargs: Any, cparams: Any) -> Any:
            return connect_once_more_on_dns(dialect.loaded_dbapi.connect, cargs, cparams, pause)

        return
    event.listen(engine, "connect", _sqlite_pragmas)
    event.listen(engine, "begin", _sqlite_begin_immediate)


def make_engine(
    url: str,
    pool_size: int = 16,
    max_overflow: int = 16,
    pool_recycle: int = POOL_RECYCLE_SECONDS,
    statement_timeout: float = 0,
    idle_in_transaction_timeout: float = 0,
    application_name: str = APPLICATION_COMMAND,
) -> Engine:
    engine = create_engine(
        url,
        **_engine_options(
            url,
            pool_size,
            max_overflow,
            pool_recycle,
            statement_timeout,
            idle_in_transaction_timeout,
            application_name,
        ),
    )
    _hook(engine, None)
    return engine


# The async driver of each sync one the hub ships with (`config._DRIVERS`): psycopg 3 drives
# both; aiomysql is built on PyMySQL, so the error numbers the hub reads (1213, 1305) stay the
# same; aiosqlite runs the standard library's sqlite3 in a thread of its own.
ASYNC_DRIVERS = {
    "postgresql+psycopg": "postgresql+psycopg_async",
    "mysql+pymysql": "mysql+aiomysql",
    "mariadb+pymysql": "mariadb+aiomysql",
    "sqlite": "sqlite+aiosqlite",
    "sqlite+pysqlite": "sqlite+aiosqlite",
}


def async_url(url: str | URL) -> URL:
    """The URL of the async engine on the same database: the same everything, the async
    driver. A driver the hub does not ship with is refused rather than guessed."""
    parsed = make_url(url)
    driver = ASYNC_DRIVERS.get(parsed.drivername)
    if driver is None:
        raise ValueError(f"no async driver for {parsed.drivername}")
    return parsed.set(drivername=driver)


def make_async_engine(
    url: str | URL,
    pool_size: int = 2,
    pool_recycle: int = POOL_RECYCLE_SECONDS,
    statement_timeout: float = 0,
    idle_in_transaction_timeout: float = 0,
    application_name: str = APPLICATION_SERVING,
) -> AsyncEngine:
    """The async engine beside a serving engine (`make_engine`): the same options, the async
    driver (`async_url`), a pool of its own carved out of the hub's (`serving.pool_shares`)
    and no overflow, which stays with the sync engine. Its events hang on `sync_engine`, where
    SQLAlchemy runs them; `write_guard` and `timing` install there too."""
    target = async_url(url)
    rendered = target.render_as_string(hide_password=False)
    kwargs = _engine_options(
        rendered,
        pool_size,
        0,
        pool_recycle,
        statement_timeout,
        idle_in_transaction_timeout,
        application_name,
    )
    if target.get_backend_name() == "sqlite":
        # aiosqlite runs each connection in a thread of its own: SQLite's same-thread check
        # does not apply, and the driver does not take the option.
        kwargs.pop("connect_args", None)
    engine = create_async_engine(target, **kwargs)
    _hook(engine.sync_engine, _pause_on_the_loop)
    return engine


SHARED_POOL_SIZE = 2

# One shared-counter engine per process, database, timeouts and recycle age. `shared_counts` and
# `shared_budget` hold only the engine configured last, so an engine per app would leave every
# earlier app's pool holding its connections until that app stops; a process that builds many
# apps (the tests do, one per client) would run the database out of connection slots. The
# process id keeps a forked worker from reusing its parent's sockets.
_shared_engines: dict[tuple[int, str, float, float, int], Engine] = {}
# Two first calls at once would otherwise each build an engine, and the one left out of the
# cache would hold its own connections until its app stops.
_shared_engines_lock = threading.Lock()


def make_shared_engine(
    engine: Engine,
    *,
    statement_timeout: float = 0,
    idle_in_transaction_timeout: float = 0,
    pool_recycle: int = POOL_RECYCLE_SECONDS,
) -> Engine | None:
    """Short counter/budget transactions must not wait for a request's pool connection.
    No extra engine off PostgreSQL: those backends keep their counters in the process. The
    same engine for every app of this process on this database (above), under a lock, so two
    first calls at once build one; disposing it at an
    app's stop only closes its idle connections, and it opens new ones when next used."""
    if engine.dialect.name != "postgresql":
        return None
    url = engine.url.render_as_string(hide_password=False)
    key = (
        os.getpid(),
        url,
        float(statement_timeout),
        float(idle_in_transaction_timeout),
        int(pool_recycle),
    )
    with _shared_engines_lock:
        shared = _shared_engines.get(key)
        if shared is None:
            shared = _shared_engines[key] = make_engine(
                url,
                pool_size=SHARED_POOL_SIZE,
                max_overflow=0,
                pool_recycle=pool_recycle,
                statement_timeout=statement_timeout,
                idle_in_transaction_timeout=idle_in_transaction_timeout,
                application_name="maity-shared",
            )
    return shared


def make_listener_engine(url: str) -> Engine:
    """An engine for the wake-up listener alone (`wakeups`): PostgreSQL, no pool, no statement
    timeout, as its one connection waits in `LISTEN` for as long as it lives."""
    engine = create_engine(
        url,
        poolclass=NullPool,
        hide_parameters=True,
        connect_args={
            "connect_timeout": CONNECT_TIMEOUT_SECONDS,
            "application_name": APPLICATION_LISTENER,
            **LISTENER_KEEPALIVES,
        },
    )

    @event.listens_for(engine, "do_connect")
    def _connect(dialect: Any, _record: Any, cargs: Any, cparams: Any) -> Any:
        return connect_once_more_on_dns(dialect.loaded_dbapi.connect, cargs, cparams)

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
        kwargs["connect_args"]["options"] = with_url_options(
            engine.url, postgres_options(statement=HEALTH_STATEMENT_SECONDS)
        )
        kwargs["connect_args"]["application_name"] = APPLICATION_HEALTH
    elif engine.dialect.name in ("mysql", "mariadb"):
        # No server-side statement timeout to set per session here: the driver stops waiting.
        kwargs["connect_args"]["read_timeout"] = HEALTH_STATEMENT_SECONDS
    health = create_engine(engine.url, **kwargs)

    @event.listens_for(health, "do_connect")
    def _connect(dialect: Any, _record: Any, cargs: Any, cparams: Any) -> Any:
        return connect_once_more_on_dns(dialect.loaded_dbapi.connect, cargs, cparams)

    return health


def xact_lock(conn: Connection, name: str) -> None:
    """Hold `name` until the transaction ends, against other processes and pods doing the same
    (PostgreSQL's transaction-level advisory lock: it works behind PgBouncer in any mode). Off
    PostgreSQL a no-op: SQLite writes one transaction at a time, and MariaDB runs one process."""
    if conn.dialect.name == "postgresql":
        conn.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(name, 0))))


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


# `maity-hub migrate` on PostgreSQL runs while the hub serves: the chain is one transaction that
# meets the hub's own (hub/context/persistence.md). A deadlock (40P01) or a lock not had within
# MIGRATE_LOCK_TIMEOUT (55P03) rolled all of it back, and it is run again from the start.
MIGRATE_LOCK_TIMEOUT = 5.0
MIGRATE_ATTEMPTS = 5
MIGRATE_PAUSE = 1.0
MIGRATE_AGAIN = {"40P01", "55P03"}


def migrate(
    engine: Engine,
    revision: str = "head",
    *,
    lock_timeout: float = MIGRATE_LOCK_TIMEOUT,
    attempts: int = MIGRATE_ATTEMPTS,
    pause: float = MIGRATE_PAUSE,
) -> None:
    from maity_hub.errors import driver_code, driver_fields

    config = alembic_config(engine)
    config.attributes["lock_timeout"] = lock_timeout
    for attempt in range(attempts):
        try:
            command.upgrade(config, revision)
            return
        except DBAPIError as error:
            again = engine.dialect.name == "postgresql" and driver_code(error) in MIGRATE_AGAIN
            if not again or attempt == attempts - 1:
                raise
            log.warning(
                "migrate retry: attempt=%d of=%d %s", attempt + 1, attempts, driver_fields(error)
            )
            time.sleep(pause * 2**attempt)


def downgrade(engine: Engine, revision: str = "base") -> None:
    command.downgrade(alembic_config(engine), revision)


def head_revision(engine: Engine) -> str | None:
    return ScriptDirectory.from_config(alembic_config(engine)).get_current_head()


def current_revision(engine: Engine) -> str | None:
    """The database's revision; connecting at all proves it is reachable."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


# `alembic_version.version_num` is 32 characters wide on every engine.
REVISION_ID_MAX = 32


def revision_id(message: str, now: datetime) -> str:
    """A revision id no parallel branch takes too: the UTC time to the second and the
    message's slug, `20261030102512_add_the_task_table`, cut to the version column."""
    slug = re.sub(r"[^a-z0-9]+", "_", message.lower()).strip("_") or "revision"
    return f"{now.astimezone(UTC):%Y%m%d%H%M%S}_{slug}"[:REVISION_ID_MAX].rstrip("_")


def create_revision(
    engine: Engine, message: str, script_location: Path | None = None, now: datetime | None = None
) -> Path:
    """Autogenerate a revision against a database at head, its id from `revision_id` and
    its file named by the id alone. `tools/rechain.py` later hangs it on main's head.

    Development only: `make revision m="..."` runs it on a scratch SQLite file.
    """
    config = alembic_config(engine, script_location)
    config.set_main_option("file_template", "%%(rev)s")  # the id holds the slug
    rev_id = revision_id(message, now or datetime.now(UTC))
    command.upgrade(config, "head")
    created = command.revision(config, message=message, autogenerate=True, rev_id=rev_id)
    if created is None or isinstance(created, list):
        raise RuntimeError("alembic did not create exactly one revision")
    return Path(created.path)


# Deadlock and serialisation failures: the database rolled the transaction back
# and expects it to be run again. InnoDB reports them under ordinary
# concurrency (two calls of one agent touching its credential and cards).
TRANSIENT = {"40001", "40P01", "1213"}
# A deadlock inside a savepoint on InnoDB takes the savepoint with it, and rolling back to it fails
# with this in place of the deadlock, which stays behind it in the exception's context. Only then is
# it run again: without a deadlock behind it, a lost savepoint is a bug.
SAVEPOINT_GONE = 1305
RETRIES = 4


def is_transient(error: BaseException) -> bool:
    from maity_hub.errors import driver_code, driver_number, errors_behind

    if not isinstance(error, OperationalError | DBAPIError):
        return False
    if driver_code(error) in TRANSIENT:
        return True
    return driver_number(error) == SAVEPOINT_GONE and any(
        driver_code(behind) in TRANSIENT for behind in errors_behind(error)
    )


def _again_after(error: DBAPIError, attempt: int) -> float:
    """The pause before the next attempt of `retrying` or `retrying_async`, logged; or the error
    raised again when it is not transient or the attempts are used up."""
    from maity_hub.errors import driver_fields

    if not is_transient(error) or attempt == RETRIES - 1:
        raise error
    log.warning(
        "database retry: attempt=%d of=%d %s",
        attempt + 1,
        RETRIES,
        driver_fields(error),
    )
    return float(0.01 * (2**attempt) * (1 + random.random()))


def retrying[T](work: Callable[[], T]) -> T:
    """Run `work` (one whole transaction) again after a transient conflict. Each repeat logs a
    line with the driver's codes and nothing of the statement, so a load test can count them."""
    for attempt in range(RETRIES):
        try:
            return work()
        except DBAPIError as error:
            time.sleep(_again_after(error, attempt))
    raise RuntimeError("unreachable")


async def retrying_async[T](work: Callable[[], Awaitable[T]]) -> T:
    """`retrying` for a transaction on the async engine: the same attempts, codes and log
    lines; the pause awaits, so the event loop serves other requests meanwhile."""
    for attempt in range(RETRIES):
        try:
            return await work()
        except DBAPIError as error:
            await asyncio.sleep(_again_after(error, attempt))
    raise RuntimeError("unreachable")
