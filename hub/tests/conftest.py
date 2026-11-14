"""Fixtures. `MAITY_TEST_DATABASE_URL` points the suite at PostgreSQL or
MariaDB; without it every test gets its own SQLite file. Under pytest-xdist each
worker gets a database of its own on that server (`<name>_gw0`, `<name>_gw1`, …),
created through `MAITY_TEST_ADMIN_DATABASE_URL` (default: the same URL).
`MAITY_TEST_SHARD=<k>/<n>` runs only the test files of shard k of n
(`pytest_collection_modifyitems`)."""

from __future__ import annotations

import os
import re
import shutil
import sys
import zlib
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, OperationalError

from maity_hub.app import create_app
from maity_hub.config import Settings, normalize_database_url
from maity_hub.db import current_revision, downgrade, head_revision, make_engine, migrate
from maity_hub.ratelimit import Limiter


def _shard() -> tuple[int, int] | None:
    """`MAITY_TEST_SHARD` as (k, n), 1 <= k <= n; unset or empty for the whole suite. Any other
    value stops the run: a typo must not run a share of the suite and look green."""
    raw = os.environ.get("MAITY_TEST_SHARD", "").strip()
    if not raw:
        return None
    # ASCII digits only, four at most: str.isdigit also takes "²", which int() refuses, and
    # int() refuses more than 4300 digits (review of #1625).
    match = re.fullmatch(r"([0-9]{1,4})/([0-9]{1,4})", raw)
    if not match or not 1 <= int(match[1]) <= int(match[2]):
        raise pytest.UsageError(
            f"MAITY_TEST_SHARD must be <k>/<n>, at most four ASCII digits a side,"
            f" with 1 <= k <= n, not {raw!r}"
        )
    return int(match[1]), int(match[2])


def pytest_configure(config: pytest.Config) -> None:
    _shard()  # a bad MAITY_TEST_SHARD stops the run before collection, with a usage error


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """One shard of the suite, by test file: a file's tests stay in one shard, so its
    module-scoped fixtures start in that shard only (in it, once per xdist worker that runs some
    of the file's tests, as without shards; the session fixtures start once per worker in every
    shard). The file
    path's CRC-32 picks the shard, the same on every run and machine, so each file runs in
    exactly one shard and the shards together run the whole suite (CI's `hub-postgresql`)."""
    shard = _shard()
    if shard is None:
        return
    k, n = shard
    keep: list[pytest.Item] = []
    drop: list[pytest.Item] = []
    for item in items:
        path = item.nodeid.split("::", 1)[0]
        (keep if zlib.crc32(path.encode()) % n == k - 1 else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep


TEST_TZ = "Europe/Vienna"  # the PostgreSQL test databases' default time zone, never UTC


@pytest.fixture(scope="session")
def _server_database_url(worker_id: str) -> str | None:
    """The PostgreSQL or MariaDB database this process runs against, or None for SQLite.
    A parallel worker gets its own database next to the configured one, so the workers
    never see each other's tables."""
    configured = os.environ.get("MAITY_TEST_DATABASE_URL")
    if not configured:
        return None
    url = make_url(normalize_database_url(configured))
    name = url.database if worker_id == "master" else f"{url.database}_{worker_id}"
    admin_configured = os.environ.get("MAITY_TEST_ADMIN_DATABASE_URL", configured)
    admin_url = make_url(normalize_database_url(admin_configured))
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            if url.get_backend_name() == "postgresql":
                exists = connection.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": name}
                ).first()
                if not exists:
                    connection.execute(text(f'CREATE DATABASE "{name}"'))
                # A server default other than UTC, as on a host in Vienna: the hub's times must
                # not depend on it (hub/context/persistence.md).
                connection.execute(text(f"ALTER DATABASE \"{name}\" SET timezone TO '{TEST_TZ}'"))
            elif worker_id != "master":
                connection.execute(text(f"CREATE DATABASE IF NOT EXISTS `{name}`"))
                if admin_url.username != url.username:
                    connection.execute(text(f"GRANT ALL ON `{name}`.* TO '{url.username}'@'%'"))
    finally:
        admin.dispose()
    return url.set(database=name).render_as_string(hide_password=False)


@pytest.fixture
def database_url(tmp_path: Path, _server_database_url: str | None) -> str:
    return _server_database_url or f"sqlite:///{tmp_path / 'hub.db'}"


@pytest.fixture(autouse=True)
def _no_background_mail(monkeypatch: pytest.MonkeyPatch) -> None:
    """The app's mail worker would send the outbox behind a test's back; tests drive
    `outbox.send_due` themselves."""
    from maity_hub.mail import outbox
    from maity_hub.notifications import mailer

    monkeypatch.setattr(outbox.Worker, "start", lambda self: None)
    monkeypatch.setattr(mailer.Worker, "start", lambda self: None)


@pytest.fixture(scope="session")
def _migrated_sqlite_file(
    tmp_path_factory: pytest.TempPathFactory, _server_database_url: str | None
) -> Path | None:
    """SQLite only: the schema at head, migrated once per process and copied into each
    test that wants a migrated database, instead of replaying every revision again."""
    if _server_database_url:
        return None
    template = tmp_path_factory.mktemp("template") / "hub.db"
    template_engine = make_engine(f"sqlite:///{template}")
    migrate(template_engine)
    template_engine.dispose()
    return template


@pytest.fixture(scope="session", autouse=True)
def _leave_the_server_database_empty(_server_database_url: str | None) -> Iterator[None]:
    """A server database is shared with whoever runs next: after the session it is empty
    again, as every test used to leave it."""
    yield
    if _server_database_url:
        engine = make_engine(_server_database_url)
        _downgrade_emptied(engine)
        engine.dispose()


def _downgrade_emptied(engine: Engine) -> None:
    """Down to no schema on a server database. The rows first: a downgrade refuses what the
    last test left behind, such as a project an organisation owns (below 0089), and which test
    ran last on a worker is chance."""
    if current_revision(engine) is not None:
        _empty_the_tables(engine)
    downgrade(engine)


TRUNCATE_LOCK_TIMEOUT = "60s"
LOCK_NOT_AVAILABLE = "55P03"  # PostgreSQL's SQLSTATE for a lock timeout


class LeakedConnection(RuntimeError):
    """A connection a test left in a transaction held locks the cleanup between tests needs."""


def _empty_the_tables(engine: Engine) -> None:
    """Delete every row of a server database at head, keeping the schema and the revision.

    On PostgreSQL a connection a test left in a transaction holds its locks, and the TRUNCATE
    waited for them without end (tsk-xz3bxa5cwv4v). It now gives up after
    `TRUNCATE_LOCK_TIMEOUT`; the suite's own sessions that hold a lock on the tables it empties
    or on a sequence they own are named and ended, so this one test fails and the next one runs
    (hub/context/testing.md 210f3def). The test database is the suite's alone (hub/README.md)."""
    tables = [t for t in inspect(engine).get_table_names() if t != "alembic_version"]
    try:
        _truncate(engine, tables)
    except OperationalError as error:
        if getattr(error.orig, "sqlstate", None) != LOCK_NOT_AVAILABLE:
            raise
        holders = _end_the_lock_holders(engine, _relations(engine, tables))
        found = (
            f"ended so the next test runs (unless named otherwise): {holders}"
            if holders
            else "no session of this suite holds them: another role's, or a lock outside the"
            " emptied tables and their sequences, so the next cleanup may wait again"
        )
        raise LeakedConnection(
            f"the cleanup before this test waited {TRUNCATE_LOCK_TIMEOUT} for locks a connection"
            f" left in a transaction held; {found}"
        ) from error


def _relations(engine: Engine, tables: list[str]) -> list[int]:
    """The ids (`oid`) of the relations the TRUNCATE empties, and of the sequences they own (a
    `serial` or identity column), which `RESTART IDENTITY` locks too: a session that only drew a
    number holds the TRUNCATE up as well (pmwg and dzse at #1289). Each name is resolved as the
    TRUNCATE resolves it, quoted and through `search_path` (`to_regclass`), not in
    `current_schema()` alone, where a table found further along the path is missed."""
    with engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "WITH emptied AS ("
                    " SELECT to_regclass(quote_ident(n))::oid AS oid"
                    " FROM unnest(CAST(:names AS text[])) AS n)"
                    " SELECT oid FROM emptied WHERE oid IS NOT NULL"
                    " UNION"
                    " SELECT d.objid FROM pg_depend d JOIN pg_class s ON s.oid = d.objid"
                    " WHERE d.classid = 'pg_class'::regclass"
                    " AND d.refclassid = 'pg_class'::regclass AND d.deptype IN ('a', 'i')"
                    " AND s.relkind = 'S' AND d.refobjid IN (SELECT oid FROM emptied)"
                ),
                {"names": tables},
            ).scalars()
        )


def _end_the_lock_holders(engine: Engine, relations: list[int]) -> list[str]:
    """The sessions that hold a lock on one of `relations` in this database: client sessions
    of this role only, other than this one, so neither another database's nor another role's
    session is touched. Each is named with its state and last statement, then ended; one that
    cannot be ended is named with the reason, and the others are still ended."""
    named: list[str] = []
    with engine.connect() as conn:
        conn.execution_options(isolation_level="AUTOCOMMIT")  # one refusal aborts no other
        rows = conn.execute(
            text(
                "SELECT DISTINCT a.pid, a.state, left(a.query, 200) AS query"
                " FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
                " WHERE l.granted AND l.relation = ANY(CAST(:relations AS oid[]))"
                " AND l.database = (SELECT oid FROM pg_database WHERE datname = current_database())"
                " AND a.datname = current_database() AND a.usename = current_user"
                " AND a.backend_type = 'client backend' AND a.pid <> pg_backend_pid()"
            ),
            {"relations": relations},
        ).all()
        for row in rows:
            holder = f"pid {row.pid} ({row.state}): {row.query}"
            try:
                conn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": row.pid})
            except DBAPIError as error:
                holder += f" (not ended: {error.orig})"
            named.append(holder)
    return named


def _truncate(engine: Engine, tables: list[str]) -> None:
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text(f"SET LOCAL lock_timeout = '{TRUNCATE_LOCK_TIMEOUT}'"))
            quoted = ", ".join(f'"{t}"' for t in tables)
            connection.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
            if "nonce_epoch" in tables:
                # The nonces known since long before the test (auth.nonces): a test signs no
                # request in the second the epoch would otherwise be set in.
                connection.execute(
                    text(
                        "INSERT INTO nonce_epoch (id, since) "
                        "VALUES (1, (now() AT TIME ZONE 'utc') - interval '1 hour')"
                    )
                )
        else:
            connection.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for table in tables:
                connection.execute(text(f"TRUNCATE TABLE `{table}`"))
            connection.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


@pytest.fixture
def engine(database_url: str, request: pytest.FixtureRequest) -> Iterator[Engine]:
    """An empty schema; for a test that also asks for `migrated` or `client`, the schema at
    head with no rows. On a server database that second state is kept from one test to the
    next and only emptied, because replaying every revision per test is what made the suite
    take an hour; a test that needs no schema gets it downgraded."""
    engine = make_engine(database_url)
    on_server = engine.dialect.name != "sqlite"
    keeps_schema = on_server and bool({"migrated", "client"} & set(request.fixturenames))
    if keeps_schema:
        if current_revision(engine) == head_revision(engine):
            _empty_the_tables(engine)
        else:
            _downgrade_emptied(engine)  # a shared server database may hold a previous run's schema
            migrate(engine)
            # The same rows as after any other test: the migration's nonce epoch is now, and a
            # request signed a few seconds back would fall before it (auth.nonces).
            _empty_the_tables(engine)
    elif on_server:
        _downgrade_emptied(engine)
    else:
        downgrade(engine)
    yield engine
    if on_server and not keeps_schema:
        _downgrade_emptied(engine)
    engine.dispose()


def migrate_fast(engine: Engine, template: Path | None) -> None:
    """`migrate`, except that an empty SQLite file is replaced by the template. The engine
    stays the same object; its pooled connections are dropped so the next one opens the copy."""
    if template is None or engine.dialect.name != "sqlite" or engine.url.database is None:
        migrate(engine)
        return
    engine.dispose()
    shutil.copyfile(template, engine.url.database)


@pytest.fixture
def web_dir(tmp_path: Path) -> Path:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text(
        '<!doctype html><html><head><meta charset="utf-8"><title>dashboard</title></head>'
        '<body><script src="js/app.js"></script></body></html>'
    )
    return web


@pytest.fixture
def settings(database_url: str, web_dir: Path) -> Settings:
    return Settings.from_env(
        {
            "MAITY_DATABASE_URL": database_url,
            "MAITY_PUBLIC_URL": "https://hub.example",
            "MAITY_WEB_DIR": str(web_dir),
        }
    )


@pytest.fixture
def client(
    settings: Settings, engine: Engine, _migrated_sqlite_file: Path | None
) -> Iterator[TestClient]:
    migrate_fast(engine, _migrated_sqlite_file)
    with TestClient(create_app(settings, engine)) as client:
        yield client


@pytest.fixture(autouse=True)
def _no_forge_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test ever reaches the real forge, whatever token a test sets."""
    from maity_hub import forge

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise forge.ForgeUnavailableError("no network in tests")

    monkeypatch.setattr(forge._opener, "open", refuse)


@pytest.fixture(autouse=True)
def _no_outbound_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nor does any read under §11.1: resolution and connection both refuse unless a
    test puts its own fakes in their place."""
    from maity_hub import outbound

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise outbound.Refused("unavailable")

    monkeypatch.setattr(outbound, "resolver", refuse)
    monkeypatch.setattr(outbound, "connector", refuse)


@pytest.fixture(autouse=True)
def _no_held_instance_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hub started with `MAITY_FORGE_INSTANCE_NAMESPACES` holds its names process-wide
    (§11.4); the next test starts with none held."""
    from maity_hub import handles

    monkeypatch.setattr(handles, "_instance_names", frozenset())


@pytest.fixture(autouse=True)
def _no_background_ktw_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """A project view schedules a Keep the Why read in the background; in tests that
    would race the next test's cache. Tests of the scheduling replace this themselves."""
    from maity_hub import ktw

    monkeypatch.setattr(ktw, "_refresh_later", lambda *args: None)


def process_limiters() -> Iterator[Limiter]:
    """Every limiter a module of the hub holds, as a module attribute or one attribute further
    down (`routes.email_sign_in.LIMITS`, a `RequestLimits` of three): found rather than listed,
    so a new limit is reset between tests without a line of its own (tsk-knmx8yw3s1xa, where
    the sign-in link's pair limit leaked and a fourth link of the suite sent no mail)."""
    for name, module in list(sys.modules.items()):
        if module is None or not (name == "maity_hub" or name.startswith("maity_hub.")):
            continue
        for value in list(vars(module).values()):
            if isinstance(value, Limiter):
                yield value
            elif not isinstance(value, type) and type(value).__module__.startswith("maity_hub."):
                for inner in list(getattr(value, "__dict__", {}).values()):
                    if isinstance(inner, Limiter):
                        yield inner


@pytest.fixture(autouse=True)
def _fresh_process_state() -> Iterator[None]:
    """In-process state (limits, nonces, clock, the forge's repository visibility)
    must not leak between tests."""
    from maity_hub import (
        availability,
        clock,
        forge,
        images,
        ktw,
        listening,
        not_listening,
        public_pages,
        shared_budget,
        shared_counts,
    )
    from maity_hub.auth import caller, verifiers
    from maity_hub.auth.credentials import NonceWindow
    from maity_hub.routes import badges, device_codes

    # The counts in the database belong to the previous test's app and engine; the tables
    # are emptied between tests anyway, and the next app configures its own.
    shared_counts.configure(None)
    shared_budget.configure(None)
    verifiers.configure(None)  # a credential written outside an app is stored plain
    listening.stop(every=True)  # a test's apps left on PostgreSQL share nothing with the next
    listening.reset()
    # The limits are the module's, set by the last app built: back to the defaults, so a test
    # that built an app with its own limit leaves none behind.
    badges.BY_ADDRESS.configure(*Settings.badge_limit)
    public_pages.BY_ADDRESS.configure(*Settings.public_page_limit)
    # Every limiter counts in this process here (the shared counts are off, above): one source
    # address and a few fixed addresses make all the visitors of the suite.
    for limiter in process_limiters():
        limiter.reset()
    device_codes._holding.clear()
    device_codes._breaker["until"] = 0.0
    # Tests run the availability sweep themselves; a worker's sweep in the middle of a
    # slow test would write to its database unasked.
    availability.INTERVAL = 24 * 3600.0
    not_listening.INTERVAL = 24 * 3600.0
    from maity_hub.jourfixe import worker as jour_fixe_worker

    jour_fixe_worker.INTERVAL = 24 * 3600.0
    from maity_hub.auth import second_factor

    second_factor._wrong_in_session.clear()
    caller.NONCES = NonceWindow()
    forge._visible.clear()
    forge._public.clear()
    forge._budgets.clear()
    images.reset()
    ktw.CACHE.clear()
    ktw.RAW.clear()
    from maity_hub import ktw_reads

    ktw_reads.FOREIGN.clear()
    ktw_reads._slots.clear()
    ktw_reads._flights.clear()
    ktw_reads._failed.clear()
    from maity_hub import maintenance

    maintenance.forget()  # one test's window must not refuse the next test's requests
    maintenance.forget_frame()
    # The window cache's clock stands still: a counting test must not see the window read
    # again because its runner is slow (tsk-aaprca1rs4ny); a test that wants expiry moves it.
    maintenance.monotonic = lambda: 0.0
    yield
    maintenance.monotonic = maintenance._process_monotonic
    clock.reset()
    from maity_hub import longpoll

    longpoll.stopping.clear()


@pytest.fixture
def migrated(engine: Engine, _migrated_sqlite_file: Path | None) -> Engine:
    migrate_fast(engine, _migrated_sqlite_file)
    return engine


ClientFactory = Callable[..., TestClient]


@pytest.fixture
def make_client(settings: Settings, migrated: Engine) -> Iterator[ClientFactory]:
    """A client with settings overrides, a base URL (https for TLS) and a peer address."""
    opened: list[TestClient] = []

    def factory(
        base_url: str = "https://hub.example",
        peer: str = "203.0.113.7",
        **overrides: object,
    ) -> TestClient:
        app = create_app(replace(settings, **overrides), migrated)  # type: ignore[arg-type]
        client = TestClient(app, base_url=base_url, client=(peer, 50000))
        client.__enter__()
        opened.append(client)
        return client

    yield factory
    for client in opened:
        client.__exit__(None, None, None)
