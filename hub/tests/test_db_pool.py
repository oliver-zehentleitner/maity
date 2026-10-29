"""The server-database pool and the single retry of a name that did not resolve."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import NullPool

from maity_hub import db
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


def test_the_options_set_milliseconds_and_an_off_value_sets_nothing() -> None:
    assert db.postgres_options(statement=30, idle_in_transaction=60) == (
        "-c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000"
    )
    assert db.postgres_options(statement=0.5) == "-c statement_timeout=500"
    assert db.postgres_options(idle_in_transaction=2) == (
        "-c idle_in_transaction_session_timeout=2000"
    )
    assert db.postgres_options() == ""


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
    assert (
        seen["options"] == "-c statement_timeout=30000 -c idle_in_transaction_session_timeout=60000"
    )
    assert seen["connect_timeout"] == db.CONNECT_TIMEOUT_SECONDS


def test_an_engine_without_timeouts_is_unbounded_as_migrate_and_the_cli_use_it() -> None:
    seen = captured_connect_args(db.make_engine("postgresql+psycopg://u:p@localhost/h"))
    assert "options" not in seen


def test_mariadb_gets_no_postgres_options() -> None:
    engine = db.make_engine("mysql+pymysql://u:p@localhost/h", 2, 0, 60, 30, 60)
    assert "options" not in captured_connect_args(engine, "pymysql")


def test_the_probe_has_a_connection_of_its_own_outside_the_pool() -> None:
    main = db.make_engine("postgresql+psycopg://u:p@localhost/h", 2, 0)
    health = db.make_health_engine(main)
    assert health is not None and health is not main
    assert isinstance(health.pool, NullPool) and health.url == main.url
    seen = captured_connect_args(health)
    assert seen["options"] == f"-c statement_timeout={db.HEALTH_STATEMENT_SECONDS * 1000}"
    assert len(health.dialect.dispatch.do_connect) == 1  # the DNS retry too


def test_sqlite_probes_through_the_one_engine(tmp_path: Any) -> None:
    assert db.make_health_engine(db.make_engine(f"sqlite:///{tmp_path}/h.db")) is None


def test_mariadb_probe_stops_waiting_for_a_hung_statement() -> None:
    main = db.make_engine("mysql+pymysql://u:p@localhost/h", 2, 0)
    health = db.make_health_engine(main)
    assert health is not None and isinstance(health.pool, NullPool)
    seen = captured_connect_args(health, "pymysql")
    assert seen["read_timeout"] == db.HEALTH_STATEMENT_SECONDS and "options" not in seen


def test_the_health_check_reads_the_probes_engine_not_the_apps(
    client: TestClient, engine: Engine
) -> None:
    """`/health` asks `app.state.health_engine`: with the app's own engine unusable it still
    answers. (The pool itself is not exhausted here; a pooled engine needs a server.)"""
    app: Any = client.app
    assert app.state.health_engine is engine  # SQLite: one engine
    app.state.engine = db.make_engine("postgresql+psycopg://u:p@localhost/h", 1, 0)
    assert client.get("/api/v1/health").status_code == 200


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
