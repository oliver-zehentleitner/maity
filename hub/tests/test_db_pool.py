"""The server-database pool and the single retry of a name that did not resolve."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.pool import NullPool

from maity_hub import db
from maity_hub.app import create_app
from maity_hub.config import ConfigError, Settings
from maity_hub.errors import connection_cause

DNS = OSError("failed to resolve host 'db': Temporary failure in name resolution")


@pytest.fixture(autouse=True)
def no_pause(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    pauses: list[float] = []
    monkeypatch.setattr(time, "sleep", pauses.append)
    return pauses


def flaky(*failures: Exception) -> tuple[Any, list[int]]:
    calls: list[int] = []
    queue = list(failures)

    def connect(*_args: Any, **_kwargs: Any) -> str:
        calls.append(1)
        if queue:
            raise queue.pop(0)
        return "connection"

    return connect, calls


def test_a_name_that_did_not_resolve_is_tried_once_more(no_pause: list[float]) -> None:
    connect, calls = flaky(DNS)
    assert db.connect_once_more_on_dns(connect, (), {}) == "connection"
    assert len(calls) == 2 and len(no_pause) == 1
    assert db.RESOLVE_PAUSE_SECONDS <= no_pause[0] <= 2 * db.RESOLVE_PAUSE_SECONDS


def test_a_second_dns_failure_goes_on(no_pause: list[float]) -> None:
    connect, calls = flaky(DNS, DNS)
    with pytest.raises(OSError):
        db.connect_once_more_on_dns(connect, (), {})
    assert len(calls) == 2


def test_any_other_failure_is_not_retried(no_pause: list[float]) -> None:
    connect, calls = flaky(OSError("connection refused"))
    with pytest.raises(OSError):
        db.connect_once_more_on_dns(connect, (), {})
    assert len(calls) == 1 and no_pause == []


def test_arguments_reach_the_driver() -> None:
    seen: list[tuple[Any, Any]] = []
    db.connect_once_more_on_dns(lambda *a, **k: seen.append((a, k)), (1,), {"x": 2})
    assert seen == [((1,), {"x": 2})]


@pytest.mark.parametrize(
    ("text", "category"),
    [
        ('could not translate host name "db" to address', "dns"),
        ("nodename nor servname provided", "dns"),
        ("getaddrinfo failed", "dns"),
        ("[Errno -3] Temporary failure in name resolution", "dns"),
        ("connection refused", "refused"),
        ("something new", "unclassified"),
    ],
)
def test_connection_cause_names_the_category(text: str, category: str) -> None:
    assert connection_cause(OSError(text)) == category


def test_a_server_engine_pools_and_reuses_the_latest_connection() -> None:
    engine = db.make_engine("postgresql+psycopg://u:p@localhost/h", 7, 3, 60)
    pool: Any = engine.pool
    assert (pool.size(), pool._max_overflow, pool._recycle, pool._pool.use_lifo) == (7, 3, 60, True)
    assert len(engine.dialect.dispatch.do_connect) == 1


def test_recycle_zero_means_never() -> None:
    engine = db.make_engine("postgresql+psycopg://u:p@localhost/h", pool_recycle=0)
    pool: Any = engine.pool
    assert pool._recycle == -1


def test_sqlite_has_no_connect_hook(tmp_path: Any) -> None:
    engine = db.make_engine(f"sqlite:///{tmp_path}/h.db")
    assert not engine.dialect.dispatch.do_connect


def test_settings_read_the_pool_from_the_environment() -> None:
    defaults = Settings.from_env({"MAITY_DATABASE_URL": "sqlite:///x.db"})
    assert (defaults.db_pool_size, defaults.db_max_overflow, defaults.db_pool_recycle) == (
        16,
        16,
        1800,
    )
    custom = Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite:///x.db",
            "MAITY_DB_POOL_RECYCLE": "0",
            "MAITY_DB_POOL_SIZE": "3",
        }
    )
    assert (custom.db_pool_size, custom.db_pool_recycle) == (3, 0)
    with pytest.raises(ConfigError):
        Settings.from_env(
            {"MAITY_DATABASE_URL": "sqlite:///x.db", "MAITY_DB_POOL_RECYCLE": "90000"}
        )


# --- timeouts and the probe's own connection ------------------------------------------------


def test_the_options_set_utc_and_milliseconds_and_an_off_value_sets_nothing() -> None:
    assert db.postgres_options(statement=30, idle_in_transaction=60) == (
        "-c TimeZone=UTC -c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000"
    )
    assert db.postgres_options(statement=0.5) == "-c TimeZone=UTC -c statement_timeout=500"
    assert db.postgres_options(idle_in_transaction=2) == (
        "-c TimeZone=UTC -c idle_in_transaction_session_timeout=2000"
    )
    assert db.postgres_options() == "-c TimeZone=UTC"


def captured_connect_args(engine: Any, driver: str = "psycopg") -> dict[str, Any]:
    """What the engine would hand to the driver, without connecting."""
    seen: dict[str, Any] = {}
    module = __import__(driver)

    def fake(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise module.OperationalError("stop")

    patch = pytest.MonkeyPatch()
    patch.setattr(module, "connect", fake)
    try:
        with pytest.raises(Exception, match="stop"):
            engine.connect()
    finally:
        patch.undo()
    return seen


def test_a_postgres_engine_sets_the_timeouts_on_each_connection() -> None:
    engine = db.make_engine("postgresql+psycopg://u:p@localhost/h", 2, 0, 60, 30, 60)
    seen = captured_connect_args(engine)
    assert seen["options"] == (
        "-c TimeZone=UTC -c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000"
    )
    assert seen["connect_timeout"] == db.CONNECT_TIMEOUT_SECONDS


def test_an_engine_without_timeouts_is_unbounded_as_migrate_and_the_cli_use_it() -> None:
    """No timeout, but UTC all the same: migrate and the CLI write timestamps too."""
    seen = captured_connect_args(db.make_engine("postgresql+psycopg://u:p@localhost/h"))
    assert seen["options"] == "-c TimeZone=UTC"


def test_options_in_the_database_url_are_kept_before_the_hubs() -> None:
    """A schema of its own (`search_path`) stays; the hub's settings come later and win."""
    url = "postgresql+psycopg://u:p@localhost/h?options=-c%20search_path%3Dmaity"
    seen = captured_connect_args(db.make_engine(url, 2, 0, 60, 30))
    assert seen["options"] == "-c search_path=maity -c TimeZone=UTC -c statement_timeout=30000"
    health = db.make_health_engine(db.make_engine(url, 2, 0))
    assert health is not None
    milliseconds = db.HEALTH_STATEMENT_SECONDS * 1000
    assert captured_connect_args(health)["options"] == (
        f"-c search_path=maity -c TimeZone=UTC -c statement_timeout={milliseconds}"
    )


def test_mariadb_gets_no_postgres_options() -> None:
    engine = db.make_engine("mysql+pymysql://u:p@localhost/h", 2, 0, 60, 30, 60)
    assert "options" not in captured_connect_args(engine, "pymysql")


def test_the_probe_has_a_connection_of_its_own_outside_the_pool() -> None:
    main = db.make_engine("postgresql+psycopg://u:p@localhost/h", 2, 0)
    health = db.make_health_engine(main)
    assert health is not None and health is not main
    assert isinstance(health.pool, NullPool) and health.url == main.url
    seen = captured_connect_args(health)
    milliseconds = db.HEALTH_STATEMENT_SECONDS * 1000
    assert seen["options"] == f"-c TimeZone=UTC -c statement_timeout={milliseconds}"
    assert len(health.dialect.dispatch.do_connect) == 1  # the DNS retry too


def test_sqlite_probes_through_the_one_engine(tmp_path: Any) -> None:
    assert db.make_health_engine(db.make_engine(f"sqlite:///{tmp_path}/h.db")) is None


def test_mariadb_probe_stops_waiting_for_a_hung_statement() -> None:
    main = db.make_engine("mysql+pymysql://u:p@localhost/h", 2, 0)
    health = db.make_health_engine(main)
    assert health is not None and isinstance(health.pool, NullPool)
    seen = captured_connect_args(health, "pymysql")
    assert seen["read_timeout"] == db.HEALTH_STATEMENT_SECONDS and "options" not in seen


def test_sqlite_has_one_engine_and_the_probe_uses_it(client: TestClient, engine: Engine) -> None:
    app: Any = client.app
    if engine.dialect.name != "sqlite":
        pytest.skip("a server database has an engine of its own for the probe")
    assert app.state.health_engine is engine


def test_the_probe_answers_while_the_pool_is_used_up(
    client: TestClient, engine: Engine, settings: Settings
) -> None:
    """The incident of 2026-10-26: every pooled connection taken, the readiness probe failing
    with them. An app whose pool is one connection, held, still answers `/health`; a call that
    needs the pool does not (SQLite has one engine and nothing to escape to)."""
    if engine.dialect.name == "sqlite":
        pytest.skip("SQLite probes through the one engine")
    small = create_engine(engine.url, pool_size=1, max_overflow=0, pool_timeout=0.3)
    app = create_app(settings, small)
    probe: Engine = app.state.health_engine
    held = small.connect()
    try:
        with pytest.raises(PoolTimeout):
            small.connect()  # the pool is used up
        assert probe is not small and isinstance(probe.pool, NullPool)
        answer = TestClient(app).get("/api/v1/health")
        assert answer.status_code == 200 and answer.json()["status"] == "ok"
    finally:
        held.close()
        small.dispose()
        probe.dispose()


def test_settings_read_the_two_timeouts() -> None:
    defaults = Settings.from_env({"MAITY_DATABASE_URL": "sqlite:///x.db"})
    assert (defaults.db_statement_timeout, defaults.db_idle_in_transaction_timeout) == (30, 60)
    custom = Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite:///x.db",
            "MAITY_DB_STATEMENT_TIMEOUT": "0",
            "MAITY_DB_IDLE_IN_TRANSACTION_TIMEOUT": "12.5",
        }
    )
    assert (custom.db_statement_timeout, custom.db_idle_in_transaction_timeout) == (0, 12.5)
    for name in ("MAITY_DB_STATEMENT_TIMEOUT", "MAITY_DB_IDLE_IN_TRANSACTION_TIMEOUT"):
        for bad in ("-1", "3601", "soon"):
            with pytest.raises(ConfigError):
                Settings.from_env({"MAITY_DATABASE_URL": "sqlite:///x.db", name: bad})


def test_a_postgres_connection_says_who_it_is() -> None:
    url = "postgresql+psycopg://u:p@localhost/h"
    assert captured_connect_args(db.make_engine(url))["application_name"] == "maity-hub-cli"
    serving = db.make_engine(url, application_name=db.APPLICATION_SERVING)
    assert captured_connect_args(serving)["application_name"] == "maity-hub"
    health = db.make_health_engine(serving)
    assert health is not None
    assert captured_connect_args(health)["application_name"] == "maity-hub-health"


def test_the_serving_hub_names_its_connections(settings: Settings) -> None:
    from maity_hub.app import serving_engine

    url = "postgresql+psycopg://u:p@localhost/h"
    engine = serving_engine(replace(settings, database_url=url))
    assert captured_connect_args(engine)["application_name"] == "maity-hub"


def test_mariadb_and_sqlite_get_no_application_name(tmp_path: Any) -> None:
    mariadb = db.make_engine("mysql+pymysql://u:p@localhost/h", application_name="x")
    assert "application_name" not in captured_connect_args(mariadb, "pymysql")
    assert "application_name" not in captured_connect_args(
        db.make_health_engine(mariadb) or mariadb, "pymysql"
    )


def test_the_hubs_name_wins_over_one_in_the_database_url() -> None:
    url = "postgresql+psycopg://u:p@localhost/h?application_name=ops-set"
    seen = captured_connect_args(db.make_engine(url, application_name=db.APPLICATION_SERVING))
    assert seen["application_name"] == "maity-hub"


def test_a_postgres_session_is_utc_whatever_the_server_default(
    engine: Engine, database_url: str
) -> None:
    """The test databases default to Vienna (conftest); the hub's own sessions read UTC, so a
    timestamp PostgreSQL converts is never shifted by an hour."""
    if engine.dialect.name != "postgresql":
        pytest.skip("a session time zone is PostgreSQL's")
    plain = create_engine(database_url, poolclass=NullPool)
    try:
        with plain.connect() as conn:
            assert conn.execute(text("SHOW TimeZone")).scalar() != "UTC"
    finally:
        plain.dispose()
    with engine.connect() as conn:
        assert conn.execute(text("SHOW TimeZone")).scalar() == "UTC"
