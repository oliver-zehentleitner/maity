"""Fixtures. `MAITY_TEST_DATABASE_URL` points the suite at PostgreSQL or
MariaDB; without it every test gets its own SQLite file. Under pytest-xdist each
worker gets a database of its own on that server (`<name>_gw0`, `<name>_gw1`, …),
created through `MAITY_TEST_ADMIN_DATABASE_URL` (default: the same URL)."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.engine import make_url

from maity_hub.app import create_app
from maity_hub.config import Settings, normalize_database_url
from maity_hub.db import current_revision, downgrade, head_revision, make_engine, migrate


@pytest.fixture(scope="session")
def _server_database_url(worker_id: str) -> str | None:
    """The PostgreSQL or MariaDB database this process runs against, or None for SQLite.
    A parallel worker gets its own database next to the configured one, so the workers
    never see each other's tables."""
    configured = os.environ.get("MAITY_TEST_DATABASE_URL")
    if not configured:
        return None
    url = make_url(normalize_database_url(configured))
    if worker_id == "master":
        return url.render_as_string(hide_password=False)
    name = f"{url.database}_{worker_id}"
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
            else:
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
        downgrade(engine)
        engine.dispose()


def _empty_the_tables(engine: Engine) -> None:
    """Delete every row of a server database at head, keeping the schema and the revision."""
    tables = [t for t in inspect(engine).get_table_names() if t != "alembic_version"]
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            quoted = ", ".join(f'"{t}"' for t in tables)
            connection.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
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
            downgrade(engine)  # a shared server database may hold a previous run's schema
            migrate(engine)
    else:
        downgrade(engine)
    yield engine
    if on_server and not keeps_schema:
        downgrade(engine)
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
    (web / "index.html").write_text("<!doctype html><title>dashboard</title>")
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
def _no_background_ktw_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """A project view schedules a Keep the Why read in the background; in tests that
    would race the next test's cache. Tests of the scheduling replace this themselves."""
    from maity_hub import ktw

    monkeypatch.setattr(ktw, "_refresh_later", lambda *args: None)


@pytest.fixture(autouse=True)
def _fresh_process_state() -> Iterator[None]:
    """In-process state (limits, nonces, clock, the forge's repository visibility)
    must not leak between tests."""
    from maity_hub import availability, clock, forge, images, ktw, mentions, not_listening
    from maity_hub.auth import caller
    from maity_hub.auth.credentials import NonceWindow
    from maity_hub.board import notes
    from maity_hub.routes import auth, badges, device_codes, joins, mail_settings, me, runners

    badges.BY_ADDRESS.reset()
    badges.NOT_SERVED.reset()
    auth.LOGIN_BY_ADDRESS.reset()
    joins.EXCHANGE_BY_ADDRESS.reset()
    runners.PAIR_BY_ADDRESS.reset()
    auth.LOGIN_BY_HANDLE.reset()
    mentions.PINGS.reset()
    mail_settings.test_limiter.reset()
    for limiter in (
        device_codes.CODES_BY_HUMAN,
        device_codes.REDEEM_BY_ADDRESS,
        device_codes.WRONG_CODES,
    ):
        limiter.reset()
    device_codes._holding.clear()
    device_codes._breaker["until"] = 0.0
    notes.POSTED.reset()
    me.EXPORTS.reset()
    # Tests run the availability sweep themselves; a worker's sweep in the middle of a
    # slow test would write to its database unasked.
    availability.INTERVAL = 24 * 3600.0
    not_listening.INTERVAL = 24 * 3600.0
    from maity_hub.jourfixe import worker as jour_fixe_worker

    jour_fixe_worker.INTERVAL = 24 * 3600.0
    from maity_hub.auth import second_factor

    second_factor.WRONG_BY_HUMAN.reset()
    second_factor.ENROLMENTS_BY_HUMAN.reset()
    second_factor._wrong_in_session.clear()
    caller.NONCES = NonceWindow()
    forge._visible.clear()
    forge._budgets.clear()
    images.reset()
    ktw.CACHE.clear()
    yield
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
